"""user_ui.py — Radar-Guard 현장 작업자용(User) 화면 [노트북 · 키오스크]

  실행: [내 PC PowerShell]  ⚠ cd 불필요 (CLAUDE.md §9)
      python 01_현행코드\\user_ui.py                     # 데모 모드 (젯슨 불필요)
      python 01_현행코드\\user_ui.py --live 192.168.0.50 # 젯슨 실데이터
      python 01_현행코드\\user_ui.py --live 127.0.0.1    # sim_jetson.py 와 루프백
      python 01_현행코드\\user_ui.py --live 192.168.0.50 --fullscreen --operator 홍길동
      python 01_현행코드\\user_ui.py --preview --fullscreen   # 디자인 미리보기

  실행: [VS Code]  Ctrl+Shift+D → 구성 선택 → F5
      현장 화면 · 데모 / 젯슨 실데이터 / 전체화면 시연 / 루프백(127.0.0.1)
      컴파운드 '루프백 검증' 은 sim_jetson.py 와 이 화면을 함께 띄운다.
      구성은 .vscode/launch.json 에 있다 (.gitignore 대상 — 개인 설정이다).

  실행: [젯슨 부스 모니터]
      ./run_user_ui.sh          # = user_ui.py --live 127.0.0.1 --fullscreen
      배포·의존 패키지는 run_user_ui_jetson.sh 머리말 참조.

  필요 패키지: console_ui.py 와 동일 (pyqt5 · pyqtgraph · numpy)
    ⚠ 이 화면 자체는 3D 를 쓰지 않으므로 pyopengl 이 없어도 무방하다.

═══ 이 파일이 하는 일 / 하지 않는 일 ═══
  한다   : 현장 작업자(HMI·안전 키오스크)용 단일 화면.
           평면도로 '어디' 를, 우측 패널로 '지금 무엇을' 을 말한다.
  안 한다: 판정, 차단 실행, 레이더 수신 구현, SOP 검색·LLM 호출.
           ↑ 수신은 radar_core.RadarLink, 즉시조치는 radar_core.INSTANT_ACTION,
             재투입 확인은 radar_core.RestorePopup 을 '그대로 import' 해 쓴다.
             복붙이 아니라 같은 코드 객체다 — 절차가 갈라질 수 없다.

  ⚠ jetson_sender.py 는 이 화면 작업으로 단 한 글자도 바뀌지 않는다.
    이 파일은 젯슨이 보낸 패킷을 읽기만 하고, 젯슨으로 나가는 것은 기존
    제어 명령(CMD_RESOLVE / CMD_RESTORE) 두 개뿐이다. 둘 다 console_ui.py 가
    이미 쓰던 것과 동일하다 — 프로토콜에 새로 추가한 것이 없다.

═══ console_ui.py(관제) 와 무엇이 다른가 ═══
  관제 화면은 '알고리즘이 맞게 도는가' 를 묻는 사람의 화면이다 —
  3D 점군 · 계측 타일 · 판단 근거 게이트 표 · 이벤트 로그 · 설정.
  이 화면은 '어디서 났고 지금 뭘 해야 하나' 만 묻는 사람의 화면이다.
  그래서 여기엔 점군·수치·모델명·임계값·로그가 하나도 없다. 삭제가 아니라
  '그쪽 화면에 이미 있다'. 두 화면은 같은 젯슨 패킷을 동시에 볼 수 있다
  (UDP 는 젯슨이 HELLO 를 보낸 클라이언트 전부에게 뿌린다).

  ⚠ 단, 같은 PC 에서 console_ui.py 와 이 파일을 동시에 켜면 둘 다 UDP
    DATA_PORT(5005) 를 바인드하려 해 뒤에 뜬 쪽이 수신을 못 한다.
    같이 보려면 서로 다른 PC 에서 띄운다.

═══ 경보 상태기계 (ISA-18.2) — console_ui.py 와 완전히 동일 ═══
  NORMAL ──경보──> UNACK(점멸·소리) ──상황 확인 완료──> ACK(점멸·소리 정지)
         <──상황 종료(사람이 누름 · CMD_RESOLVE)──
  ⚠ 자동 해제는 없다.  ⚠ '확인' 은 소리를 끄는 것이지 경보를 지우는 것이 아니다.
  ⚠ 화면 버튼이 4개뿐이라 '확인' 과 '종료' 를 한 버튼의 2단계로 둔다.
    (버튼을 5개로 늘리면 시안의 4분할이 깨지고, 경보 중 오조작이 늘어난다)

═══ 색에 대하여 ═══
  이 화면은 우측 지시 패널만 '흰 카드' 다. 나머지는 radar_common 의 다크 팔레트다.
  ⚠ 흰 배경 위에서는 GREEN(#22C55E) · AMBER(#F59E0B) 가 거의 안 읽힌다(대비 부족).
    그래서 '흰 카드 안에서만 쓰는 진한 대체색' 을 아래 K_* 로 따로 둔다.
    radar_common 은 젯슨과 공유하는 파일이라 화면 전용 색을 거기 넣지 않는다.
"""
import os
import sys
import math
import time
import argparse

from PyQt5 import QtCore, QtGui, QtWidgets

# ── 로직 계층. 복사하지 않고 import 한다 → 같은 코드 객체 ─────────────────
import facility as fac
import radar_core as core
from radar_core import (
    RadarLink, INSTANT_ACTION, RestorePopup,
    ST_NORMAL, ST_UNACK, ST_ACK,
)
from radar_common import (
    LINK_TIMEOUT, CMD_RESOLVE, CMD_RESTORE,
    PH_LIVE, PHASE_KO, parse_pre_alert,
    EVENT_KO, ZONE_KO, ZONE_IDS, RADAR_ZONE, SEV_KO, AUTO_TRIP_EVENTS,
    BREAKER_SCOPE, sev_color, event_sev, zone_equipped,
    BG, PANEL, PANEL_HI, EDGE, TXT, DIM, FAINT,
    CYAN, GREEN, AMBER, RED, RADIUS, RADIUS_SM,
)

APP_VERSION = 'User v1.0'

# ══════════════════════════════════════════════════════════════════════
# 0. 타이포그래피 — console_ui.py 와 같은 규칙(있으면 쓰고 없으면 기본 고딕)
# ══════════════════════════════════════════════════════════════════════
#  ⚠ 윈도우(관제 노트북)와 리눅스(젯슨 부스 화면) 양쪽에서 뜬다. JetPack 에는
#    한글 폰트가 기본 탑재돼 있지 않아 후보를 같이 둔다 — 없으면 아래
#    resolve_font() 가 경고를 찍는다(조용히 □ 로 뜨는 것이 최악이다).
FONT_CANDIDATES = ['Pretendard', 'Pretendard Variable',
                   'Noto Sans KR', 'Noto Sans CJK KR',
                   'NanumGothic', 'NanumBarunGothic',
                   'Malgun Gothic', 'Gulim']
FONT = 'Malgun Gothic'


_EXIT_PIXMAP = None


def exit_pixmap():
    """비상구 아이콘 원본 이미지 — 사용자 제공 참조 사진을 그대로 쓴다(재작도 아님).

    ⚠ [8/25] 이전엔 QPainter로 손그림했으나 참조 사진과 계속 미묘하게 달라 사용자가
      원본 그대로 넣어 달라고 함 — assets/exit_icon.png(원본 배경을 투명 처리한 것)를
      QPixmap으로 로드해 그대로 그린다. 매 paintEvent마다 디스크에서 다시 읽지 않도록
      모듈 전역에 1회만 캐시한다.
    """
    global _EXIT_PIXMAP
    if _EXIT_PIXMAP is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'assets', 'exit_icon.png')
        _EXIT_PIXMAP = QtGui.QPixmap(path)
        if _EXIT_PIXMAP.isNull():
            print(f'⚠ 비상구 아이콘 로드 실패: {path}', file=sys.stderr)
    return _EXIT_PIXMAP


def resolve_font():
    """설치된 폰트 중 우선순위가 가장 높은 것. QApplication 생성 후 호출."""
    global FONT
    fams = set(QtGui.QFontDatabase().families())
    if not fams:
        print(f'⚠ QFontDatabase 가 폰트를 하나도 찾지 못함 — {FONT}(초기값)로 진행',
              file=sys.stderr)
    for name in FONT_CANDIDATES:
        if name in fams:
            FONT = name
            break
    core.FONT = FONT          # import 해서 쓰는 팝업들도 같은 폰트를 쓰게 한다
    global IC_BELL, IC_LOCK, IC_POWER
    IC_BELL = glyph('🔔', '♪')
    IC_LOCK = glyph('🔒', '⚙')
    IC_POWER = glyph('⏻', '◉')
    # ⚠ [젯슨] 한글 폰트가 없으면 화면의 모든 글자가 □ 로 뜬다. 그림은
    #   멀쩡해 보여서 '폰트 문제' 라는 걸 알아채기까지 오래 걸린다.
    #   → 조용히 넘어가지 않고 해결 명령까지 찍는다 (CLAUDE.md §9).
    try:
        if not QtGui.QFontMetrics(QtGui.QFont(FONT, 12)).inFont('가'):
            print(f'⚠ 폰트 {FONT} 에 한글 글리프가 없습니다 — 글자가 □ 로 보입니다.\n'
                  f'   [젯슨] sudo apt install -y fonts-nanum fonts-noto-cjk '
                  f'&& fc-cache -f', file=sys.stderr)
    except Exception:
        pass
    return FONT


def glyph(pref, fallback):
    """폰트에 없는 글자는 네모(tofu)로 그려진다 — 있으면 쓰고 없으면 대체한다.

    ⚠ 데모 PC 마다 이모지 폰트가 다르다. 자물쇠·전원 기호가 □ 로 뜨는 것은
      키오스크 화면에서 그대로 '고장난 화면' 으로 읽힌다. QApplication 생성
      후에 한 번만 판정한다.
    """
    try:
        fm = QtGui.QFontMetrics(QtGui.QFont(FONT, 20))
        if hasattr(fm, 'inFontUcs4'):
            return pref if fm.inFontUcs4(ord(pref)) else fallback
        return pref if fm.inFont(pref) else fallback
    except Exception:
        return fallback


# 초기값은 어느 폰트에나 있는 쪽. resolve_font() 가 이모지를 쓸 수 있으면 올린다.
IC_BELL, IC_LOCK, IC_POWER, IC_OK = '♪', '⚙', '◉', '✓'


def apply_dark_palette(app):
    """앱 전역 다크 팔레트. (console_ui.py 의 같은 함수와 목적·값이 같다)

    ⚠ 스타일시트를 안 건 위젯(QInputDialog·QMessageBox·QMenu 팝업 등)이 밝은
      기본값으로 뜨는 것을 막는다. 스타일시트는 '보이는 것' 만 고치지만
      팔레트는 '아직 안 만든 것' 까지 고친다.
    """
    C = QtGui.QColor
    p = QtGui.QPalette()
    p.setColor(QtGui.QPalette.Window, C(BG))
    p.setColor(QtGui.QPalette.WindowText, C(TXT))
    p.setColor(QtGui.QPalette.Base, C(PANEL))
    p.setColor(QtGui.QPalette.AlternateBase, C(PANEL_HI))
    p.setColor(QtGui.QPalette.Text, C(TXT))
    p.setColor(QtGui.QPalette.Button, C(PANEL))
    p.setColor(QtGui.QPalette.ButtonText, C(TXT))
    p.setColor(QtGui.QPalette.BrightText, C(RED))
    p.setColor(QtGui.QPalette.ToolTipBase, C(PANEL_HI))
    p.setColor(QtGui.QPalette.ToolTipText, C(TXT))
    p.setColor(QtGui.QPalette.Link, C(CYAN))
    p.setColor(QtGui.QPalette.Highlight, C(CYAN))
    p.setColor(QtGui.QPalette.HighlightedText, C('#062028'))
    try:
        p.setColor(QtGui.QPalette.PlaceholderText, C(FAINT))
    except AttributeError:
        pass                      # Qt 5.12 이하
    for role in (QtGui.QPalette.Text, QtGui.QPalette.ButtonText,
                 QtGui.QPalette.WindowText):
        p.setColor(QtGui.QPalette.Disabled, role, C(FAINT))
    app.setPalette(p)


# 8px 그리드 (console_ui.py 와 동일)
SP1, SP2, SP3, SP4, SP5, SP6 = 4, 8, 12, 16, 24, 32

# 키오스크는 1~3 m 떨어져서 본다. 관제(11pt 본문)보다 한 단계씩 크다.
U_TITLE = 22      # 상단 상태 제목
U_BRAND = 15
U_H1 = 17         # 패널 제목
U_H2 = 14         # 지시 항목 본문
U_BODY = 12
U_LABEL = 11
U_CAP = 9

# ── 흰 카드 전용 색 (radar_common 에 넣지 않는 이유는 파일 상단 참조) ──
K_CARD = '#FFFFFF'
K_INK = '#111827'         # 흰 배경 본문
K_INK2 = '#4B5563'        # 흰 배경 보조
K_LINE = '#E5E7EB'        # 흰 배경 구분선
K_RED = '#DC2626'         # 흰 배경 위 빨강 (RED #EF4444 는 흰 바탕에서 흐리다)
K_GREEN = '#15803D'       # 흰 배경 위 초록
K_AMBER = '#B45309'       # 흰 배경 위 주황
K_WARN_BG = '#FEF2F2'     # 금지 안내 박스 배경
K_WARN_LINE = '#FECACA'
K_OK_BG = '#F0FDF4'
K_OK_LINE = '#BBF7D0'

