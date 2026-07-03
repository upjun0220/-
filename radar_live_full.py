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
    RAG_OK = True
except ImportError:
    RAG_OK = False

# ═══════════════════════════════════════════════════════════
# 1. CONFIG
# ═══════════════════════════════════════════════════════════
JSON_PATH     = '/home/project/stage1_filtered.json'
CLF_LOG_PATH  = '/home/project/clf_decisions.jsonl'   # classify 판정 로그(문턱 튜닝용)

# ── 정지형(협착/감전) Zone + 지속시간 게이트 (2026-07-02 3차 패치) ──
# 실측 확정: 레이더 feature만으론 '서있는 사람(n 3~5, ds 0.19~0.31)'과
# '끼인/감전 사람(라이브 n 4~7, ds 0.28~0.33)' 구분 불가.
# -> 위험 Zone 안에서 저동작 정지가 STAT_HOLD_SEC 지속되면 경보 (산업안전 논리).
# 좌표는 바닥평면 (x, z) [m], 천장 레이더 원점 기준. ⚠️ 현장 실측으로 조정할 것.
DANGER_ZONES = {
    'B': {'x': (-2.0, 2.0), 'z': (-2.0, 2.0), 'label': 'TEST-ALL(임시: 전체시야)'},
    # 데모 후 실제 Zone으로 축소. 예: 'A': {'x': (0.5, 1.5), 'z': (-0.5, 0.8), 'label': '배전반'},
}
STAT_N_MIN    = 4      # 사람 존재 최소 포인트 (빈공간 차단 문턱과 동일)
STAT_DS_MIN   = 0.10   # [7/3 패치] 생체 존재 하한: 사람은 호흡·미세동요로 프레임 dop_std가
                       # 절대 0.17 밑으로 안 내려감(실측 1000프레임). 정적 클러터(매트·꺼진
                       # 선풍기·케이블)는 ~0 -> 빈 공간 PRE-ALERT 오탐 차단 (TI 재실감지 원리)
STAT_DS_MAX   = 0.35   # 저동작: 프레임 dop_std < 이 값 (정지·미세움직임. 보행 0.43+)
# 2단계 경보 (산업 man-down 장비 표준 방식: pre-alert -> escalation).
# 설비 앞 정당한 정지 작업의 오경보 방지: 1차는 경고만(움직이면 자동 취소),
# 계속 무동작이면 2차 critical latch. 상용 장비 무동작 타이머는 1분~수시간 설정형 --
# 아래 값은 데모용 축소값이며 실배치 시 상향 필요.
STAT_PRE_SEC  = 15.0   # 1차: Zone 내 정지 이만큼 지속 -> PRE-ALERT 로그(경고, 비latch)
STAT_CRIT_SEC = 30.0   # 2차: 계속 무동작 -> stationary 경보(critical, latch)
MAINT_MODE    = False  # True = 계획 정비 중(LOTO/작업허가) -> 정지형 경보 억제
STAT_MISS_TOL = 5      # 조건 이탈 프레임 이만큼 연속되면 타이머 리셋 (~0.5s 튐 용인)
CONN_STR      = 'postgresql://postgres:password@localhost:5432/radar_guard'

# ── (옵션) 경량 LLM 요약 — 수행계획서 '생성형 AI 조치 가이드' 복원용 ──
# llama3:8b(Q4 4.9GB)는 Orin Nano 8GB 공유메모리에서 OOM 프리징 유발(실측).
# llama3.2:3b(Q4 2.0GB)는 같은 Llama 3 계열로 메모리 버짓 내 동작(README 분석 참조).
# 사용법: 젯슨에서 `ollama pull llama3.2:3b` + 단독 테스트 통과 후 True로.
# False면 기존과 100% 동일(검색 전용) -> 시연 안전 기본값.
USE_LLM_SUMMARY = False
LLM_MODEL       = 'llama3.2:3b'

N_WARMUP      = 150      # real frames for normal baseline (~15 sec at 10 fps)
CEILING_H     = 2.30     # 천장(센서)~바닥 실측 거리(m). height = CEILING_H - y(range)
FEATURE_DIM   = 8
SEQ_LEN       = 5        # LSTM-AE 입력 시퀀스 길이
CLF_WIN       = 20       # 규칙 classify 집계 창(~2s). 실측 문턱이 20프레임 기준이라 별도 유지
HISTORY_LEN   = 120
CONFIRM_FRAMES = 3       # 이상이 이만큼 연속돼야 경보 latch (순간 움직임 디바운스)
CONFIRM_EVENTS = 3       # non-fall 판정이 이만큼 '연속 동일'해야 latch (전이 오탐 억제, ~수 초)
POLL_SEC      = 0.4
UPDATE_MS     = 1000
DEBUG_TIMING  = True     # print per-update loop time to terminal (진단용)
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
    'stationary_anomaly':  'STATIONARY ANOMALY (VERIFY: SHOCK/ENTRAPMENT)',
    'electric_shock_risk': 'ELECTRIC SHOCK RISK',
    'pinching':            'PINCHING / ENTRAPMENT',
    'vibration_anomaly':   'VIBRATION ANOMALY',
}
EVENT_ZONE = {
    'fall_detected': 'C', 'stationary_anomaly': 'B',
    'electric_shock_risk': 'A', 'pinching': 'B', 'vibration_anomaly': 'C',
}
EVENT_CATEGORY = {
    'fall_detected':       '03_naksan_eunggeupcheo',
    'electric_shock_risk': '01_gamjeon_LOTO',
    'pinching':            '02_hyeopcak_kkim',
    'vibration_anomaly':   '04_yeji_boen',
}
SEV_COLOR = {'normal': '#44ff88', 'warning': '#ffaa00', 'critical': '#ff3333'}

