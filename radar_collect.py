"""
radar_collect.py -- 천장 설치 라벨 데이터 수집 도구 (판별치 튜닝용)
====================================================================
radar_live_full.py 와 별개의 프로그램. 목적: 낙상/빠른앉기/보행/정상
(+협착/감전 탐색) 동작을 버튼으로 라벨링해 feature 윈도우를 파일로
기록 -> 이 데이터로 classify() 판별치를 실측 기준으로 확정한다.

실행 (천장 설치, 파서 먼저):
  [터미널 1 - 젯슨]  python3 ~/radar_parser.py
  [터미널 2 - 젯슨]  python3 ~/radar_collect.py

사용법:
  1) 사람이 레이더(천장) 아래에서 동작 수행 (낙상/앉기/보행/정상)
  2) 동작 "직후" 해당 버튼 클릭 -> 직전 2초 구간이 라벨과 함께 저장됨
  3) 각 클래스 목표(10개) 채우면 화면에 "수집 완료" 표시
  4) 생성된 events_collect.jsonl 을 튜닝 담당(Claude)에게 전달

좌표계 (천장 설치 기준):
  TI 좌표에서 y = range(boresight) = 천장 센서에서 아래로의 거리.
  height_above_floor = CEILING_H - y     (사람 서있으면 큼, 쓰러지면 0 근처)
  바닥 평면 = (x, z)

출력: /home/project/events_collect.jsonl  (한 줄 = 라벨 샘플 1개)
"""

import json, os, time, threading, traceback
from datetime import datetime
from collections import deque

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from mpl_toolkits.mplot3d import Axes3D  # noqa
matplotlib.rcParams['font.family'] = 'DejaVu Sans'

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
JSON_PATH        = '/home/project/stage1_filtered.json'
OUT_PATH         = '/home/project/events_collect.jsonl'
CEILING_H        = 2.30       # 천장(센서)~바닥 거리 (m)  -- 실측값
POLL_SEC         = 0.2
UPDATE_MS        = 800
WINDOW_SEC       = 2.0        # 버튼 클릭 시 저장할 직전 구간 (초)
FPS_EST          = 10
WINDOW_FRAMES    = int(WINDOW_SEC * FPS_EST)   # ~20 frames
TARGET_PER_CLASS = 10
DEBUG_TIMING     = False

# 핵심 클래스(완료 판정 대상) + 탐색 클래스(구분 가능성만 확인)
CORE_CLASSES    = ['fall', 'fast_sit', 'walk', 'normal']
# [7/6] wave = 서서 팔 크게 상하로 흔들기 (낙상 오탐 유발 동작 -> 판별자 확보용)
EXPLORE_CLASSES = ['pinch', 'shock', 'vib', 'wave']   # vib = 기계 진동(선풍기 등, 사람 X)
CLASSES         = CORE_CLASSES + EXPLORE_CLASSES
CLASS_LABEL = {
    'fall': 'FALL', 'fast_sit': 'FAST-SIT', 'walk': 'WALK',
    'normal': 'NORMAL', 'pinch': 'PINCH', 'shock': 'SHOCK', 'vib': 'VIB(machine)',
    'wave': 'WAVE(arm)',
}
BTN_COLOR = {
    'fall': '#3a0a0a', 'fast_sit': '#2a1a0a', 'walk': '#0a1a2a',
    'normal': '#0a2a12', 'pinch': '#1a0a2a', 'shock': '#2a2a0a', 'vib': '#0a2a2a',
    'wave': '#2a1030',
}
BTN_TEXT_COLOR = {
    'fall': '#ff6666', 'fast_sit': '#ffbb66', 'walk': '#66bbff',
    'normal': '#66ff99', 'pinch': '#cc88ff', 'shock': '#ffff66', 'vib': '#66ffee',
    'wave': '#ff99dd',
}

# ═══════════════════════════════════════════════════════════
# SHARED STATE
# ═══════════════════════════════════════════════════════════
_lock = threading.RLock()
state = {
    'latest_pts':  [],
    'window':      deque(maxlen=WINDOW_FRAMES),   # 최근 per-frame feature dict
    'counts':      {c: 0 for c in CLASSES},
    'last_saved':  '(none yet)',
    'data_ok':     False,
    'last_data_t': 0.0,
}


def feat_from_frame(pts):
    """한 프레임 포인트 -> 천장기준 feature dict."""
    if not pts:
        return None
    arr = np.array([[p['x'], p['y'], p['z'], p['doppler'], p['intensity']]
                    for p in pts], dtype=np.float32)
    cx, cy, cz = float(arr[:, 0].mean()), float(arr[:, 1].mean()), float(arr[:, 2].mean())
    height   = CEILING_H - cy                       # 천장기준 바닥 위 높이
    dop_mean = float(arr[:, 3].mean())
    dop_std  = float(arr[:, 3].std())
    inten    = float(arr[:, 4].mean())
    n        = int(arr.shape[0])
    spread_xz = float(0.5 * (arr[:, 0].std() + arr[:, 2].std()))   # 바닥평면 확산
    return {
        't': round(time.time(), 3),
        'cx': round(cx, 4), 'cy': round(cy, 4), 'cz': round(cz, 4),
        'height': round(height, 4), 'n': n,
        'dop_mean': round(dop_mean, 5), 'dop_std': round(dop_std, 5),
        'inten': round(inten, 1), 'spread_xz': round(spread_xz, 4),
    }


