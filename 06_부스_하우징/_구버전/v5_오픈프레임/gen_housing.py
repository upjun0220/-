#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radar-Guard | IWR6843ISK-ODS 오버헤드 하우징 3D 프린팅 생성기
v5 (2026-07-22) — 개방형(open-frame) 재설계

[v4 -> v5 변경 이유]
 v4는 바닥판이 있는 '박스형'이었다. 문제 3가지:
  1) FOV 클리핑 : 안테나 주변 42x42 PETG 벽이 ODS 광각(±60deg)을 원통형으로 가렸다.
     안테나가 개구 바닥에서 h 만큼 뜨면 반각 = atan(21/h).
     h=8.5 -> 68deg (여유), h=14.5 -> 55deg (스펙 미달, 바닥 구석의 누운 사람이 잘림).
  2) 부품 간섭 : 안테나면과 부품면이 같은 면이라, 안테나를 아래로 두면
     J3(CAN 커넥터, 3핀 헤더)가 바닥판을 때린다. 피하려고 스탠드오프를 올리면 1)이 악화.
  3) 클러터    : 안테나 바로 앞의 PETG가 불필요한 반사원이 된다.
 -> 바닥판과 개구벽을 전부 제거. 보드는 코너 4점 보스로만 지지하고 아래는 완전 개방.
    J3는 허공으로 향하므로 보드 무개조(인두/니퍼 불필요, 이미 1회 파손 이력 있는 보드 보호).

[체결 방식] 동봉 M3 볼트를 '아래에서 위로' 관통 삽입 -> 보드 윗면(부품 없는 면)에서 너트 조임.
           보스 구멍은 관통 Ø3.3 (v4는 막힌 Ø2.7이라 볼트가 아예 안 들어갔음).

