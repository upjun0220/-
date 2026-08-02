"""
radar_viz.py — IWR6843 실시간 Point Cloud 시각화
==================================================
radar_parser.py 와 동시에 실행:

    [젯슨 터미널 1]  python3 ~/radar_parser.py
    [젯슨 터미널 2]  python3 ~/radar_viz.py

흐름:
  - stage1_filtered.json 을 0.5초마다 폴링
  - 최신 프레임의 x, y, z scatter 3D + Z 시계열 + 포인트 수 실시간 업데이트
  - 낙상 감지 기준: Z 중심 (centroid_z) 1.7 m → 0.3 m 급강하

의존 패키지:
    python3 -m pip install matplotlib --break-system-packages

실행 환경: 젯슨 터미널 (로컬 디스플레이 연결)
"""

import json
import time
import os
import numpy as np
import matplotlib
matplotlib.use('TkAgg')          # Jetson 로컬 디스플레이 (HDMI 연결 시)
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D   # noqa: F401 (3D 서브플롯 활성화)
from matplotlib.animation import FuncAnimation
from collections import deque

# ── 설정 ────────────────────────────────────────────────────────────
JSON_PATH    = '/home/project/stage1_filtered.json'
POLL_SEC     = 0.5       # json 폴링 간격 (초)
HISTORY_LEN  = 100       # Z 시계열에 표시할 최대 프레임 수
FALL_Z_THR   = 0.6       # 낙상 판정 Z 임계값 (m) — 이 값 이하면 빨간색 표시
UPDATE_MS    = int(POLL_SEC * 1000)   # FuncAnimation 인터벌

# ── 상태 버퍼 ────────────────────────────────────────────────────────
cz_history   = deque([1.7] * HISTORY_LEN, maxlen=HISTORY_LEN)  # centroid Z 이력
cnt_history  = deque([0]   * HISTORY_LEN, maxlen=HISTORY_LEN)  # 포인트 수 이력
_last_mtime  = 0.0
_last_frames = []

# ── Figure / Axes 초기화 ─────────────────────────────────────────────
fig = plt.figure(figsize=(14, 7), facecolor='#1a1a2e')
fig.suptitle('Radar-Guard | IWR6843 실시간 Point Cloud', color='white', fontsize=13, y=0.97)

# 왼쪽: 3D scatter
ax3d = fig.add_subplot(1, 3, 1, projection='3d', facecolor='#16213e')
ax3d.set_title('Point Cloud (최신 프레임)', color='white', fontsize=10)
ax3d.set_xlabel('X (m)', color='#aaaacc', fontsize=8)
ax3d.set_ylabel('Y / 깊이 (m)', color='#aaaacc', fontsize=8)
ax3d.set_zlabel('Z / 높이 (m)', color='#aaaacc', fontsize=8)
ax3d.tick_params(colors='#888899', labelsize=7)
ax3d.set_xlim(-2, 2)
ax3d.set_ylim(0, 5)
ax3d.set_zlim(0, 2.5)
for pane in (ax3d.xaxis.pane, ax3d.yaxis.pane, ax3d.zaxis.pane):
    pane.fill = False
    pane.set_edgecolor('#333355')
scatter3d = ax3d.scatter([], [], [], c=[], cmap='plasma',
                          vmin=0, vmax=600, s=20, alpha=0.85)
# 3D subplot 밖에 고정 텍스트로 표시 (text2D는 3D 렌더링 때 위치 흔들림)
status_text = fig.text(0.01, 0.50, '⏳ 대기 중...',
                        color='white', fontsize=10, va='center',
                        bbox=dict(boxstyle='round,pad=0.4',
                                  facecolor='#16213e', edgecolor='#444466', alpha=0.9))

# 가운데: Z 시계열 (낙상 핵심 지표)
ax_z = fig.add_subplot(1, 3, 2, facecolor='#16213e')
ax_z.set_title('Centroid Z 시계열  ← 낙상 감지 핵심', color='white', fontsize=10)
ax_z.set_xlabel('프레임', color='#aaaacc', fontsize=8)
ax_z.set_ylabel('Z (m)', color='#aaaacc', fontsize=8)
ax_z.tick_params(colors='#888899', labelsize=7)
ax_z.set_ylim(0, 2.5)
ax_z.axhline(y=FALL_Z_THR, color='red', linestyle='--', linewidth=1.2, alpha=0.7)
ax_z.axhline(y=1.7, color='#44ff88', linestyle=':', linewidth=1.0, alpha=0.5)
ax_z.text(HISTORY_LEN * 0.02, FALL_Z_THR + 0.05, f'낙상 임계 {FALL_Z_THR}m',
          color='red', fontsize=7)
ax_z.text(HISTORY_LEN * 0.02, 1.75, '정상 서있는 높이 1.7m',
          color='#44ff88', fontsize=7)