# ═══════════════════════════════════════════════════════════
# PIPELINE THREAD  (parser JSONL tail 읽기)
# ═══════════════════════════════════════════════════════════
def pipeline_loop():
    read_offset = 0
    print('[COLLECT] pipeline 시작 -- 레이더 데이터 대기')
    while True:
        time.sleep(POLL_SEC)

        if not os.path.exists(JSON_PATH):
            with _lock:
                state['data_ok'] = False
            continue

        try:
            fsize = os.path.getsize(JSON_PATH)
        except OSError:
            continue
        if fsize < read_offset:
            read_offset = 0          # 파서 재시작(파일 초기화) 감지

        try:
            with open(JSON_PATH, 'rb') as f:
                f.seek(read_offset)
                chunk = f.read()
        except OSError:
            continue
        if not chunk:
            continue

        last_nl = chunk.rfind(b'\n')
        if last_nl == -1:
            continue
        read_offset += last_nl + 1

        for line in chunk[:last_nl + 1].split(b'\n'):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pts = rec.get('points', [])
            if not pts:
                continue
            fr = feat_from_frame(pts)
            if fr is None:
                continue
            with _lock:
                state['latest_pts']  = pts
                state['window'].append(fr)
                state['data_ok']     = True
                state['last_data_t'] = time.time()


def pipeline_safe():
    while True:
        try:
            pipeline_loop()
        except Exception as e:
            print('[PIPE-CRASH]', e)
            traceback.print_exc()
            time.sleep(3.0)


# ═══════════════════════════════════════════════════════════
# SAVE ONE LABELED SAMPLE
# ═══════════════════════════════════════════════════════════
def save_sample(label):
    with _lock:
        window = list(state['window'])
    if len(window) < 3:
        print(f'[SKIP] not enough data ({len(window)} frames) -- check person is in view, retry')
        with _lock:
            state['last_saved'] = f'[SKIP] {CLASS_LABEL[label]}: not enough data'
        return

    sample = {
        'label':    label,
        'ts':       datetime.now().isoformat(timespec='seconds'),
        'ceiling_h': CEILING_H,
        'n_frames': len(window),
        'frames':   window,
    }
    try:
        with open(OUT_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(sample, ensure_ascii=False) + '\n')
    except OSError as e:
        print('[SAVE-ERR]', e)
        return

    with _lock:
        state['counts'][label] += 1
        c = state['counts'][label]
        state['last_saved'] = f'{CLASS_LABEL[label]} saved ({c}/{TARGET_PER_CLASS})'
    print(f'[SAVE] {label} #{c}  ({len(window)} frames) -> {OUT_PATH}')


def core_done():
    with _lock:
        return all(state['counts'][c] >= TARGET_PER_CLASS for c in CORE_CLASSES)


# ═══════════════════════════════════════════════════════════
# FIGURE
# ═══════════════════════════════════════════════════════════
fig = plt.figure(figsize=(15, 8), facecolor='#080818')
fig.suptitle('Radar-Guard  |  Label Data Collector (ceiling mount, CEILING_H=%.2fm)' % CEILING_H,
             color='white', fontsize=12, fontweight='bold', y=0.98)

# -- 3D point cloud (x, z, height) --
ax3d = fig.add_axes([0.02, 0.18, 0.46, 0.72], projection='3d')
ax3d.set_facecolor('#08081a')
ax3d.set_title('Point Cloud  (vertical = height above floor)', color='white', fontsize=9, pad=4)
ax3d.set_xlabel('X (m)', color='#8899bb', fontsize=7)
ax3d.set_ylabel('Z floor (m)', color='#8899bb', fontsize=7)
ax3d.set_zlabel('Height (m)', color='#8899bb', fontsize=7)
ax3d.tick_params(colors='#556677', labelsize=6)
ax3d.set_xlim(-2, 2); ax3d.set_ylim(-2, 2); ax3d.set_zlim(0, 2.5)
for pn in (ax3d.xaxis.pane, ax3d.yaxis.pane, ax3d.zaxis.pane):
    pn.fill = False; pn.set_edgecolor('#1a1a33')
scatter3d = ax3d.scatter([], [], [], c=[], cmap='plasma', vmin=200, vmax=600, s=16, alpha=0.85)

