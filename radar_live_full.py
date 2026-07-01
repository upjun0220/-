"""
radar_live_full.py v3 -- Radar-Guard Real-time Control System
=============================================================
Full pipeline: Real radar data -> LMS -> LSTM-AE -> Classify -> RAG -> SOP

Run order:
  [Terminal 1]  python3 ~/radar_parser.py        (data collection)
  [Terminal 2]  python3 ~/radar_live_full.py      (analysis + display)

Prerequisites (Jetson terminal):
  sudo docker start radar-guard-db
  ollama serve

5-Phase workflow:
  [READY]      Waiting for user to click 'Start Baseline Collection'
  [WARMUP]     Collecting N_WARMUP real frames as normal baseline
  [WAIT_TRAIN] Baseline done -- waiting for user to click 'Start Training'
  [TRAINING]   Fitting LSTM-AE on collected data (~20-30 sec)
  [LIVE]       Real-time anomaly detection + RAG SOP generation

Display layout (5 panels + step guide + progress bar):
  [Step Guide: Radar ON -> Baseline -> Training -> LIVE]
  [Status Bar (single line, full width)]
  [Progress Bar (visible during WARMUP)]
  -------------------------------------------------------
  [3D Cloud]  [Centroid Z]  [Anomaly Score]
  [Event Log]  [SOP / Action Guide (2 cols wide)  ]
  -------------------------------------------------------
  [Start Baseline Btn]          [Reset Baseline Btn]
"""

import json, os, time, threading, textwrap, warnings
from datetime import datetime
from collections import deque

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.widgets import Button
from mpl_toolkits.mplot3d import Axes3D  # noqa
from matplotlib.animation import FuncAnimation
matplotlib.rcParams['font.family'] = 'DejaVu Sans'

import torch
import torch.nn as nn
from torch import optim
from sklearn.preprocessing import MinMaxScaler

warnings.filterwarnings("ignore")

# RAG imports (graceful fallback)
try:
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    from langchain_community.vectorstores import PGVector
    from langchain_core.prompts import PromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    RAG_OK = True
except ImportError:
    RAG_OK = False

# ═══════════════════════════════════════════════════════════
# 1. CONFIG
# ═══════════════════════════════════════════════════════════
JSON_PATH     = '/home/project/stage1_filtered.json'
CONN_STR      = 'postgresql://postgres:password@localhost:5432/radar_guard'

N_WARMUP      = 300      # real frames for normal baseline (~30 sec at 10 fps)
FEATURE_DIM   = 8
SEQ_LEN       = 5
HISTORY_LEN   = 120
N_RESET       = 15
POLL_SEC      = 0.4
UPDATE_MS     = 800
FALL_Z_THR    = 0.6
WRAP_WIDTH    = 52

DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# Phase constants
PH_READY      = 'READY'
PH_WARMUP     = 'WARMUP'
PH_WAIT_TRAIN = 'WAIT_TRAIN'
PH_TRAINING   = 'TRAINING'
PH_LIVE       = 'LIVE'

STEP_LABELS = [
    '  Radar ON  ',
    '  Baseline  ',
    '  Training  ',
    '  LIVE  ',
]
STEP_COLORS_ACTIVE   = ['#00ccff', '#ffcc00', '#ff8800', '#44ff88']
STEP_COLORS_INACTIVE = ['#223344', '#332200', '#331800', '#112211']
STEP_TEXT_INACTIVE   = '#445566'

# WAIT_TRAIN maps to step index 2 (Training) but with a different color
STEP_COLOR_WAIT_TRAIN = '#ffcc00'   # yellow: "ready to train"

EVENT_LABELS = {
    'fall_detected':       'FALL DETECTED',
    'electric_shock_risk': 'ELECTRIC SHOCK RISK',
    'pinching':            'PINCHING / ENTRAPMENT',
    'vibration_anomaly':   'VIBRATION ANOMALY',
}
EVENT_ZONE = {
    'fall_detected': 'C', 'electric_shock_risk': 'A',
    'pinching': 'B',       'vibration_anomaly': 'C',
}
EVENT_CATEGORY = {
    'fall_detected':       '03_naksan_eunggeupcheo',
    'electric_shock_risk': '01_gamjeon_LOTO',
    'pinching':            '02_hyeopcak_kkim',
    'vibration_anomaly':   '04_yeji_boen',
}
SEV_COLOR = {'normal': '#44ff88', 'warning': '#ffaa00', 'critical': '#ff3333'}

# ═══════════════════════════════════════════════════════════
# 2. PIPELINE CLASSES
# ═══════════════════════════════════════════════════════════
class LMSFilter:
    def __init__(self, order=8, mu=0.005):
        self.w = np.zeros(order); self.buf = np.zeros(order)
        self.order, self.mu = order, mu

    def filter(self, x, ref):
        self.buf = np.roll(self.buf, 1); self.buf[0] = ref
        y = np.dot(self.w, self.buf); e = x - y
        self.w += 2 * self.mu * e * self.buf
        return float(e)


def extract_features(frame_pts, prev_c=None):
    if not frame_pts:
        return np.zeros(FEATURE_DIM, dtype=np.float32)
    pts = np.array([[p['x'], p['y'], p['z'], p['doppler'], p['intensity']]
                    for p in frame_pts], dtype=np.float32)
    c        = pts[:, :3].mean(axis=0)
    mean_dop = float(pts[:, 3].mean())
    dop_std  = float(pts[:, 3].std() + 1e-8)
    int_mean = float(pts[:, 4].mean())
    n_pts    = float(len(pts))
    z_vel    = float(c[2] - prev_c[2]) if prev_c is not None else 0.0
    return np.array([c[0], c[1], c[2], mean_dop, dop_std, int_mean, n_pts, z_vel],
                    dtype=np.float32)