# ── 평면도 전용 색 (시안의 CAD 도면 느낌) ──
#  ⚠ 관제 화면(console_ui) 의 평면도는 radar_common 팔레트를 그대로 쓴다.
#    이 화면은 1~3 m 떨어져서 보는 키오스크라 EDGE(#263247) 벽선은 그 거리에서
#    사실상 안 보인다. 도면 선만 밝기를 올린다 — 색이 아니라 밝기라서 '색 =
#    위험 등급' 규칙(CLAUDE.md §4)과 충돌하지 않는다.
PLAN_FLOOR = '#0A0E16'      # 도면 바닥 (거의 검정)
PLAN_WALL = '#C8D3E4'       # 벽 — 도면의 골격
PLAN_EQUIP = '#6B7A93'      # 설비 윤곽 — 벽보다 한 단계 낮게
PLAN_CARD = '#2A313C'       # 구역 이름표 카드
PLAN_CARD_EDGE = '#414B5C'
EVAC_GREEN = '#2ECC71'      # 대피 경로 — 도면 위에서 GREEN(#22C55E)보다 잘 읽힌다

# ── 하단 액션 버튼 색 (시안 배색) ──
#  ⚠ 빨강을 '전원 재투입' 에 쓰는 것은 CLAUDE.md §4 의 예외가 아니다.
#    그 규칙은 '위험을 뜻할 때만 빨강' 이고, 활선 재투입은 이 화면에서
#    가장 위험한 조작이다. radar_core.btn(accent=True) 도 같은 용도로 쓴다.
B_GRAY, B_GRAY_H = '#1F2937', '#374151'
B_BLUE, B_BLUE_H = '#1D4ED8', '#2563EB'
B_GOLD, B_GOLD_H = '#EAB308', '#FACC15'
B_RED, B_RED_H = '#DC2626', '#EF4444'

WEEKDAY_KO = ('월', '화', '수', '목', '금', '토', '일')

# ── 즉시조치가 등록되지 않은 이벤트의 대체 경로 ────────────────────────
#  ⚠ radar_core.INSTANT_ACTION 이 즉시조치의 정본이다. 여기에 조치 문장을
#    새로 쓰지 않는다 — 안전 문서를 화면 파일이 지어내면 정본이 둘이 된다.
#    의미가 같은 이벤트만 '같은 절차를 본다' 고 연결하고, 그것도 없으면
#    조치를 지어내는 대신 '등록되지 않음' 을 화면에 그대로 밝힌다.
#    (현재 미등록: overcurrent · voltage_drop — README/OUTBOX 로 보고할 것)
SOP_ALIAS = {
    'fall_suspected': 'fall_detected',
}

# ══ 관리자 승인 (전원 재투입 전용) ══════════════════════════════════════
#  ⚠ 이건 '보안' 이 아니라 '오조작 방지' 다. 계정이 저장소에 평문으로 들어
#    있으므로 실제 현장에 배치하기 전에 반드시 교체해야 한다. 코드를 고치지
#    않고 바꿀 수 있게 환경변수를 먼저 본다:
#       PowerShell:  $env:RADAR_ADMIN_ID='...' ; $env:RADAR_ADMIN_PW='...'
#  ⚠ 이 승인은 노트북 화면 안에서만 유효하다. 승인 없이도 젯슨은 자기 판단으로
#    차단을 유지한다 — 즉 이 관문이 뚫려도 안전 로직이 무너지지는 않는다.
ADMIN_ID = os.environ.get('RADAR_ADMIN_ID', 'project')
ADMIN_PW = os.environ.get('RADAR_ADMIN_PW', '1111')
AUTH_MAX_TRY = 5          # 연속 실패 허용 횟수
AUTH_LOCK_SEC = 30        # 초과 시 재투입 버튼을 잠그는 시간 [초]


# ══ 디자인 미리보기 ════════════════════════════════════════════════════
#  ⚠ 아래 값은 젯슨이 보낸 것이 아니다. 화면 배치·색·버튼 상태를 눈으로
#    확인하기 위한 합성 패킷이며, --preview 로 띄웠을 때만 쓰인다.
#    그 사실이 화면에서 숨겨지지 않도록 평면도 하단에 '실데이터 아님' 을
#    적고 창 제목에도 붙인다 (CLAUDE.md §4 — 없는 수치를 그럴듯하게 채우지 않는다).
#  ⚠ 시나리오는 감전 확정이다. 시안(발표자료)의 화면과 같은 상태가 나온다:
#    Zone A 위험 · 전원 차단 완료(실측) · 즉시 수행 지시 4단계.
_PREVIEW_SEQ = [0]
PREVIEW_EVENT = 'electric_shock_risk_confirmed'


def preview_packet(active=True):
    """디자인 미리보기용 합성 패킷 한 장."""
    _PREVIEW_SEQ[0] += 1
    return {
        'schema_version': 2, 'seq': _PREVIEW_SEQ[0], 'ts': time.time(),
        'phase': PH_LIVE, 'warmup_count': 150, 'threshold': 0.025,
        'data_ok': True, 'data_age': 0.1, 'scan_left': None, 'pre_alert': '',
        'centroid': {'cx': 0.18, 'cy': 1.52, 'cz': -0.24},
        'height': 0.78, 'n_pts': 8, 'dop_std': 0.42,
        'track_state': 'tracking',
        'occupied': True,
        'zone_state': {z: ('ALERT' if (z == RADAR_ZONE and active) else 'NORMAL')
                       for z in ZONE_IDS},
        'power': {'curr': 0.152, 'volt': 7.81, 'src': 'ina226'},
        'breaker': {'state': {z: ('TRIPPED' if z == RADAR_ZONE else 'ON')
                              for z in ZONE_IDS},
                    'reason': {RADAR_ZONE: PREVIEW_EVENT},
                    'src': 'modbus', 'connected': True},
        'ev': {'active': active, 'type': PREVIEW_EVENT,
               'types': [PREVIEW_EVENT], 'items': {}, 'rev': 0,
               'sev': 'critical', 'conf': 0.93, 'zone': RADAR_ZONE,
               'id': _PREVIEW_SEQ[0], 'ts': time.time(),
               'evidence': None, 'gates': None, 'rejected': []},
        'cfg': {'N_WARMUP': 150, 'SCAN_SEC': 12.0},
    }


# ══════════════════════════════════════════════════════════════════════
# 1. UI 키트
# ══════════════════════════════════════════════════════════════════════
def kf(size=U_BODY, bold=False):
    q = QtGui.QFont(FONT, size)
    q.setBold(bold)
    return q


def klb(text='', size=U_BODY, color=TXT, bold=False, wrap=False, align=None,
        spacing=0):
    w = QtWidgets.QLabel(text)
    w.setFont(kf(size, bold))
    css = f'color:{color};border:none;background:transparent;'
    if spacing:
        css += f'letter-spacing:{spacing}px;'
    w.setStyleSheet(css)
    w.setWordWrap(wrap)
    if align is not None:
        w.setAlignment(align)
    return w


def kcard(bg=PANEL, border=None, radius=RADIUS):
    fr = QtWidgets.QFrame()
    b = f'1px solid {border}' if border else 'none'
    fr.setStyleSheet(f'QFrame{{background:{bg};border:{b};'
                     f'border-radius:{radius}px;}}')
    return fr


def mix(a, b, t):
    """색 a 를 b 쪽으로 t(0~1) 만큼 섞는다. 비활성 버튼 색을 만드는 데 쓴다."""
    ca, cb = QtGui.QColor(a), QtGui.QColor(b)
    return QtGui.QColor(int(ca.red() * (1 - t) + cb.red() * t),
                        int(ca.green() * (1 - t) + cb.green() * t),
                        int(ca.blue() * (1 - t) + cb.blue() * t))


def kvbox(w, m=SP4, s=SP3):
    v = QtWidgets.QVBoxLayout(w)
    v.setContentsMargins(m, m, m, m)
    v.setSpacing(s)
    return v


def khbox(w=None, m=0, s=SP3):
    h = QtWidgets.QHBoxLayout(w) if w is not None else QtWidgets.QHBoxLayout()
    h.setContentsMargins(m, m, m, m)
    h.setSpacing(s)
    return h


def clear_layout(lay):
    """레이아웃 안의 위젯을 전부 지운다 (지시 목록을 매 경보마다 다시 만든다)."""
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
        elif it.layout() is not None:
            clear_layout(it.layout())


class BigButton(QtWidgets.QPushButton):
    """하단 액션 버튼 — 아이콘 + 제목 + 부연 한 줄을 한 버튼에 그린다.

    ⚠ QPushButton 은 서식 있는 텍스트를 못 받는다. 제목과 부연을 QLabel 로
      겹쳐 얹으면 눌림·비활성 상태에서 라벨 색이 따로 놀아 '비활성인데 글씨는
      선명한' 버튼이 된다(관제 v1 에서 겪었다). → 직접 그린다.
    """

    def __init__(self, icon, title, sub, base, hover, fg='#FFFFFF'):
        super().__init__()
        self.icon_ch, self.title, self.sub = icon, title, sub
        self.base, self.hover, self.fg = base, hover, fg
        self.setMinimumHeight(88)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        # 스타일시트를 비워 둔다 — 전부 paintEvent 가 그린다
        self.setStyleSheet('QPushButton{border:none;background:transparent;}')

    def set_action(self, icon=None, title=None, sub=None):
        # ⚠ 0.5초마다 불린다. 값이 그대로인데 update() 를 부르면 버튼 4개가
        #   초당 2번씩 통째로 다시 그려진다 — 바뀔 때만 다시 그린다.
        before = (self.icon_ch, self.title, self.sub)
        if icon is not None:
            self.icon_ch = icon
        if title is not None:
            self.title = title
        if sub is not None:
            self.sub = sub
        if (self.icon_ch, self.title, self.sub) != before:
            self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        off = not self.isEnabled()
        if off:
            # ⚠ [8/25] 예전엔 비활성 버튼을 통짜 회색(PANEL_LO)으로 칠했다.
            #   경보가 없는 평상시에는 4개 중 2개가 그 회색이 되어 화면이
            #   '고장난 것' 처럼 보였다(실제로 그렇게 보고받았다).
            #   → 버튼의 제 색을 패널 쪽으로 눌러 정체성은 남기고, 테두리로
            #     '있긴 한데 지금은 못 누른다' 를 말한다. 부제에 이유를 쓴다.
            bg = mix(self.base, PANEL, 0.70)
            fg = mix(self.fg, PANEL, 0.50)
        elif self.underMouse() and not self.isDown():
            bg, fg = QtGui.QColor(self.hover), QtGui.QColor(self.fg)
        else:
            bg, fg = QtGui.QColor(self.base), QtGui.QColor(self.fg)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, RADIUS, RADIUS)
        if off:
            p.setPen(QtGui.QPen(mix(self.base, PANEL, 0.35), 1.4))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawRoundedRect(r, RADIUS, RADIUS)
        if self.isDown() and self.isEnabled():
            # 눌림 표시 — 색을 바꾸는 대신 안쪽 테두리를 준다(색=등급 원칙 유지)
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 110), 2))
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(3, 3, -3, -3), RADIUS - 2, RADIUS - 2)

        # 아이콘 + (제목/부연) 을 하나의 덩어리로 묶어 가운데 정렬한다
        p.setFont(kf(20, True))
        icon_w = p.fontMetrics().width(self.icon_ch)
        p.setFont(kf(U_H1, True))
        fm_t = p.fontMetrics()
        tw = fm_t.width(self.title)
        p.setFont(kf(U_CAP))
        fm_s = p.fontMetrics()
        sw = fm_s.width(self.sub) if self.sub else 0
        text_w = max(tw, sw)
        gap = SP3 if self.icon_ch else 0
        total = icon_w + gap + text_w
        x0 = (self.width() - total) / 2
        cy = self.height() / 2

        if self.icon_ch:
            p.setFont(kf(20, True))
            p.setPen(fg)
            p.drawText(QtCore.QRectF(x0, cy - 16, icon_w, 32),
                       QtCore.Qt.AlignCenter, self.icon_ch)
        tx = x0 + icon_w + gap
        p.setFont(kf(U_H1, True))
        p.setPen(fg)
        if self.sub:
            p.drawText(QtCore.QRectF(tx, cy - fm_t.height() - 1, text_w,
                                     fm_t.height()),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self.title)
            p.setFont(kf(U_CAP))
            c = QtGui.QColor(fg)
            c.setAlpha(200 if not off else 235)
            p.setPen(c)
            p.drawText(QtCore.QRectF(tx, cy + 2, text_w, fm_s.height() + 2),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self.sub)
        else:
            p.drawText(QtCore.QRectF(tx, cy - fm_t.height() / 2, text_w,
                                     fm_t.height()),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self.title)
        p.end()