ax_z.spines['bottom'].set_color('#333355')
ax_z.spines['left'].set_color('#333355')
ax_z.spines['top'].set_visible(False)
ax_z.spines['right'].set_visible(False)
line_z, = ax_z.plot([], [], color='#00c8ff', linewidth=2)

# 오른쪽: 포인트 수 + 도플러 바 차트
ax_cnt = fig.add_subplot(1, 3, 3, facecolor='#16213e')
ax_cnt.set_title('포인트 수 시계열', color='white', fontsize=10)
ax_cnt.set_xlabel('프레임', color='#aaaacc', fontsize=8)
ax_cnt.set_ylabel('포인트 수', color='#aaaacc', fontsize=8)
ax_cnt.tick_params(colors='#888899', labelsize=7)
ax_cnt.set_ylim(0, 150)
ax_cnt.spines['bottom'].set_color('#333355')
ax_cnt.spines['left'].set_color('#333355')
ax_cnt.spines['top'].set_visible(False)
ax_cnt.spines['right'].set_visible(False)
line_cnt, = ax_cnt.plot([], [], color='#ffaa00', linewidth=2)

# 메타 텍스트 (하단)
meta_text = fig.text(0.5, 0.01,
    f'📡 폴링: {JSON_PATH}  |  간격: {POLL_SEC}s  |  히스토리: {HISTORY_LEN}프레임',
    ha='center', color='#666688', fontsize=8)

fig.tight_layout(rect=[0, 0.04, 1, 0.96])


# ── 데이터 로드 ──────────────────────────────────────────────────────
def load_latest_frame():
    """stage1_filtered.json 에서 최신 프레임을 읽어 반환. 변경 없으면 None."""
    global _last_mtime, _last_frames
    if not os.path.exists(JSON_PATH):
        return None, None

    try:
        mtime = os.path.getmtime(JSON_PATH)
    except OSError:
        return None, None

    if mtime == _last_mtime and _last_frames:
        return _last_frames[-1], _last_frames   # 변경 없음 → 캐시 반환

    try:
        with open(JSON_PATH, 'r') as f:
            frames = json.load(f)
        if not frames:
            return None, None
        _last_mtime = mtime
        _last_frames = frames
        return frames[-1], frames
    except (json.JSONDecodeError, OSError):
        return None, None   # 파일 쓰는 중 — 다음 폴링 때 재시도


# ── FuncAnimation 업데이트 함수 ──────────────────────────────────────
def update(_frame_idx):
    frame_pts, _ = load_latest_frame()

    # ── 3D scatter 업데이트 ────────────────────────────────────────
    if frame_pts:
        xs = [p['x']         for p in frame_pts]
        ys = [p['y']         for p in frame_pts]
        zs = [p['z']         for p in frame_pts]
        cs = [p['intensity'] for p in frame_pts]

        scatter3d._offsets3d = (xs, ys, zs)
        scatter3d.set_array(np.array(cs))

        cz = float(np.mean(zs)) if zs else 1.7
        n  = len(frame_pts)
        cz_history.append(cz)
        cnt_history.append(n)

        # 낙상 여부 판정 — fig.text 위치 고정이므로 흔들리지 않음
        is_fall = cz < FALL_Z_THR
        color   = '#ff4444' if is_fall else '#44ff88'
        label   = f'FALL!\nZ={cz:.2f}m\n{n}pts' if is_fall else f'OK\nZ={cz:.2f}m\n{n}pts'
        status_text.set_text(label)
        status_text.set_color(color)
        status_text.get_bbox_patch().set_edgecolor(color)
    else:
        cz_history.append(cz_history[-1])
        cnt_history.append(0)
        status_text.set_text('대기 중...')
        status_text.set_color('#888888')

    # ── Z 시계열 업데이트 ──────────────────────────────────────────
    xs_t = list(range(len(cz_history)))
    ys_z = list(cz_history)
    line_z.set_data(xs_t, ys_z)
    ax_z.set_xlim(0, HISTORY_LEN)

    # ── 포인트 수 시계열 업데이트 ──────────────────────────────────
    line_cnt.set_data(list(range(len(cnt_history))), list(cnt_history))
    ax_cnt.set_xlim(0, HISTORY_LEN)

    return scatter3d, line_z, line_cnt, status_text


# ── 실행 ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 60)
    print("  Radar-Guard 실시간 시각화  |  radar_viz.py")
    print("=" * 60)
    print(f"  폴링 대상: {JSON_PATH}")
    print(f"  폴링 간격: {POLL_SEC}s")
    print(f"  낙상 임계: Z < {FALL_Z_THR} m")
    print()
    print("  [젯슨 터미널 1] python3 ~/radar_parser.py  ← 수집")
    print("  [젯슨 터미널 2] python3 ~/radar_viz.py     ← 지금 이거")
    print()
    print("  창 닫기 또는 Ctrl+C 로 종료")
    print("=" * 60)

    ani = FuncAnimation(fig, update, interval=UPDATE_MS,
                        blit=False, cache_frame_data=False)
    plt.show()