# 사고 이력 패널용 짧은 라벨 (좁은 칸에 맞게)
EVENT_SHORT = {
    'fall_detected':      'FALL',
    'stationary_anomaly': 'STATIONARY (verify)',
    'electric_shock_risk':'SHOCK',
    'pinching':           'PINCH',
    'vibration_anomaly':  'VIBRATION',
}

# 이벤트 발생 즉시(몇 초 내) 띄우는 하드코딩 첫 조치.
# 상세 매뉴얼(pgvector 검색 원문, 몇 초)은 그 아래에 나중에 붙는다. 응급 UX용.
INSTANT_ACTION = {
    'fall_detected': (
        "[IMMEDIATE]  FALL DETECTED\n"
        "  1. Check consciousness / breathing\n"
        "  2. DO NOT move victim (spinal risk)\n"
        "  3. Cut nearby hazards; secure area\n"
        "  4. Call emergency; monitor until help\n"
    ),
    'stationary_anomaly': (
        "[IMMEDIATE]  STATIONARY ANOMALY (verify: shock/entrapment)\n"
        "  1. Before approach: confirm power OFF (LOTO)\n"
        "     -- if shock: NO bare-hand contact\n"
        "  2. If entrapment: NO forced pulling\n"
        "  3. Call emergency\n"
        "  4. Verify type on-site, then follow SOP\n"
    ),
    'vibration_anomaly': (
        "[CHECK]  Vibration / minor anomaly\n"
        "  - Visual check the zone\n"
    ),
}
def instant_action(ev_type):
    return INSTANT_ACTION.get(ev_type, f"[ALERT] {EVENT_LABELS.get(ev_type, ev_type)}\n")