# ══════════════════════════════════════════════════════════════════════
# 2. 공장 평면도 — 이 화면의 '어디'
# ══════════════════════════════════════════════════════════════════════
class UserPlan(QtWidgets.QWidget):
    """facility.py 의 좌표만 보고 그린다. 이 클래스에 치수가 하나도 없다.

    ⚠ 그래서 "실사용 시 시설 도면으로 교체한다" 가 말이 아니라 사실이다 —
      facility.py 만 바꾸면 이 화면이 그 현장이 된다.

    ═══ 색이 말하는 것 (관제 화면과 같은 규칙) ═══
      초록 감시 중        · 레이더가 살아 있고 이상 없음
      주황 사전경보       · 정지형 카운트다운 중 (경보 아님)
      빨강 경보(점멸)     · 확정 사고 — 발광 + 파선 테두리 + ⚠ 표식
      회색 파선 장비 미설치 · 레이더가 없는 구역. 감시한다고 말하지 않는다.
      회색 실선 연결 대기   · 레이더는 있는데 링크가 없음
    """

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(400)
        self.setMinimumWidth(520)
        self.state = {z: {'sev': None, 'live': False, 'pre': None, 'et': None}
                      for z in fac.ZONES}
        self.worker = None          # (zone, plan_x, plan_y)
        self.blink = False
        self.preview = False        # True 면 하단 고지에 '실데이터 아님' 을 덧붙인다

    # ── 상태 갱신 ────────────────────────────────────────────────────
    def set_zone(self, zone, live=False, sev=None, pre=None, et=None):
        if zone in self.state:
            self.state[zone] = {'live': live, 'sev': sev, 'pre': pre, 'et': et}

    def set_worker(self, zone, cx, cz):
        p = fac.to_plan(zone, cx, cz)
        self.worker = None if p is None else (zone, p[0], p[1])

    def set_blink(self, on):
        if on != self.blink:
            self.blink = on
            self.update()

    # ── 좌표 변환 ────────────────────────────────────────────────────
    def _fit(self):
        W, H = fac.SIZE
        pad = SP3
        sx = (self.width() - pad * 2) / W
        sy = (self.height() - pad * 2 - 20) / H     # 하단 고지 자리
        s = max(min(sx, sy), 1.0)
        ox = (self.width() - W * s) / 2
        oy = (self.height() - 20 - H * s) / 2
        return s, ox, oy

    def _pt(self, x, y, f):
        s, ox, oy = f
        return QtCore.QPointF(ox + x * s, oy + y * s)

    def _rect(self, r, f):
        s, ox, oy = f
        return QtCore.QRectF(ox + r[0] * s, oy + r[1] * s, r[2] * s, r[3] * s)

    # ── 렌더 ─────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        f = self._fit()

        # 바닥
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QBrush(QtGui.QColor(PLAN_FLOOR)))
        p.drawRect(self._rect((0, 0) + tuple(fac.SIZE), f))

        self._draw_equipment(p, f)

        # ⚠ coverage 를 zones 보다 먼저 그린다. 둘 다 위험 시 같은 빨강 파선을
        #   쓰는데 순서가 반대면 경보 중 파선 사각형 두 개가 겹쳐 보여
        #   "테두리가 이중으로 어긋나 보인다"는 오독을 만든다. zones 의 굵은
        #   발광 테두리가 위에 덮이면 coverage 는 평상시엔 그대로 보이고
        #   경보 중엔 자연히 뒤로 물러난다 — 정보를 지우지 않고 위계만 정리.
        self._draw_coverage(p, f)
        self._draw_zones(p, f)

        # 벽 — 도면의 골격이므로 가장 위에
        p.setPen(QtGui.QPen(QtGui.QColor(PLAN_WALL), 1.8))
        for x1, y1, x2, y2 in fac.WALLS:
            p.drawLine(self._pt(x1, y1, f), self._pt(x2, y2, f))

        self._draw_evac(p, f)
        self._draw_labels(p, f)
        self._draw_worker(p, f)
        self._draw_legend(p)

        # 데모 고지 — 이 도면이 무엇인지 숨기지 않는다
        p.setPen(QtGui.QColor(FAINT))
        p.setFont(kf(U_CAP))
        note = fac.DEMO_NOTE + ('   ·   디자인 미리보기 — 실데이터 아님'
                                if self.preview else '')
        p.drawText(QtCore.QRectF(0, self.height() - 18, self.width() - SP3, 16),
                   QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, note)
        p.end()

    @staticmethod
    def _volume_brush(rect, color, top_alpha=72, bottom_alpha=26):
        """세로 그라데이션 — 평판 CAD 느낌 대신 은은한 입체감을 준다."""
        g = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        c1 = QtGui.QColor(color)
        c1.setAlpha(top_alpha)
        c2 = QtGui.QColor(color)
        c2.setAlpha(bottom_alpha)
        g.setColorAt(0.0, c1)
        g.setColorAt(1.0, c2)
        return QtGui.QBrush(g)

    def _draw_equipment(self, p, f):
        """설비 윤곽 — 도면 밀도·산업현장 느낌용. 판정과 무관하다.

        ⚠ [8/25] "CAD 도면처럼 평판이다" · "가구류가 밋밋하다" · "패널이 부실하다"
          는 지적으로 3차 재작도했다. fac.EQUIPMENT 각 항목의 첫 값이 종류다.
            'rect'        얇은 윤곽만 — 부품함처럼 정말 작고 단순한 것만
            'desk'        서랍 칸선 + 의자 원 — 사무 책상
            'monitor'     베젤 + 화면(어둡게) + 스탠드 — 모니터
            'rack'        선반 칸선 + 적재 틱 — 계전기 랙·자재 선반
            'machine'     주축대(그라데이션) + 스핀들(구멍) — 공작기계·조립대
            'transformer' 탱크(그라데이션) + 냉각핀 + 부싱(원) — 변압기
            'panel'       명판 + 양개문 분할선 + 계기 2개 + 스위치 — 배전반류
            'conveyor'    양쪽 레일 + 롤러(짧은 가로선) — 컨베이어
            'tank'        원(그라데이션) + 리브(동심원 2단) + 노즐 — 저장탱크·드럼
            'pipe'        가는 선 — 배관·덕트·배선 트렌치(연결선. 설비 아님)
          모든 몸체는 단색 채움 대신 _volume_brush() 세로 그라데이션을 쓰고,
          윤곽선(1.2~1.6)과 디테일선(0.7~0.9)의 굵기를 의도적으로 벌렸다 —
          굵기가 전부 같으면 무엇이 외곽이고 무엇이 디테일인지 안 읽힌다.
        """
        equip_pen = QtGui.QColor(PLAN_EQUIP)
        for item in fac.EQUIPMENT:
            kind = item[0]
            if kind == 'rect':
                _, x, y, w, h = item
                p.setPen(QtGui.QPen(equip_pen, 1.0))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRect(self._rect((x, y, w, h), f))
            elif kind == 'desk':
                _, x, y, w, h = item
                rect = self._rect((x, y, w, h), f)
                p.setPen(QtGui.QPen(equip_pen, 1.2))
                p.setBrush(self._volume_brush(rect, equip_pen, 58, 18))
                p.drawRoundedRect(rect, 1.5, 1.5)
                horiz = rect.width() >= rect.height()
                p.setPen(QtGui.QPen(equip_pen, 0.8))
                if horiz:
                    dw = rect.width() * 0.24
                    drawer = QtCore.QRectF(rect.right() - dw, rect.top(),
                                           dw, rect.height())
                    p.drawLine(QtCore.QPointF(drawer.left(), drawer.top()),
                              QtCore.QPointF(drawer.left(), drawer.bottom()))
                    for i in (1, 2):
                        yy = drawer.top() + drawer.height() * i / 3
                        p.drawLine(QtCore.QPointF(drawer.left(), yy),
                                  QtCore.QPointF(drawer.right(), yy))
                    chair_c = QtCore.QPointF(rect.left() + rect.width() * 0.32,
                                             rect.top() + rect.height() * 0.5)
                else:
                    dh = rect.height() * 0.24
                    drawer = QtCore.QRectF(rect.left(), rect.bottom() - dh,
                                           rect.width(), dh)
                    p.drawLine(QtCore.QPointF(drawer.left(), drawer.top()),
                              QtCore.QPointF(drawer.right(), drawer.top()))
                    for i in (1, 2):
                        xx = drawer.left() + drawer.width() * i / 3
                        p.drawLine(QtCore.QPointF(xx, drawer.top()),
                                  QtCore.QPointF(xx, drawer.bottom()))
                    chair_c = QtCore.QPointF(rect.left() + rect.width() * 0.5,
                                             rect.top() + rect.height() * 0.32)
                # ⚠ 의자는 사각형 밖으로 내밀지 않는다 — 8/25 실측: 밖으로 내밀면
                #   근처 대피 경로선과 겹쳐 잘못 읽힌다. 책상 안쪽에 담는다.
                p.setPen(QtGui.QPen(equip_pen, 1.0))
                p.setBrush(QtCore.Qt.NoBrush)
                cr = min(rect.width(), rect.height()) * 0.22
                p.drawEllipse(chair_c, cr, cr)          # 의자
            elif kind == 'monitor':
                _, x, y, w, h = item
                rect = self._rect((x, y, w, h), f)
                p.setPen(QtGui.QPen(equip_pen, 0.9))
                p.setBrush(self._volume_brush(rect, equip_pen, 62, 22))
                p.drawRoundedRect(rect, 1.2, 1.2)
                mx, my = rect.width() * 0.14, rect.height() * 0.14
                screen = rect.adjusted(mx, my, -mx, -my * 2.2)
                p.setBrush(QtGui.QBrush(QtGui.QColor(PLAN_FLOOR)))
                p.drawRect(screen)
                sx = rect.center().x()
                p.setPen(QtGui.QPen(equip_pen, 1.1))
                p.drawLine(QtCore.QPointF(sx, screen.bottom()),
                          QtCore.QPointF(sx, rect.bottom() - 1))
            elif kind == 'rack':
                _, x, y, w, h = item
                rect = self._rect((x, y, w, h), f)
                p.setPen(QtGui.QPen(equip_pen, 1.2))
                p.setBrush(self._volume_brush(rect, equip_pen, 30, 8))
                p.drawRect(rect)
                horiz = rect.width() >= rect.height()
                n = 3
                p.setPen(QtGui.QPen(equip_pen, 0.8))
                for i in range(1, n):
                    if horiz:
                        yy = rect.top() + i * rect.height() / n
                        p.drawLine(QtCore.QPointF(rect.left(), yy),
                                  QtCore.QPointF(rect.right(), yy))
                    else:
                        xx = rect.left() + i * rect.width() / n
                        p.drawLine(QtCore.QPointF(xx, rect.top()),
                                  QtCore.QPointF(xx, rect.bottom()))
                p.setBrush(QtGui.QBrush(equip_pen))     # 적재물 틱 — 칸마다 하나씩
                for i in range(n):
                    if horiz:
                        cy = rect.top() + (i + 0.5) * rect.height() / n
                        p.drawRect(QtCore.QRectF(rect.left() + 1.5, cy - 1.2, 3.0, 2.4))
                    else:
                        cx = rect.left() + (i + 0.5) * rect.width() / n
                        p.drawRect(QtCore.QRectF(cx - 1.2, rect.top() + 1.5, 2.4, 3.0))
            elif kind == 'machine':
                _, x, y, w, h = item
                rect = self._rect((x, y, w, h), f)
                p.setPen(QtGui.QPen(equip_pen, 1.4))
                p.setBrush(self._volume_brush(rect, equip_pen, 56, 20))
                p.drawRoundedRect(rect, 1.6, 1.6)       # 베드(본체)
                horiz = rect.width() >= rect.height()
                if horiz:
                    hw = min(rect.width() * 0.30, rect.height() * 1.1)
                    head = QtCore.QRectF(rect.left(), rect.top(), hw, rect.height())
                    spindle = QtCore.QPointF(rect.left() + hw * 0.55,
                                             rect.center().y())
                    rr = rect.height() * 0.20
                    dial = QtCore.QPointF(rect.right() - rect.width() * 0.14,
                                          rect.top() + rect.height() * 0.22)
                else:
                    hh = min(rect.height() * 0.30, rect.width() * 1.1)
                    head = QtCore.QRectF(rect.left(), rect.top(), rect.width(), hh)
                    spindle = QtCore.QPointF(rect.center().x(),
                                             rect.top() + hh * 0.55)
                    rr = rect.width() * 0.20
                    dial = QtCore.QPointF(rect.left() + rect.width() * 0.22,
                                          rect.bottom() - rect.height() * 0.14)
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(self._volume_brush(head, equip_pen, 235, 150))
                p.drawRect(head)                        # 주축대 — 진하게, 입체감
                p.setPen(QtGui.QPen(QtGui.QColor(PLAN_FLOOR), 1.0))
                p.setBrush(QtGui.QBrush(QtGui.QColor(PLAN_FLOOR)))
                p.drawEllipse(spindle, rr, rr)           # 스핀들 구멍
                p.setPen(QtGui.QPen(equip_pen, 1.0))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawEllipse(spindle, rr * 0.55, rr * 0.55)  # 척 조(claw) 표시
                p.setBrush(QtGui.QBrush(equip_pen))      # 제어반 다이얼
                p.drawEllipse(dial, rect.height() * 0.09, rect.height() * 0.09)
            elif kind == 'transformer':
                _, x, y, w, h = item
                rect = self._rect((x, y, w, h), f)
                fin = max(rect.height() * 0.18, 3.0)
                body = rect.adjusted(0, fin, 0, -fin)
                p.setPen(QtGui.QPen(equip_pen, 1.4))
                p.setBrush(self._volume_brush(body, equip_pen, 74, 30))
                p.drawRoundedRect(body, 1.4, 1.4)        # 본체 탱크
                p.setPen(QtGui.QPen(equip_pen, 0.8))
                n = max(int(rect.width() / 7.0), 3)
                for i in range(n):
                    xx = rect.left() + (i + 0.5) * rect.width() / n
                    p.drawLine(QtCore.QPointF(xx, rect.top()),
                              QtCore.QPointF(xx, body.top()))
                    p.drawLine(QtCore.QPointF(xx, body.bottom()),
                              QtCore.QPointF(xx, rect.bottom()))
                p.setPen(QtGui.QPen(equip_pen, 1.0))
                p.setBrush(QtGui.QBrush(equip_pen))      # 부싱(애자) — 몸체보다 진하게
                for i in range(3):
                    bx = body.left() + (i + 1) * body.width() / 4
                    p.drawEllipse(QtCore.QPointF(bx, body.top()), 2.2, 2.2)
                    p.drawLine(QtCore.QPointF(bx, body.top() - 2.2),
                              QtCore.QPointF(bx, body.top()))
            elif kind == 'panel':
                _, x, y, w, h = item
                rect = self._rect((x, y, w, h), f)
                p.setPen(QtGui.QPen(equip_pen, 1.3))
                p.setBrush(self._volume_brush(rect, equip_pen, 62, 22))
                p.drawRoundedRect(rect, 1.2, 1.2)
                horiz = rect.width() >= rect.height()
                # 상단(또는 좌측) 명판 — 얇은 안쪽 테두리
                p.setPen(QtGui.QPen(equip_pen, 0.7))
                nb = (rect.adjusted(rect.width() * 0.10, rect.height() * 0.08,
                                    -rect.width() * 0.10, -rect.height() * 0.72)
                      if horiz else
                      rect.adjusted(rect.width() * 0.08, rect.height() * 0.10,
                                    -rect.width() * 0.72, -rect.height() * 0.10))
                p.drawRect(nb)
                # 양개문 분할선
                p.setPen(QtGui.QPen(equip_pen, 1.0))
                if horiz:
                    p.drawLine(QtCore.QPointF(rect.center().x(), nb.bottom() + 1),
                              QtCore.QPointF(rect.center().x(), rect.bottom() - 2))
                else:
                    p.drawLine(QtCore.QPointF(nb.right() + 1, rect.center().y()),
                              QtCore.QPointF(rect.right() - 2, rect.center().y()))
                # 계기 2개 + 스위치 1개 — 문마다 하나씩
                p.setPen(QtGui.QPen(equip_pen, 1.0))
                p.setBrush(QtGui.QBrush(equip_pen))
                r = min(rect.width(), rect.height()) * 0.13
                g1 = QtCore.QPointF(rect.left() + rect.width() * 0.28,
                                    nb.bottom() + rect.height() * 0.20)
                g2 = QtCore.QPointF(rect.left() + rect.width() * 0.72,
                                    nb.bottom() + rect.height() * 0.20)
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawEllipse(g1, r, r)
                p.drawEllipse(g2, r, r)
                sw_y = rect.bottom() - rect.height() * 0.18
                p.setPen(QtGui.QPen(equip_pen, 1.6, QtCore.Qt.SolidLine,
                                    QtCore.Qt.RoundCap))
                p.drawLine(QtCore.QPointF(rect.left() + rect.width() * 0.28, sw_y),
                          QtCore.QPointF(rect.left() + rect.width() * 0.40,
                                        sw_y - rect.height() * 0.10))
            elif kind == 'conveyor':
                _, x, y, w, h = item
                rect = self._rect((x, y, w, h), f)
                horiz = rect.width() >= rect.height()
                step = 9.0
                p.setPen(QtGui.QPen(equip_pen, 1.5))     # 레일 — 굵게
                if horiz:
                    p.drawLine(rect.topLeft(), rect.topRight())
                    p.drawLine(rect.bottomLeft(), rect.bottomRight())
                else:
                    p.drawLine(rect.topLeft(), rect.bottomLeft())
                    p.drawLine(rect.topRight(), rect.bottomRight())
                p.setPen(QtGui.QPen(equip_pen, 0.8))     # 롤러 — 가늘게
                if horiz:
                    n = max(int(rect.width() / step), 1)
                    for i in range(n + 1):
                        xx = rect.left() + i * rect.width() / n
                        p.drawLine(QtCore.QPointF(xx, rect.top()),
                                  QtCore.QPointF(xx, rect.bottom()))
                else:
                    n = max(int(rect.height() / step), 1)
                    for i in range(n + 1):
                        yy = rect.top() + i * rect.height() / n
                        p.drawLine(QtCore.QPointF(rect.left(), yy),
                                  QtCore.QPointF(rect.right(), yy))
            elif kind == 'tank':
                _, cx, cy, r = item
                c = self._pt(cx, cy, f)
                s = f[0]
                rr = r * s
                tank_rect = QtCore.QRectF(c.x() - rr, c.y() - rr, rr * 2, rr * 2)
                p.setPen(QtGui.QPen(equip_pen, 1.3))
                p.setBrush(self._volume_brush(tank_rect, equip_pen, 68, 24))
                p.drawEllipse(c, rr, rr)
                p.setPen(QtGui.QPen(equip_pen, 0.8))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawEllipse(c, rr * 0.72, rr * 0.72)  # 리브(단)
                p.drawEllipse(c, rr * 0.40, rr * 0.40)  # 맨홀
                p.setPen(QtGui.QPen(equip_pen, 1.1))
                p.drawLine(QtCore.QPointF(c.x(), c.y() - rr),
                          QtCore.QPointF(c.x(), c.y() - rr - 4.0))  # 상단 노즐
            elif kind == 'pipe':
                _, x1, y1, x2, y2 = item
                p.setPen(QtGui.QPen(equip_pen, 1.6, QtCore.Qt.SolidLine,
                                    QtCore.Qt.RoundCap))
                p.drawLine(self._pt(x1, y1, f), self._pt(x2, y2, f))

    def _draw_zones(self, p, f):
        """구역 사각형.

        ⚠ 평상시 구역에는 아무것도 그리지 않는다. 세 구역을 전부 색칠하면
          도면이 색 블록 3개로 덮여 '어디가 문제인가' 가 사라진다. 평상시
          구역의 상태는 이름표 카드의 테두리 색이 말한다(_draw_labels).
          → 도면 위에서 채워진 사각형은 '지금 문제인 곳' 하나뿐이다.
        """
        for z, d in fac.ZONES.items():
            st = self.state.get(z, {})
            rect = self._rect(d['rect'], f)
            sev, pre = st.get('sev'), st.get('pre')
            if sev in ('critical', 'warning'):
                col = QtGui.QColor(sev_color(sev))
                on = (sev != 'critical') or self.blink
                # 발광 — 바깥으로 퍼지는 반투명 사각형을 겹친다.
                #   ⚠ QGraphicsDropShadowEffect 를 쓰면 위젯 전체가 오프스크린
                #     버퍼로 캐시돼 10 Hz 재도색에서 눈에 띄게 느려진다.
                p.setPen(QtCore.Qt.NoPen)
                for i in range(9, 0, -1):
                    g = QtGui.QColor(col)
                    g.setAlpha(int((7 if not on else 12) * (10 - i) / 3))
                    p.setBrush(g)
                    p.drawRoundedRect(rect.adjusted(-5 * i, -5 * i, 5 * i, 5 * i),
                                      16, 16)
                fill = QtGui.QColor(col)
                fill.setAlpha(126 if on else 74)
                p.setBrush(fill)
                p.setPen(QtGui.QPen(QtGui.QColor('#FFFFFF' if on else col),
                                    3 if on else 2, QtCore.Qt.DashLine))
                p.drawRoundedRect(rect, 8, 8)
            elif pre:
                p.setPen(QtGui.QPen(QtGui.QColor(AMBER), 2, QtCore.Qt.DashLine))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRoundedRect(rect, 8, 8)

    def _draw_coverage(self, p, f):
        """감지영역 — 실측 DANGER_ZONES 스케일. 도면에서 여기만 '진짜 치수' 다."""
        for z in fac.RADARS:
            cov = fac.coverage(z)
            if not cov:
                continue
            st = self.state.get(z, {})
            col = (sev_color(st['sev']) if st.get('sev') else
                   (AMBER if st.get('pre') else
                    (CYAN if st.get('live') else FAINT)))
            c = QtGui.QColor(col)
            p.setPen(QtGui.QPen(c, 1.4, QtCore.Qt.DashLine))
            c.setAlpha(30)
            p.setBrush(QtGui.QBrush(c))
            p.drawRect(self._rect(cov, f))

    @staticmethod
    def _arrow(p, a, b, size=9.0, at=0.5, color=None):
        """선분 a→b 의 at(0~1) 지점에 진행 방향 화살촉을 찍는다.

        ⚠ 파선만으로는 '경로' 로 읽히지 어느 쪽으로 가라는 건지 안 읽힌다.
          대피 경로는 방향이 곧 정보다.
        """
        dx, dy = b.x() - a.x(), b.y() - a.y()
        ln = math.hypot(dx, dy)
        if ln < size * 2.2:
            return
        ux, uy = dx / ln, dy / ln
        mx, my = a.x() + dx * at, a.y() + dy * at
        tip = QtCore.QPointF(mx + ux * size * 0.62, my + uy * size * 0.62)
        l = QtCore.QPointF(mx - ux * size * 0.38 - uy * size * 0.60,
                           my - uy * size * 0.38 + ux * size * 0.60)
        r = QtCore.QPointF(mx - ux * size * 0.38 + uy * size * 0.60,
                           my - uy * size * 0.38 - ux * size * 0.60)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QBrush(QtGui.QColor(color or EVAC_GREEN)))
        p.drawPolygon(QtGui.QPolygonF([tip, l, r]))

    @staticmethod
    def _sparkle(c, r):
        """4각 섬광(◆ 을 오목하게 판 모양). 시안 범례의 '위험 감지 구역' 표식."""
        pts = []
        for i in range(8):
            ang = math.radians(90 * (i // 2) + (45 if i % 2 else 0))
            rad = r if i % 2 == 0 else r * 0.30
            pts.append(QtCore.QPointF(c.x() + rad * math.cos(ang),
                                      c.y() - rad * math.sin(ang)))
        return QtGui.QPolygonF(pts)

    @staticmethod
    def _exit_sign(p, c, side=28.0):
        """비상구 표지 — 사용자 제공 참조 사진(assets/exit_icon.png) 원본을 그린다.

        ⚠ [8/25] 이전엔 QPainter로 손그림했으나 참조 사진과 계속 미묘하게 달라
          "그대로 넣으라"는 지시를 받았다. 재작도 대신 원본 이미지를 그대로
          그린다 — 벡터 코드는 exit_pixmap() 참조.
        """
        pm = exit_pixmap()
        if pm.isNull():
            return
        target = QtCore.QRectF(c.x() - side / 2, c.y() - side / 2, side, side)
        p.drawPixmap(target, pm, QtCore.QRectF(pm.rect()))

    def _draw_evac(self, p, f):
        """비상 대피 경로 · 비상구. ⚠ facility.py 의 데모 동선이다(실제 피난 동선 아님).

        ⚠ 화살촉은 구간 끝쪽(75 %)에 찍는다. 가운데에 찍으면 꺾이는 지점에서
          '어디로 꺾이는지' 가 안 보인다 — 사람은 갈림길에서 방향을 찾는다.
          긴 구간에는 앞쪽(35 %)에 하나 더 찍어 멀리서도 흐름이 읽히게 한다.
        """
        pen = QtGui.QPen(QtGui.QColor(EVAC_GREEN), 3.6, QtCore.Qt.CustomDashLine)
        pen.setDashPattern([3.0, 2.0])          # 펜 굵기 배수 → 약 11px 선 / 7px 공백
        pen.setCapStyle(QtCore.Qt.FlatCap)
        for route in fac.EVAC_ROUTES:
            pts = [self._pt(x, y, f) for x, y in route]
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            for i in range(len(pts) - 1):
                p.drawLine(pts[i], pts[i + 1])
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                self._arrow(p, a, b, 10.0, at=0.75)
                if math.hypot(b.x() - a.x(), b.y() - a.y()) > 120:
                    self._arrow(p, a, b, 10.0, at=0.35)
        for x, y, _d in fac.EXITS:
            self._exit_sign(p, self._pt(x, y, f), 42.0)

    def _draw_labels(self, p, f):
        """구역 이름은 가운데. 경보 구역만 ⚠ 와 이름표를 크게 얹는다."""
        for z, d in fac.ZONES.items():
            st = self.state.get(z, {})
            rect = self._rect(d['rect'], f)
            sev, pre, live = st.get('sev'), st.get('pre'), st.get('live')
            if sev in ('critical', 'warning'):
                col = QtGui.QColor(sev_color(sev))
                cx, cy = rect.center().x(), rect.center().y()
                # ⚠ 표식 — 사고 아이콘. 텍스트 글리프라 폰트 의존이 있어
                #   삼각형을 직접 그리고 느낌표만 글자로 얹는다.
                side = max(min(rect.width(), rect.height()) * 0.30, 34.0)
                top = QtCore.QPointF(cx, cy - side * 0.72)
                bl = QtCore.QPointF(cx - side * 0.62, cy + side * 0.36)
                br = QtCore.QPointF(cx + side * 0.62, cy + side * 0.36)
                p.setPen(QtGui.QPen(QtGui.QColor('#FFFFFF'),
                                    max(side * 0.09, 2.0),
                                    QtCore.Qt.SolidLine, QtCore.Qt.RoundCap,
                                    QtCore.Qt.RoundJoin))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawPolygon(QtGui.QPolygonF([top, br, bl]))
                p.setFont(kf(max(int(side * 0.40), 10), True))
                p.setPen(QtGui.QColor('#FFFFFF'))
                p.drawText(QtCore.QRectF(cx - side * 0.5, cy - side * 0.34,
                                         side, side * 0.66),
                           QtCore.Qt.AlignCenter, '!')
                # 이름표 — 빨간 칩 위 흰 글씨 두 줄
                p.setFont(kf(U_H1, True))
                fm = p.fontMetrics()
                t1 = f'Zone {z}'
                t2 = d['name']
                cw = max(fm.width(t1), fm.width(t2)) + SP5
                ch = fm.height() * 2 + SP2
                chip = QtCore.QRectF(cx - cw / 2, cy + side * 0.50, cw, ch)
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(QtGui.QBrush(col))
                p.drawRoundedRect(chip, 6, 6)
                p.setPen(QtGui.QColor('#FFFFFF'))
                p.drawText(QtCore.QRectF(chip.x(), chip.y() + SP1 / 2, cw,
                                         fm.height()),
                           QtCore.Qt.AlignCenter, t1)
                p.drawText(QtCore.QRectF(chip.x(), chip.y() + SP1 / 2 + fm.height(),
                                         cw, fm.height()),
                           QtCore.Qt.AlignCenter, t2)
                continue

            # ── 평상시 이름표 카드 ────────────────────────────────
            #  시안처럼 'Zone C / 생산라인 2' 두 줄이 기본이다.
            #  ⚠ 세 번째 줄은 '감시 중' 일 때 쓰지 않는다. 정상은 카드 테두리
            #    초록으로 이미 말하고, 세 구역에 같은 글자를 세 번 쓰면 시선만
            #    잡아먹는다. 반대로 '장비 미설치'·'연결 대기'·사전경보는 반드시
            #    쓴다 — 감시하지 않는 구역을 감시하는 것처럼 두면 안 된다.
            if pre:
                col2, sub = AMBER, pre
            elif live:
                col2, sub = GREEN, ''
            elif not zone_equipped(z):
                col2, sub = FAINT, '장비 미설치'
            else:
                col2, sub = FAINT, '연결 대기'
            w_avail = int(rect.width() - SP3 * 2)
            if w_avail < 40:
                continue
            p.setFont(kf(U_H1, True))
            fm1 = p.fontMetrics()
            t1 = fm1.elidedText(f'Zone {z}', QtCore.Qt.ElideRight, w_avail)
            p.setFont(kf(U_LABEL))
            fm2 = p.fontMetrics()
            t2 = fm2.elidedText(d['name'], QtCore.Qt.ElideRight, w_avail)
            widths = [fm1.width(t1), fm2.width(t2)]
            bh = fm1.height() + fm2.height() + SP3
            t3 = ''
            if sub:
                p.setFont(kf(U_CAP))
                fm3 = p.fontMetrics()
                t3 = fm3.elidedText(sub, QtCore.Qt.ElideRight, w_avail)
                widths.append(fm3.width(t3))
                bh += fm3.height()
            bw = min(max(widths) + SP5 * 2, rect.width() - SP2 * 2)
            cx, cy = rect.center().x(), rect.center().y()
            card_r = QtCore.QRectF(cx - bw / 2, cy - bh / 2, bw, bh)
            p.setPen(QtGui.QPen(QtGui.QColor(col2 if (live or pre)
                                             else PLAN_CARD_EDGE), 1.2))
            p.setBrush(QtGui.QBrush(QtGui.QColor(PLAN_CARD)))
            p.drawRoundedRect(card_r, RADIUS_SM, RADIUS_SM)
            y = card_r.top() + SP3 / 2
            p.setFont(kf(U_H1, True))
            p.setPen(QtGui.QColor('#FFFFFF' if (live or pre) else DIM))
            p.drawText(QtCore.QRectF(card_r.x(), y, bw, fm1.height()),
                       QtCore.Qt.AlignCenter, t1)
            y += fm1.height()
            p.setFont(kf(U_LABEL))
            p.setPen(QtGui.QColor(DIM if (live or pre) else FAINT))
            p.drawText(QtCore.QRectF(card_r.x(), y, bw, fm2.height()),
                       QtCore.Qt.AlignCenter, t2)
            if t3:
                y += fm2.height()
                p.setFont(kf(U_CAP))
                p.setPen(QtGui.QColor(col2))
                p.drawText(QtCore.QRectF(card_r.x(), y, bw,
                                         p.fontMetrics().height()),
                           QtCore.Qt.AlignCenter, t3)

    def _draw_worker(self, p, f):
        """작업자 현재 위치 — 젯슨이 보낸 centroid 를 도면 좌표로 옮긴 것."""
        if not self.worker:
            return
        z, x, y = self.worker
        st = self.state.get(z, {})
        col = QtGui.QColor(sev_color(st['sev']) if st.get('sev') else
                           (AMBER if st.get('pre') else CYAN))
        c = self._pt(x, y, f)
        halo = QtGui.QColor(col)
        halo.setAlpha(70)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QBrush(halo))
        p.drawEllipse(c, 14, 14)
        p.setBrush(QtGui.QBrush(col))
        p.setPen(QtGui.QPen(QtGui.QColor(BG), 2))
        p.drawEllipse(c, 6, 6)

    def _draw_legend(self, p):
        """좌측 하단 범례.

        ⚠ 글리프(■ ● ▬)로 쓰면 폰트에 따라 크기·굵기가 제각각이라 견본이
          실제 화면의 표시와 달라 보인다. 화면에 그린 것과 같은 도형을 그린다.
        ⚠ 시안의 '로봇 현재 위치' 는 이 시스템에선 작업자다.
        """
        rows = ('위험 감지 구역', '작업자 현재 위치', '비상 대피 경로')
        p.setFont(kf(U_LABEL, True))
        fm = p.fontMetrics()
        tw = max(fm.width(t) for t in rows)
        tile = 26.0                               # 아이콘 타일 한 변
        rh = max(fm.height(), int(tile))
        bw = tw + tile + SP3 * 3
        bh = rh * len(rows) + SP2 * (len(rows) - 1) + SP4 * 2
        box = QtCore.QRectF(SP4, self.height() - 26 - bh, bw, bh)
        p.setPen(QtGui.QPen(QtGui.QColor(PLAN_CARD_EDGE), 1.2))
        p.setBrush(QtGui.QBrush(QtGui.QColor(10, 14, 22, 236)))
        p.drawRoundedRect(box, RADIUS, RADIUS)
        y = box.y() + SP4
        x = box.x() + SP4
        for i, text in enumerate(rows):
            cy = y + rh / 2
            t = QtCore.QRectF(x, cy - tile / 2, tile, tile)
            c = t.center()
            if i == 0:
                # 위험 감지 구역 — 시안과 같은 붉은 타일 + 4각 섬광
                p.setPen(QtGui.QPen(QtGui.QColor(RED), 1.6))
                p.setBrush(QtGui.QBrush(QtGui.QColor(62, 18, 22)))
                p.drawRoundedRect(t, 5, 5)
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(QtGui.QBrush(QtGui.QColor(RED)))
                p.drawPolygon(self._sparkle(c, tile * 0.36))
            elif i == 1:
                # 작업자 현재 위치 — 도면에 실제로 그리는 표식 그대로.
                #   ⚠ 시안은 노란 화살표(로봇의 진행 방향)지만, 레이더는
                #     centroid 만 준다. 사람이 어느 쪽을 보는지는 측정되지
                #     않는다 — 화살표를 그리면 없는 정보를 주장하게 된다.
                #     그래서 방향 없는 점이고, 범례도 같은 점을 쓴다.
                p.setPen(QtGui.QPen(QtGui.QColor(CYAN), 1.6))
                p.setBrush(QtGui.QBrush(QtGui.QColor(10, 34, 44)))
                p.drawRoundedRect(t, 5, 5)
                halo = QtGui.QColor(CYAN)
                halo.setAlpha(84)
                p.setPen(QtCore.Qt.NoPen)
                p.setBrush(QtGui.QBrush(halo))
                p.drawEllipse(c, 8.5, 8.5)
                p.setBrush(QtGui.QBrush(QtGui.QColor(CYAN)))
                p.setPen(QtGui.QPen(QtGui.QColor(BG), 1.4))
                p.drawEllipse(c, 4.2, 4.2)
            else:
                # 비상 대피 경로 — 도면에 찍는 비상구 표지와 같은 그림
                self._exit_sign(p, c, tile)
            p.setPen(QtGui.QColor('#E6ECF5'))
            p.setFont(kf(U_LABEL, True))
            p.drawText(QtCore.QRectF(x + tile + SP3, y, tw, rh),
                       QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, text)
            y += rh + SP2


# ══════════════════════════════════════════════════════════════════════
# 3. 우측 지시 패널 — 이 화면의 '지금 무엇을'
# ══════════════════════════════════════════════════════════════════════
class GuidePanel(QtWidgets.QFrame):
    """헤더(등급색) + 흰 카드(현재 상태 · 즉시 수행 지시 · 금지 안내).

    ⚠ 여기에 AI 생성 문장·모델명·검색 과정은 넣지 않는다. 이 패널이 말하는
      것은 ① 젯슨이 보낸 사실(구역·차단 상태) ② radar_core.INSTANT_ACTION 의
      확정 절차뿐이다. 둘 다 네트워크·LLM 상태와 무관하게 항상 표시된다.
    """
    WIDTH = 440

    def __init__(self):
        super().__init__()
        self.setFixedWidth(self.WIDTH)
        self.setStyleSheet(f'QFrame{{background:{K_CARD};border:none;'
                           f'border-radius:{RADIUS}px;}}')
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ── 헤더 ──
        self.head = QtWidgets.QFrame()
        hv = kvbox(self.head, SP4, SP1)
        top = khbox(s=SP3)
        self.h_icon = klb('!', 20, '#FFFFFF', bold=True)
        self.h_icon.setFixedWidth(26)
        self.h_icon.setAlignment(QtCore.Qt.AlignCenter)
        top.addWidget(self.h_icon)
        self.h_title = klb('현재 안전 지시사항', U_H1, '#FFFFFF', bold=True)
        top.addWidget(self.h_title, 1)
        hv.addLayout(top)
        self.h_sub = klb('', U_LABEL, '#FFFFFF')
        hv.addWidget(self.h_sub)
        v.addWidget(self.head)

        # ── 본문 (흰 카드) ──
        body = QtWidgets.QWidget()
        body.setStyleSheet(f'background:{K_CARD};')
        bv = kvbox(body, SP4, SP3)
        bv.addWidget(klb('현재 상태', U_LABEL, K_INK2, bold=True))
        self.row_zone = self._status_row()
        self.row_power = self._status_row()
        bv.addWidget(self.row_zone['w'])
        bv.addWidget(self.row_power['w'])

        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f'background:{K_LINE};border:none;')
        bv.addWidget(line)

        self.steps_title = klb('즉시 수행 지시', U_LABEL, K_INK2, bold=True)
        bv.addWidget(self.steps_title)

        inner = QtWidgets.QWidget()
        inner.setStyleSheet(f'background:{K_CARD};')
        self.steps = QtWidgets.QVBoxLayout(inner)
        self.steps.setContentsMargins(0, 0, 0, 0)
        self.steps.setSpacing(SP3)
        # ⚠ 지시가 6개를 넘으면 세로가 모자란다. Qt 는 그때 위젯을 겹쳐 그리는데
        #   조치 문장이 겹치는 것은 '못 읽는 것' 이 아니라 '잘못 읽는 것' 이다.
        sa = QtWidgets.QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QtWidgets.QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        sa.setStyleSheet(
            f'QScrollArea{{background:{K_CARD};border:none;}}'
            f'QScrollBar:vertical{{background:transparent;width:8px;margin:0;}}'
            f'QScrollBar::handle:vertical{{background:{K_LINE};'
            f'border-radius:4px;min-height:28px;}}'
            f'QScrollBar::add-line,QScrollBar::sub-line{{height:0;}}'
            f'QScrollBar::add-page,QScrollBar::sub-page{{background:transparent;}}')
        sa.setWidget(inner)
        bv.addWidget(sa, 1)

        # ── 금지 안내 박스 ──
        self.note = QtWidgets.QFrame()
        nv = khbox(self.note, SP3, SP3)
        self.n_icon = klb('!', U_H2, K_RED, bold=True)
        self.n_icon.setFixedWidth(18)
        self.n_icon.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignHCenter)
        nv.addWidget(self.n_icon)
        self.n_text = klb('', U_LABEL, K_RED, bold=True, wrap=True)
        nv.addWidget(self.n_text, 1)
        bv.addWidget(self.note)
        v.addWidget(body, 1)

        # ⚠ set_normal / set_note 은 0.5초마다 불린다. 내용이 같은데 위젯을
        #   다시 만들면 초당 2번씩 라벨이 파괴·생성돼 스크롤 위치가 튀고
        #   불필요한 재도색이 생긴다. 마지막 내용을 기억해 두고 바뀔 때만 짓는다.
        self._normal_key = None
        self._note_key = None
        self.set_normal('감시 대기', '젯슨 연결을 기다리는 중입니다', AMBER)

    # ── 부품 ─────────────────────────────────────────────────────────
    @staticmethod
    def _status_row():
        w = QtWidgets.QWidget()
        w.setStyleSheet(f'background:{K_CARD};')
        h = khbox(w, 0, SP3)
        dot = klb('●', U_H2, K_GREEN, bold=True)
        dot.setFixedWidth(16)
        text = klb('', U_H2, K_INK, bold=True, wrap=True)
        h.addWidget(dot)
        h.addWidget(text, 1)
        return {'w': w, 'dot': dot, 'text': text}

    @staticmethod
    def _set_row(row, text, color, mark='●'):
        row['dot'].setText(mark)
        row['dot'].setStyleSheet(
            f'color:{color};border:none;background:transparent;')
        row['text'].setText(text)
        row['text'].setStyleSheet(
            f'color:{color};border:none;background:transparent;')

    def _set_head(self, color, icon, title, sub):
        self.head.setStyleSheet(
            f'QFrame{{background:{color};border:none;'
            f'border-top-left-radius:{RADIUS}px;'
            f'border-top-right-radius:{RADIUS}px;}}')
        self.h_icon.setText(icon)
        self.h_title.setText(title)
        self.h_sub.setText(sub)

    def _set_note(self, text, color, bg, line):
        self.note.setStyleSheet(
            f'QFrame{{background:{bg};border:1px solid {line};'
            f'border-radius:{RADIUS_SM}px;}}')
        self.n_icon.setStyleSheet(
            f'color:{color};border:none;background:transparent;')
        self.n_text.setText(text)
        self.n_text.setStyleSheet(
            f'color:{color};border:none;background:transparent;')

    def _step_row(self, n, title, sub, color):
        w = QtWidgets.QWidget()
        w.setStyleSheet(f'background:{K_CARD};')
        h = khbox(w, 0, SP3)
        num = QtWidgets.QLabel(str(n))
        num.setFixedSize(26, 26)
        num.setAlignment(QtCore.Qt.AlignCenter)
        num.setFont(kf(U_LABEL, True))
        num.setStyleSheet(f'background:{color};color:#FFFFFF;'
                          f'border-radius:13px;')
        h.addWidget(num, 0, QtCore.Qt.AlignTop)
        col = QtWidgets.QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        col.addWidget(klb(title, U_H2, K_INK, bold=True, wrap=True))
        if sub:
            col.addWidget(klb(sub, U_CAP, K_INK2, wrap=True))
        h.addLayout(col, 1)
        return w

    # ── 화면 상태 ────────────────────────────────────────────────────
    def set_normal(self, title, sub, color, lines=()):
        """평상시·대기·감시중단 — 경보가 아닐 때의 패널."""
        key = ('normal', title, sub, color, tuple(lines))
        if key == self._normal_key:
            return
        self._normal_key = key
        icon = IC_OK if color == GREEN else '!'
        self._set_head(color, icon, title, sub)
        self.steps_title.setText('안내')
        clear_layout(self.steps)
        for text in (lines or (
                '경보가 발생하면 이 자리에 즉시 수행 지시가 표시됩니다.',)):
            self.steps.addWidget(klb(text, U_BODY, K_INK2, wrap=True))
        self.steps.addStretch(1)

    def set_alarm(self, name, ts, color, steps, missing=False):
        """경보 — 사고 종류 · 발생 시각 · 번호 매긴 즉시 조치."""
        self._normal_key = None      # 다음 평상시 복귀 때 반드시 다시 짓는다
        self._set_head(color, '!', '긴급 안전 지시사항', f'발생 시간 : {ts}')
        self.steps_title.setText('즉시 수행 지시')
        clear_layout(self.steps)
        if missing:
            # ⚠ 조치를 지어내지 않는다. 없으면 없다고 쓴다 (CLAUDE.md §4).
            self.steps.addWidget(klb(
                f'"{name}" 의 즉시 조치 절차가 시스템에 등록돼 있지 않습니다.\n'
                f'관제 화면 [SOP 가이드] 와 현장 책임자 지시를 따르십시오.',
                U_H2, K_AMBER, bold=True, wrap=True))
        for i, (cat, text) in enumerate(steps, 1):
            self.steps.addWidget(self._step_row(i, text, cat, color))
        self.steps.addStretch(1)

    def set_status_rows(self, zone_text, zone_color, power_text, power_color,
                        zone_mark='●', power_mark='●'):
        self._set_row(self.row_zone, zone_text, zone_color, zone_mark)
        self._set_row(self.row_power, power_text, power_color, power_mark)

    def set_note(self, kind, text):
        if (kind, text) == self._note_key:
            return
        self._note_key = (kind, text)
        if kind == 'danger':
            self._set_note(text, K_RED, K_WARN_BG, K_WARN_LINE)
        elif kind == 'warn':
            self._set_note(text, K_AMBER, '#FFFBEB', '#FDE68A')
        else:
            self._set_note(text, K_GREEN, K_OK_BG, K_OK_LINE)


