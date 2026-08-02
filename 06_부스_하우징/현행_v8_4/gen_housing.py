#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radar-Guard | IWR6843ISK-ODS (PROC075 Rev C) 오버헤드 하우징 3D 프린팅 생성기
v6 (2026-07-22) — 개방형(open-frame) + USB 장력해소 모듈

[모든 치수 출처] TI 공식 설계파일 SWRR165B.ZIP 의 Rev C STEP(PROC075C_PCB.step) 에서
                 기계적으로 추출. 눈대중 추정 없음. (레이더보드_실측규격.md 참조)

[좌표계] STEP 원본 그대로 사용.
   X: 0 .. 55 (mm)        Y: -7.832 .. 60.624 (mm)
   +Y = 안테나 방향(위)    -Y·+X 코너 = 마이크로USB(J5)
   보드 bbox 중심 = (27.5, 26.396)

[장착 방향] 오버헤드. 안테나면이 아래(바닥)를 향함 = 부품/안테나면이 하방.
   보드를 4개 보스 위에 '안테나면 아래로' 올려놓고,
   볼트를 아래(바닥쪽)에서 끼워 보드 뒷면(위)에서 너트로 조임.
   보스는 접지 스트립 위의 코너 홀에만 닿음(안테나 소자·부품 회피).

[개방형 근거] 안테나 위치에 ±2mm 불확실성 존재(Rev A/C 차이).
   개구 벽을 두면 정렬 리스크가 됨 → 벽을 없애 정렬 자체를 불필요화.
   보드면(z=z_ant) 아래는 4개 보스 외에 아무 구조물 없음 → 하방 FOV 전면 개방.

[USB 장력해소] 마이크로USB(J5, 5핀)는 과거 1회 파손 이력(장력).
   3중 방어:  (1) 크래들 = 커넥터 몸체를 밑에서 받쳐 하중 지레작용 차단
             (2) 케이블 클램프 = 케이블을 하우징에 케이블타이로 고정 → 장력이 납땜부에 안감
             (3) 서비스 루프 훅 = 프레임까지 여유길이 확보(무장력)