# ═══════════════════════════════════════════════════════════
# 2. PIPELINE CLASSES
# ═══════════════════════════════════════════════════════════
class LMSFilter:
    def __init__(self, order=8, mu=0.008):
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
    """천장 설치 + 실측 데이터(events_collect.jsonl, 50샘플) 기반 규칙 분류.

    좌표계: y = 센서 아래로의 거리(range). height = CEILING_H - y.
    feat 벡터 = [cx, cy(=y), cz, mean_dop, dop_std, int_mean, n_pts, z_vel].

    실측으로 확정한 판별치 (원본 50샘플 50/50, 2026-07-02 라이브 오탐 패치 반영):
      - FALL        : 프레임 dop_std 피크 >= 1.2  (낙상 격렬함; 다른 동작 전부 <=1.16)
      - WALK(양성)  : n_p75 >= 15                (평균 대신 75백분위 - 전이/가장자리 희석에 강함)
      - 정지형 이상 : classify에서 제거 -> Zone+지속시간 게이트로 이관 (3차 패치)
      - 진동 경고   : 창 전반부+후반부 dop_std 평균 둘 다 >= 0.40 (지속성 요구)
      - 그 외       : 빠른앉기/정상/일과성 동작 -> 정상

    중요: 낙상은 '높이가 0으로 떨어짐'이 아니라 '도플러 격렬함'으로 잡힘(실측 확인).
          천장 레이더는 쓰러진 사람 centroid 높이가 ~1.4m로 유지됨.
    """
    win = [f for f in feat_win if float(f[6]) > 0]        # n_pts>0 프레임만 집계
    if not win:
        return {'event_type': 'normal', 'severity': 'normal', 'confidence': 0.0}

    ds_list     = [float(f[4]) for f in win]
    n_list      = [float(f[6]) for f in win]
    dopstd_max  = max(ds_list)
    dopstd_mean = sum(ds_list) / len(ds_list)   # 지속적 움직임 세기(순간 스파이크에 둔감)
    n_mean      = sum(n_list) / len(n_list)
    n_p75       = float(np.percentile(n_list, 75))          # 상위 프레임 포인트수(가장자리/전이 희석에 강함)
    half        = max(1, len(ds_list) // 2)
    ds_first    = sum(ds_list[:half]) / half                 # 창 전반부 평균
    ds_last     = sum(ds_list[half:]) / max(1, len(ds_list) - half)  # 창 후반부 평균
    cy_vals     = [float(f[1]) for f in win]
    h_drop      = max(cy_vals) - min(cy_vals)               # height=C-y 이므로 y범위 = 높이변화폭

    excess = score / thr if thr > 0 else 1.0
    conf   = round(min(0.99, 0.55 + 0.20 * min(1.0, max(0.0, excess - 1.0))), 2)

    # 0) 빈 공간 / 노이즈: 포인트 거의 없음 -> 무조건 정상.
    #    (케이블이 한 프레임 튀어도 여기서 차단 -> 빈방 오경보 방지)
    if n_mean < 4:
        return {'event_type': 'normal', 'severity': 'normal', 'confidence': 0.0}

    # 1) 낙상 -- 격렬한 움직임 피크 + 사람 존재 (실측 10/10, 오검출 0)
    if dopstd_max >= 1.2 and n_mean >= 5:
        return {'event_type': 'fall_detected', 'severity': 'critical',
                'confidence': round(min(0.99, conf + 0.10), 2)}

    # 2) [2026-07-02 3차 패치] 정지형(협착/감전) 규칙은 classify에서 제거됨.
    #    옛 규칙(dop_std<0.6, 8<=n_mean<18)은 라이브에서 n이 4~7로 잡혀 미달했고,
    #    n 하한을 내리면 '가만히 서있기'와 구분 불가(feature 동일 - 실측 확인).
    #    -> pipeline_loop의 Zone+지속시간 게이트(DANGER_ZONES, STAT_HOLD_SEC)가 담당.

    # 3) 보행 / 정상 활동 -> 경보 없음
    #    [2026-07-02 패치] n_mean>=18 -> n_p75>=15: 라이브에선 FOV 가장자리/전이
    #    프레임이 섞여 평균이 희석됨(실측 walk 24~38이 라이브에선 절반까지 하락).
    #    "일부 프레임이라도 포인트가 많으면 사람 활동"으로 인정.
    if n_p75 >= 15:
        return {'event_type': 'normal', 'severity': 'normal', 'confidence': 0.0}

    # 4) 지속적 동요만 경고 -- 창 전반부/후반부 '둘 다' 0.40 이상이어야 진동.
    #    [2026-07-02 패치] 걷기 dop_std 평균(0.41~0.48)이 문턱 0.40 바로 위라
    #    보행/앉기 전이 창이 평균만으로 진동에 걸렸음. 진동은 정의상 지속적
    #    -> 창 양쪽 절반 모두에서 유지될 때만 인정 (앉기 등 일과성 동작 제외).
    if ds_first >= 0.40 and ds_last >= 0.40:
        return {'event_type': 'vibration_anomaly', 'severity': 'warning',
                'confidence': round(min(0.75, 0.40 + 0.10 * excess), 2)}

    # 5) 그 외 (미미한 움직임) -> 정상
    return {'event_type': 'normal', 'severity': 'normal', 'confidence': 0.0}

# ═══════════════════════════════════════════════════════════
# 3. SHARED STATE
# ═══════════════════════════════════════════════════════════
_lock = threading.RLock()   # RLock: 같은 스레드의 재진입 허용 (add_log 중첩 데드락 방지)
state = {
    'phase':             PH_READY,
    'warmup_count':      0,
    'start_requested':   False,
    'train_requested':   False,
    'reset_requested':   False,
    'resolve_requested': False,   # 사람이 Event Resolved 버튼 누름 -> latch된 경보 해제
    'latest_pts':       [],
    'cz_h':   deque([1.7] * HISTORY_LEN, maxlen=HISTORY_LEN),
    'sc_h':   deque([0.0] * HISTORY_LEN, maxlen=HISTORY_LEN),
    'ds_h':   deque([0.0] * HISTORY_LEN, maxlen=HISTORY_LEN),   # dop_std(떨림/진동) 히스토리
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
    'instant_sop': '',   # 이벤트 즉시 첫 조치(하드코딩). RAG 상세 SOP가 아래 붙음
    'pre_alert':   '',   # 정지형 1차 PRE-ALERT 배너 텍스트 (노란색, 비latch, 카운트다운)
    'logs': deque(maxlen=20),
    'incidents': deque(maxlen=20),   # 사고 이력: {type, zone, detected, resolved}
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
        instant = state.get('instant_sop', '')           # 즉시 조치는 항상 상단 유지
        state['sop_text'] = instant + '\n>> Searching safety manual...'

    if not RAG_OK:
        with _lock:
            state['sop_text']    = instant + '\n[Detailed SOP unavailable: LangChain not installed]'
            state['rag_running'] = False
        return

    try:
        # 검색만: 임베딩(nomic, 가벼움) + pgvector 유사도 검색. LLM 생성 없음.
        # -> llama3:8b를 안 돌리므로 젯슨 프리징(OOM) 원인 제거.
        emb  = OllamaEmbeddings(model='nomic-embed-text')
        vs   = PGVector(connection_string=CONN_STR, embedding_function=emb,
                        collection_name='safety_manual')
        docs = vs.similarity_search(situation, k=2,
               filter={'category': category}) if category \
               else vs.similarity_search(situation, k=2)
        if not docs:
            with _lock:
                state['sop_text']    = instant + f'\n[Manual: no match for category {category}]'
                state['rag_running'] = False
            return
        # 검색된 매뉴얼 원문 조각을 그대로 표시 (LLM 재작성 없음)
        excerpts = []
        for i, d in enumerate(docs, 1):
            src  = d.metadata.get('source_file', '?')
            body = ' '.join(d.page_content.split())[:360]     # 공백 정리 + 길이 제한
            excerpts.append(f'[{i}] ({src})\n{textwrap.fill(body, width=WRAP_WIDTH)}')
        manual = '\n\n'.join(excerpts)
        with _lock:
            state['sop_text']    = (instant +
                f'\n=== Manual (retrieved, top {len(docs)}) ===\n\n{manual}')
            state['rag_running'] = False
        add_log(f'Manual retrieved ({len(docs)} chunk) - retrieval-only, no LLM')

        # ── (옵션) 경량 LLM 요약: 검색 원문 표시 "후"에 별도로 시도 ──
        # 실패해도 위 검색 결과는 이미 화면에 있으므로 시연에 영향 없음.
        # 켜는 조건: 젯슨에 llama3.2:3b 설치 + 단독 테스트 통과 + USE_LLM_SUMMARY=True.
        if USE_LLM_SUMMARY:
            try:
                llm = ChatOllama(model=LLM_MODEL, temperature=0.2,
                                 num_ctx=1024,      # 컨텍스트 축소 -> 메모리 절약
                                 num_predict=180,   # 짧은 요약만 생성
                                 keep_alive=0)      # 생성 후 즉시 언로드 -> 상시 점유 방지
                ctx = ' '.join(d.page_content for d in docs)[:1500]
                out = llm.invoke(
                    f'상황: {situation}\n아래 안전 매뉴얼 발췌를 근거로, 현장 작업자가 '
                    f'지금 즉시 따라야 할 조치를 한국어 3~4줄로 요약하라:\n{ctx}'
                ).content.strip()
                with _lock:
                    state['sop_text'] += (f'\n\n=== AI summary ({LLM_MODEL}) ===\n'
                                          + textwrap.fill(out, width=WRAP_WIDTH))
                add_log(f'LLM summary appended ({LLM_MODEL})')
            except Exception as e:
                add_log(f'LLM summary skipped: {e}')   # 검색 결과는 유지됨

    except Exception as e:
        with _lock:
            state['sop_text']    = instant + f'\n[Manual search error: {e}]\n  check: docker start radar-guard-db / ollama serve'
            state['rag_running'] = False
        add_log(f'RAG error: {e}')

# ═══════════════════════════════════════════════════════════
# 5. PIPELINE THREAD
# ═══════════════════════════════════════════════════════════
def pipeline_loop():
    lms         = LMSFilter()
    feat_buf    = []
    clf_buf     = []          # 규칙 classify용 장기 히스토리(~CLF_WIN 프레임)
    warmup_feat = []
    prev_c      = None
    anom_streak = 0           # 연속 이상 프레임 수 (디바운스)
    pend_et     = None        # non-fall 경보 후보 (연속 판정 확인용)
    pend_cnt    = 0           # 같은 판정이 연속으로 나온 횟수
    stat_since  = None        # 위험 Zone 내 정지 시작 시각 (Zone+지속시간 게이트)
    stat_miss   = 0           # 정지 조건 연속 이탈 프레임 수
    stat_zone   = None        # 현재 정지 중인 Zone id
    stat_pre    = False       # 1차 PRE-ALERT 발화 여부 (2단계 경보)
    stat_log_t  = 0.0         # 게이트 상태 로그 rate-limit (~2초마다)
    read_offset = 0
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
                state['instant_sop']     = ''
                state['pre_alert']       = ''
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
            clf_buf     = []
            warmup_feat = []
            prev_c      = None
            anom_streak = 0
            pend_et     = None
            pend_cnt    = 0
            stat_since  = None
            stat_miss   = 0
            stat_zone   = None
            stat_pre    = False
            model       = None
            scaler      = None
            thr         = 0.01
            read_offset = 0      # re-read JSONL stream from start

        time.sleep(POLL_SEC)

        # ── Load new frames (JSONL, offset-based tail read) ──
        # 전체 파일을 다시 파싱하지 않고, 지난번 읽은 위치(read_offset)
        # 이후의 새 줄만 읽는다. -> 파일이 아무리 커져도 비용 일정.
        no_file = not os.path.exists(JSON_PATH)
        with _lock:
            state['data_ok'] = not no_file
        if no_file:
            continue

        try:
            fsize = os.path.getsize(JSON_PATH)
        except OSError:
            continue
        if fsize < read_offset:
            read_offset = 0          # 파서 재시작(파일 초기화) 감지 -> 처음부터

        try:
            with open(JSON_PATH, 'rb') as f:
                f.seek(read_offset)
                chunk = f.read()
        except OSError:
            continue

        if not chunk:
            continue

        # 마지막 완전한 줄까지만 소비 (쓰는 도중의 partial line 방지)
        last_nl = chunk.rfind(b'\n')
        if last_nl == -1:
            continue                 # 아직 완전한 줄 없음
        read_offset += last_nl + 1

        new_frames = []
        for line in chunk[:last_nl + 1].split(b'\n'):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            new_frames.append(rec.get('points', []))

        if not new_frames:
            continue

        for frame_pts in new_frames:
            if not frame_pts:
                # 빈 프레임 = 사람 없음 -> Zone 정지 타이머도 이탈 처리
                stat_miss += 1
                if stat_miss >= STAT_MISS_TOL:
                    stat_since = None; stat_zone = None; stat_pre = False
                continue

            with _lock:
                state['latest_pts']  = frame_pts
                state['last_data_t'] = time.time()

            ys  = [p['y'] for p in frame_pts]
            cz  = CEILING_H - (float(np.mean(ys)) if ys else CEILING_H)  # 천장기준 높이(바닥 위 높이)
            n   = len(frame_pts)
            feat = extract_features(frame_pts, prev_c)
            ref     = float(np.random.normal(0, 0.004))
            feat[3] = lms.filter(feat[3], ref)
            prev_c  = feat[:3].copy()

            with _lock:
                state['cz_h'].append(cz)
                state['cnt_h'].append(n)
                state['ds_h'].append(float(feat[4]))   # dop_std(떨림/진동 세기)

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
                        newly_done = state['phase'] != PH_WAIT_TRAIN
                        if newly_done:
                            state['phase'] = PH_WAIT_TRAIN
                    if newly_done:   # add_log는 락 밖에서 호출 (락 중첩 방지)
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
            clf_buf.append(feat.tolist())          # 규칙 classify용 장기 창
            if len(clf_buf) > CLF_WIN:
                clf_buf.pop(0)

            # ── 정지형(협착/감전) Zone+지속시간 게이트 (매 프레임, AE와 독립) ──
            # 조건: 위험 Zone 안 + 사람 존재(n>=4) + 저동작(ds<0.35) 지속.
            _n, _ds = float(feat[6]), float(feat[4])
            _cx, _czf = float(feat[0]), float(feat[2])   # 바닥평면 (x, z)
            _zone_hit = None
            for _zid, _zc in DANGER_ZONES.items():
                if _zc['x'][0] <= _cx <= _zc['x'][1] and _zc['z'][0] <= _czf <= _zc['z'][1]:
                    _zone_hit = _zid
                    break
            if MAINT_MODE:
                stat_since = None; stat_zone = None; stat_pre = False   # 계획 정비: 억제
                with _lock:
                    state['pre_alert'] = ''
            elif _zone_hit and _n >= STAT_N_MIN and STAT_DS_MIN < _ds < STAT_DS_MAX:
                if stat_since is None:
                    stat_since = time.time()
                    stat_zone  = _zone_hit
                stat_miss = 0
                # 1차 PRE-ALERT (경고, 비latch): 움직이면 자동 취소됨
                _dwell = time.time() - stat_since
                # [게이트 상태 로그] 오탐 시 어떤 물체(위치·특성)가 타이머를 돌렸는지 확정용
                if time.time() - stat_log_t >= 2.0:
                    stat_log_t = time.time()
                    try:
                        with open(CLF_LOG_PATH, 'a') as _lf:
                            _lf.write(json.dumps({
                                't': round(time.time(), 2), 'type': 'stat_gate',
                                'zone': stat_zone, 'dwell': round(_dwell, 1),
                                'n': _n, 'ds': round(_ds, 3),
                                'cx': round(_cx, 2), 'cz': round(_czf, 2),
                                'height': round(CEILING_H - float(feat[1]), 2),
                                'inten': round(float(feat[5])),
                            }) + '\n')
                    except Exception:
                        pass
                if not stat_pre and _dwell >= STAT_PRE_SEC:
                    stat_pre = True
                    add_log(f'PRE-ALERT Zone {stat_zone}: no-motion {int(_dwell)}s '
                            f'-- move to cancel ({int(STAT_CRIT_SEC - _dwell)}s to CRITICAL)')
                if stat_pre:
                    # 화면 배너(노란색)에 실시간 카운트다운 표시
                    _remain = max(0, int(STAT_CRIT_SEC - _dwell))
                    with _lock:
                        state['pre_alert'] = (f'PRE-ALERT  Zone {stat_zone}: no-motion {int(_dwell)}s'
                                              f'  --  MOVE to cancel  ({_remain}s to CRITICAL)')
            else:
                stat_miss += 1
                if stat_miss >= STAT_MISS_TOL:
                    if stat_pre:
                        add_log(f'PRE-ALERT cleared Zone {stat_zone}: motion resumed')
                    stat_since = None; stat_zone = None; stat_pre = False
                    with _lock:
                        state['pre_alert'] = ''

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
                ts = datetime.now().strftime('%H:%M:%S')

                # ── 수동 해제 (사람이 Event Resolved 버튼) ─────────────
                # 경보는 자동으로 안 꺼진다: 넘어진 사람은 가만히 있어서
                # 'score 정상 복귀 = 해결'로 판단하면 안 됨. 사람이 확인해야 해제.
                if state['resolve_requested']:
                    state['resolve_requested'] = False
                    if state['ev_active']:
                        et = state['ev_type']; zn = state['ev_zone']
                        lbl = EVENT_LABELS.get(et, et)
                        state.update({
                            'ev_active': False, 'ev_type': None,
                            'ev_sev': 'normal', 'ev_conf': 0.0,
                            'norm_count': 0, 'sop_text': '', 'instant_sop': '',
                        })
                        for inc in reversed(state['incidents']):   # 최근 미해제 사고에 해제시각 기록
                            if inc['resolved'] is None:
                                inc['resolved'] = ts
                                break
                        state['logs'].append(f'[{ts}] RESOLVED Zone {zn}: {lbl} (manual ack)')

                is_anomaly = score > thr

                # 디바운스: 이상이 CONFIRM_FRAMES 연속돼야 경보 latch.
                # (순간 움직임/떨림은 몇 프레임 못 넘겨 무시됨 -> 오탐 감소)
                # 새 이벤트는 현재 latch된 경보가 없을 때만 포착(사고 대응에 집중).
                if is_anomaly and not state['ev_active']:
                    anom_streak += 1
                else:
                    anom_streak = 0

                if anom_streak >= CONFIRM_FRAMES:
                    anom_streak = 0
                    fw  = np.array(clf_buf, dtype=np.float32)   # ~20프레임 창으로 규칙 판별
                    clf = classify(fw, score, thr)
                    et  = clf['event_type']
                    raw_et = et                                  # 규칙의 원판정 (latch 확정 전)

                    # [판정 로그] 모든 classify 호출을 기록 -> 미검출/오탐 원인 확정용.
                    # 로그가 아예 안 쌓이면 AE 게이트에서 막힌 것, 쌓이는데 normal이면 규칙 문턱 문제.
                    try:
                        _w  = fw[fw[:, 6] > 0]
                        if len(_w) >= 2:
                            _ds = _w[:, 4]; _n = _w[:, 6]; _h = max(1, len(_ds)//2)
                            with open(CLF_LOG_PATH, 'a') as _lf:
                                _lf.write(json.dumps({
                                    't': round(time.time(), 2),
                                    'verdict': raw_et, 'pend': f'{pend_et}:{pend_cnt}',
                                    'ds_max': round(float(_ds.max()), 3),
                                    'ds_first': round(float(_ds[:_h].mean()), 3),
                                    'ds_last': round(float(_ds[_h:].mean()), 3),
                                    'n_mean': round(float(_n.mean()), 1),
                                    'n_p75': round(float(np.percentile(_n, 75)), 1),
                                    'h_drop': round(float(_w[:, 1].max() - _w[:, 1].min()), 3),
                                    'score_x': round(score / thr if thr > 0 else 0, 2),
                                }) + '\n')
                    except Exception:
                        pass   # 로깅 실패가 파이프라인을 죽이면 안 됨

                    # [2026-07-02 패치] 경보는 latch(수동 해제)라 오탐 1번이 계속
                    # 유지됨. 낙상(일회성 사건)은 즉시 latch, 나머지(진동/정지형
                    # = 지속 상태)는 같은 판정이 CONFIRM_EVENTS번 연속돼야 latch
                    # -> 보행/앉기 전이 창이 우연히 1번 걸려도 경보 안 됨.
                    if et == 'normal':
                        pend_et, pend_cnt = None, 0   # 정상 판정 -> 후보 리셋
                    elif et != 'fall_detected':
                        if et == pend_et:
                            pend_cnt += 1
                        else:
                            pend_et, pend_cnt = et, 1
                        if pend_cnt < CONFIRM_EVENTS:
                            et = 'normal'             # 아직 확정 아님 -> 경보 보류
                        else:
                            pend_et, pend_cnt = None, 0

                    if et == 'normal':
                        pass   # 빈 공간/정지/정상/보행/미확정 -> 경보 만들지 않음 (오탐 방지)
                    else:
                        zn  = EVENT_ZONE.get(et, 'C')
                        instant = instant_action(et)          # 즉시 첫 조치(몇 초 내 표시)
                        state.update({
                            'ev_active': True, 'ev_type': et,
                            'ev_sev': clf['severity'],
                            'ev_conf': clf['confidence'],
                            'ev_zone': zn,
                            'instant_sop': instant,
                            'sop_text': instant + '\n>> Searching safety manual (pgvector)...',
                        })
                        lbl = EVENT_LABELS.get(et, et)
                        msg = f'ALERT Zone {zn}: {lbl} (conf={clf["confidence"]:.0%} score={score/thr:.1f}x)'
                        state['logs'].append(f'[{ts}] {msg}')
                        state['incidents'].append({           # 사고 이력 기록
                            'type': et, 'zone': zn, 'detected': ts, 'resolved': None})
                        if not state['rag_running'] and RAG_OK:
                            state['rag_running'] = True
                            threading.Thread(target=run_rag, args=(et, zn), daemon=True).start()

                # ── 정지형 2차 경보: PRE-ALERT 후에도 무동작 지속 -> critical latch ──
                if (stat_since is not None and not state['ev_active']
                        and time.time() - stat_since >= STAT_CRIT_SEC):
                    et2 = 'stationary_anomaly'
                    zn2 = stat_zone or EVENT_ZONE.get(et2, 'B')
                    dwell = time.time() - stat_since
                    stat_since = None; stat_zone = None; stat_miss = 0; stat_pre = False
                    state['pre_alert'] = ''          # PRE-ALERT 배너 -> critical 경보로 승격
                    instant2 = instant_action(et2)
                    state.update({
                        'ev_active': True, 'ev_type': et2,
                        'ev_sev': 'critical',
                        'ev_conf': 0.85,   # human-in-the-loop: 현장 확인 필요
                        'ev_zone': zn2,
                        'instant_sop': instant2,
                        'sop_text': instant2 + '\n>> Searching safety manual (pgvector)...',
                    })
                    lbl2 = EVENT_LABELS.get(et2, et2)
                    state['logs'].append(
                        f'[{ts}] ALERT Zone {zn2}: {lbl2} (no-motion {dwell:.0f}s in danger zone)')
                    state['incidents'].append({
                        'type': et2, 'zone': zn2, 'detected': ts, 'resolved': None})
                    if not state['rag_running'] and RAG_OK:
                        state['rag_running'] = True
                        threading.Thread(target=run_rag, args=(et2, zn2), daemon=True).start()
                # else: 경보 latch 유지 (자동 해제 없음)

def pipeline_loop_safe():
    """pipeline_loop을 감싸 예외를 터미널에 출력(+재시작).
    파이프라인 스레드가 예외로 조용히 죽으면 warmup이 멈추고 Reset도
    안 먹는(플래그를 읽을 스레드가 없으므로) 증상이 난다 → 여기서 추적."""
    import traceback
    while True:
        try:
            pipeline_loop()
        except Exception as e:
            print('\n[PIPELINE-CRASH] ==================================')
            print(f'[PIPELINE-CRASH] {type(e).__name__}: {e}')
            traceback.print_exc()
            print('[PIPELINE-CRASH] 3초 후 재시작...\n')
            time.sleep(3.0)


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

# ── Active Alarm Banner (latched; cleared only by Event Resolved) ──
alarm_banner = fig.text(0.5, 0.086, '', color='white', fontsize=10,
                        va='center', ha='center', fontfamily='monospace',
                        fontweight='bold', visible=False,
                        bbox=dict(boxstyle='round,pad=0.45', facecolor='#3a0000',
                                  edgecolor='#ff3333', linewidth=1.6, alpha=0.97))

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
ax3d.set_ylabel('Z floor (m)', color='#8899bb', fontsize=7, labelpad=1)
ax3d.set_zlabel('Height (m)', color='#8899bb', fontsize=7, labelpad=1)
ax3d.tick_params(colors='#556677', labelsize=6)
ax3d.set_xlim(-2, 2); ax3d.set_ylim(-2, 2); ax3d.set_zlim(0, 2.5)
for pn in (ax3d.xaxis.pane, ax3d.yaxis.pane, ax3d.zaxis.pane):
    pn.fill = False; pn.set_edgecolor('#1a1a33')
scatter3d = ax3d.scatter([], [], [], c=[], cmap='plasma',
                          vmin=200, vmax=600, s=16, alpha=0.85)

# -- Panel 2: Centroid Z timeseries --
ax_z = fig.add_subplot(gs[0, 1], facecolor='#08081a')
ax_z.set_title('Centroid Height  (CEILING_H - y;  fall = doppler)', color='white', fontsize=8, pad=3)
ax_z.set_ylim(0, 2.5); ax_z.set_xlim(0, HISTORY_LEN)
ax_z.axhline(1.70, color='#44cc66', lw=0.8, ls=':', alpha=0.55)
ax_z.axhline(0.0,  color='#8899bb', lw=0.8, ls=':', alpha=0.4)
ax_z.text(2, 1.76, 'Standing ~1.7m', color='#44cc66', fontsize=7)
ax_z.text(2, 0.08, 'Floor 0m', color='#8899bb', fontsize=7)
for sp in ax_z.spines.values(): sp.set_color('#1a1a33')
ax_z.tick_params(colors='#556677', labelsize=7)
ax_z.set_xlabel('Frames', color='#8899bb', fontsize=7)
ax_z.set_ylabel('Height (m)',  color='#8899bb', fontsize=7)
line_z, = ax_z.plot([], [], color='#00ccff', lw=1.8)

# -- Panel 3: Anomaly Score --
ax_sc = fig.add_subplot(gs[0, 2], facecolor='#08081a')
ax_sc.set_title('Motion / Vibration  (dop_std)', color='white', fontsize=8, pad=3)
ax_sc.set_xlim(0, HISTORY_LEN); ax_sc.set_ylim(0, 2.0)
for sp in ax_sc.spines.values(): sp.set_color('#1a1a33')
ax_sc.tick_params(colors='#556677', labelsize=7)
ax_sc.set_xlabel('Frames', color='#8899bb', fontsize=7)
ax_sc.set_ylabel('dop_std', color='#8899bb', fontsize=7)
line_sc, = ax_sc.plot([], [], color='#ffaa00', lw=1.8)
thr_line  = ax_sc.axhline(1.2, color='#ff4444', ls='--', lw=1.1, alpha=0.85, label='fall thr 1.2')
ax_sc.text(2, 0.62, 'stationary/vib', color='#88aacc', fontsize=6)
ax_sc.legend(loc='upper right', fontsize=7,
             facecolor='#08081a', edgecolor='#334455', labelcolor='white')

# -- Panel 4: Event Log --
ax_log = fig.add_subplot(gs[1, 0], facecolor='#060614')
ax_log.set_title('Incident History', color='white', fontsize=8, pad=3)
ax_log.axis('off')
log_text = ax_log.text(0.02, 0.97, '', transform=ax_log.transAxes,
                        color='#aabbcc', fontsize=7, va='top',
                        fontfamily='monospace')

# -- Panel 5: SOP / Guide Panel --
ax_sop = fig.add_subplot(gs[1, 1:])
ax_sop.set_facecolor('#04040e')
ax_sop.set_title('Action Guide  /  SOP (instant + pgvector retrieval)',
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
            "======= RETRIEVING SOP =======\n\n"
            "  Searching safety manual (pgvector)...\n"
            "  (retrieval-only, a few seconds)\n\n"
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
        ds_h       = list(state['ds_h'])
        ev_active  = state['ev_active']
        ev_type    = state['ev_type']
        ev_sev     = state['ev_sev']
        ev_conf    = state['ev_conf']
        ev_zone    = state['ev_zone']
        thr        = state['threshold']
        sop        = state['sop_text']
        rag_run    = state['rag_running']
        pre_alert  = state['pre_alert']
        logs       = list(state['logs'])
        incidents  = list(state['incidents'])
        last_dt    = state['last_data_t']
        data_ok    = state['data_ok']

    xs_t  = list(range(len(cz_h)))
    stale = (time.time() - last_dt > 5.0) if last_dt > 0 else False

    # ---- 3D scatter ----
    if pts:
        n  = len(pts)
        cz = CEILING_H - float(np.mean([p['y'] for p in pts]))   # 천장기준 높이
        draw_pts = pts[::max(1, n // 40)]      # decimate -> <=40 pts (render 부하 감소)
        xs = [p['x'] for p in draw_pts]
        zf = [p['z'] for p in draw_pts]                          # 바닥평면 z축
        hs = [CEILING_H - p['y'] for p in draw_pts]              # 높이 = CEILING_H - y
        cs = [p['intensity'] for p in draw_pts]
        scatter3d._offsets3d = (xs, zf, hs)                      # (x, 바닥z, 높이)
        scatter3d.set_array(np.array(cs, dtype=float))
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
            f'[STEP 2]  Radar data OK (H={cz:.2f}m  pts={n})  '
            f'-- Click  "Start Baseline Collection"  to begin')
        status_box.set_color('#00ccff')
        status_box.get_bbox_patch().set_edgecolor('#00ccff')
    elif phase == PH_WARMUP:
        pct = int(wc / N_WARMUP * 100)
        status_box.set_text(
            f'[STEP 2: COLLECTING]  {wc} / {N_WARMUP} frames  ({pct}%)  '
            f'-- Stand still  |  H={cz:.2f}m  pts={n}')
        status_box.set_color('#ffcc00')
        status_box.get_bbox_patch().set_edgecolor('#ffcc00')
    elif phase == PH_WAIT_TRAIN:
        status_box.set_text(
            f'[STEP 3 READY]  Baseline complete!  Click  "Start Training"  button  |  H={cz:.2f}m  pts={n}')
        status_box.set_color('#ffcc00')
        status_box.get_bbox_patch().set_edgecolor('#ffcc00')
    elif phase == PH_TRAINING:
        status_box.set_text(
            f'[STEP 3: TRAINING]  LSTM-AE fitting...  Do not move  |  H={cz:.2f}m  pts={n}')
        status_box.set_color('#ff8800')
        status_box.get_bbox_patch().set_edgecolor('#ff8800')
    else:
        # LIVE
        if ev_active and ev_type:
            lbl = EVENT_LABELS.get(ev_type, ev_type)
            status_box.set_text(
                f'[ALERT]  {lbl}  |  Zone {ev_zone}  conf={ev_conf:.0%}  '
                f'|  H={cz:.2f}m  pts={n}')
        else:
            status_box.set_text(
                f'[STEP 4: LIVE - NORMAL]  H={cz:.2f}m  pts={n}  '
                f'|  score={sc_h[-1]:.5f}  thr={thr:.5f}')
        status_box.set_color(sev_col)
        status_box.get_bbox_patch().set_edgecolor(sev_col)

    # ---- Z timeseries ----
    line_z.set_data(xs_t, cz_h)
    line_z.set_color('#ff4444' if (ev_active and ev_type == 'fall_detected') else '#00ccff')

    # ---- Motion / Vibration (dop_std) ----
    line_sc.set_data(xs_t, ds_h)
    line_sc.set_color(sev_col)
    ax_sc.set_ylim(0, max(2.0, float(np.max(ds_h) if ds_h else 0) * 1.2 + 1e-7))

    # ---- Incident history ----
    if incidents:
        inc_lines = []
        for inc in incidents[-8:]:
            slbl = EVENT_SHORT.get(inc['type'], inc['type'])
            if inc['resolved']:
                inc_lines.append(f"[{inc['detected']}] {slbl}  Zone {inc['zone']}")
                inc_lines.append(f"      resolved {inc['resolved']}")
            else:
                inc_lines.append(f"[{inc['detected']}] {slbl}  Zone {inc['zone']}  << ACTIVE")
        log_text.set_text('\n'.join(inc_lines))
    else:
        log_text.set_text('No incidents yet.\nAlarms will be recorded here.')

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

    # ---- Active alarm banner (latched) / PRE-ALERT banner (yellow) ----
    if ev_active and ev_type:
        lbl = EVENT_LABELS.get(ev_type, ev_type)
        alarm_banner.set_text(f'[ ! ]  ACTIVE ALARM  Zone {ev_zone}: {lbl}   ->  press [Event Resolved]')
        alarm_banner.set_color('white')
        alarm_banner.get_bbox_patch().set_facecolor('#3a0000')
        alarm_banner.get_bbox_patch().set_edgecolor('#ff3333')
        alarm_banner.set_visible(True)
    elif pre_alert:
        # 정지형 1차 경고: 노란색 + 실시간 카운트다운. 움직이면 자동으로 사라짐.
        alarm_banner.set_text(f'[ ~ ]  {pre_alert}')
        alarm_banner.set_color('#ffdd66')
        alarm_banner.get_bbox_patch().set_facecolor('#3a2a00')
        alarm_banner.get_bbox_patch().set_edgecolor('#ffcc00')
        alarm_banner.set_visible(True)
    else:
        alarm_banner.set_visible(False)

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
    # Start Baseline (center)
    ax_btn_start = fig.add_axes([0.37, 0.025, 0.26, 0.048])
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

    # Event Resolved (left, under Incident History) -- manual acknowledge of a latched alarm
    ax_btn_resolve = fig.add_axes([0.06, 0.025, 0.26, 0.048])
    btn_resolve = Button(ax_btn_resolve,
                         'EVENT RESOLVED  (clear latched alarm)',
                         color='#0a1e0a', hovercolor='#0d3a1a')
    btn_resolve.label.set_color('#66ff99')
    btn_resolve.label.set_fontsize(9)
    btn_resolve.label.set_fontweight('bold')

    def do_resolve(_event=None):
        ts = datetime.now().strftime('%H:%M:%S')
        with _lock:
            active = state['ev_active']
            state['resolve_requested'] = True
        if active:
            print(f'[{ts}] [BTN] Event Resolved clicked -- clearing latched alarm')
        else:
            print(f'[{ts}] [BTN] Event Resolved clicked -- no active alarm')

    btn_resolve.on_clicked(do_resolve)

    # ── Start pipeline thread ─────────────────────────────
    t = threading.Thread(target=pipeline_loop_safe, daemon=True)
    t.start()

    add_log('System started -- waiting for radar data')
    add_log(f'Data path: {JSON_PATH}')

    # ── Manual render loop (replaces FuncAnimation) ───────
    # FuncAnimation의 Tk 타이머는 draw가 느려지면 콜백이 계속 쌓여
    # 결국 창 전체가 얼어붙는다(=warmup 98%에서 멈추던 원인).
    # 수동 루프는 매 사이클 update()를 try/except로 감싸므로 한 프레임이
    # 실패해도 죽지 않고, draw_idle+flush_events로 GUI 이벤트를 직접 밀어내
    # (plt.pause 미사용 → TkAgg 데드락 회피) draw가 느려도 얼지 않는다.
    update_sec = UPDATE_MS / 1000.0
    plt.show(block=False)
    frame_i = 0
    t_prev  = time.time()
    while plt.fignum_exists(fig.number):
        try:
            update(frame_i)
            # plt.pause() 대신 명시적 draw+flush (TkAgg+스레드 데드락 회피)
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
        except Exception as e:
            print(f'[UPD-ERR] frame={frame_i}: {e}')
        if DEBUG_TIMING:
            now = time.time()
            print(f'[UPD] frame={frame_i}  loop_dt={now - t_prev:.2f}s')
            t_prev = now
        frame_i += 1
        time.sleep(update_sec)
    print('[EXIT] window closed -- bye')