# ══════════════════════════════════════════════════════════════════════
# 4. 관리자 승인 — 전원 재투입 앞의 관문
# ══════════════════════════════════════════════════════════════════════
class AdminAuthDialog(core.Dialog):
    """아이디·비밀번호를 받아 재투입 승인 여부를 돌려준다.

    ⚠ 왜 이 관문이 필요한가:
      LOTO 의 핵심은 '에너지를 격리한 사람만 해제한다' 이다. 현장 키오스크는
      누구나 만질 수 있는 위치에 있으므로, 재투입만은 화면 앞에 선 사람이
      아니라 승인 권한이 있는 사람이 눌렀다는 것을 화면이 확인해야 한다.

    ⚠ 무엇을 하지 않는가:
      비밀번호를 어딘가로 보내지 않고, 해시도 쓰지 않으며, 통과 여부를
      젯슨에 알리지도 않는다. 젯슨은 이 승인과 무관하게 자기 판단으로 차단을
      유지한다 — 이 관문은 '사람이 실수로 누르는 것' 을 막는 장치다.
    """

    def __init__(self, parent=None):
        super().__init__(parent, '관리자 승인', 480, 420)
        self.tries = 0
        self.locked_out = False
        self.v.addWidget(core.lb(
            f'{BREAKER_SCOPE} 재투입은 관리자 승인이 필요합니다.',
            U_BODY, RED, bold=True, wrap=True))
        self.v.addWidget(core.lb(
            '승인 권한이 있는 담당자가 직접 입력하십시오. '
            '입력한 계정은 이 노트북 밖으로 나가지 않습니다.',
            9, DIM, wrap=True))

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, SP3, 0, 0)
        form.setSpacing(SP3)
        self.id_in = QtWidgets.QLineEdit()
        self.pw_in = QtWidgets.QLineEdit()
        self.pw_in.setEchoMode(QtWidgets.QLineEdit.Password)
        for e, ph in ((self.id_in, '관리자 아이디'), (self.pw_in, '비밀번호')):
            e.setFont(kf(U_BODY))
            e.setMinimumHeight(38)
            e.setPlaceholderText(ph)
            e.setStyleSheet(core.EDIT_QSS)
            e.returnPressed.connect(self._submit)
            e.textChanged.connect(self._sync)
        form.addRow(core.lb('아이디', U_LABEL, DIM), self.id_in)
        form.addRow(core.lb('비밀번호', U_LABEL, DIM), self.pw_in)
        self.v.addLayout(form)

        self.msg = core.lb('', U_LABEL, AMBER, wrap=True)
        self.v.addWidget(self.msg)
        self.v.addStretch()

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(SP2)
        cancel = core.btn('취소', U_BODY, height=44)
        cancel.clicked.connect(self.reject)
        self.ok = core.btn('승인', U_BODY, height=44, accent=True)
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self._submit)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(self.ok, 1)
        self.v.addLayout(row)

    def _sync(self):
        self.ok.setEnabled(bool(self.id_in.text().strip())
                           and bool(self.pw_in.text()))

    def _submit(self):
        uid = self.id_in.text().strip()
        pw = self.pw_in.text()
        if not uid or not pw:
            return
        if uid == ADMIN_ID and pw == ADMIN_PW:
            self.accept()
            return
        self.tries += 1
        self.pw_in.clear()
        self.pw_in.setFocus()
        left = AUTH_MAX_TRY - self.tries
        if left <= 0:
            self.locked_out = True
            self.reject()
            return
        # ⚠ 아이디가 틀렸는지 비밀번호가 틀렸는지 구분해 말하지 않는다.
        self.msg.setText(f'아이디 또는 비밀번호가 올바르지 않습니다 · '
                         f'남은 시도 {left}회')
        self.msg.setStyleSheet(f'color:{RED};border:none;')

    def ask(self):
        """승인되면 관리자 아이디, 아니면 None. 잠금은 locked_out 으로 알린다."""
        self.tries = 0
        self.locked_out = False
        self.id_in.clear()
        self.pw_in.clear()
        self.msg.setText('')
        self._sync()
        self.id_in.setFocus()
        if self.exec_() == QtWidgets.QDialog.Accepted:
            return self.id_in.text().strip()
        return None


