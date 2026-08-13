"""
radar_collect_roi.py -- ROI·클러터 영향 비교용 라벨 데이터 수집 도구
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

import json, os, re, time, threading, traceback
from datetime import datetime
from collections import deque

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
matplotlib.rcParams['font.family'] = 'DejaVu Sans'

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
JSON_PATH        = '/home/project/stage1_filtered.json'
# [8/11] 출력 파일 분리. 기존 events_collect.jsonl 은 전처리가 다른 데이터다.
#   7월분: 알루미늄 프레임 없음 + ROI 없음
#   이 파일: 프레임 있음 + 아래 ROI 적용
#   한 파일에 라벨만 같은 채로 쌓이면 나중에 구분이 불가능하다.
SESSION_ID       = re.sub(r'[^A-Za-z0-9_-]', '_',
                          os.environ.get('RADAR_SESSION', 'roi_v3'))
OUT_PATH         = f'/home/project/events_{SESSION_ID}.jsonl'
EMPTY_PATH       = f'/home/project/empty_{SESSION_ID}.jsonl'
CEILING_H        = 2.30       # 천장(센서)~바닥 거리 (m)  -- 실측값

# [8/11] jetson_sender.py 의 classify 입력 전처리와 반드시 같아야 하는 값.
#   왜: 이 도구의 출력으로 classify 문턱을 정한다. 판정부가 보는 것과 다른 값을
#       재고 있으면 그 숫자로 문턱을 잡을 수 없다.
#   실측 차이(2026-08-11, 같은 낙상 구간 frame 52350~52900 재계산):
#       ds_max +4.5% / ds_broad -25% / horiz +47.9% / h_drop +102.8% / n_mean -47.1%
#       -> n_mean 은 절반 가까이, horiz 는 절반 가까이 어긋났다.
#   ⚠ 클러터 제거는 넣지 않는다. jetson_sender 가 2026-08-11 자로 classify 입력에서
#     클러터 제거를 뺐기 때문이다(클러터 스팟이 사람 통행 영역에 박히면 낙상
#     포인트를 지운다 — 실측 53.4% 소실). 판정부가 안 쓰는 걸 여기 넣으면 다시 어긋난다.
#   ⚠ jetson_sender.py 의 NEAR_FIELD_MIN_RANGE / FRAME_INNER_HALF 를 바꾸면
#     여기도 같이 바꿔야 한다.
NEAR_FIELD_MIN_RANGE = 0.5
FRAME_INNER_HALF     = 0.72   # 3030 기둥 안쪽 1.44m 의 절반
ROI_X = (-FRAME_INNER_HALF, FRAME_INNER_HALF)
ROI_Z = (-FRAME_INNER_HALF, FRAME_INNER_HALF)
ROI_Y = (NEAR_FIELD_MIN_RANGE, CEILING_H + 0.25)
POLL_SEC         = 0.2
UPDATE_MS        = 800
WINDOW_SEC       = 2.0        # 버튼 클릭 시 저장할 직전 구간 (초)
FPS_EST          = 10
WINDOW_FRAMES    = int(WINDOW_SEC * FPS_EST)   # ~20 frames
DEBUG_TIMING     = False

# ROI 낙상 문턱 재검증에 필요한 양성·난음성만 수집한다.
TARGET = {'fall': 10, 'fast_sit': 6, 'crouch': 6,
          'wave': 5, 'walk': 3, 'normal': 3}
CORE_CLASSES    = ['fall', 'fast_sit', 'crouch', 'wave', 'walk', 'normal']
EXPLORE_CLASSES = []
CLASSES         = CORE_CLASSES + EXPLORE_CLASSES
CLASS_LABEL = {
    'fall': 'FALL', 'fast_sit': 'FAST-SIT', 'walk': 'WALK',
    'normal': 'NORMAL', 'crouch': 'CROUCH', 'exit': 'ENTRY/EXIT',
    'vib': 'VIB(machine)', 'wave': 'WAVE(arm)', 'still': 'STILL(lie)',
}
BTN_COLOR = {
    'fall': '#3a0a0a', 'fast_sit': '#2a1a0a', 'walk': '#0a1a2a',
    'normal': '#0a2a12', 'crouch': '#24300a', 'exit': '#102a30',
    'vib': '#0a2a2a', 'wave': '#2a1030', 'still': '#08203a',
}
BTN_TEXT_COLOR = {
    'fall': '#ff6666', 'fast_sit': '#ffbb66', 'walk': '#66bbff',
    'normal': '#66ff99', 'crouch': '#ddff77', 'exit': '#77ddff',
    'vib': '#66ffee', 'wave': '#ff99dd', 'still': '#66ccff',
}

CUR_PERSON = 'A'
CUR_POSITION = 'center'

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
    'empty_request': False,
    'empty_until': None,
    'empty_frames': [],
    'empty_msg': 'not recorded',
}


def apply_roi(pts):
    """[8/11] jetson_sender.py 의 classify 입력과 동일한 전처리.
    근거리 아티팩트 컷 + 알루미늄 프레임 안쪽만 남긴다. 클러터 제거는 하지 않는다.
    """
    return [p for p in pts
            if p['y'] >= NEAR_FIELD_MIN_RANGE
            and ROI_X[0] <= p['x'] <= ROI_X[1]
            and ROI_Z[0] <= p['z'] <= ROI_Z[1]
            and ROI_Y[0] <= p['y'] <= ROI_Y[1]]


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
    # 과거 수백 MB를 재생하지 않고 실행 이후 프레임만 수집한다.
    try:
        read_offset = os.path.getsize(JSON_PATH)
    except OSError:
        read_offset = 0
    print(f'[COLLECT] pipeline 시작 -- 현재 파일 끝 offset={read_offset}')
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
            raw_pts = rec.get('points', [])
            now = time.time()
            with _lock:
                if state['empty_request'] and state['empty_until'] is None:
                    state['empty_request'] = False
                    state['empty_until'] = now + 60.0
                    state['empty_frames'] = []
                    state['empty_msg'] = 'recording 60s'
                    print('[EMPTY] 빈방 원본 60초 수집 시작 -- 모두 ROI 밖으로 이동')
                empty_until = state['empty_until']
                if empty_until is not None:
                    state['empty_frames'].append({'t': round(now, 3), 'points': raw_pts})

            if empty_until is not None:
                if now >= empty_until:
                    with _lock:
                        empty_frames = state['empty_frames']
                        state['empty_until'] = None
                        state['empty_frames'] = []
                    record = {'session': SESSION_ID, 'person': CUR_PERSON,
                              'position': CUR_POSITION, 'duration_sec': 60,
                              'preproc': {'roi_half': FRAME_INNER_HALF,
                                          'near': NEAR_FIELD_MIN_RANGE},
                              'frames': empty_frames}
                    with open(EMPTY_PATH, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(record, ensure_ascii=False) + '\n')
                    with _lock:
                        state['empty_msg'] = f'saved {len(empty_frames)} frames'
                    print(f'[EMPTY] {len(empty_frames)} frames -> {EMPTY_PATH}')
                continue

            if not raw_pts:
                continue
            # [8/11] 피처 계산 전에 ROI 를 적용한다. 화면 표시도 같은 점을 쓴다
            #   — 3D 뷰에 보이는 것과 저장되는 값이 달라지면 라벨링 판단이 어긋난다.
            pts = apply_roi(raw_pts)
            if not pts:
                continue
            fr = feat_from_frame(pts)
            if fr is None:
                continue
            # 원본을 함께 보존해 ROI·클러터 조건을 바꿔도 같은 사건을 재계산한다.
            fr['raw_pts'] = raw_pts
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
        'person':   CUR_PERSON,
        'session':  SESSION_ID,
        'position': CUR_POSITION,
        'ts':       datetime.now().isoformat(timespec='seconds'),
        'ceiling_h': CEILING_H,
        # [8/11] 전처리 조건을 레코드에 박아둔다. 나중에 파일이 섞이거나
        #   ROI 값을 바꿨을 때 어느 조건에서 찍은 데이터인지 알 수 없으면
        #   그 데이터로 문턱을 잡을 수 없다.
        'preproc':  {'roi': True, 'near': NEAR_FIELD_MIN_RANGE,
                     'half': FRAME_INNER_HALF, 'clutter': False},
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
        state['last_saved'] = f'{CLASS_LABEL[label]} saved ({c}/{TARGET[label]})'
    print(f'[SAVE] {label} #{c}  ({len(window)} frames) -> {OUT_PATH}')


def core_done():
    with _lock:
        return all(state['counts'][c] >= TARGET[c] for c in CORE_CLASSES)


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

# -- 동작 버튼 (두 줄) --
btns = {}
_bx = 0.04
_bw = 0.17
_gap = 0.015
for i, c in enumerate(CLASSES):
    row, col = divmod(i, 5)
    axb = fig.add_axes([_bx + col * (_bw + _gap), 0.085 - row * 0.065, _bw, 0.05])
    b = Button(axb, CLASS_LABEL[c], color=BTN_COLOR[c], hovercolor='#333355')
    b.label.set_color(BTN_TEXT_COLOR[c])
    b.label.set_fontsize(8.5)
    b.label.set_fontweight('bold')
    b.on_clicked(lambda _evt, lab=c: save_sample(lab))
    btns[c] = b

ax_empty = fig.add_axes([0.79, 0.145, 0.18, 0.045])
btn_empty = Button(ax_empty, 'EMPTY 60s', color='#182238', hovercolor='#334466')
btn_empty.label.set_color('#88ccff')

def _start_empty(_evt):
    with _lock:
        if state['empty_until'] is None:
            state['empty_request'] = True

btn_empty.on_clicked(_start_empty)


def _on_key(evt):
    """사람 A/B/C/D와 위치 1~5를 파일을 재시작하지 않고 전환한다."""
    global CUR_PERSON, CUR_POSITION
    if evt.key in ('a', 'b', 'c', 'd', 'e'):
        CUR_PERSON = evt.key.upper()
        with _lock:
            for c in state['counts']:
                state['counts'][c] = 0
        print(f'[PERSON] {CUR_PERSON} -- 현재 사람 카운터 초기화')
    positions = {'1': 'center', '2': 'north', '3': 'east',
                 '4': 'south', '5': 'west'}
    if evt.key in positions:
        CUR_POSITION = positions[evt.key]
        print(f'[POSITION] {CUR_POSITION}')

fig.canvas.mpl_connect('key_press_event', _on_key)


def build_info():
    with _lock:
        data_ok  = state['data_ok']
        window   = list(state['window'])
        counts   = dict(state['counts'])
        last     = state['last_saved']
        last_dt  = state['last_data_t']
        empty_until = state['empty_until']
        empty_msg = state['empty_msg']
    stale = (time.time() - last_dt > 5.0) if last_dt > 0 else True

    lines = []
    lines.append(f'PERSON {CUR_PERSON}  |  POSITION {CUR_POSITION}  '
                 '(a/b/c/d/e, 1=center 2=N 3=E 4=S 5=W)')
    if empty_until is not None:
        lines.append(f'EMPTY: recording {max(0, empty_until-time.time()):.0f}s left')
    else:
        lines.append(f'EMPTY: {empty_msg}')
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
    lines.append('[COLLECTED] current person')
    for c in CORE_CLASSES:
        mark = ' OK' if counts[c] >= TARGET[c] else ''
        lines.append(f"  {CLASS_LABEL[c]:<12} {counts[c]:>2}/{TARGET[c]}{mark}")
    lines.append('  ---- explore (separability check) ----')
    for c in EXPLORE_CLASSES:
        lines.append(f"  {CLASS_LABEL[c]:<12} {counts[c]:>2}/{TARGET[c]}")
    lines.append('')
    lines.append(f'LAST: {last}')
    lines.append('')
    if core_done():
        lines.append('>>> DONE! Current person reached target.')
        lines.append(f'    Output: {OUT_PATH}')
    else:
        lines.append('>> Right AFTER the motion, click its button.')
        lines.append('   (button = saves last 2s window with label)')
    return '\n'.join(lines)


def update(_i):
    with _lock:
        pts    = list(state['latest_pts'])
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
    print('  목표      : ' + ', '.join(f'{c}={TARGET[c]}' for c in CLASSES))
    print(f'  세션      : {SESSION_ID}  (RADAR_SESSION 환경변수로 변경)')
    print('  사람 키   : a/b/c/d/e | 위치 키: 1=center 2=N 3=E 4=S 5=W')
    print(f'  빈방      : EMPTY 60s 버튼 -> {EMPTY_PATH}')
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