# -- Info / counters panel --
ax_info = fig.add_axes([0.52, 0.18, 0.46, 0.72])
ax_info.set_facecolor('#04040e')
ax_info.axis('off')
info_text = ax_info.text(0.02, 0.98, '', transform=ax_info.transAxes,
                         color='#ccddee', fontsize=10, va='top', fontfamily='monospace')

# -- Buttons (bottom row) --
btns = {}
_bx = 0.04
_bw = 0.10       # [7/6] 8버튼(wave 추가)이 한 줄에 들어가게 축소
_gap = 0.012
for i, c in enumerate(CLASSES):
    axb = fig.add_axes([_bx + i * (_bw + _gap), 0.045, _bw, 0.07])
    b = Button(axb, CLASS_LABEL[c], color=BTN_COLOR[c], hovercolor='#333355')
    b.label.set_color(BTN_TEXT_COLOR[c])
    b.label.set_fontsize(8.5)
    b.label.set_fontweight('bold')
    b.on_clicked(lambda _evt, lab=c: save_sample(lab))
    btns[c] = b


def build_info():
    with _lock:
        data_ok  = state['data_ok']
        window   = list(state['window'])
        counts   = dict(state['counts'])
        last     = state['last_saved']
        last_dt  = state['last_data_t']
    stale = (time.time() - last_dt > 5.0) if last_dt > 0 else True

    lines = []
    if not data_ok:
        lines.append('DATA: [WAIT] run parser (python3 ~/radar_parser.py)')
    elif stale:
        lines.append('DATA: [STALLED >5s] check parser/sensor')
    else:
        lines.append('DATA: [OK] receiving')

    if window:
        f = window[-1]
        lines.append(f"NOW: height={f['height']:.2f}m  n={f['n']}  "
                     f"dop_std={f['dop_std']:.4f}  spread={f['spread_xz']:.3f}")
    else:
        lines.append('NOW: (no points)')
    lines.append('')
    lines.append(f'[COLLECTED]  target {TARGET_PER_CLASS}/class')
    for c in CORE_CLASSES:
        mark = ' OK' if counts[c] >= TARGET_PER_CLASS else ''
        lines.append(f"  {CLASS_LABEL[c]:<10} {counts[c]:>2}/{TARGET_PER_CLASS}{mark}")
    lines.append('  ---- explore (separability check) ----')
    for c in EXPLORE_CLASSES:
        lines.append(f"  {CLASS_LABEL[c]:<10} {counts[c]:>2}/{TARGET_PER_CLASS}")
    lines.append('')
    lines.append(f'LAST: {last}')
    lines.append('')
    if core_done():
        lines.append('>>> DONE! Core 4 classes reached target.')
        lines.append('    Send events_collect.jsonl to tuning.')
    else:
        lines.append('>> Right AFTER the motion, click its button.')
        lines.append('   (button = saves last 2s window with label)')
    return '\n'.join(lines)


def update(_i):
    with _lock:
        pts    = list(state['latest_pts'])
        done   = False
    # 3D scatter
    if pts:
        n = len(pts)
        draw = pts[::max(1, n // 40)]
        xs = [p['x'] for p in draw]
        zs = [p['z'] for p in draw]
        hs = [CEILING_H - p['y'] for p in draw]
        cs = [p['intensity'] for p in draw]
        scatter3d._offsets3d = (xs, zs, hs)
        scatter3d.set_array(np.array(cs, dtype=float))
    info_text.set_text(build_info())
    if core_done():
        info_text.set_color('#88ffaa')
    else:
        info_text.set_color('#ccddee')
    return scatter3d, info_text


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
if __name__ == '__main__':
    print('=' * 60)
    print('  Radar-Guard | 라벨 데이터 수집기')
    print('=' * 60)
    print(f'  입력 : {JSON_PATH}')
    print(f'  출력 : {OUT_PATH}')
    print(f'  천장 높이 : {CEILING_H} m')
    print(f'  윈도우    : {WINDOW_SEC}s (~{WINDOW_FRAMES} frames)')
    print(f'  목표      : 클래스당 {TARGET_PER_CLASS}개')
    print('  [터미널 1] python3 ~/radar_parser.py   (먼저)')
    print('  [터미널 2] python3 ~/radar_collect.py  (이것)')
    print('=' * 60)

    t = threading.Thread(target=pipeline_safe, daemon=True)
    t.start()

    # 수동 렌더 루프 (plt.pause 미사용 -> TkAgg 데드락 회피, RLock 사용)
    update_sec = UPDATE_MS / 1000.0
    plt.show(block=False)
    frame_i = 0
    t_prev = time.time()
    while plt.fignum_exists(fig.number):
        try:
            update(frame_i)
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
        except Exception as e:
            print(f'[UPD-ERR] {e}')
        if DEBUG_TIMING:
            now = time.time()
            print(f'[UPD] {frame_i} dt={now - t_prev:.2f}s'); t_prev = now
        frame_i += 1
        time.sleep(update_sec)
    print('[EXIT] 수집기 종료')