# ══════════════════════════════════════════════════════════════════════
# 5. LOTO 상태 확인 팝업
# ══════════════════════════════════════════════════════════════════════
class LotoPopup(core.Dialog):
    """차단기 상태 읽기 전용.

    ⚠ 이 화면은 차단하지도 복구하지도 않는다. 젯슨이 실행한 결과를 보여줄 뿐이다.
      전류·전압 그래프는 관제(console_ui) 의 [전기 설비] 에 있다 — 근무자가
      판단에 쓸 정보가 아니라 엔지니어가 추적할 정보이기 때문이다.
    """

    def __init__(self, parent=None):
        super().__init__(parent, 'LOTO 상태 확인', 560, 430)
        self.src = core.lb('', 9, AMBER, wrap=True)
        self.v.addWidget(self.src)
        self.tbl = QtWidgets.QTableWidget(len(ZONE_IDS), 3)
        self.tbl.setHorizontalHeaderLabels(['구역', '설비 회로', '사유'])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.horizontalHeader().setDefaultSectionSize(150)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setFont(kf(U_BODY))
        self.tbl.setStyleSheet(core.TABLE_QSS)
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tbl.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.v.addWidget(self.tbl, 1)
        self.v.addWidget(core.lb(
            f'차단 범위는 {BREAKER_SCOPE} 1개다. 차단·재투입 실행은 젯슨이 하며 '
            f'이 화면은 상태 표시만 한다 (링크가 끊겨도 차단은 유지된다).',
            9, DIM, wrap=True))
        b = core.btn('닫기', 12, height=40)
        b.clicked.connect(self.accept)
        self.v.addWidget(b)

    def refresh(self, pkt):
        breaker = (pkt or {}).get('breaker') or {}
        snap = breaker.get('state') or {}
        reasons = breaker.get('reason') or {}
        src = breaker.get('src')
        if src == 'modbus' and breaker.get('connected'):
            self.src.setText('Modbus 릴레이 응답 정상 — 아래는 실측 상태다')
            self.src.setStyleSheet(f'color:{GREEN};border:none;')
        else:
            self.src.setText('Modbus 릴레이 실측 미확인 — 현장 차단 여부를 직접 확인할 것')
            self.src.setStyleSheet(f'color:{AMBER};border:none;')
        for r, z in enumerate(ZONE_IDS):
            off = snap.get(z, 'ON') != 'ON'
            why = reasons.get(z)
            cells = (f'Zone {z} · {ZONE_KO.get(z, "")}',
                     '차단됨' if off else '투입',
                     (EVENT_KO.get(why, why) if why else
                      ('사유 미기록' if off else '')))
            for c, t in enumerate(cells):
                it = QtWidgets.QTableWidgetItem(str(t))
                it.setForeground(QtGui.QColor(
                    (RED if off else GREEN) if c == 1 else TXT))
                self.tbl.setItem(r, c, it)

    def show_for(self, pkt):
        self.refresh(pkt)
        self.show()
        self.raise_()