class LSTM_AE(nn.Module):
    def __init__(self, n_feat, emb_dim, seq_len):
        super().__init__()
        self.seq_len = seq_len
        self.enc1 = nn.LSTM(n_feat,     emb_dim,    batch_first=True)
        self.enc2 = nn.LSTM(emb_dim,    emb_dim//2, batch_first=True)
        self.dec1 = nn.LSTM(emb_dim//2, emb_dim//2, batch_first=True)
        self.dec2 = nn.LSTM(emb_dim//2, emb_dim,    batch_first=True)
        self.fc   = nn.Linear(emb_dim, n_feat)

    def forward(self, x):
        _, (h, _) = self.enc1(x)
        _, (h, _) = self.enc2(h.transpose(0, 1))
        x = h.transpose(0, 1).repeat(1, self.seq_len, 1)
        x, _ = self.dec1(x); x, _ = self.dec2(x)
        return self.fc(x)


def train_on_real_data(feature_list):
    data   = np.array(feature_list, dtype=np.float32)
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(data)
    seqs   = np.array([scaled[i:i+SEQ_LEN] for i in range(len(scaled)-SEQ_LEN)],
                      dtype=np.float32)
    X = torch.from_numpy(seqs).float().to(DEVICE)

    model = LSTM_AE(FEATURE_DIM, 16, SEQ_LEN).to(DEVICE)
    opt   = optim.AdamW(model.parameters(), lr=0.001)
    crit  = nn.MSELoss()
    model.train()
    for epoch in range(120):
        opt.zero_grad()
        loss = crit(model(X), X)
        loss.backward(); opt.step()
        time.sleep(0.01)    # every epoch: release GIL for animation thread

    model.eval()
    with torch.no_grad():
        r  = model(X)
        ls = torch.mean((r - X)**2, dim=(1, 2)).cpu().numpy()
        thr = float(np.mean(ls) + 3 * np.std(ls))
    return model, scaler, thr


def classify(feat_win, score, thr):
    peak    = feat_win[-1]
    cy, mean_dop, dop_std, z_vel = float(peak[1]), float(peak[3]), float(peak[4]), float(peak[7])
    excess  = score / thr
    conf    = round(min(0.99, 0.55 + 0.20 * min(1.0, excess - 1.0)), 2)
    if z_vel < -0.10 and abs(mean_dop) > 0.18:
        return {'event_type': 'fall_detected',       'severity': 'critical', 'confidence': round(min(0.99, conf+0.10), 2)}
    if dop_std > 0.030 and abs(z_vel) < 0.15:
        return {'event_type': 'electric_shock_risk', 'severity': 'critical', 'confidence': round(min(0.99, conf+0.08), 2)}
    if dop_std > 0.010 and abs(z_vel) < 0.15 and cy < 0.85:
        return {'event_type': 'pinching',            'severity': 'critical', 'confidence': conf}
    if dop_std > 0.002:
        return {'event_type': 'vibration_anomaly',   'severity': 'warning',  'confidence': round(min(0.99, 0.45+0.30*min(1.0, excess-1.0)), 2)}
    return     {'event_type': 'fall_detected',       'severity': 'warning',  'confidence': round(min(0.75, 0.40+0.10*excess), 2)}

# ═══════════════════════════════════════════════════════════
# 3. SHARED STATE
# ═══════════════════════════════════════════════════════════
_lock = threading.Lock()
state = {
    'phase':             PH_READY,
    'warmup_count':      0,
    'start_requested':   False,
    'train_requested':   False,
    'reset_requested':   False,
    'latest_pts':       [],
    'cz_h':   deque([1.7] * HISTORY_LEN, maxlen=HISTORY_LEN),
    'sc_h':   deque([0.0] * HISTORY_LEN, maxlen=HISTORY_LEN),
    'cnt_h':  deque([0]   * HISTORY_LEN, maxlen=HISTORY_LEN),
    'ev_active':  False,
    'ev_type':    None,
    'ev_sev':     'normal',
    'ev_conf':    0.0,
    'ev_zone':    'C',
    'threshold':  0.01,
    'norm_count': 0,
    'rag_running': False,
    'sop_text':    '',
    'logs': deque(maxlen=20),
    'last_data_t': 0.0,
    'data_ok':     False,   # True once JSON file exists and has data
}


def add_log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    with _lock:
        state['logs'].append(f'[{ts}] {msg}')
    print(f'[LOG {ts}] {msg}')

# ═══════════════════════════════════════════════════════════
# 4. RAG THREAD
# ═══════════════════════════════════════════════════════════
def run_rag(ev_type, zone):
    situation = f'{EVENT_LABELS.get(ev_type, ev_type)} detected in Zone {zone}'
    category  = EVENT_CATEGORY.get(ev_type)
    add_log(f'RAG started: {situation}')
    with _lock:
        state['sop_text'] = '>> Generating SOP guide...\n   (Llama3 inference, ~1-2 min)'

    if not RAG_OK:
        with _lock:
            state['sop_text']    = 'RAG unavailable: LangChain not installed.'
            state['rag_running'] = False
        return

    try:
        emb  = OllamaEmbeddings(model='nomic-embed-text')
        vs   = PGVector(connection_string=CONN_STR, embedding_function=emb,
                        collection_name='safety_manual')
        llm  = ChatOllama(model='llama3:8b', temperature=0)
        docs = vs.similarity_search(situation, k=3,
               filter={'category': category}) if category \
               else vs.similarity_search(situation, k=3)
        if not docs:
            with _lock:
                state['sop_text']    = f'No manual found for category: {category}'
                state['rag_running'] = False
            return
        context  = '\n\n---\n\n'.join(d.page_content for d in docs)
        prompt   = PromptTemplate.from_template(
            "You are an industrial safety expert. "
            "Using the safety manual excerpts below, provide a numbered step-by-step "
            "action guide IN ENGLISH for the detected situation. "
            "Only use information from the manual. Do not guess.\n\n"
            "SAFETY MANUAL:\n{context}\n\n"
            "DETECTED SITUATION: {situation}\n\n"
            "ACTION GUIDE:"
        )
        chain    = prompt | llm | StrOutputParser()
        response = chain.invoke({'context': context, 'situation': situation})
        wrapped  = '\n'.join(
            textwrap.fill(line, width=WRAP_WIDTH) if line.strip() else ''
            for line in response.split('\n')
        )
        with _lock:
            state['sop_text']    = f'=== SOP: {EVENT_LABELS.get(ev_type)} ===\n\n{wrapped}'
            state['rag_running'] = False
        add_log('RAG complete - SOP guide ready')

    except Exception as e:
        with _lock:
            state['sop_text']    = f'RAG error: {e}\n\nCheck:\n  docker start radar-guard-db\n  ollama serve'
            state['rag_running'] = False
        add_log(f'RAG error: {e}')

# ═══════════════════════════════════════════════════════════
# 5. PIPELINE THREAD
# ═══════════════════════════════════════════════════════════
def pipeline_loop():
    lms         = LMSFilter()
    feat_buf    = []
    warmup_feat = []
    prev_c      = None
    last_mtime  = 0.0
    proc_idx    = -1
    model       = None
    scaler      = None
    thr         = 0.01

    add_log('Pipeline started -- waiting for radar data')

    while True:
        # ── Reset check ────────────────────────────────────
        do_reset = False
        with _lock:
            if state['reset_requested']:
                state['reset_requested'] = False
                state['phase']            = PH_READY
                state['warmup_count']     = 0
                state['start_requested']  = False
                state['train_requested']  = False
                state['ev_active']        = False
                state['ev_type']         = None
                state['ev_sev']          = 'normal'
                state['ev_conf']         = 0.0
                state['norm_count']      = 0
                state['sop_text']        = ''
                state['rag_running']     = False
                state['threshold']       = 0.01
                state['logs'].append(
                    f'[{datetime.now().strftime("%H:%M:%S")}] '
                    f'RESET -- click Start Baseline to recollect'
                )
                do_reset = True

        if do_reset:
            lms         = LMSFilter()
            feat_buf    = []
            warmup_feat = []
            prev_c      = None
            model       = None
            scaler      = None
            thr         = 0.01
            proc_idx    = -1      # restart from beginning of JSON
            last_mtime  = 0.0    # force re-read

        time.sleep(POLL_SEC)

        # ── Load JSON ──────────────────────────────────────
        no_file = not os.path.exists(JSON_PATH)
        with _lock:
            state['data_ok'] = not no_file
        if no_file:
            continue

        try:
            mtime = os.path.getmtime(JSON_PATH)
        except OSError:
            continue
        if mtime == last_mtime:
            continue

        try:
            with open(JSON_PATH, 'r') as f:
                all_frames = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        last_mtime = mtime

        new_frames = all_frames[proc_idx + 1:]
        if not new_frames:
            continue

        for frame_pts in new_frames:
            proc_idx += 1
            if not frame_pts:
                continue

            with _lock:
                state['latest_pts']  = frame_pts
                state['last_data_t'] = time.time()

            zs  = [p['z'] for p in frame_pts]
            cz  = float(np.mean(zs)) if zs else 1.7
            n   = len(frame_pts)
            feat = extract_features(frame_pts, prev_c)
            ref     = float(np.random.normal(0, 0.004))
            feat[3] = lms.filter(feat[3], ref)
            prev_c  = feat[:3].copy()

            with _lock:
                state['cz_h'].append(cz)
                state['cnt_h'].append(n)

            # ── READY phase: wait for Start button ─────────
            with _lock:
                current_phase = state['phase']
                start_req     = state['start_requested']

            if current_phase == PH_READY:
                if start_req:
                    with _lock:
                        state['start_requested'] = False
                        state['phase']           = PH_WARMUP
                    add_log('Baseline collection started -- stand still!')
                else:
                    with _lock:
                        state['sc_h'].append(0.0)
                    continue   # skip this frame, wait for button

            # ── WARMUP phase ───────────────────────────────
            if model is None:
                warmup_feat.append(feat.tolist())
                wc = len(warmup_feat)
                with _lock:
                    state['warmup_count'] = wc
                    # Only set WARMUP if not already past it
                    if state['phase'] not in (PH_WAIT_TRAIN, PH_TRAINING, PH_LIVE):
                        state['phase'] = PH_WARMUP

                if wc % 30 == 0 or wc == 1:
                    print(f'  [WARMUP] {wc}/{N_WARMUP} frames ({int(wc/N_WARMUP*100)}%)')

                if wc >= N_WARMUP:
                    # Baseline done -- wait for user to click Start Training
                    with _lock:
                        if state['phase'] != PH_WAIT_TRAIN:
                            state['phase'] = PH_WAIT_TRAIN
                            add_log(f'Baseline complete ({N_WARMUP} frames). Click "Start Training" to proceed.')

                    # Spin until train button pressed
                    with _lock:
                        train_req = state['train_requested']
                    if not train_req:
                        with _lock:
                            state['sc_h'].append(0.0)
                        continue

                    # Train requested -- go
                    with _lock:
                        state['train_requested'] = False
                        state['phase'] = PH_TRAINING
                    add_log('Training LSTM-AE...')

                    # Train in separate thread so animation stays alive
                    _done = threading.Event()
                    _res  = {}

                    def _train_worker(feat_copy=warmup_feat[:]):
                        m, s, t = train_on_real_data(feat_copy)
                        _res['model'] = m; _res['scaler'] = s; _res['thr'] = t
                        _done.set()

                    threading.Thread(target=_train_worker, daemon=True).start()

                    while not _done.wait(timeout=0.3):
                        with _lock:
                            state['last_data_t'] = time.time()

                    model  = _res['model']
                    scaler = _res['scaler']
                    thr    = _res['thr']

                    with _lock:
                        state['threshold'] = thr
                        state['phase']     = PH_LIVE
                    add_log(f'Training done. Threshold={thr:.5f}. LIVE detection active.')

                with _lock:
                    state['sc_h'].append(0.0)
                continue

            # ── LIVE detection phase ───────────────────────
            feat_buf.append(feat.tolist())
            if len(feat_buf) > SEQ_LEN:
                feat_buf.pop(0)

            score = 0.0
            if len(feat_buf) == SEQ_LEN:
                try:
                    arr    = np.array(feat_buf, dtype=np.float32)
                    scaled = scaler.transform(arr)
                    X      = torch.from_numpy(scaled[np.newaxis]).float().to(DEVICE)
                    with torch.no_grad():
                        recon = model(X)
                        score = float(torch.mean((recon - X)**2).item())
                except Exception:
                    score = 0.0

            with _lock:
                state['sc_h'].append(score)
                is_anomaly = score > thr

                if is_anomaly:
                    state['norm_count'] = 0
                    if not state['ev_active']:
                        fw  = np.array(feat_buf, dtype=np.float32)
                        clf = classify(fw, score, thr)
                        et  = clf['event_type']
                        zn  = EVENT_ZONE.get(et, 'C')
                        state.update({
                            'ev_active': True, 'ev_type': et,
                            'ev_sev': clf['severity'],
                            'ev_conf': clf['confidence'],
                            'ev_zone': zn, 'sop_text': '',
                        })
                        lbl = EVENT_LABELS.get(et, et)
                        msg = f'ALERT Zone {zn}: {lbl} (conf={clf["confidence"]:.0%} score={score/thr:.1f}x)'
                        state['logs'].append(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}')
                        if not state['rag_running'] and RAG_OK:
                            state['rag_running'] = True
                            threading.Thread(target=run_rag, args=(et, zn), daemon=True).start()
                else:
                    if state['ev_active']:
                        state['norm_count'] += 1
                        if state['norm_count'] >= N_RESET:
                            et  = state['ev_type']; zn = state['ev_zone']
                            lbl = EVENT_LABELS.get(et, et)
                            state.update({
                                'ev_active': False, 'ev_type': None,
                                'ev_sev': 'normal', 'ev_conf': 0.0,
                                'norm_count': 0, 'sop_text': '',
                            })
                            state['logs'].append(
                                f'[{datetime.now().strftime("%H:%M:%S")}] '
                                f'CLEAR Zone {zn}: {lbl} resolved'
                            )

# ═══════════════════════════════════════════════════════════
# 6. MATPLOTLIB FIGURE
# ═══════════════════════════════════════════════════════════
fig = plt.figure(figsize=(17, 9), facecolor='#080818')
fig.suptitle('Radar-Guard  |  IWR6843ISK-ODS  |  Real-time Safety Monitor',
             color='white', fontsize=12, fontweight='bold', y=0.99)

# ── Step Guide (4 steps) ─────────────────────────────────
# Labels: ① Radar ON  ② Baseline  ③ Training  ④ LIVE
step_texts = []
step_xs = [0.13, 0.36, 0.59, 0.82]
step_y   = 0.967
step_arrows_x = [0.255, 0.485, 0.715]
for sx, label, col_off in zip(step_xs, STEP_LABELS, STEP_COLORS_INACTIVE):
    t = fig.text(sx, step_y, label,
                 color=STEP_TEXT_INACTIVE, fontsize=9, ha='center', va='center',
                 fontfamily='monospace', fontweight='bold',
                 bbox=dict(boxstyle='round,pad=0.4', facecolor='#0a0a1e',
                           edgecolor='#223344', alpha=0.95))
    step_texts.append(t)

# Arrows between steps
for ax_pos in step_arrows_x:
    fig.text(ax_pos, step_y, '  -->  ', color='#334455',
             fontsize=9, ha='center', va='center', fontfamily='monospace')

# ── Status Bar (single wide line) ────────────────────────
status_box = fig.text(0.5, 0.948, 'Initializing...',
                      color='white', fontsize=9.5, va='center', ha='center',
                      fontfamily='monospace',
                      bbox=dict(boxstyle='round,pad=0.38', facecolor='#101028',
                                edgecolor='#445566', alpha=0.95))

# ── Progress Bar ─────────────────────────────────────────
ax_prog = fig.add_axes([0.04, 0.925, 0.92, 0.012])
ax_prog.set_xlim(0, 1); ax_prog.set_ylim(0, 1)
ax_prog.axis('off')
ax_prog.set_facecolor('#0a0a1e')
prog_bg   = mpatches.FancyBboxPatch((0, 0.1), 1.0, 0.8, boxstyle='round,pad=0.01',
                                    facecolor='#151530', edgecolor='#223344', linewidth=0.8)
prog_fill = mpatches.FancyBboxPatch((0, 0.1), 0.0, 0.8, boxstyle='round,pad=0.01',
                                    facecolor='#00aaff', edgecolor='none', alpha=0.85)
ax_prog.add_patch(prog_bg)
ax_prog.add_patch(prog_fill)
prog_label = ax_prog.text(0.5, 0.5, '', ha='center', va='center',
                          color='white', fontsize=8, fontfamily='monospace')

# ── GridSpec (5 data panels) ─────────────────────────────
gs = gridspec.GridSpec(
    2, 3, figure=fig,
    left=0.04, right=0.98, top=0.91, bottom=0.10,
    hspace=0.38, wspace=0.28,
    height_ratios=[1.15, 1],
)

# -- Panel 1: 3D Point Cloud --
ax3d = fig.add_subplot(gs[0, 0], projection='3d')
ax3d.set_facecolor('#08081a')
ax3d.set_title('3D Point Cloud  (latest frame)', color='white', fontsize=8, pad=3)
ax3d.set_xlabel('X (m)', color='#8899bb', fontsize=7, labelpad=1)
ax3d.set_ylabel('Y/Depth (m)', color='#8899bb', fontsize=7, labelpad=1)
ax3d.set_zlabel('Z/Height (m)', color='#8899bb', fontsize=7, labelpad=1)
ax3d.tick_params(colors='#556677', labelsize=6)
ax3d.set_xlim(-2, 2); ax3d.set_ylim(0, 5); ax3d.set_zlim(0, 2.5)
for pn in (ax3d.xaxis.pane, ax3d.yaxis.pane, ax3d.zaxis.pane):
    pn.fill = False; pn.set_edgecolor('#1a1a33')
scatter3d = ax3d.scatter([], [], [], c=[], cmap='plasma',
                          vmin=200, vmax=600, s=16, alpha=0.85)

# -- Panel 2: Centroid Z timeseries --
ax_z = fig.add_subplot(gs[0, 1], facecolor='#08081a')
ax_z.set_title('Centroid Z  (fall indicator)', color='white', fontsize=8, pad=3)
ax_z.set_ylim(0, 2.5); ax_z.set_xlim(0, HISTORY_LEN)
ax_z.axhline(FALL_Z_THR, color='#ff4444', lw=1.0, ls='--', alpha=0.75)
ax_z.axhline(1.70,        color='#44cc66', lw=0.8, ls=':',  alpha=0.55)
ax_z.text(2, FALL_Z_THR+0.06, f'Fall thr {FALL_Z_THR}m', color='#ff6666', fontsize=7)
ax_z.text(2, 1.76, 'Normal ~1.7m', color='#44cc66', fontsize=7)
for sp in ax_z.spines.values(): sp.set_color('#1a1a33')
ax_z.tick_params(colors='#556677', labelsize=7)
ax_z.set_xlabel('Frames', color='#8899bb', fontsize=7)
ax_z.set_ylabel('Z (m)',  color='#8899bb', fontsize=7)
line_z, = ax_z.plot([], [], color='#00ccff', lw=1.8)

# -- Panel 3: Anomaly Score --
ax_sc = fig.add_subplot(gs[0, 2], facecolor='#08081a')
ax_sc.set_title('Anomaly Score  (MSE Loss)', color='white', fontsize=8, pad=3)
ax_sc.set_xlim(0, HISTORY_LEN); ax_sc.set_ylim(0, 0.05)
for sp in ax_sc.spines.values(): sp.set_color('#1a1a33')
ax_sc.tick_params(colors='#556677', labelsize=7)
ax_sc.set_xlabel('Frames', color='#8899bb', fontsize=7)
ax_sc.set_ylabel('MSE',    color='#8899bb', fontsize=7)
line_sc, = ax_sc.plot([], [], color='#ffaa00', lw=1.8)
thr_line  = ax_sc.axhline(0, color='#ff4444', ls='--', lw=1.1, alpha=0.8, label='threshold')
ax_sc.legend(loc='upper right', fontsize=7,
             facecolor='#08081a', edgecolor='#334455', labelcolor='white')

# -- Panel 4: Event Log --
ax_log = fig.add_subplot(gs[1, 0], facecolor='#060614')
ax_log.set_title('Event Log', color='white', fontsize=8, pad=3)
ax_log.axis('off')
log_text = ax_log.text(0.02, 0.97, '', transform=ax_log.transAxes,
                        color='#aabbcc', fontsize=7, va='top',
                        fontfamily='monospace')

# -- Panel 5: SOP / Guide Panel --
ax_sop = fig.add_subplot(gs[1, 1:])
ax_sop.set_facecolor('#04040e')
ax_sop.set_title('Action Guide  /  SOP (Llama3 + pgvector RAG)',
                  color='white', fontsize=8, pad=3)
ax_sop.axis('off')
sop_text = ax_sop.text(0.015, 0.97, '',
                        transform=ax_sop.transAxes,
                        color='#ccddee', fontsize=7.5, va='top',
                        fontfamily='monospace')

# ═══════════════════════════════════════════════════════════
# 7. STEP GUIDE HELPERS
# ═══════════════════════════════════════════════════════════
def _step_idx(phase, data_ok):
    """Returns 0-3 index of current active step."""
    if not data_ok:
        return -1
    if phase == PH_READY:
        return 0
    if phase == PH_WARMUP:
        return 1
    if phase in (PH_WAIT_TRAIN, PH_TRAINING):
        return 2
    return 3   # LIVE

def update_step_guide(phase, data_ok):
    idx = _step_idx(phase, data_ok)
    for i, (t, col_a, col_i) in enumerate(zip(step_texts, STEP_COLORS_ACTIVE, STEP_COLORS_INACTIVE)):
        if i <= idx:
            t.set_color(STEP_COLORS_ACTIVE[i])
            t.get_bbox_patch().set_facecolor('#0a1020')
            t.get_bbox_patch().set_edgecolor(STEP_COLORS_ACTIVE[i])
        else:
            t.set_color(STEP_TEXT_INACTIVE)
            t.get_bbox_patch().set_facecolor('#0a0a1e')
            t.get_bbox_patch().set_edgecolor('#223344')

def update_progress_bar(phase, warmup_count):
    if phase == PH_WARMUP:
        pct = warmup_count / N_WARMUP
        prog_fill.set_width(pct)
        prog_fill.set_facecolor('#00aaff')
        prog_label.set_text(f'Baseline collection: {warmup_count} / {N_WARMUP} frames  ({int(pct*100)}%)'
                            f'  -- Stand still in front of radar')
        prog_label.set_color('white')
        ax_prog.set_visible(True)
    elif phase == PH_WAIT_TRAIN:
        prog_fill.set_width(1.0)
        prog_fill.set_facecolor('#ffcc00')
        prog_label.set_text(f'Baseline COMPLETE  ({N_WARMUP} / {N_WARMUP} frames)  '
                            f'-- Click  "Start Training"  to proceed')
        prog_label.set_color('#ffdd44')
        ax_prog.set_visible(True)
    elif phase == PH_TRAINING:
        prog_fill.set_width(1.0)
        prog_fill.set_facecolor('#ffaa00')
        prog_label.set_text('Training LSTM-AE model...  Please wait (~20-30 sec)  --  Do not move')
        prog_label.set_color('#ffcc44')
        ax_prog.set_visible(True)
    elif phase == PH_LIVE:
        prog_fill.set_width(1.0)
        prog_fill.set_facecolor('#44ff88')
        prog_label.set_text('LIVE detection active  --  Monitoring for anomalies')
        prog_label.set_color('#44ff88')
        ax_prog.set_visible(True)
    else:
        prog_fill.set_width(0.0)
        prog_label.set_text('')
        ax_prog.set_visible(True)

def make_guide_text(phase, data_ok, ev_active, ev_type, ev_zone, ev_conf, rag_run, sop, warmup_count):
    """Returns the text to show in the action guide / SOP panel."""
    if not data_ok:
        return (
            "======= SETUP GUIDE =======\n\n"
            "  Step 1 (NOT DONE):  Start radar data collection\n\n"
            "  [Jetson Terminal 1]\n"
            "    python3 ~/radar_parser.py\n\n"
            "  Waiting for data file:\n"
            f"    {JSON_PATH}\n\n"
            "  Once radar_parser.py is running,\n"
            "  radar points will appear in the 3D panel\n"
            "  and Step 1 will turn blue."
        )
    if phase == PH_READY:
        return (
            "======= SETUP GUIDE =======\n\n"
            "  Step 1  (DONE):    Radar data is flowing  ✓\n\n"
            "  Step 2  (TODO):    Collect normal baseline\n\n"
            "  >> Click  [ Start Baseline Collection ]  button\n"
            "     at the bottom-left of this window.\n\n"
            "  Then stand still in front of the radar\n"
            "  for ~30 seconds.\n\n"
            "  The system will learn what 'normal' looks like\n"
            "  and then start automatic anomaly detection."
        )
    if phase == PH_WARMUP:
        pct = int(warmup_count / N_WARMUP * 100)
        bars_done  = int(pct / 5)
        bar_str    = '[' + '#' * bars_done + '-' * (20 - bars_done) + ']'
        return (
            "======= BASELINE COLLECTION =======\n\n"
            f"  Progress: {bar_str} {pct}%\n"
            f"  Frames:   {warmup_count} / {N_WARMUP}\n\n"
            "  >> STAND STILL in front of the radar.\n"
            "     Do not move until 100% is reached.\n\n"
            "  The system is recording your normal\n"
            "  radar signature to use as a reference.\n\n"
            "  After collection, training starts automatically."
        )
    if phase == PH_WAIT_TRAIN:
        return (
            "======= BASELINE COMPLETE =======\n\n"
            f"  Collected {N_WARMUP} frames of normal data.  ✓\n\n"
            "  Step 3  (TODO):    Train LSTM-AE model\n\n"
            "  >> Click  [ Start Training (Step 3) ]  button\n"
            "     at the bottom-left of this window.\n\n"
            "  Training takes ~20-30 seconds.\n"
            "  Stand still during training as well.\n\n"
            "  After training, LIVE detection starts automatically."
        )
    if phase == PH_TRAINING:
        return (
            "======= TRAINING IN PROGRESS =======\n\n"
            "  LSTM Autoencoder is learning...\n\n"
            "  >> DO NOT MOVE  (~20-30 sec remaining)\n\n"
            "  The model is fitting to the collected\n"
            "  baseline data to detect anomalies.\n\n"
            "  Detection will start automatically\n"
            "  when training is complete."
        )
    # LIVE
    if sop:
        lines = sop.split('\n')[:22]
        return '\n'.join(lines)
    if rag_run:
        return (
            "======= GENERATING SOP =======\n\n"
            "  Llama3 is generating response...\n"
            "  (Typical: 1-2 minutes)\n\n"
            "  Do not close this window."
        )
    if ev_active and ev_type:
        return (
            f"  ANOMALY DETECTED\n\n"
            f"  Type:  {EVENT_LABELS.get(ev_type, ev_type)}\n"
            f"  Zone:  {ev_zone}\n"
            f"  Conf:  {ev_conf:.0%}\n\n"
            "  Querying safety manual...\n"
            "  SOP guide will appear shortly."
        )
    return (
        "======= LIVE MONITORING =======\n\n"
        "  No anomaly detected.\n\n"
        "  System is monitoring in real-time.\n"
        "  SOP guide will appear automatically\n"
        "  when an anomaly is detected.\n\n"
        "  Use [ Reset Baseline ] button\n"
        "  to recollect normal baseline data."
    )

# ═══════════════════════════════════════════════════════════
# 8. ANIMATION UPDATE
# ═══════════════════════════════════════════════════════════
def update(_i):
    with _lock:
        phase      = state['phase']
        wc         = state['warmup_count']
        pts        = list(state['latest_pts'])
        cz_h       = list(state['cz_h'])
        sc_h       = list(state['sc_h'])
        ev_active  = state['ev_active']
        ev_type    = state['ev_type']
        ev_sev     = state['ev_sev']
        ev_conf    = state['ev_conf']
        ev_zone    = state['ev_zone']
        thr        = state['threshold']
        sop        = state['sop_text']
        rag_run    = state['rag_running']
        logs       = list(state['logs'])
        last_dt    = state['last_data_t']
        data_ok    = state['data_ok']

    xs_t  = list(range(len(cz_h)))
    stale = (time.time() - last_dt > 5.0) if last_dt > 0 else False

    # ---- 3D scatter ----
    if pts:
        xs = [p['x'] for p in pts]; ys = [p['y'] for p in pts]
        zs = [p['z'] for p in pts]; cs = [p['intensity'] for p in pts]
        scatter3d._offsets3d = (xs, ys, zs)
        scatter3d.set_array(np.array(cs, dtype=float))
        cz = float(np.mean(zs)); n = len(pts)
    else:
        cz = 1.7; n = 0

    # ---- Step guide ----
    update_step_guide(phase, data_ok)

    # ---- Progress bar ----
    update_progress_bar(phase, wc)

    # ---- Status bar ----
    sev_col = SEV_COLOR.get(ev_sev, '#44ff88')
    if not data_ok:
        status_box.set_text(
            f'[WAITING]  No radar data file.  '
            f'Run: python3 ~/radar_parser.py  |  Target: {JSON_PATH}')
        status_box.set_color('#ff8800')
        status_box.get_bbox_patch().set_edgecolor('#ff8800')
    elif stale:
        status_box.set_text(
            f'[NO DATA]  Radar data stopped (>5 sec).  Check radar_parser.py  |  Phase: {phase}')
        status_box.set_color('#ff8800')
        status_box.get_bbox_patch().set_edgecolor('#ff8800')
    elif phase == PH_READY:
        status_box.set_text(
            f'[STEP 2]  Radar data OK (Z={cz:.2f}m  pts={n})  '
            f'-- Click  "Start Baseline Collection"  to begin')
        status_box.set_color('#00ccff')
        status_box.get_bbox_patch().set_edgecolor('#00ccff')
    elif phase == PH_WARMUP:
        pct = int(wc / N_WARMUP * 100)
        status_box.set_text(
            f'[STEP 2: COLLECTING]  {wc} / {N_WARMUP} frames  ({pct}%)  '
            f'-- Stand still  |  Z={cz:.2f}m  pts={n}')
        status_box.set_color('#ffcc00')
        status_box.get_bbox_patch().set_edgecolor('#ffcc00')
    elif phase == PH_WAIT_TRAIN:
        status_box.set_text(
            f'[STEP 3 READY]  Baseline complete!  Click  "Start Training"  button  |  Z={cz:.2f}m  pts={n}')
        status_box.set_color('#ffcc00')
        status_box.get_bbox_patch().set_edgecolor('#ffcc00')
    elif phase == PH_TRAINING:
        status_box.set_text(
            f'[STEP 3: TRAINING]  LSTM-AE fitting...  Do not move  |  Z={cz:.2f}m  pts={n}')
        status_box.set_color('#ff8800')
        status_box.get_bbox_patch().set_edgecolor('#ff8800')
    else:
        # LIVE
        if ev_active and ev_type:
            lbl = EVENT_LABELS.get(ev_type, ev_type)
            status_box.set_text(
                f'[ALERT]  {lbl}  |  Zone {ev_zone}  conf={ev_conf:.0%}  '
                f'|  Z={cz:.2f}m  pts={n}')
        else:
            status_box.set_text(
                f'[STEP 4: LIVE - NORMAL]  Z={cz:.2f}m  pts={n}  '
                f'|  score={sc_h[-1]:.5f}  thr={thr:.5f}')
        status_box.set_color(sev_col)
        status_box.get_bbox_patch().set_edgecolor(sev_col)

    # ---- Z timeseries ----
    line_z.set_data(xs_t, cz_h)
    line_z.set_color('#ff4444' if (ev_active and ev_type == 'fall_detected') else '#00ccff')

    # ---- Anomaly score ----
    line_sc.set_data(xs_t, sc_h)
    line_sc.set_color(sev_col)
    if thr > 0:
        thr_line.set_ydata([thr, thr])
        ax_sc.set_ylim(0, max(0.05, float(np.max(sc_h) if sc_h else 0) * 1.3 + 1e-7))

    # ---- Event log ----
    log_text.set_text('\n'.join(logs[-15:]))

    # ---- SOP / Guide panel ----
    guide = make_guide_text(phase, data_ok, ev_active, ev_type,
                            ev_zone, ev_conf, rag_run, sop, wc)
    sop_text.set_text(guide)
    if ev_active and ev_type:
        sop_text.set_color('#ffcccc')
    elif phase == PH_LIVE:
        sop_text.set_color('#ccddee')
    else:
        sop_text.set_color('#aabbcc')

    # btn_start label refresh (defined after button creation in main)
    if '_refresh_btn_label' in globals():
        _refresh_btn_label()
    return scatter3d, line_z, line_sc, status_box, log_text, sop_text, prog_fill, prog_label

# ═══════════════════════════════════════════════════════════
# 9. MAIN
# ═══════════════════════════════════════════════════════════
if __name__ == '__main__':
    print('=' * 65)
    print('  Radar-Guard v3 | Real-time Control System')
    print('=' * 65)
    print(f'  Radar data : {JSON_PATH}')
    print(f'  DB         : {CONN_STR}')
    print(f'  RAG        : {"ENABLED (LangChain)" if RAG_OK else "DISABLED (install LangChain)"}')
    print(f'  Device     : {DEVICE}')
    print(f'  Warmup     : {N_WARMUP} frames of real normal data required')
    print()
    print('  Prerequisites (Jetson terminal):')
    print('    sudo docker start radar-guard-db')
    print('    ollama serve')
    print()
    print('  [Terminal 1]  python3 ~/radar_parser.py')
    print('  [Terminal 2]  python3 ~/radar_live_full.py  <- this')
    print('=' * 65)
    print()

    # ── Buttons ──────────────────────────────────────────
    # Start Baseline (left)
    ax_btn_start = fig.add_axes([0.06, 0.025, 0.26, 0.048])
    btn_start = Button(ax_btn_start,
                       'START Baseline Collection  (Step 2)',
                       color='#0a1a2a', hovercolor='#0d2a4a')
    btn_start.label.set_color('#00ccff')
    btn_start.label.set_fontsize(9)
    btn_start.label.set_fontweight('bold')

    def do_start(_event=None):
        with _lock:
            phase = state['phase']
        ts = datetime.now().strftime('%H:%M:%S')
        if phase == PH_READY:
            with _lock:
                state['start_requested'] = True
                state['logs'].append(f'[{ts}] [BTN] Start Baseline -- stand still!')
            print(f'[{ts}] [BTN] Start Baseline Collection clicked')
        elif phase == PH_WAIT_TRAIN:
            with _lock:
                state['train_requested'] = True
                state['logs'].append(f'[{ts}] [BTN] Start Training -- stand still!')
            print(f'[{ts}] [BTN] Start Training clicked')
        elif phase == PH_WARMUP:
            print('Already collecting baseline...')
        elif phase == PH_TRAINING:
            print('Already training...')
        else:
            print('System is LIVE. Use Reset to recollect baseline.')

    def _refresh_btn_label(_i=None):
        """Update Start button label to match current phase."""
        with _lock:
            phase = state['phase']
        if phase == PH_READY:
            btn_start.label.set_text('START Baseline Collection  (Step 2)')
            btn_start.label.set_color('#00ccff')
        elif phase == PH_WARMUP:
            btn_start.label.set_text('Collecting baseline...  (stand still)')
            btn_start.label.set_color('#888888')
        elif phase == PH_WAIT_TRAIN:
            btn_start.label.set_text('START Training  (Step 3)  -- click here!')
            btn_start.label.set_color('#ffdd00')
        elif phase == PH_TRAINING:
            btn_start.label.set_text('Training in progress...  (stand still)')
            btn_start.label.set_color('#888888')
        else:
            btn_start.label.set_text('LIVE  -- Use Reset to recollect')
            btn_start.label.set_color('#44ff88')

    btn_start.on_clicked(do_start)

    # Reset Baseline (right)
    ax_btn_reset = fig.add_axes([0.67, 0.025, 0.26, 0.048])
    btn_reset = Button(ax_btn_reset,
                       'RESET Baseline  (recollect normal data)',
                       color='#1a0a0a', hovercolor='#3a0a0a')
    btn_reset.label.set_color('#ff8866')
    btn_reset.label.set_fontsize(9)

    def do_reset(_event=None):
        with _lock:
            state['reset_requested'] = True
        print(f'[{datetime.now().strftime("%H:%M:%S")}] [BTN] Reset -- returning to READY')

    btn_reset.on_clicked(do_reset)

    # ── Start pipeline thread ─────────────────────────────
    t = threading.Thread(target=pipeline_loop, daemon=True)
    t.start()

    add_log('System started -- waiting for radar data')
    add_log(f'Data path: {JSON_PATH}')

    ani = FuncAnimation(fig, update, interval=UPDATE_MS,
                        blit=False, cache_frame_data=False)
    plt.show()