실행(PowerShell):  python gen_housing.py
"""
import numpy as np, trimesh
import trimesh.transformations as tf
from trimesh.creation import box, cylinder, icosphere

# ============================================================
# [!] 실측 교체 구역 — 아래 5개 값만 바꾸면 전체가 따라 갱신됨
#     현재 값은 '가정값'이며 TI 공식 문서(SWRU546E)에 보드 기구도면이 없어
#     공개 자료로는 확증 불가. 반드시 캘리퍼스 실측으로 교체할 것.
# ============================================================
board_L = 65.0     # 보드 가로(mm)                      [가정값]
board_W = 50.0     # 보드 세로(mm)                      [가정값]
board_t = 1.6      # 기판 두께(mm)                      [가정값]
hole_ix = 4.5      # 보드 모서리 -> 홀 중심 X 거리(mm)   [가정값]
hole_iy = 4.5      # 보드 모서리 -> 홀 중심 Y 거리(mm)   [가정값]

boss_d  = 6.4      # 보스(턱) 바깥지름. 홀 주변 부품 키프아웃보다 작아야 함 [요실측]

# ==== 체결 ====
screw_d   = 3.0    # M3 (TI UG SWRU546E 2.4.3절에서 M3 확인됨)
hole_thru = 3.3    # 관통홀 지름 = M3 + 여유 0.3

# ==== 하우징 (개방형) ====
clr       = 1.5    # 보드 주변 여유
wall      = 3.0    # 벽 두께
post_h    = 5.0    # 보드 밑면 ~ 하우징 하단 (볼트머리 여유). 여기가 FOV에 노출되는 유일한 구간
headroom  = 20.0   # 보드 윗면 ~ 하우징 상단 (USB 서비스루프 공간)

# ==== 3030 클램프 (v4와 동일, 알루미늄 프레임에 그대로 물림) ====
profile_w = 30.0; clampC = 0.6      # 채널 내폭 30.6
swc = 4.0; saddle_h = 26.0; saddle_len = 62.0

cav_L = board_L + 2*clr; cav_W = board_W + 2*clr
out_L = cav_L + 2*wall;  out_W = cav_W + 2*wall
wall_h = post_h + board_t + headroom
hx = board_L/2 - hole_ix; hy = board_W/2 - hole_iy   # 홀 중심 좌표

def T(x=0, y=0, z=0):
    m = np.eye(4); m[:3, 3] = [x, y, z]; return m

def thread_hole_Y(x, z, L):
    """가로(Y축) 내부 나사산 구멍 — clamp_screw.stl(r_core3.0, r_pitch3.7, bead1.2, pitch3.0)용."""
    core = cylinder(radius=3.30, height=L, sections=40)
    parts = [core]
    pitch = 3.0; rp = 3.7; bcut = 1.55
    turns = L/pitch; tmax = 2*np.pi*turns; n = int(tmax*rp/0.8)
    for i in range(n+1):
        th = tmax*i/n; zz = -L/2 + pitch*th/(2*np.pi)
        if not (13.5 < abs(zz) < 21.5): continue
        b = icosphere(subdivisions=1, radius=bcut)
        b.apply_translation([rp*np.cos(th), rp*np.sin(th), zz]); parts.append(b)
    cut = trimesh.boolean.union(parts, engine='manifold')
    cut.apply_transform(tf.rotation_matrix(np.pi/2, [1, 0, 0]))
    cut.apply_transform(T(x, 0, z))
    return cut

def make_tray():
    """바닥판 없는 사각 튜브 + 코너 거싯 + 보스 4개."""
    # 1) 벽만 (바닥 없음) — 아래로 완전 관통
    tray = box([out_L, out_W, wall_h]); tray.apply_transform(T(0, 0, wall_h/2))
    cav  = box([cav_L, cav_W, wall_h*3]); cav.apply_transform(T(0, 0, wall_h/2))
    tray = tray.difference(cav, engine='manifold')

    # 2) 보스 4개 (보드가 이 위에 앉음) — z = 0 ~ post_h
    add = []
    for sx in (hx, -hx):
        for sy in (hy, -hy):
            p = cylinder(radius=boss_d/2, height=post_h, sections=32)
            p.apply_transform(T(sx, sy, post_h/2)); add.append(p)

    # 3) 코너 거싯 — 벽 안쪽 코너에서 보스까지 대각 연결.
    #    FOV 중앙을 피하려고 일부러 코너에만 둠.
    for sx in (1, -1):
        for sy in (1, -1):
            cx, cy = sx*cav_L/2, sy*cav_W/2      # 벽 안쪽 코너
            bxp, byp = sx*hx, sy*hy              # 보스 중심
            mx, my = (cx+bxp)/2, (cy+byp)/2
            ln = float(np.hypot(cx-bxp, cy-byp)) + boss_d*0.6
            ang = float(np.arctan2(byp-cy, bxp-cx))
            g = box([ln, 4.0, post_h])
            g.apply_transform(tf.rotation_matrix(ang, [0, 0, 1]))
            g.apply_transform(T(mx, my, post_h/2)); add.append(g)
    tray = tray.union(add, engine='manifold')

    # 4) 관통홀 Ø3.3 — 아래에서 볼트 삽입
    hl = []
    for sx in (hx, -hx):
        for sy in (hy, -hy):
            h = cylinder(radius=hole_thru/2, height=post_h*4, sections=28)
            h.apply_transform(T(sx, sy, post_h/2)); hl.append(h)
    tray = tray.difference(hl, engine='manifold')

    zc = post_h + board_t + 3   # 보드 윗면 기준

    # 5) USB 배출 슬롯 (한쪽 짧은 벽)
    slot = box([wall*3, 12, headroom]); slot.apply_transform(T(out_L/2, 0, zc+headroom/2-2))
    tray = tray.difference(slot, engine='manifold')

    # 6) 케이블 서비스루프 권취 포스트 + 장력 차단 포스트
    add2 = []
    for py in (8, -8):
        p = box([5, 3, 10]); p.apply_transform(T(cav_L/2-4, py, zc+3)); add2.append(p)
    for wy in (11, -11):
        wp = cylinder(radius=3, height=headroom-3, sections=24)
        wp.apply_transform(T(cav_L/2-18, wy, zc+(headroom-3)/2)); add2.append(wp)
        cap = cylinder(radius=5, height=2.5, sections=24)
        cap.apply_transform(T(cav_L/2-18, wy, zc+headroom-4)); add2.append(cap)
    tray = tray.union(add2, engine='manifold')

    # 7) 벤트 (긴 벽 2면) — 보드 윗면 위쪽에만
    vent = []
    for vx in (-10, 0, 10):
        for sy in (1, -1):
            v = box([2.4, wall*3, 10]); v.apply_transform(T(vx, sy*out_W/2, zc+2)); vent.append(v)
    tray = tray.difference(vent, engine='manifold')

    # 8) 뚜껑 체결용 코너 보스 (M3 셀프탭 Ø2.7)
    bx = out_L/2 - wall/2 - 2.6; by = out_W/2 - wall/2 - 2.6
    bs = []
    for sx in (bx, -bx):
        for sy in (by, -by):
            b = cylinder(radius=3.2, height=wall_h, sections=24)
            b.apply_transform(T(sx, sy, wall_h/2)); bs.append(b)
    tray = tray.union(bs, engine='manifold')
    ch = []
    for sx in (bx, -bx):
        for sy in (by, -by):
            h = cylinder(radius=1.35, height=wall_h*1.2, sections=20)
            h.apply_transform(T(sx, sy, wall_h/2)); ch.append(h)
    tray = tray.difference(ch, engine='manifold')
    return tray

def make_lid():
    lt = 3.0
    lid = box([out_L, out_W, lt]); lid.apply_transform(T(0, 0, lt/2))
    ch_in = profile_w + clampC
    yoff = ch_in/2 + swc/2
    walls = []
    for sy in (yoff, -yoff):
        w = box([saddle_len, swc, saddle_h]); w.apply_transform(T(0, sy, lt+saddle_h/2)); walls.append(w)
    lid = lid.union(walls, engine='manifold')
    lid = lid.difference(thread_hole_Y(0, lt+15, out_W+12), engine='manifold')
    bx = out_L/2 - wall/2 - 2.6; by = out_W/2 - wall/2 - 2.6
    ch = []
    for sx in (bx, -bx):
        for sy in (by, -by):
            h = cylinder(radius=1.7, height=20, sections=20); h.apply_transform(T(sx, sy, lt)); ch.append(h)
    lid = lid.difference(ch, engine='manifold')
    return lid

if __name__ == '__main__':
    tray = make_tray(); lid = make_lid()
    tray.export('housing_tray.stl'); lid.export('housing_lid.stl')
    l2 = lid.copy(); l2.apply_transform(T(0, 0, wall_h+2))
    trimesh.util.concatenate([tray, l2]).export('housing_assembly.stl')

    fov = np.degrees(np.arctan2(min(cav_L, cav_W)/2, post_h))
    print('=== v5 open-frame ===')
    print('외형        : %.1f x %.1f x %.1f mm   (v4: 74 x 59 x 30.1)' % (out_L, out_W, wall_h))
    print('보스 홀 좌표 : (+-%.1f, +-%.1f)  관통 O%.1f' % (hx, hy, hole_thru))
    print('안테나 하방  : 완전 개방 (개구벽 없음)')
    print('벽 하단 노출 : %.1f mm  -> 이론 반각 %.0f deg (>=60 필요)' % (post_h, fov))
    print('watertight  : tray=%s  lid=%s' % (tray.is_watertight, lid.is_watertight))
    print('필요 볼트    : M3 x %.0f mm 이상 (보스%.1f + 기판%.1f + 너트2.4)'
          % (np.ceil(post_h+board_t+2.4+1), post_h, board_t))