# ══════════════════════════════════════════════════════════════════════
# 6. 메인 창
# ══════════════════════════════════════════════════════════════════════
class UserConsole(QtWidgets.QMainWindow):
    """현장 작업자용 단일 화면. 페이지 이동이 없다 — 이동할 곳이 없기 때문이다."""

    def __init__(self, link=None, demo=False, operator='미지정', preview=False):
        super().__init__()
        self.link = link
        self.demo = demo
        self.preview = preview
        self.operator = operator or '미지정'
        self.pkt = {}
        self.alarm = ST_NORMAL
        self.alert = None
        self.alert_t0 = 0.0        # ★ 노트북 수신 시각 기준 (젯슨 시계 안 씀)
        self.last_ev_id = 0
        self.last_ev_rev = 0
        self.today = 0
        self.boot_t = time.time()
        self.quiet_since = time.time()
        self.blink = False
        self.muted = False
        self._beep_n = 0
        self._auth_lock_until = 0.0   # 승인 연속 실패 시 재투입 버튼 잠금 만료 시각
        self._approved_by = None      # (관리자 아이디, 승인 시각) — 최근 1건
        self._pre = None
        self._link_ok = bool(demo)

        self.setWindowTitle(
            f'Radar-Guard 현장 안전 관제 {APP_VERSION}'
            + ('  [디자인 미리보기 · 실데이터 아님]' if preview else ''))
        self.resize(1600, 1000)
        # 시안 기준 비율. 이보다 작아지면 지시 4개 + 하단 버튼이 세로로 안 들어간다.
        self.setMinimumSize(1280, 820)
        self.setStyleSheet(
            f'QMainWindow{{background:{BG};}}'
            f'QWidget{{color:{TXT};}}'
            f'QToolTip{{background:{PANEL_HI};color:{TXT};'
            f'border:1px solid {EDGE};padding:4px;}}')

        root = QtWidgets.QWidget()
        root.setObjectName('rgUserRoot')
        root.setStyleSheet(f'#rgUserRoot{{background:{BG};}}')
        self.setCentralWidget(root)
        v = kvbox(root, SP4, SP3)

        v.addWidget(self._build_header())
        v.addLayout(self._build_body(), 1)
        v.addWidget(self._build_actions())

        # ── 팝업 (관제와 같은 객체를 쓴다 — 절차가 갈라질 수 없다) ──
        self.loto = LotoPopup(self)
        self.auth = AdminAuthDialog(self)
        self.restore = RestorePopup(self)

        # ── 링크 ──
        if link:
            link.packet.connect(self.on_packet)
            link.linkstate.connect(self.on_link)
        if demo:
            self.demo_src = core._DemoSource()
            self.demo_timer = QtCore.QTimer(self)
            self.demo_timer.timeout.connect(
                lambda: self.on_packet(self.demo_src.read()))
            self.demo_timer.start(100)

        self.ui_timer = QtCore.QTimer(self)
        self.ui_timer.timeout.connect(self.tick_ui)
        self.ui_timer.start(500)
        if preview:
            self.plan.preview = True
            self.fire_preview()
        self._sync_buttons()
        self.tick_ui()

    # ══════════════════════════════════════════════════════════════════
    # 화면 구성
    # ══════════════════════════════════════════════════════════════════
    def _build_header(self):
        bar = kcard(PANEL)
        h = khbox(bar, SP4, SP4)
        brand = khbox(s=SP2)
        brand.addWidget(klb('◈', U_TITLE, CYAN, bold=True))
        brand.addWidget(klb('안전 관제 시스템', U_BRAND, TXT, bold=True))
        left = QtWidgets.QWidget()
        left.setLayout(brand)
        left.setFixedWidth(230)
        h.addWidget(left)

        self.status_lb = klb('', U_TITLE, DIM, bold=True,
                             align=QtCore.Qt.AlignCenter)
        h.addWidget(self.status_lb, 1)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(0)
        self.date_lb = klb('', U_CAP, DIM, align=QtCore.Qt.AlignRight)
        self.who_lb = klb('', U_CAP, DIM, align=QtCore.Qt.AlignRight)
        right.addWidget(self.date_lb)
        right.addWidget(self.who_lb)
        rw = QtWidgets.QWidget()
        rw.setLayout(right)
        rw.setFixedWidth(230)
        h.addWidget(rw)

        self.menu_btn = QtWidgets.QToolButton()
        self.menu_btn.setText('☰')
        self.menu_btn.setFont(kf(U_H1, True))
        self.menu_btn.setFixedSize(40, 40)
        self.menu_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.menu_btn.setStyleSheet(
            f'QToolButton{{background:transparent;color:{TXT};border:none;}}'
            f'QToolButton::menu-indicator{{image:none;}}'
            f'QToolButton:hover{{color:{CYAN};}}')
        self.menu_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.menu_btn.setMenu(self._build_menu())
        h.addWidget(self.menu_btn)
        return bar

    def _build_menu(self):
        m = QtWidgets.QMenu(self)
        m.setFont(kf(U_BODY))
        m.setStyleSheet(
            f'QMenu{{background:{PANEL_HI};color:{TXT};'
            f'border:1px solid {EDGE};padding:6px;}}'
            f'QMenu::item{{padding:8px 18px;border-radius:4px;}}'
            f'QMenu::item:selected{{background:{CYAN};color:#062028;}}')
        m.addAction('전체 화면 전환 (F11)', self.toggle_fullscreen)
        m.addAction('작업자 이름 변경', self.change_operator)
        m.addAction('LOTO 상태 확인', lambda: self.loto.show_for(self.pkt))
        if self.preview:
            # ⚠ 합성 경보를 다시 띄운다. 미리보기에서만 존재하는 항목이다 —
            #   실운용 화면에 '경보를 만드는 버튼' 이 있으면 안 된다.
            m.addAction('경보 재현 (미리보기)', self.fire_preview)
        m.addSeparator()
        m.addAction('종료', self.close)
        return m

    def _build_body(self):
        body = khbox(s=SP3)
        plan_card = kcard(PANEL)
        pv = kvbox(plan_card, SP4, SP3)
        head = khbox(s=SP3)
        head.addWidget(klb('공장 평면도 (실시간 상황)', U_H1, TXT, bold=True))
        head.addStretch()
        for mark, color, text in (('●', RED, '위험'), ('●', FAINT, '정상')):
            head.addWidget(klb(mark, U_LABEL, color))
            head.addWidget(klb(text, U_LABEL, DIM))
        pv.addLayout(head)
        self.plan = UserPlan()
        pv.addWidget(self.plan, 1)
        body.addWidget(plan_card, 1)

        self.guide = GuidePanel()
        body.addWidget(self.guide)
        return body

    def _build_actions(self):
        w = QtWidgets.QWidget()
        h = khbox(w, 0, SP3)
        self.b_mute = BigButton(IC_BELL, '알림 음소거', '', B_GRAY, B_GRAY_H)
        self.b_mute.setFixedWidth(210)
        self.b_ack = BigButton(IC_OK, '상황 확인 완료',
                               '위험 구역 확인 및 대피 완료', B_BLUE, B_BLUE_H)
        self.b_loto = BigButton(IC_LOCK, 'LOTO 상태 확인',
                                '전원 차단 상태 확인', B_GOLD, B_GOLD_H, '#1F2937')
        # ⚠ 제목은 한 줄로 둔다. paintEvent 는 줄바꿈을 처리하지 않는다.
        self.b_restore = BigButton(IC_POWER, 'LOTO 해제 · 수동 전원 재투입',
                                   '관리자 승인 후 실행', B_RED, B_RED_H)
        self.b_mute.clicked.connect(self.toggle_mute)
        self.b_ack.clicked.connect(self.on_primary)
        self.b_loto.clicked.connect(lambda: self.loto.show_for(self.pkt))
        self.b_restore.clicked.connect(self.do_restore)
        for b, stretch in ((self.b_mute, 0), (self.b_ack, 3),
                           (self.b_loto, 2), (self.b_restore, 3)):
            h.addWidget(b, stretch)
        return w

    # ══════════════════════════════════════════════════════════════════
    # 링크 · 패킷
    # ══════════════════════════════════════════════════════════════════
    def fire_preview(self):
        """합성 경보를 띄운다. --preview 전용 (실운용 경로에서는 불리지 않는다)."""
        self._link_ok = True
        self.on_packet(preview_packet(active=True))

    def on_link(self, alive):
        self._link_ok = alive

    def on_packet(self, pkt):
        self.pkt = pkt
        self._link_ok = True
        self._pump_state(pkt)
        self._pre = (parse_pre_alert(pkt.get('pre_alert'))
                     if self.alarm == ST_NORMAL else None)
        self._update_plan(pkt)
        if self.loto.isVisible():
            self.loto.refresh(pkt)

    def _pump_state(self, pkt):
        """경보 상태기계 — console_ui.ConsoleV2._pump_state 와 동일하다."""
        ev = pkt.get('ev') or {}
        eid = ev.get('id') or 0
        rev = ev.get('rev') or 0
        if ev.get('active') and (eid != self.last_ev_id or rev != self.last_ev_rev):
            updating = eid == self.last_ev_id and self.last_ev_id != 0
            self.last_ev_id = eid
            self.last_ev_rev = rev
            self.on_event(ev, updating=updating)
        elif not ev.get('active') and self.alarm != ST_NORMAL:
            # 젯슨이 먼저 해소한 경우(노트북 '상황 종료' 의 왕복 결과 포함)
            self.clear_alarm()

    def _update_plan(self, pkt):
        """평면도 구역 상태. 경보 > 사전경보 > 감시중 > 미설치 순으로 결정한다."""
        ev = pkt.get('ev') or {}
        live_ph = pkt.get('phase') == PH_LIVE
        alarm_zone = ev.get('zone') if ev.get('active') else None
        asev = (ev.get('sev') or event_sev(ev.get('type'))) if alarm_zone else None
        pre = self._pre
        for z in fac.ZONES:
            self.plan.set_zone(
                z,
                live=bool(self._link_ok and zone_equipped(z) and live_ph),
                sev=asev if z == alarm_zone else None,
                pre=(pre['text'] if (pre and pre['zone'] == z
                                     and z != alarm_zone) else None),
                et=ev.get('type') if z == alarm_zone else None)
        c = pkt.get('centroid') or {}
        if pkt.get('track_state') == 'tracking' and c:
            self.plan.set_worker(RADAR_ZONE, c.get('cx', 0.0), c.get('cz', 0.0))
        elif self.demo:
            self.plan.set_worker(RADAR_ZONE, c.get('cx', 0.0), c.get('cz', 0.0))
        else:
            # 추적을 놓쳤으면 위치를 그리지 않는다 — 없는 것을 지어내지 않는다.
            self.plan.worker = None
        self.plan.update()

    # ══════════════════════════════════════════════════════════════════
    # 경보
    # ══════════════════════════════════════════════════════════════════
    @staticmethod
    def _sop_type(ev):
        """복합 경보에서 조치의 기준이 될 유형. console_ui 와 같은 우선순위."""
        types = list(dict.fromkeys(ev.get('types') or [ev.get('type')]))
        priority = ('electric_shock_risk_confirmed', 'pinching',
                    'pinching_suspected', 'leakage_current',
                    'electric_shock_risk', 'fall_detected',
                    'overcurrent', 'voltage_drop')
        return next((t for t in priority if t in types), ev.get('type'))

    @staticmethod
    def _steps_for(sop_type):
        """(항목 목록, 미등록 여부). 조치 문장의 정본은 INSTANT_ACTION 이다."""
        key = SOP_ALIAS.get(sop_type, sop_type)
        block = INSTANT_ACTION.get(key)
        if not block:
            return [], True
        return [(cat, text) for cat, lines in block for text in lines], False

    def on_event(self, ev, updating=False):
        self.alert = dict(ev)
        if not updating:
            self.alert_t0 = time.time()      # ★ 노트북 시각. 젯슨 시계 안 씀.
            self.today += 1
        self.alarm = ST_UNACK
        types = list(dict.fromkeys(ev.get('types') or [ev.get('type')]))
        name = ' + '.join(EVENT_KO.get(t, t) for t in types if t) or '이상'
        sev = ev.get('sev') or event_sev(ev.get('type'))
        col = sev_color(sev)
        ts = time.strftime('%H:%M:%S', time.localtime(self.alert_t0))
        steps, missing = self._steps_for(self._sop_type(ev))
        self.guide.set_alarm(name, ts, col, steps, missing)
        self._refresh_status_rows()
        self._sync_buttons()

    def do_ack(self):
        """상황 확인 완료 = 소리·점멸만 끈다. 경보는 그대로 남는다 (ISA-18.2)."""
        if self.alarm == ST_UNACK:
            self.alarm = ST_ACK
            self._sync_buttons()

    def do_resolve(self):
        """상황 종료 = 사람이 현장을 확인했다는 선언. 자동 해제는 없다."""
        if not core.confirm(self, '상황 종료',
                            '현장 상황이 해소된 것을 직접 확인하셨습니까?\n\n'
                            '전원은 자동으로 복구되지 않습니다 (LOTO).\n'
                            '재투입은 [LOTO 해제] 버튼으로 별도 진행하십시오.',
                            yes='해소 확인', no='취소', danger=True):
            return
        if self.link:
            self.link.send_cmd(CMD_RESOLVE)
        self.clear_alarm()

    def clear_alarm(self):
        if self.alarm == ST_NORMAL:
            return
        self.alarm = ST_NORMAL
        self.alert = None
        self.quiet_since = time.time()
        if self.preview:
            # 미리보기에는 뒤따르는 패킷이 없다. 평면도만 붉은 채로 남아
            # '종료했는데 여전히 경보' 로 보이는 것을 막는다.
            #   ⚠ 차단 상태는 그대로 둔다 — 종료 후 재투입 화면을 이어서 본다.
            self.pkt = preview_packet(active=False)
            self._update_plan(self.pkt)
        self._sync_buttons()

    def on_primary(self):
        if self.alarm == ST_UNACK:
            self.do_ack()
        elif self.alarm == ST_ACK:
            self.do_resolve()

    def do_restore(self):
        """전원 재투입 — ① 관리자 승인 ② 체크리스트 ③ 젯슨에 요청.

        ⚠ 순서가 곧 책임 순서다. 승인을 체크리스트 뒤에 두면 '체크는 작업자가
          하고 승인만 관리자가 눌렀다' 가 되어, 확인 주체와 승인 주체가
          갈라진다. 승인을 먼저 받고 그 사람이 체크리스트를 확인한다.
        ⚠ RestorePopup(체크 3개)은 관제 화면과 같은 객체를 쓴다 — 절차가
          두 화면에서 갈라질 수 없다.
        """
        if self._auth_locked():
            return
        snap = ((self.pkt.get('breaker') or {}).get('state')) or {}
        zs = [z for z, s in snap.items() if s != 'ON']
        if not zs:
            return
        admin = self.auth.ask()
        if admin is None:
            if self.auth.locked_out:
                # 연속 실패 — 버튼을 잠시 잠근다. 무한 재시도를 막는 것이지
                #   비밀번호를 지키는 장치는 아니다(파일 상단 주석 참조).
                self._auth_lock_until = time.time() + AUTH_LOCK_SEC
                self._sync_buttons()
            return
        if not self.restore.ask(zs):
            return
        if self.link:
            self.link.send_cmd(CMD_RESTORE, zones=zs)
        self._approved_by = (admin, time.strftime('%H:%M'))
        self._sync_buttons()

    def _auth_locked(self):
        return time.time() < self._auth_lock_until

    # ══════════════════════════════════════════════════════════════════
    # 표시 갱신
    # ══════════════════════════════════════════════════════════════════
    def _breaker_line(self, zone, et):
        """차단이 '실제로' 됐는지를 차단기 상태로 확인해서 쓴다.

        ⚠ console_ui.ConsoleV2._set_auto_action 과 같은 분기다. 항상
          '차단 완료' 라고 쓰면 차단기가 미연결이거나 실패한 경우에도 완료라고
          말하게 된다. 관제 화면과 이 화면이 같은 사건을 다르게 말하면 안 된다.
        """
        breaker = (self.pkt.get('breaker') or {})
        bs = breaker.get('state') or {}
        reasons = breaker.get('reason') or {}
        src = breaker.get('src')
        off = bs.get(zone, 'ON') != 'ON'
        reason = reasons.get(zone)
        if et is None:
            if off:
                why = EVENT_KO.get(reason, reason or '사유 미기록')
                return f'전원 차단 상태 : 차단 유지 · {why}', K_RED, '!'
            return '전원 차단 상태 : 정상 투입', K_GREEN, '●'
        if et not in AUTO_TRIP_EVENTS:
            if off:
                why = EVENT_KO.get(reason, reason or '사유 미확인')
                return (f'전원 차단 상태 : 기존 차단 유지 · {why}',
                        K_GREEN, '✓')
            return ('전원 차단 상태 : 자동 차단 대상 아님 · 경보 전파 완료',
                    K_GREEN, '✓')
        if off and reason != et:
            why = EVENT_KO.get(reason, reason or '사유 미확인')
            if src == 'modbus':
                return f'전원 차단 상태 : 기존 차단 유지 · {why}', K_GREEN, '✓'
            return (f'전원 차단 상태 : 기존 차단 상태 · {why} (실측 미확인)',
                    K_AMBER, '!')
        if off and src == 'modbus':
            return '전원 차단 상태 : 차단 완료', K_GREEN, '✓'
        if off:
            return ('전원 차단 상태 : 차단 신호 발신 (실측 미확인 — 현장 확인 필요)',
                    K_AMBER, '!')
        return ('전원 차단 상태 : 차단이 확인되지 않음 — [LOTO 상태 확인]',
                K_RED, '!')

    def _refresh_status_rows(self):
        """우측 패널의 '현재 상태' 두 줄."""
        if self.alarm != ST_NORMAL and self.alert:
            ev = self.alert
            z = ev.get('zone') or RADAR_ZONE
            sev = ev.get('sev') or event_sev(ev.get('type'))
            zcol = K_RED if sev == 'critical' else K_AMBER
            ztext = (f'Zone {z} ({ZONE_KO.get(z, "")}) '
                     f'{SEV_KO.get(sev, "")} 상황 감지')
            ptext, pcol, pmark = self._breaker_line(z, ev.get('type'))
            self.guide.set_status_rows(ztext, zcol, ptext, pcol, '!', pmark)
            return
        z = RADAR_ZONE
        ptext, pcol, pmark = self._breaker_line(z, None)
        ph = self.pkt.get('phase')
        if not self._live_ok():
            if self.pkt and ph is not None and ph != PH_LIVE:
                ztext = (f'Zone {z} ({ZONE_KO.get(z, "")}) '
                         f'{PHASE_KO.get(ph, ph)} — 감시 전')
            else:
                ztext = f'Zone {z} ({ZONE_KO.get(z, "")}) 감시 중단 — 데이터 없음'
            self.guide.set_status_rows(ztext, K_AMBER, ptext, pcol, '!', pmark)
            return
        if self._pre:
            ztext = (f'Zone {self._pre["zone"]} '
                     f'({ZONE_KO.get(self._pre["zone"], "")}) '
                     f'{self._pre["text"]}')
            self.guide.set_status_rows(ztext, K_AMBER, ptext, pcol, '!', pmark)
            return
        self.guide.set_status_rows(
            f'Zone {z} ({ZONE_KO.get(z, "")}) 감시 중 · 이상 없음',
            K_GREEN, ptext, pcol, '●', pmark)

    def _live_ok(self):
        """'감시 중' 이라고 말해도 되는가.

        ⚠ 링크가 없거나 LIVE 가 아니면 초록으로 칠하지 않는다. 감시하지 않는
          상태를 정상으로 표시하는 것이 이 앱이 할 수 있는 가장 위험한 거짓말이다.
        """
        if self.demo or self.preview:
            return True
        if not self.link:
            return False
        age = self.link.age()
        if age is None or age > LINK_TIMEOUT:
            return False
        return self.pkt.get('phase') == PH_LIVE

    def _sync_buttons(self):
        on_alarm = self.alarm != ST_NORMAL
        if self.alarm == ST_UNACK:
            self.b_ack.setEnabled(True)
            self.b_ack.set_action(IC_OK, '상황 확인 완료',
                                  '위험 구역 확인 및 대피 완료')
        elif self.alarm == ST_ACK:
            self.b_ack.setEnabled(True)
            self.b_ack.set_action(IC_OK, '상황 종료 처리',
                                  '현장 확인 후 경보 해제')
        else:
            self.b_ack.setEnabled(False)
            self.b_ack.set_action(IC_OK, '상황 확인 완료',
                                  '진행 중인 경보 없음')
        self.b_mute.set_action(IC_BELL,
                               '알림 켜기' if self.muted else '알림 음소거',
                               '경보음 꺼짐' if self.muted else '')
        snap = ((self.pkt.get('breaker') or {}).get('state')) or {}
        tripped = [z for z, s in snap.items() if s != 'ON']
        # ⚠ 경보가 종료되기 전에는 재투입을 열지 않는다. 시안의 금지 문구
        #   ('안전 절차 완료 전까지 LOTO 해제 및 전원 재투입을 금지합니다')를
        #   글자만이 아니라 버튼 상태로도 강제한다.
        locked = self._auth_locked()
        # ⚠ 미리보기에서만 경보 중에도 열어 둔다. 실운용에서는 시안의 금지 문구
        #   ('안전 절차 완료 전까지 …재투입을 금지합니다')를 버튼 상태로 강제한다.
        self.b_restore.setEnabled(
            bool(tripped) and (self.preview or not on_alarm) and not locked)
        if locked:
            sub = f'승인 실패 — {int(self._auth_lock_until - time.time()) + 1}초 후 재시도'
        elif on_alarm and self.preview:
            sub = '관리자 승인 후 실행 (미리보기)'
        elif on_alarm:
            sub = '경보 종료 후 실행 가능'
        elif tripped:
            sub = f'차단 {len(tripped)}개 · 관리자 승인 필요'
        elif self._approved_by:
            sub = (f'재투입 요청 완료 · 승인 {self._approved_by[0]} '
                   f'{self._approved_by[1]}')
        else:
            sub = '차단된 설비 회로 없음'
        self.b_restore.set_action(None, None, sub)

    # ══════════════════════════════════════════════════════════════════
    # 0.5초 UI 갱신 (시계 · 점멸 · 경과시간 · stale)
    # ══════════════════════════════════════════════════════════════════
    def tick_ui(self):
        self.blink = not self.blink
        now = time.localtime()
        self.date_lb.setText(time.strftime('%Y.%m.%d', now)
                             + f' ({WEEKDAY_KO[now.tm_wday]})   '
                             + time.strftime('%H:%M:%S', now))
        self.who_lb.setText(f'작업자 : {self.operator}')
        self._refresh_status_rows()
        self._sync_buttons()

        if self.alarm != ST_NORMAL and self.alert:
            self._tick_alarm()
            return

        self.plan.set_blink(False)
        if not self._live_ok():
            ph = self.pkt.get('phase')
            if self.pkt and ph is not None and ph != PH_LIVE:
                title, sub = '감시 대기', f'{PHASE_KO.get(ph, ph)} · 관제 화면에서 준비'
                note = ('정상 기준이 학습되기 전까지는 이상을 판별할 수 없습니다. '
                        '관제 화면 [현장 준비] 에서 빈 방 스캔을 진행하십시오.')
            else:
                title, sub = '감시 중단', '젯슨에서 데이터를 받지 못하고 있습니다'
                note = ('데이터를 받지 못하는 동안 이 화면은 현장 상태를 '
                        '보장하지 않습니다. 젯슨과 네트워크를 확인하십시오.')
            self._set_status_title('감시 중단' if title == '감시 중단'
                                   else '감시 대기', AMBER, '!')
            self.guide.set_normal(title, sub, AMBER)
            self.guide.set_note('warn', note)
            return

        if self._pre:
            z = self._pre['zone']
            self._set_status_title('사전 경보 확인', AMBER, '!')
            self.guide.set_normal(
                '사전 경보', f"Zone {z} · {self._pre['text']}", AMBER,
                lines=('해당 구역에서 움직임이 감지되지 않고 있습니다.',
                       '움직이면 자동으로 취소됩니다 — 경보가 아닙니다.',
                       '움직일 수 없는 상태라면 즉시 현장을 확인하십시오.'))
            self.guide.set_note('warn',
                                '이 단계에서는 전원을 차단하지 않습니다. '
                                '경보로 승격되면 지시가 이 자리에 표시됩니다.')
            return

        q = int(time.time() - self.quiet_since)
        up = int(time.time() - self.boot_t)
        self._set_status_title('정상 감시 중', GREEN, '●')
        self.guide.set_normal(
            '정상 감시 중', f'{q // 3600}시간 {q % 3600 // 60}분 무경보', GREEN,
            lines=('경보가 발생하면 이 자리에 즉시 수행 지시가 표시됩니다.',
                   f'오늘 경보 {self.today}건 · '
                   f'가동 {up // 3600:02d}:{up % 3600 // 60:02d}'))
        self.guide.set_note('ok',
                            f'차단 범위는 {BREAKER_SCOPE} 1개입니다. '
                            f'전원 재투입은 경보 종료 후에만 가능합니다.')

    def _tick_alarm(self):
        ev = self.alert or {}
        sev = ev.get('sev') or event_sev(ev.get('type'))
        col = sev_color(sev)
        unack = (self.alarm == ST_UNACK)
        on = (not unack) or (sev != 'critical') or self.blink
        self.plan.set_blink(self.blink)
        el = int(time.time() - self.alert_t0)
        types = list(dict.fromkeys(ev.get('types') or [ev.get('type')]))
        name = ' + '.join(EVENT_KO.get(t, t) for t in types if t) or '이상'
        z = ev.get('zone') or RADAR_ZONE
        self._set_status_title(
            f'{name} 감지 · Zone {z} {ZONE_KO.get(z, "")}',
            col if on else DIM, '!')
        ts = time.strftime('%H:%M:%S', time.localtime(self.alert_t0))
        self.guide.h_sub.setText(
            f'발생 시간 : {ts}    경과 {el // 60:02d}:{el % 60:02d}    '
            f"{'미확인' if unack else '확인됨'}")
        self.guide.set_note(
            'danger',
            f'안전 절차 완료 전까지 LOTO 해제 및 전원 재투입을 금지합니다. '
            f'(차단 범위: {BREAKER_SCOPE})')
        # ⚠ 주의(warning)도 소리는 낸다. 정지형 이상은 감전·협착일 수 있어
        #   조용히 넘어가면 안 된다. 다만 확정 사고보다 드물게 울려 '가서 확인'
        #   과 '지금 뛰어가' 를 귀로도 구분하게 한다.
        if unack and self.blink and not self.muted:
            self._beep_n += 1
            if sev == 'critical' or self._beep_n % 4 == 0:
                QtWidgets.QApplication.beep()

    def _set_status_title(self, text, color, icon):
        self.status_lb.setText(f'{icon}  {text}')
        self.status_lb.setStyleSheet(
            f'color:{color};border:none;background:transparent;')

    # ══════════════════════════════════════════════════════════════════
    # 잡동사니
    # ══════════════════════════════════════════════════════════════════
    def toggle_mute(self):
        self.muted = not self.muted
        self._sync_buttons()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def change_operator(self):
        name, ok = QtWidgets.QInputDialog.getText(
            self, '작업자 이름', '이 키오스크의 담당 작업자 이름을 입력하세요',
            text='' if self.operator == '미지정' else self.operator)
        if ok:
            self.operator = name.strip() or '미지정'

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_F11:
            self.toggle_fullscreen()
            return
        if e.key() == QtCore.Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
            return
        super().keyPressEvent(e)

    def closeEvent(self, e):
        if self.link:
            self.link.stop()
        e.accept()


