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
  3) 목표(각 21 = 3명×7, 전체 합계) 채우면 "DONE" 표시. 사람 전환은 키 a/b/c
  4) 생성된 events_collect.jsonl 을 튜닝 담당(Claude)에게 전달

좌표계 (천장 설치 기준):
  TI 좌표에서 y = range(boresight) = 천장 센서에서 아래로의 거리.
  height_above_floor = CEILING_H - y     (사람 서있으면 큼, 쓰러지면 0 근처)
  바닥 평면 = (x, z)

출력: /home/project/events_collect.jsonl  (한 줄 = 라벨 샘플 1개)
"""

import sys, json, os, time, threading, traceback
from datetime import datetime
from collections import deque, Counter

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
from matplotlib.widgets import Button
from matplotlib.patches import Rectangle
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
DEBUG_TIMING     = False

# ── 인당(=세션당) 목표 수량. 사람마다 스크립트를 재실행하므로 카운트는 사람별로 리셋됨.
#    DONE_CLASSES 4개를 목표만큼 채우면 '완료' 표시. 나머지(fast_sit/vib 등)는 카운터만.
TARGET = {
    'fall': 7, 'wave': 15, 'walk': 15, 'normal': 15, 'still': 15,   # [7/9] 인당: 낙상 7, 나머지 15 (a/b/c 전환 시 카운터 리셋)
    'fast_sit': 0, 'pinch': 0, 'shock': 0, 'vib': 0,   # 0 = 완료판정 제외(카운터만)
}
DONE_CLASSES = ['fall', 'wave', 'walk', 'normal', 'still']

# ── [7/9] 사람 태그: collector 1회 실행으로 3명 태깅. 키 a/b/c 로 현재 사람 전환(기본 A). ──
#    (per-person 재실행 없이 한 번에 수집 -> 나중에 body-type LOO 분석용 태그는 유지)
CUR_PERSON = 'A'

# ── [7/9] 수집은 항상 RAW (클러터 제거 안 함). 정적 클러터는 오프라인에서 3D로 제거 ──
# 이유: 수집 때 2D 클러터를 지우면 (x,z) 기둥이 통째로 삭제돼 사람 점까지 날아가고(Target
# Masking), 지운 점은 되돌릴 수 없음. -> 원본을 그대로 저장하고, 오프라인에서 3D 클러터맵을
# 입혀 dy까지 튜닝. 아래 [REC empty-room] 버튼으로 '빈방 원본'을 따로 녹화해 그 3D맵 재료로 씀.
EMPTY_RAW_PATH = '/home/project/empty_room_raw.jsonl'  # 빈방 raw 프레임 저장(오프라인 3D맵 재료)
EMPTY_REC_SEC  = 12.0    # 빈방 raw 녹화 길이(초)

# 핵심 클래스(완료 판정 대상) + 탐색 클래스(구분 가능성만 확인)
CORE_CLASSES    = ['fall', 'fast_sit', 'walk', 'normal']
# [7/6] wave = 서서 팔 크게 상하로 흔들기 (낙상 오탐 유발 동작 -> 판별자 확보용)
EXPLORE_CLASSES = ['pinch', 'shock', 'vib', 'wave', 'still']   # vib=기계진동, still=정지 사람
CLASSES         = CORE_CLASSES + EXPLORE_CLASSES
CLASS_LABEL = {
    'fall': 'FALL', 'fast_sit': 'FAST-SIT', 'walk': 'WALK',
    'normal': 'NORMAL(stand)', 'pinch': 'PINCH', 'shock': 'SHOCK', 'vib': 'VIB(machine)',
    'wave': 'WAVE(arm)', 'still': 'STILL(lie)',
}
BTN_COLOR = {
    'fall': '#3a0a0a', 'fast_sit': '#2a1a0a', 'walk': '#0a1a2a',
    'normal': '#0a2a12', 'pinch': '#1a0a2a', 'shock': '#2a2a0a', 'vib': '#0a2a2a',
    'wave': '#2a1030', 'still': '#08203a',
}
BTN_TEXT_COLOR = {
    'fall': '#ff6666', 'fast_sit': '#ffbb66', 'walk': '#66bbff',
    'normal': '#66ff99', 'pinch': '#cc88ff', 'shock': '#ffff66', 'vib': '#66ffee',
    'wave': '#ff99dd', 'still': '#66ccff',
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
    # ── 빈방 RAW 녹화 상태 (오프라인 3D 클러터맵 재료) ──
    'rec_request': False,    # REC empty-room 버튼이 True로 세팅
    'rec_until':   None,     # 녹화 종료 시각(None = 녹화 아님)
    'rec_left':    None,     # 남은 녹화 시간(초) - UI 표시용
    'rec_frames':  0,        # 이번 녹화에 저장된 프레임 수
    'rec_msg':     '(empty-room raw: not recorded)',
}


# ═══════════════════════════════════════════════════════════
# (클러터 제거 로직 삭제됨 - 수집은 항상 RAW. 정적 클러터는 오프라인 3D 처리)
# ═══════════════════════════════════════════════════════════


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
    rec_fh = None          # 빈방 raw 녹화 파일 핸들 (녹화 중에만 열림)
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
            pts = rec.get('points', [])   # 빈방이면 [] 일 수 있음 (스캔은 계속돼야 함)

            now = time.time()
            with _lock:
                rec_req   = state['rec_request']
                rec_until = state['rec_until']

            # ── 빈방 RAW 녹화 요청 처리 (녹화 중이 아닐 때만 시작) ──
            #    ⚠️ 빈방은 포인트가 0일 수 있으므로 'if not pts: continue' 보다 먼저 처리!
            if rec_req and rec_until is None:
                rec_until = now + EMPTY_REC_SEC
                try:
                    rec_fh = open(EMPTY_RAW_PATH, 'w', encoding='utf-8')
                except OSError as e:
                    rec_fh = None
                    print('[REC] 파일 열기 실패:', e)
                with _lock:
                    state['rec_request'] = False
                    state['rec_until']   = rec_until
                    state['rec_left']    = EMPTY_REC_SEC
                    state['rec_frames']  = 0
                    state['rec_msg']     = 'RECORDING empty room (raw)...'
                print(f'[REC] 빈방 raw 녹화 시작 {EMPTY_REC_SEC:.0f}s -- 전원 시야 밖! -> {EMPTY_RAW_PATH}')

            # ── 녹화 중: 원본 프레임을 그대로 파일에 기록 (포인트 0이어도 타이머 진행) ──
            if rec_until is not None:
                if rec_fh is not None and pts:
                    rec_fh.write(json.dumps({'t': round(now, 3), 'points': pts},
                                            ensure_ascii=False) + '\n')
                    with _lock:
                        state['rec_frames'] += 1
                with _lock:
                    state['latest_pts'] = pts
                    if pts:
                        state['data_ok']     = True
                        state['last_data_t'] = now
                    state['rec_left'] = max(0.0, rec_until - now)
                if now < rec_until:
                    continue
                # 녹화 종료 -> 파일 닫기
                if rec_fh is not None:
                    rec_fh.close(); rec_fh = None
                with _lock:
                    nfr = state['rec_frames']
                    state['rec_until'] = None
                    state['rec_left']  = None
                    state['rec_msg']   = f'saved {nfr} frames -> {EMPTY_RAW_PATH}'
                print(f'[REC] 완료: {nfr} 프레임 -> {EMPTY_RAW_PATH}')
                continue   # 이 프레임(빈방)은 라벨 저장 안 함

            # ── 정상 경로: RAW 그대로 (클러터 제거 안 함) ──
            if not pts:
                continue
            fr = feat_from_frame(pts)
            if fr is None:
                continue
            fr['pts'] = pts        # [7/9 B] 원본 점 동봉 -> 오프라인에서 3D 클러터 적용/dy 튜닝 가능
            with _lock:
                state['latest_pts']  = pts
                state['window'].append(fr)
                state['data_ok']     = True
                state['last_data_t'] = now


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
        tgt = TARGET.get(label, 0)
        suffix = f'/{tgt}' if tgt > 0 else ''
        state['last_saved'] = f'{CLASS_LABEL[label]} saved ({c}{suffix})  [person {CUR_PERSON}]'
    print(f'[SAVE] {label} #{c}  ({len(window)} frames) -> {OUT_PATH}')


def core_done():
    with _lock:
        return all(state['counts'][c] >= TARGET[c] for c in DONE_CLASSES)


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
_bw = 0.095      # [7/8] 9버튼(still 추가)이 한 줄에 들어가게 축소
_gap = 0.010
for i, c in enumerate(CLASSES):
    axb = fig.add_axes([_bx + i * (_bw + _gap), 0.045, _bw, 0.07])
    b = Button(axb, CLASS_LABEL[c], color=BTN_COLOR[c], hovercolor='#333355')
    b.label.set_color(BTN_TEXT_COLOR[c])
    b.label.set_fontsize(8.5)
    b.label.set_fontweight('bold')
    b.on_clicked(lambda _evt, lab=c: save_sample(lab))
    btns[c] = b

# -- REC empty-room (raw) 버튼 : 빈방 원본 녹화 (오프라인 3D 클러터맵 재료) --
ax_rec = fig.add_axes([0.80, 0.125, 0.16, 0.05])
btn_rec = Button(ax_rec, 'REC empty-room (12s)', color='#101a2a', hovercolor='#333355')
btn_rec.label.set_color('#88ccff')
btn_rec.label.set_fontsize(8.5)
btn_rec.label.set_fontweight('bold')

def _do_rec(_evt):
    with _lock:
        if state['rec_until'] is None:
            state['rec_request'] = True
btn_rec.on_clicked(_do_rec)

# -- 스캔/클러터 실시간 진행바 (live_full 처럼 보라색으로 채워짐) --
ax_prog = fig.add_axes([0.04, 0.125, 0.72, 0.045])
ax_prog.set_xlim(0, 1); ax_prog.set_ylim(0, 1); ax_prog.axis('off')
prog_bg   = Rectangle((0, 0), 1, 1, color='#141422'); ax_prog.add_patch(prog_bg)
prog_fill = Rectangle((0, 0), 0, 1, color='#a050ff'); ax_prog.add_patch(prog_fill)  # 보라
prog_txt  = ax_prog.text(0.5, 0.5, '', ha='center', va='center',
                         color='white', fontsize=9, fontweight='bold')


# -- 사람 태그 전환 (키 a/b/c) : collector 1회 실행으로 3명 태깅 --
def _on_key(evt):
    global CUR_PERSON
    if evt.key in ('a', 'b', 'c'):
        p = evt.key.upper()
        if p != CUR_PERSON:            # 새 사람 -> UI 카운터만 0으로 리셋 (이전 데이터는 이미 jsonl에 저장됨)
            CUR_PERSON = p
            with _lock:
                for _c in state['counts']:
                    state['counts'][_c] = 0
            print(f'[PERSON] -> {CUR_PERSON}  (UI counts reset; saved data kept)')
fig.canvas.mpl_connect('key_press_event', _on_key)


def build_info():
    with _lock:
        data_ok    = state['data_ok']
        window     = list(state['window'])
        counts     = dict(state['counts'])
        last       = state['last_saved']
        last_dt    = state['last_data_t']
        rec_left   = state['rec_left']
        rec_frames = state['rec_frames']
        rec_msg    = state['rec_msg']
    stale = (time.time() - last_dt > 5.0) if last_dt > 0 else True

    lines = []
    lines.append(f'PERSON: {CUR_PERSON}     (press a / b / c to switch person)')
    lines.append('MODE: RAW (no clutter removal - offline 3D, raw points saved)')
    if rec_left is not None:
        lines.append(f'EMPTY-REC: [RECORDING] {rec_left:.0f}s  ({rec_frames} frames) -- stay OUT of view!')
    else:
        lines.append(f'EMPTY-REC: {rec_msg}')
    lines.append('')
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
    lines.append('[COLLECTED]  (current person - target 7 each; switch resets counter)')
    for c in DONE_CLASSES:
        mark = ' OK' if counts[c] >= TARGET[c] else ''
        lines.append(f"  {CLASS_LABEL[c]:<11} {counts[c]:>2}/{TARGET[c]}{mark}")
    lines.append('  ---- explore (counter) ----')
    for c in CLASSES:
        if c in DONE_CLASSES:
            continue
        lines.append(f"  {CLASS_LABEL[c]:<11} {counts[c]:>2}")
    lines.append('')
    lines.append(f'LAST: {last}')
    lines.append('')
    if core_done():
        lines.append('>>> DONE! this person reached target (7 each). Press next person key.')
    else:
        lines.append('>> Click the matching button right AFTER the action.')
        lines.append('   (button = saves last 2s window with the label)')
    return '\n'.join(lines)


def update(_i):
    with _lock:
        pts        = list(state['latest_pts'])
        rec_left   = state['rec_left']
        rec_frames = state['rec_frames']
        rec_msg    = state['rec_msg']
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
    info_text.set_color('#88ffaa' if core_done() else '#ccddee')

    # -- 진행바: 녹화중=보라(실시간 채움) / 평소=초록(RAW 수집중) --
    if rec_left is not None:
        frac = 1.0 - max(0.0, min(1.0, rec_left / EMPTY_REC_SEC))
        prog_fill.set_width(max(0.02, frac))
        prog_fill.set_color('#a050ff')
        prog_txt.set_text(f'Recording empty-room raw...  {rec_left:.0f}s left  ({rec_frames} frames)  (stay OUT of view!)')
    else:
        prog_fill.set_width(1.0)
        prog_fill.set_color('#2e7d4f')
        prog_txt.set_text(f'RAW mode (no clutter removal)   .   empty-room raw: {rec_msg}')
    return scatter3d, info_text, prog_fill, prog_txt


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
    print(f'  목표(합계) : ' + ', '.join(f'{CLASS_LABEL[c]} {TARGET[c]}' for c in DONE_CLASSES))
    print(f'  사람(person) : 키 a/b/c 로 전환 (기본 {CUR_PERSON}). collector 1회 실행으로 3명 태깅.')
    print('  [터미널 1] python3 ~/radar_parser.py   (먼저)')
    print('  [터미널 2] python3 ~/radar_collect.py  (이것)')
    print('=' * 60)

    print('  수집 모드 : RAW (클러터 제거 안 함 - 정적 클러터는 오프라인 3D 처리)')
    print(f'  빈방 raw  : [REC empty-room] 버튼으로 빈방 원본 {EMPTY_REC_SEC:.0f}s 녹화 -> {EMPTY_RAW_PATH}')
    print('              (오프라인 3D 클러터맵 재료. 낙상/동작 수집 전에 1회 녹화 권장.)')
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