실행(PowerShell):  python gen_housing.py
"""
import numpy as np, trimesh
import trimesh.transformations as tf
from trimesh.creation import box, cylinder, icosphere

# ============================================================
# [실측 확정값] — TI Rev C STEP 추출
# ============================================================
board_L = 55.000     # X
board_W = 68.456     # Y (스팬 -7.832 .. 60.624)
board_t = 1.516
BY0, BY1 = -7.832, 60.624       # 보드 Y 범위(STEP 절대)
BX0, BX1 = 0.0, 55.0            # 보드 X 범위

# ============================================================
# [보드 방향] v7 (2026-07-23) — 안테나면 아래로 뒤집어 실장(오버헤드)에 맞춘 Y축 미러.
#   보드를 컴포넌트면 위(=안테나 아래)로 뒤집으면 홀/부품이 보드 bbox 중심(Y=26.396)
#   기준으로 Y가 반전됨. X는 불변(좌우 그대로) → USB(5핀)가 '오른쪽-위'로 이동(사진2).
#   ※ 원점대칭(X,Y 모두 반전)이 아니라 '가로축 미러(Y만 반전)'가 물리적으로 맞음.
#     - 뒤집기 = 거울(반사), 회전 아님 / 오른쪽은 유지되고 위아래만 바뀜 / 3핀헤더 좌측 유지가 증거.
#   MIRROR_Y=False 로 두면 v6(안테나 위) 원본 좌표로 복귀.
# ============================================================
MIRROR_Y = True
TIE_ANCHOR = True                          # v8.4: 하부 -Y 타이패드. 슬롯은 X관통(하부 개방공간↔바깥)
TIE_WALLSLOT = False                       # v8.4: 폐지 — 캐비티 내부로 나와서 뚜껑 닫으면 못 씀

# ============================================================
# [v8.1 수정] 2026-07-25 — v8 타이앵커 결함 2건 수정
#   (a) v8은 +X벽을 통짜로 z0..z_ant 연장하고 5.0x3.2 창만 뚫었음 → 마이크로USB
#       '플러그'가 못 지나감(USB 2.0 Micro-B 플러그 쉘 규격 6.85x1.80,
#       하우징 ~8x3, 오버몰드 ~11x5.5). 커넥터 정면 0.97mm 앞을 막은 셈.
#       → 창을 TIE_WIN_W(12mm) x 전높이(z0..z_ant) 로 완전 개방. v7과 동일한
#         플러그 진입로 확보(v7은 이 구간이 통째로 비어 있었고 실제 조립 성공).
#   (b) v8 타이슬롯이 립 Y폭(12.0) 대비 jy±5.0·폭2.2 라서 필요반폭 6.1 > 6.0
#       → 양끝이 0.1mm 터진 U자 노치가 됨(타이가 빠짐). 단면적 40.44mm²로 확인.
#   (c) v8 슬롯 단면 1.8x2.2 는 부품표의 '3mm 케이블타이'(폭 ~3.4 x 두께 ~1.1)가
#       물리적으로 안 지나감.
#
# [v8.2 수정] 2026-07-26 — 실물 사진 확인 + USB-IF 규격 대조. v6~v8 공통 결함 해결.
#   (d) ★근본원인: +X 벽(x 57.1~61.1, z 5~24.5)이 플러그 오버몰드를 막는다.
#       - 사진 확인: 오버몰드 앞면이 보드 끝선(x=55)에 맞닿음 → 벽 4mm를 반드시 관통
#       - 오버몰드 높이 6.4(실제품)~8.5(규격상한), 플러그 축 z=3.64 중심
#         → 윗면 z 6.84~7.89 이 벽 시작(z=5.0)보다 1.8~2.9mm 위 → 걸림
#       - 이건 v8만이 아니라 v6·v7에도 있던 문제(v7은 보드 안착만 검증, USB 미검증)
#       → +X 벽에 USB 개구부를 뚫는다(45° 게이블 지붕 = 서포트 불필요).
#   (e) 개구부 반폭 5.75가 필요한데 코너 볼트기둥(OY1-3) 때문에 4.61밖에 안 나옴.
#       기둥은 보드 간섭 때문에 -X로도 못 옮김(x<58.1이면 보드와 충돌).
#       → +Y 외벽만 4→6mm 확장(wall_Y1). 외형 79.5→81.5. 개구 반폭 6.61 확보.
#
# [v8.3 추가] 2026-07-26 — 장력 앵커 복원. 단, '선반'이 아니라 '타이'.
#   · 하중경로: 앵커가 없으면 케이블 힘은 100% J5 납땜부로 간다(다른 경로 없음).
#   · 그러나 '오버몰드를 밑에서 받치는 선반'은 넣을 자리가 없다 —
#     오버몰드 하면 z = +0.44(실제품 6.4) / -0.61(규격상한 8.5) 로 이미 하우징
#     바닥면(z=0)에 붙어 있다. 선반은 바닥면보다 더 내려가야만 가능.
#   · 애초에 막아야 할 하중이 다르다. 케이블 자중 30g×팔 25.6mm = 7.4 mN·m 인데
#     USB Micro 규격 §6.7 무손상 한계는 15mm 지점 25N = 375 mN·m → 자중은 2.0%.
#     정적으로는 안 부러진다. 실제 위험은 '잡아채기'(과거 파손 정황과 일치).
#     → 눌러 받치는 선반이 아니라 '묶는 타이'가 맞는 대책.
#   · 앵커 2곳, 둘 다 플러그 봉투(Y 50.1~60.9 / Z ≤7.89) 밖:
#     (a) -Y 하부 패드      : 플러그 옆, 케이블 나오자마자 결속 (1차)
#     (b) +X 상부 벽 슬롯   : 게이블 꼭지 위 solid 구간. 프로파일로 올라가는
#                             서비스 루프를 하우징에 고정 (2차)
# ============================================================
USB_RELIEF = True    # +X 벽 USB 개구부
USB_REL_W  = 11.5    # 개구 Y폭 (규격상한 오버몰드 10.6 / 실제품 10.8 + 여유)
USB_REL_Z  = 8.5     # 개구 상단 높이 (규격상한 오버몰드 윗면 7.89 + 여유)
TIE_PAD_OFF = 6.0    # 패드 +Y끝 ~ 플러그축 거리 (오버몰드 반폭 5.4 + 0.6 이격)
TIE_PIL_W  = 13.0    # -Y 타이패드 Y폭
# ★v8.4: 슬롯 방향을 Z관통 → X관통 으로 변경.
#   Z관통은 위가 +X 벽(z 5~24.5)에 막혀서 '아래로만 열린 막힌 구멍'이 됐다(z=8.6에서 죽음).
#   X관통이면 바깥(x>61.1 = 공중)과 안쪽(x<57.1 = 보드 밑 개방공간) 양쪽이 다 열린다.
#   둘 다 하우징 아래에서 손이 닿으므로 뚜껑·보드와 무관하게 조립 후에도 결속 가능.
TIE_SLOT_Y  = 2.0    # 슬롯 Y폭 (타이 두께 ~1.1 통과)
TIE_SLOT_Z0 = 1.2    # 슬롯 하단 z (아래 바닥살 1.2mm)
TIE_SLOT_YS = (-9.5, -2.0)   # 패드 +Y끝(py1) 기준 슬롯 중심 오프셋
_yc = (BY0 + BY1) / 2.0                    # 보드 bbox Y중심 = 26.396
def mY(y): return (2*_yc - y) if MIRROR_Y else y

# 마운팅 홀 8개 중 사용할 4개(최대 스팬 코너) — 전부 Ø3.000 PTH. Y반전: 57.124→-4.33, 8.624→44.17
HOLES = [(3.0, mY(57.124)), (52.0, mY(57.124)), (52.0, mY(8.624)), (3.0, mY(8.624))]

# 돌출 부품(안테나=하방면). 반사는 min/max를 뒤바꾸므로 y0<y1 유지되게 mY(큰값)을 y0로.
J3 = dict(x0=-3.29, x1=1.71, y0=mY(21.14), y1=mY(17.33), h=2.30)   # CAN 커넥터(좌측 돌출)
J5 = dict(x0=50.70, x1=56.13, y0=mY(1.38), y1=mY(-6.82), h=2.72)   # 마이크로USB(미러후 우상)
ANT = dict(x0=19.5, x1=54.3, y0=mY(56.1), y1=mY(31.1))            # 안테나 구역(±2mm)

# ==== 체결 ====
hole_thru = 3.4      # 하우징 관통홀(보드 Ø3.0, 공차는 하우징이 흡수)
boss_d    = 5.6      # 보스 바깥지름(작게 유지 → 안테나 코너 FOV 손실 최소)

# 뚜껑↔트레이 코너 볼트 = M3 관통 + 바깥 너트조임 (v8). 셀프탭 아님 → 양쪽 다 클리어런스 관통.
#   벽을 밖으로 두껍게(3→4mm) 한 만큼 코너 기둥도 두꺼워져 Ø3.4 구멍 주변 살 확보(→너트 조여도 안 갈라짐).
LIDBOSS_R    = 3.0   # 코너 기둥 반경(Ø6.0). 벽 확장분으로 보드 간섭 없이 확보
LIDBOSS_HOLE = 1.7   # 코너 관통홀 반경(Ø3.4) — 3mm 볼트 여유 통과, 반대편 너트로 조임

# ==== 캐비티/벽 여유 (비대칭 — 돌출부 반영) ====
clr_L = 4.30   # -X: J3(-3.29) 회피 + 1.0 마진
clr_R = 2.10   # +X: J5(56.13) 회피 + 1.0 마진 (보드끝 55 기준 +1.13 돌출)
clr_Y = 1.50   # ±Y
wall  = 4.0    # v8: 3→4 (밖으로만 확장). 내부 캐비티(clr_*)는 불변 → 보드 핏 그대로. 강성↑·코너살↑
wallY1 = 6.0   # v8.2: +Y 외벽만 4→6. 코너 볼트기둥을 USB 개구부 밖으로 밀어내기 위함(캐비티 불변)

# ==== 수직 스택 (z=0 = 바닥/floor 쪽 하단) ====
post_h   = 5.0                     # 보스 높이(=보드 안테나면 z). 이 아래는 개방
headroom = 18.0                    # 보드 뒷면 위 여유(뒷면부품3.25 + 케이블루프)
z_ant    = post_h                  # 안테나면(보드 하면)
z_bk     = z_ant + board_t         # 보드 뒷면(상면)
z_top    = z_bk + headroom         # 벽 상단 = 뚜껑 안착면
wall_h_top = z_top

# ==== 3030 클램프 (알루미늄 프레임 물림) ====
profile_w = 30.0; clampC = 0.6     # 채널 내폭 30.6
swc = 4.0; saddle_h = 26.0; saddle_len = 70.0
knob_thread_L = None               # thread_hole_Y 로 처리

# ---- 캐비티/외형 (STEP 절대좌표) ----
CX0, CX1 = BX0 - clr_L, BX1 + clr_R          # 캐비티 X
CY0, CY1 = BY0 - clr_Y, BY1 + clr_Y          # 캐비티 Y
OX0, OX1 = CX0 - wall, CX1 + wall             # 외형 X
OY0, OY1 = CY0 - wall, CY1 + wallY1           # 외형 Y (+Y만 6mm — v8.2)
cx = (OX0 + OX1)/2; cy = (OY0 + OY1)/2        # 하우징 중심(뚜껑 새들 정렬용)
_ins = LIDBOSS_R                               # 코너 기둥 인셋 = 반경 → 기둥 바깥면이 외곽과 flush
LID_BOSS_XY = [(OX0+_ins,OY0+_ins),(OX1-_ins,OY0+_ins),
               (OX1-_ins,OY1-_ins),(OX0+_ins,OY1-_ins)]

def T(x=0, y=0, z=0):
    m = np.eye(4); m[:3, 3] = [x, y, z]; return m
def boxc(sx, sy, sz, x, y, z):
    """중심(x,y,z), 크기(sx,sy,sz) 박스"""
    b = box([sx, sy, sz]); b.apply_transform(T(x, y, z)); return b
def cyl(r, h, x, y, z, sec=40):
    c = cylinder(radius=r, height=h, sections=sec); c.apply_transform(T(x, y, z)); return c

def thread_hole_Y(x, z, L):
    """가로(Y축) 내부 나사산 구멍 — clamp_screw.stl(r_core3.0,r_pitch3.7,bead1.2,pitch3.0)용."""
    core = cylinder(radius=3.30, height=L, sections=40); parts = [core]
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

# ======================================================================
def make_tray():
    add = []; cut = []

    # (1) 벽 = 사각 튜브. z_ant .. z_top (보드면 위쪽만). 아래는 개방.
    outer = boxc(OX1-OX0, OY1-OY0, z_top-z_ant, cx, cy, (z_ant+z_top)/2)
    cav   = boxc(CX1-CX0, CY1-CY0, (z_top-z_ant)*3, cx, cy, (z_ant+z_top)/2)
    tray  = outer.difference(cav, engine='manifold')

    # (2) 보스 4개 (z 0..z_ant), 코너 홀. 보드가 이 위에 안테나면으로 안착.
    for (hx, hy) in HOLES:
        add.append(cyl(boss_d/2, post_h, hx, hy, post_h/2))

    # (3) 보스-벽 연결 거싯 (코너에만, 얇게) → 강성/재현성 확보, 안테나 회피
    for (hx, hy) in HOLES:
        wx = OX0+wall/2 if hx < cx else OX1-wall/2      # 가까운 벽 X중심
        wy = OY0+wall/2 if hy < cy else OY1-wall/2
        # 보스에서 코너벽까지 X리브 + Y리브 (z 0..z_ant)
        add.append(boxc(abs(wx-hx)+boss_d*0.5, 3.0, post_h, (wx+hx)/2, hy, post_h/2))
        add.append(boxc(3.0, abs(wy-hy)+boss_d*0.5, post_h, hx, (wy+hy)/2, post_h/2))

    tray = trimesh.boolean.union([tray]+add, engine='manifold')

    # (4) 관통홀 Ø3.4 (아래에서 볼트 삽입)
    for (hx, hy) in HOLES:
        cut.append(cyl(hole_thru/2, post_h*4, hx, hy, post_h/2, sec=28))

    # (5) 뚜껑 체결 코너 기둥(Ø6.0, M3 관통) — 벽 '바깥 코너 meat' 안. 보드 footprint 회피.
    bset=[]
    for (sx, sy) in LID_BOSS_XY:
        bset.append(cyl(LIDBOSS_R, z_top-z_ant, sx, sy, (z_ant+z_top)/2))
    tray = trimesh.boolean.union([tray]+bset, engine='manifold')
    for (sx, sy) in LID_BOSS_XY:   # Ø3.4 클리어런스 관통(바닥으로 볼트 빠져 너트조임)
        cut.append(cyl(LIDBOSS_HOLE, (z_top-z_ant)*1.2, sx, sy, (z_ant+z_top)/2, sec=24))

    # (6) 벤트 (긴 벽 = ±Y 면, 보드 뒷면 위쪽) — 방열
    zc = z_bk + 4
    for vx in (cx-12, cx, cx+12):
        cut.append(boxc(2.4, wall*3, 9, vx, OY1, zc))
        cut.append(boxc(2.4, wall*3, 9, vx, OY0, zc))

    # (6b) J5 커넥터 몸체 클리어런스 — H7 거싯이 커넥터를 관통하지 않도록 비움
    #      (커넥터 하면 z_conn_bot .. 보드면 z_ant). 크래들 선반(z<z_conn_bot)은 보존.
    z_conn_bot = z_ant - J5['h']
    cut.append(boxc(J5['x1']-J5['x0']+3.0, J5['y1']-J5['y0']+3.0, z_ant-z_conn_bot+0.4,
                    (J5['x0']+J5['x1'])/2, (J5['y0']+J5['y1'])/2, (z_conn_bot+z_ant)/2+0.2))

    tray = tray.difference(trimesh.boolean.union(cut, engine='manifold'), engine='manifold')

    # (6c) ★v8.2 USB 개구부 — 플러그 오버몰드가 +X 벽을 관통하게 뚫는다.
    #      사진 확인: 오버몰드 앞면이 보드 끝선(x=55)에 맞닿음 → 벽(57.1~61.1) 관통 필수.
    #      오버몰드 z 상단이 6.84(실제품)~7.89(규격상한) 이라 벽 시작 z=5.0 위로 넘어감.
    #      지붕은 45° 게이블 → 수평 브리지 없음 = 서포트/막힘 없음.
    if USB_RELIEF:
        jy = (J5['y0'] + J5['y1']) / 2
        rel = boxc(wall*3, USB_REL_W, USB_REL_Z - z_ant,
                   OX1 - wall/2, jy, (z_ant + USB_REL_Z)/2)
        s = USB_REL_W / np.sqrt(2.0)                       # 45° 회전 정사각 → 수평 대각 = 개구폭
        gab = box([wall*3, s, s])
        gab.apply_transform(tf.rotation_matrix(np.pi/4, [1, 0, 0]))
        gab.apply_transform(T(OX1 - wall/2, jy, USB_REL_Z))
        tray = tray.difference(trimesh.boolean.union([rel, gab], engine='manifold'),
                               engine='manifold')

    # (7) USB(5핀) 장력해소 모듈 제거 (v7) — 사용자 요청: 크래들이 인필 격자로 막히던
    #     부분을 '완전 빈 공간'으로 개방. 커넥터는 보드면 아래(개방 프레임)로 돌출하므로
    #     케이블은 하부 개방부로 자유롭게 인출됨. keep-out (6b)만 유지해 보스/거싯이
    #     커넥터 몸체를 침범하지 않게 함.
    # (7b) 케이블타이 고정점 (v8) — 고정점을 '케이블 나오는 바닥쪽(커넥터 높이)'으로 이동.
    #      v7은 립을 보드면 위(z5~8)에 뒀는데, USB 케이블은 반대편(바닥쪽)으로 늘어져서
    #      위 립은 당김을 못 잡음(사용자 지적). → +X벽을 바닥(z0)까지 얇게 연장하고
    #      커넥터 높이에 케이블 통과슬롯 + 타이슬롯을 둠. 케이블을 나오자마자 하우징에 묶어
    #      당김 장력이 J5 납땜부 전에 끊김. 얇은판+관통슬롯이라 격자막힘 없음.
    # (7c) v8.3 (a) -Y 하부 타이패드 — 플러그 봉투 밖(+Y끝이 축에서 TIE_PAD_OFF)
    #      닫힌 Z관통 슬롯 2개. 타이: 슬롯1↓ → 하부 개방공간 → 슬롯2↑ → 케이블 위로 결속.
    if TIE_ANCHOR:
        jy = (J5['y0'] + J5['y1']) / 2                       # 미러후 USB 중심 ≈ 55.5
        py1 = jy - TIE_PAD_OFF
        py0 = py1 - TIE_PIL_W
        pyc = (py0 + py1) / 2
        pil = boxc(wall, TIE_PIL_W, z_ant, OX1 - wall/2, pyc, z_ant/2)
        tray = trimesh.boolean.union([tray, pil], engine='manifold')
        # X관통 슬롯 2개. 천장은 z=z_ant(위의 벽 밑면)가 그대로 막아주므로 얇은 살이 안 생김.
        sh = z_ant - TIE_SLOT_Z0
        cuts = []
        for d in TIE_SLOT_YS:
            cuts.append(boxc(wall*3, TIE_SLOT_Y, sh, OX1 - wall/2, py1 + d, TIE_SLOT_Z0 + sh/2))
            # v8.4b: 슬롯 천장도 45° 게이블 → 수평 브리지 0 = 서포트 안 붙음(USB 개구부와 동일 처리)
            g = box([wall*3, TIE_SLOT_Y/np.sqrt(2.0), TIE_SLOT_Y/np.sqrt(2.0)])
            g.apply_transform(tf.rotation_matrix(np.pi/4, [1, 0, 0]))
            g.apply_transform(T(OX1 - wall/2, py1 + d, z_ant))
            cuts.append(g)
        tray = tray.difference(trimesh.boolean.union(cuts, engine='manifold'), engine='manifold')
    return tray

def make_usb_relief():
    """USB 크래들 + 케이블 클램프 지지구조 (additive)."""
    jy = (J5['y0']+J5['y1'])/2                 # 커넥터 Y중심 ≈ -2.72
    z_conn_bot = z_ant - J5['h']               # 커넥터 하면 ≈ 2.28
    add = []
    # (a) +X 벽을 J5 구간에서 아래로 연장 (z0.9..z_ant) → 크래들 지지기둥
    add.append(boxc(wall, 11.0, z_ant-0.9, (CX1+OX1)/2, jy, (0.9+z_ant)/2))
    # (b) 크래들 선반 : 커넥터 밑을 받침 (x 49.5..CX1, z0.9..커넥터하면)
    shelf_x0 = 49.5; shelf_x1 = OX1
    add.append(boxc(shelf_x1-shelf_x0, 11.0, z_conn_bot-0.9,
                    (shelf_x0+shelf_x1)/2, jy, (0.9+z_conn_bot)/2))
    # (c) 케이블 클램프 새들 : +X 바깥으로 돌출, 상단에 케이블 안착 + 타이슬롯(컷은 별도)
    add.append(boxc(6.0, 11.0, 4.5, OX1+3.0, jy, 0.9+4.5/2))
    # (d) 서비스 루프 훅 : +X 상부 벽 바깥에 케이블 감는 훅 (무장력 여유)
    hz = z_bk + 6
    add.append(cyl(2.5, 8.0, OX1+3.0, cy-6, hz))
    add.append(cyl(4.5, 2.5, OX1+3.0, cy-6, hz+5.0))    # 이탈방지 캡
    return trimesh.boolean.union(add, engine='manifold')

def make_usb_cuts():
    """USB 모듈의 케이블 통로 + 케이블타이 슬롯 (subtractive)."""
    jy = (J5['y0']+J5['y1'])/2
    cut = []
    # 케이블 통로(+X로 관통) : 커넥터 중심 높이, 폭4.5
    cut.append(boxc(12.0, 5.0, 3.2, OX1+2.0, jy, z_ant-J5['h']/2-0.2))
    # 케이블타이 슬롯 2개 (클램프 새들 좌우로 관통, Y방향)
    for sx in (OX1+1.0, OX1+5.0):
        cut.append(boxc(2.0, 16.0, 2.2, sx, jy, 0.9+3.2))
    return trimesh.boolean.union(cut, engine='manifold')

# ======================================================================
def make_lid():
    lt = 3.0
    lid = boxc(OX1-OX0, OY1-OY0, lt, cx, cy, lt/2)
    # 3030 새들 채널(하우징 중심 정렬, Y축 방향으로 길게)
    ch_in = profile_w + clampC
    xoff = ch_in/2 + swc/2
    walls=[]
    for sx in (cx-xoff, cx+xoff):
        walls.append(boxc(swc, saddle_len, saddle_h, sx, cy, lt+saddle_h/2))
    lid = trimesh.boolean.union([lid]+walls, engine='manifold')
    # 프레임 관통볼트(5mm) — v8: 딤플 대신 실제 Ø5.5 관통홀을 딤플 중심에 뚫음.
    #   업체가 이미 이 위치에 5.5mm로 뚫어 5mm 볼트가 잘 들어감을 확인 → 모델에 반영(수동드릴 불필요).
    #   양쪽 새들 벽을 X축으로 관통(가운데 3030 채널부는 공백).
    zc = lt + 15                                   # 프로파일 단면 중심 높이(딤플과 동일)
    xoff = (profile_w+clampC)/2 + swc/2            # 새들 벽 중심 X오프셋
    fh = cylinder(radius=5.5/2, height=(xoff+swc/2)*2 + 6, sections=32)
    fh.apply_transform(tf.rotation_matrix(np.pi/2, [0,1,0]))   # 축을 Z→X
    fh.apply_transform(T(cx, cy, zc))
    lid = lid.difference(fh, engine='manifold')
    # 뚜껑↔트레이 코너 관통홀 Ø3.4 (트레이와 동일 좌표, 3mm 볼트 관통)
    cc=[]
    for (sx,sy) in LID_BOSS_XY:
        cc.append(cyl(LIDBOSS_HOLE, 20, sx, sy, lt, sec=24))
    lid = lid.difference(trimesh.boolean.union(cc,engine='manifold'), engine='manifold')
    return lid

# ======================================================================
if __name__ == '__main__':
    tray = make_tray(); lid = make_lid()
    tray.export('housing_tray.stl'); lid.export('housing_lid.stl')
    l2 = lid.copy(); l2.apply_transform(T(0, 0, wall_h_top+2))
    trimesh.util.concatenate([tray, l2]).export('housing_assembly.stl')

    # ---- 검증 리포트 ----
    print('=== v8.4 | Y-mirror | 벽4mm(+Y 6mm) | 코너 M3관통+너트 | 프레임 Ø5.5관통 | USB 개구부 + X관통 타이앵커 ===')
    print('MIRROR_Y     : %s  (홀 Y: 57.124→%.2f, 8.624→%.2f)'%(MIRROR_Y, mY(57.124), mY(8.624)))
    # 코너 기둥 ↔ 보드 최소 간섭거리(음수면 충돌)
    def _clr(px,py):
        cxb=min(max(px,BX0),BX1); cyb=min(max(py,BY0),BY1)
        return np.hypot(px-cxb, py-cyb) - LIDBOSS_R
    mind=min(_clr(px,py) for px,py in LID_BOSS_XY)
    print('코너기둥 Ø%.1f, 구멍 Ø%.1f, 구멍주변살 %.2fmm | 보드 최소틈 %.2fmm %s'%(
          LIDBOSS_R*2, LIDBOSS_HOLE*2, LIDBOSS_R-LIDBOSS_HOLE, mind,
          'OK' if mind>0.4 else '⚠충돌위험'))
    print('외형        : %.1f(X) x %.1f(Y) x %.1f(Z) mm'%(OX1-OX0, OY1-OY0, z_top))
    print('보드        : %.1f x %.1f x %.3f (STEP 실측)'%(board_L, board_W, board_t))
    print('캐비티 여유  : -X %.1f(J3회피) +X %.1f(J5회피) ±Y %.1f'%(clr_L,clr_R,clr_Y))
    print('사용 홀      : %s  관통 Ø%.1f'%(HOLES, hole_thru))
    print('보드면 아래  : 개방(보스 %d개 Ø%.1f + 코너거싯만)'%(len(HOLES),boss_d))
    # FOV: 안테나 최근접 보스까지 수평거리 vs 보스높이
    axc=(ANT['x0']+ANT['x1'])/2; ayc=(ANT['y0']+ANT['y1'])/2
    dmin=min(np.hypot(hx-max(ANT['x0'],min(hx,ANT['x1'])),
                      hy-max(ANT['y0'],min(hy,ANT['y1']))) for hx,hy in HOLES)
    print('안테나 구역  : X%.1f..%.1f Y%.1f..%.1f 중심(%.1f,%.1f)'%(
          ANT['x0'],ANT['x1'],ANT['y0'],ANT['y1'],axc,ayc))
    print('  → 보스가 안테나 bbox 침범: %s'%(
          '있음(H2 코너 근접)' if dmin<0.1 else '없음(최근접 %.1fmm)'%dmin))
    print('USB(5핀)     : 크래들 제거 → 개방(격자막힘 해소). 케이블은 하부 개방부로 인출. 커넥터 keep-out 유지')
    _jy = (J5["y0"]+J5["y1"])/2
    if USB_RELIEF:
        _post_y = OY1 - LIDBOSS_R                            # 코너 볼트기둥 중심
        print('USB 개구부   : Y %.2f..%.2f (%.1fmm) / Z %.1f..%.1f + 45°게이블(꼭지 z%.2f) / X 벽 관통'
              %(_jy-USB_REL_W/2, _jy+USB_REL_W/2, USB_REL_W, z_ant, USB_REL_Z,
                USB_REL_Z+USB_REL_W/2))
        print('  오버몰드    : 규격상한 10.6x8.5 → 필요 Y반폭 5.30 / Z상단 7.89. 개구 반폭 %.2f, 상단 %.1f  %s'
              %(USB_REL_W/2, USB_REL_Z, 'OK' if USB_REL_W/2>=5.3 and USB_REL_Z>=7.89 else '⚠부족'))
        print('  코너기둥    : 중심 y=%.3f, 접선 y=%.3f → 개구 +Y끝(%.3f)과 여유 %.2fmm %s'
              %(_post_y, _post_y-LIDBOSS_R, _jy+USB_REL_W/2,
                (_post_y-LIDBOSS_R)-(_jy+USB_REL_W/2),
                'OK' if (_post_y-LIDBOSS_R)-(_jy+USB_REL_W/2)>0.5 else '⚠간섭'))
    _ovw, _ovh = 10.8, 8.5                                   # 실제품 폭 / 규격상한 높이
    if TIE_ANCHOR:
        _p1=_jy-TIE_PAD_OFF; _p0=_p1-TIE_PIL_W
        _s=[_p1+d for d in TIE_SLOT_YS]
        print('타이앵커     : -Y 패드 y %.2f..%.2f, z 0..%.1f (x %.1f..%.1f)'%(_p0,_p1,z_ant,OX1-wall,OX1))
        print('  슬롯       : ★X관통★ %.1f(Y) x %.1f(Z), z %.1f..%.1f, y중심 %.2f / %.2f'
              %(TIE_SLOT_Y, z_ant-TIE_SLOT_Z0, TIE_SLOT_Z0, z_ant, _s[0], _s[1]))
        print('               바깥(x>%.1f 공중) ↔ 안쪽(x<%.1f 보드밑 개방공간) 양쪽 개방 → 조립 후에도 결속 가능'
              %(OX1, OX1-wall))
        print('  주변살     : 바닥 %.1f / 패드-Y끝 %.2f / 슬롯사이 %.2f / 패드+Y끝 %.2f mm'
              %(TIE_SLOT_Z0, _s[0]-TIE_SLOT_Y/2-_p0, (_s[1]-TIE_SLOT_Y/2)-(_s[0]+TIE_SLOT_Y/2), _p1-(_s[1]+TIE_SLOT_Y/2)))
        print('  플러그봉투 : -Y끝 y=%.3f 와 이격 %.2fmm %s'
              %(_jy-_ovw/2, (_jy-_ovw/2)-_p1, 'OK' if (_jy-_ovw/2)-_p1>0.3 else '⚠간섭'))
    print('               (주 방어는 3030 프로파일 결속. 위는 하우징측 보험)')
    print('프레임 고정  : 뚜껑에 Ø5.5 X축 관통홀(모델 반영). 업체는 3030(알루미늄)만 같은 축으로 관통드릴')
    print('볼트 소요    : 보드체결 M3x12 x4(아래→위 뒷면너트) + 뚜껑↔트레이 M3x25~30 관통+너트 x4'
          ' (그립 %.1fmm) + 프레임 관통볼트 x1(업체규격)'%(3.0 + (z_top-z_ant)))
    print('watertight  : tray=%s  lid=%s'%(tray.is_watertight, lid.is_watertight))