# ══════════════════════════════════════════════════════════════════════
# 7. 진입점
# ══════════════════════════════════════════════════════════════════════
def build_app(argv=None):
    """QApplication + 창을 만들어 돌려준다. (헤드리스 렌더 검증에서도 쓴다)"""
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', nargs='?', const='127.0.0.1', default=None,
                    metavar='젯슨IP', help='젯슨 실데이터 수신 (기본 127.0.0.1)')
    ap.add_argument('--host', default=None, help='--live 와 동일 (하위호환)')
    ap.add_argument('--operator', default='미지정', help='이 키오스크 담당 작업자')
    ap.add_argument('--fullscreen', action='store_true', help='키오스크 전체 화면')
    ap.add_argument('--preview', action='store_true',
                    help='디자인 미리보기 — 합성 경보 상태로 띄운다(실데이터 아님)')
    a, _ = ap.parse_known_args(argv)
    host = a.host or a.live
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    resolve_font()
    app.setFont(kf(U_LABEL))
    apply_dark_palette(app)
    link = None
    if host:
        link = RadarLink(host)
        print(f'젯슨 {host} 구독 시작 (HELLO 발신 중)…')
    if a.preview and host:
        print('⚠ --preview 는 젯슨 실데이터와 함께 쓸 수 없습니다 — --live 를 무시합니다.',
              file=sys.stderr)
        link, host = None, None
    w = UserConsole(link, demo=(host is None and not a.preview),
                    operator=a.operator, preview=a.preview)
    fit_to_screen(app, w)
    if a.fullscreen:
        w.showFullScreen()
    return app, w, link


def fit_to_screen(app, win):
    """부스 모니터가 설계 기준(1280×820)보다 작아도 뜨게 한다.

    ⚠ 최소 크기를 그대로 두면 작은 패널에서는 창이 화면 밖으로 나가 하단
      액션 버튼이 잘린다. 경보 화면에서 '상황 확인' 버튼이 안 보이는 것은
      기능이 없는 것과 같다. → 최소 크기를 화면에 맞춰 내리고, 좁아졌다는
      사실은 콘솔에 남긴다(조용히 줄이지 않는다).
    """
    screen = app.primaryScreen()
    if screen is None:
        return
    g = screen.availableGeometry()
    if g.width() < 1280 or g.height() < 820:
        print(f'⚠ 화면 {g.width()}×{g.height()} — 설계 기준 1280×820 보다 작습니다. '
              f'요소가 좁게 보일 수 있습니다.', file=sys.stderr)
        win.setMinimumSize(max(int(g.width() * 0.9), 720),
                           max(int(g.height() * 0.9), 480))
    win.resize(min(1600, g.width()), min(1000, g.height()))


def main():
    app, w, link = build_app()
    if link:
        link.start()
    if not w.isFullScreen():
        w.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
