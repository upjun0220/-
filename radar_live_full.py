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

import json, os, time, threading, textwrap, warnings, sys
from datetime import datetime
from collections import deque, Counter

import numpy as np
import matplotlib
# ── [7/4] Headless 모드 ──────────────────────────────────────
#   `python3 radar_live_full.py --headless` 또는 환경변수 RADAR_HEADLESS=1
#   -> Matplotlib GUI 창/실시간 렌더 루프를 켜지 않음(젯슨에서 Ollama/RAG와
#      CPU·메모리 경쟁하는 '연속 draw'가 실제 비용 -> 이를 제거).
#   -> 탐지·판정·로그 저장·데이터셋 저장은 그대로 수행.
#   Agg 백엔드는 디스플레이(X) 없이도 동작하므로 헤드리스 젯슨에서 안전.
HEADLESS = ('--headless' in sys.argv) or (os.environ.get('RADAR_HEADLESS') == '1')
matplotlib.use('Agg' if HEADLESS else 'TkAgg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.widgets import Button
from mpl_toolkits.mplot3d import Axes3D  # noqa
matplotlib.rcParams['font.family'] = 'DejaVu Sans'

# ── [7/4] 한글 SOP 표시용 폰트 ────────────────────────────────
#   DejaVu Sans는 한글 미지원 -> 하드코딩 SOP/상세 SOP 한글이 □로 깨짐.
#   설치된 한글 폰트를 찾아 지정. 없으면 경고(젯슨: sudo apt install fonts-nanum).
def _set_korean_font():
    try:
        import matplotlib.font_manager as fm
        avail = {f.name for f in fm.fontManager.ttflist}
        for _name in ('NanumGothic', 'NanumBarunGothic', 'Malgun Gothic', 'AppleGothic',
                      'Noto Sans CJK KR', 'Noto Sans KR', 'UnDotum', 'Baekmuk Gulim'):
            if _name in avail:
                matplotlib.rcParams['font.family'] = _name
                matplotlib.rcParams['axes.unicode_minus'] = False
                return _name
    except Exception:
        pass
    return None
KOREAN_FONT = _set_korean_font() if not HEADLESS else None
if not HEADLESS and KOREAN_FONT is None:
    print('[FONT] ⚠ 한글 폰트 없음 -> SOP 한글이 깨질 수 있음.  '
          '젯슨: sudo apt install fonts-nanum && (캐시) rm -rf ~/.cache/matplotlib')

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

# [7/6] RF 낙상/동작 분류기 (팔흔들기 오탐 억제). 파일 없으면 규칙만 사용(안전).
RF_MODEL_PATH = os.path.expanduser('~/fall_classifier.joblib')
try:
    import joblib
    _rf_ck    = joblib.load(RF_MODEL_PATH)
    RF_MODEL  = _rf_ck['model']
    RF_FEATURES = _rf_ck['features']
    RF_OK     = True
    print(f'[RF] fall_classifier 로드 OK ({len(RF_FEATURES)} feats) -> wave 오탐 억제 활성')
except Exception as _rfe:
    RF_MODEL = None; RF_OK = False
    print(f'[RF] 모델 없음/로드실패 -> 규칙만 사용: {_rfe}')

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
STAT_N_MIN    = 3      # [7/3 9차] 4->3: 누운 사람은 반사가 약해 n=3 프레임 빈발 (이슈 2)
STAT_DS_MIN   = 0.04   # [7/3 9차] 0.10->0.04: 누운 사람 호흡 미세동요까지 포함 (이슈 2).
                       # '절대 0'인 완전 정적 반사는 여전히 차단 + 스캔 클러터 맵이 보조
STAT_DS_MAX   = 0.35   # 저동작: 프레임 dop_std < 이 값 (정지·미세움직임. 보행 0.43+)
STAT_POS_R    = 1.5    # [7/6] 1.0->1.5: 멀리 선 사람은 희소포인트(n 3~6)라 centroid가
                       # 프레임당 >1m 튐(실측 로그) -> 앵커 벗어나 미스 누적 -> 타이머 리셋.
                       # 빈방 노이즈는 방 전체(>2m)를 점프하므로 1.5m로도 여전히 차단됨.
STAT_HIT_RATIO = 0.65  # 타이머 진행 중 조건충족 프레임 비율 하한 (노이즈 ~50%는 못 채움)
STAT_HIT_TIMEOUT = 5.0 # [7/3 9차] 3->5초: 누운 사람의 드문 히트 허용 (이슈 2)
# [7/3 4차] 진입 게이트: 정지 타이머는 최근 이 시간 안에 '이동 프레임'(n>=14 또는
# ds>=0.40 = 걸어 들어오는 사람)이 있었을 때만 시작할 수 있음.
# 근거: 사람의 정지형 사고는 반드시 '이동->정지' 시퀀스. 고스트/멀티패스 반사는
# 이동 이력이 없으므로 타이머 자체를 못 염 (빈 방 오탐 원천 차단).
STAT_ENTRY_SEC = 8.0
# [7/3 5차] 클러터 자동 스캔: baseline 시작 직후 SCAN_SEC 동안 '빈 방'을 스캔해
# 반복 관측되는 정적 반사 위치(케이블·가전 고스트 등)를 클러터 스팟으로 자동 학습.
# -> 장소/케이블 위치가 바뀌어도 RESET 한 번으로 자동 적응 (하드코딩 제거).
# 학습 결과는 baseline 파일에 함께 저장돼 다음 실행에서 재사용됨.
SCAN_SEC        = 12.0   # 빈 방 스캔 시간 (이 동안 전원 시야 밖!)
SCAN_GRID       = 0.30   # 위치 군집 격자 (m)
SCAN_MIN_HITS   = 6      # 이 횟수 이상 반복 관측된 격자만 클러터 인정
SCAN_MAX_SPOTS  = 8      # 최대 스팟 수 (과도 마스킹 방지)
CLUTTER_SPOT_R  = 0.35   # [7/3 9차] 0.30->0.35: 케이블 흔들림의 이탈 반경 커버 (이슈 1,4)
CLUTTER_SPOTS   = []     # 수동 시드(비상용). 스캔 완료 시 학습 결과가 여기에 더해짐.
# 2단계 경보 (산업 man-down 장비 표준 방식: pre-alert -> escalation).
# 설비 앞 정당한 정지 작업의 오경보 방지: 1차는 경고만(움직이면 자동 취소),
# 계속 무동작이면 2차 critical latch. 상용 장비 무동작 타이머는 1분~수시간 설정형 --
# 아래 값은 데모용 축소값이며 실배치 시 상향 필요.
STAT_PRE_SEC  = 15.0   # 1차: Zone 내 정지 이만큼 지속 -> PRE-ALERT 로그(경고, 비latch)
STAT_CRIT_SEC = 30.0   # 2차: 계속 무동작 -> stationary 경보(critical, latch)
MAINT_MODE    = False  # True = 계획 정비 중(LOTO/작업허가) -> 정지형 경보 억제
STAT_MISS_TOL = 10     # [7/6] 5->10: 희소포인트 순간 튐(~1s)을 용인해 정당한 20s dwell이
                       # 리셋되지 않게. 실제 이탈은 STAT_HIT_TIMEOUT(5s presence-lost)가 정리.
CONN_STR      = 'postgresql://postgres:password@localhost:5432/radar_guard'

# ── (옵션) 경량 LLM 요약 — 수행계획서 '생성형 AI 조치 가이드' 복원용 ──
# llama3:8b(Q4 4.9GB)는 Orin Nano 8GB 공유메모리에서 OOM 프리징 유발(실측).
# [7/4 팀 결정] llama3.2:3b(Q4 2.0GB) -> gemma2:2b(Q4 1.6GB)로 전환.
#   근거: 비전/레이더 인지 모듈 + 자율주행 노드와 공유메모리 경쟁 시 2B가 OOM 여유 큼,
#   초당 토큰(TPS) 빨라 PRE-ALERT 즉시 보고에 유리. RAG 요약/정형 안전매뉴얼 검색엔
#   2B instruct로 충분(단일 목적). 심층 추론용은 클라우드/관제 후처리로 분리.
# 사용법: 젯슨에서 `ollama pull gemma2:2b` + 단독 테스트 통과 후 True로.
# False면 기존과 100% 동일(검색 전용) -> 시연 안전 기본값.
USE_LLM_SUMMARY = False
LLM_MODEL       = 'gemma2:2b'
# [7/4] 상세 SOP 팝업: 경보 시 Gemma가 상세 초동조치를 생성해 별도 창에 표시.
#   langchain/pgvector 없이 Ollama REST(/api/generate)를 urllib로 직접 호출 -> 의존성 최소.
#   메모리: 생성 시 Gemma ~1.6GB 로드(실측 스택 4.4GB + 1.6 = 6.0GB, 여유 1.5GB) 후 즉시 언로드.
DETAILED_SOP_POPUP = True
OLLAMA_URL         = 'http://localhost:11434/api/generate'
# [7/4] SOP 표시 언어: 'ko'(한글, 폰트 필요) / 'en'(영어, 폰트 무관 - 폴백).
#   한글이 □로 깨지면 젯슨에 `sudo apt install fonts-nanum` 하거나 여기를 'en'으로.
SOP_LANG           = 'en'

# ── Baseline 모델 저장/재사용 (7/3) ──
# 학습 완료 시 자동 저장. 다음 실행에서 파일이 있으면 웜업/학습 생략하고 바로 LIVE.
# ⚠️ 레이더 위치·환경이 바뀌면 저장된 baseline이 무효 -> RESET 버튼으로 재수집(자동 덮어씀).
BASELINE_PATH = '/home/project/baseline_model.pt'
LOAD_BASELINE = True   # False = 항상 새로 웜업/학습

N_WARMUP      = 150      # real frames for normal baseline (~15 sec at 10 fps)
CEILING_H     = 2.30     # 천장(센서)~바닥 실측 거리(m). height = CEILING_H - y(range)
FEATURE_DIM   = 9        # [7/4 9차원] cx,cy,cz,mean_dop,dop_std,int_mean,n_pts,z_vel,z_accel
                         #   z_vel = 수직(높이) 속도(천장기준: 높이축=y), z_accel = 그 가속도(EMA)
                         #   ⚠ 8차원 구 baseline_model.pt는 로드 불가 -> RESET 후 재수집·재학습 필요
SEQ_LEN       = 5        # LSTM-AE 입력 시퀀스 길이
CLF_WIN       = 20       # 규칙 classify 집계 창(~2s). 실측 문턱이 20프레임 기준이라 별도 유지
HISTORY_LEN   = 120
CONFIRM_FRAMES = 3       # 이상이 이만큼 연속돼야 경보 latch (순간 움직임 디바운스)
CONFIRM_EVENTS = 3       # non-fall 판정이 이만큼 '연속 동일'해야 latch (전이 오탐 억제, ~수 초)
FALL_CONFIRM   = 2       # [7/3 6차] 낙상도 2연속 확정 (경계선 오탐 차단, 지연 ~0.3s)
# [7/6] z_accel 하한 게이트 — 라이브 검증 결과 '비활성'(0).
#   근거: 수집데이터는 낙상 zacc 182~1389로 팔흔들기(15~155)와 분리됐으나, 라이브는
#   포인트 희소로 스케일이 달라 낙상 zacc도 15~155로 팔흔들기와 '겹침'(젯슨 로그 확인).
#   -> zacc로는 라이브에서 둘을 못 가름. 팔흔들기 오탐은 라벨 데이터 수집 후 재설계 필요.
#   (0 = 게이트 없음. 팔흔들기 판별자 확정되면 값 복원)
FALL_ZACC_MIN  = 0
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
INSTANT_ACTION_KO = {
    'fall_detected': (
        "[즉시 조치]  낙상 감지\n"
        "  1. 의식·호흡 확인\n"
        "  2. 환자를 함부로 움직이지 말 것 (척추 손상 위험)\n"
        "  3. 주변 위험요소 차단·현장 확보\n"
        "  4. 119 신고 후 구조 도착까지 관찰\n"
    ),
    'stationary_anomaly': (
        "[즉시 조치]  정지형 이상 (감전/협착 여부 확인)\n"
        "  1. 접근 전 전원 차단 확인 (LOTO)\n"
        "     -- 감전 의심 시: 맨손 접촉 금지\n"
        "  2. 협착 시: 무리하게 잡아당기지 말 것\n"
        "  3. 119 신고\n"
        "  4. 현장에서 유형 확인 후 SOP 따를 것\n"
    ),
    'vibration_anomaly': (
        "[점검]  진동 / 경미한 이상\n"
        "  - 해당 구역 육안 점검\n"
    ),
}
INSTANT_ACTION_EN = {
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
    d = INSTANT_ACTION_KO if SOP_LANG == 'ko' else INSTANT_ACTION_EN
    fb = f"[경보] {EVENT_LABELS.get(ev_type, ev_type)}\n" if SOP_LANG == 'ko' \
         else f"[ALERT] {EVENT_LABELS.get(ev_type, ev_type)}\n"
    return d.get(ev_type, fb)

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


def extract_features(frame_pts, prev_c=None, prev_zvel=0.0, dt=None, ema_zacc=0.0,
                     ema_a=0.5):
    """[7/4 9차원] 천장 기준 좌표계 인지: 수직축 = y(range), height = CEILING_H - y.
    바닥평면(수평) = (x, z). 이전엔 z_vel을 '바닥 z 변화'로 잡아 수직이 아니라 수평을
    쟀고 classify에서 안 썼음 -> 물리적으로 맞게 '수직(높이) 속도'로 재정의.
      idx7 z_vel   : 수직속도 = prev_cy - cy  (+상승 / -하강; 높이=CEIL-y 이므로 부호반전)
      idx8 z_accel : 수직가속도 = (z_vel - prev_zvel)/dt, EMA 스무딩(노이즈 억제, 지연 최소).
                     dt 없거나 0, 또는 첫 프레임이면 안전하게 0 처리.
    """
    if not frame_pts:
        return np.zeros(FEATURE_DIM, dtype=np.float32)
    pts = np.array([[p['x'], p['y'], p['z'], p['doppler'], p['intensity']]
                    for p in frame_pts], dtype=np.float32)
    c        = pts[:, :3].mean(axis=0)
    mean_dop = float(pts[:, 3].mean())
    dop_std  = float(pts[:, 3].std() + 1e-8)
    int_mean = float(pts[:, 4].mean())
    n_pts    = float(len(pts))
    # 수직(높이) 속도: 높이 상승 = cy 감소이므로 prev_cy - cy
    z_vel    = float(prev_c[1] - c[1]) if prev_c is not None else 0.0
    # 수직 가속도(EMA). dt/이전값 없으면 raw=0 -> 안전
    if dt is not None and dt > 1e-6 and prev_c is not None:
        raw_acc = (z_vel - float(prev_zvel)) / dt
    else:
        raw_acc = 0.0
    z_accel  = float(ema_a * raw_acc + (1.0 - ema_a) * float(ema_zacc))
    return np.array([c[0], c[1], c[2], mean_dop, dop_std, int_mean, n_pts, z_vel, z_accel],
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


def build_clutter_map(scan_pts):
    """빈 방 스캔 좌표들을 격자 군집화 -> 반복 관측 격자만 클러터 스팟으로 반환."""
    cnt = Counter((round(x / SCAN_GRID), round(z / SCAN_GRID)) for x, z in scan_pts)
    spots = [(gx * SCAN_GRID, gz * SCAN_GRID, CLUTTER_SPOT_R)
             for (gx, gz), k in cnt.most_common(SCAN_MAX_SPOTS) if k >= SCAN_MIN_HITS]
    return spots


def _rf_features(win):
    """classify의 win(9차원 벡터 리스트) -> train_fall_classifier.extract()와 동일 19피처.
    (샌드박스 검증: 수집 프레임 기반 추출과 0/70 불일치 = 라이브·오프라인 완전 일치)"""
    if len(win) < 4:
        return None
    cx = np.array([float(f[0]) for f in win]); cy = np.array([float(f[1]) for f in win])
    cz = np.array([float(f[2]) for f in win]); ds = np.array([float(f[4]) for f in win])
    n  = np.array([float(f[6]) for f in win]); dop = np.array([float(f[3]) for f in win])
    h  = CEILING_H - cy
    half = max(1, len(ds) // 2)
    ds_first = ds[:half].mean(); ds_last = ds[half:].mean()
    zvel = np.zeros(len(win))
    for i in range(1, len(win)):
        zvel[i] = cy[i-1] - cy[i]
    zvv = zvel[np.abs(zvel) > 0.05]
    zsc = int(np.sum(np.diff(np.sign(zvv)) != 0)) if len(zvv) > 2 else 0
    def _pk(a, t=0.6):
        p = 0
        for i in range(1, len(a) - 1):
            if a[i] >= t and a[i] >= a[i-1] and a[i] > a[i+1]: p += 1
        return p
    pk = int(np.argmax(ds))
    return [
        float(ds.max()), float(ds.mean()), float(ds_first), float(ds_last),
        float(ds.max() / max(0.15, ds_first)), int((ds >= 0.8).sum()),
        float(ds_last / (ds.max() + 1e-6)), _pk(ds), zsc,
        float(cy.max() - cy.min()), float(h.min()), float(h[-3:].mean()), float(h[:3].mean()),
        float(np.hypot(cx.max()-cx.min(), cz.max()-cz.min())),
        float(np.hypot(cx[pk:].mean()-cx[:max(1,pk)].mean(), cz[pk:].mean()-cz[:max(1,pk)].mean())),
        float(n.mean()), float(np.percentile(n, 75)), float(n.max()),
        float(np.abs(dop).mean()),
    ]


def _rf_veto(win):
    """RF가 이 창을 '낙상 아님'(wave 등)으로 판단하면 True -> 규칙 낙상을 억제.
    RF 실패/모델없음 시 False (규칙 판정 유지 = 낙상 안 놓치는 안전측)."""
    if not RF_OK:
        return False
    try:
        feats = _rf_features(win)
        if feats is None:
            return False
        return RF_MODEL.predict([feats])[0] != 'fall'
    except Exception:
        return False


def classify(feat_win, score, thr):
    """천장 설치 + 실측 데이터(events_collect.jsonl, 50샘플) 기반 규칙 분류.

    좌표계: y = 센서 아래로의 거리(range). height = CEILING_H - y.
    feat 벡터 = [cx, cy(=y), cz, mean_dop, dop_std, int_mean, n_pts, z_vel, z_accel] (9차원).
      cy=y=수직(높이)축, (cx,cz)=바닥평면(수평), z_vel/z_accel=수직 속도/가속도.

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

    # [7/4 10차] 수평 성분 복원 — 천장 기준: 바닥평면 = (cx, cz).
    #   낙상은 '무너지며' 바닥평면으로 traverse/확산 -> centroid 수평 이동폭이 큼.
    #   제자리 빠른앉기는 수직만 내려가고 수평 고정(실측 horiz_range: 낙상 0.75~1.26
    #   vs 빠른앉기 0.35~0.79) -> 도플러가 라이브에서 튀어도 이 축으로 앉기 배제.
    cx_vals     = [float(f[0]) for f in win]
    cz_vals     = [float(f[2]) for f in win]
    horiz_range = float(np.hypot(max(cx_vals) - min(cx_vals),
                                 max(cz_vals) - min(cz_vals)))   # 바닥평면 이동폭
    # 수직 가속도(z_accel, idx8) 피크 — 보조 신뢰도용(정지·보행 대비 사건성 가산).
    #   ⚠ 단독 낙상 판정 금지: 실측상 낙상/빠른앉기 모두 수직하강이라 둘을 못 가름.
    #   보행(hacc≈0.19)과 사건(≈0.67)만 가름 -> 게이트 아닌 confidence 가산에만 사용.
    zacc_amp    = max((abs(float(f[8])) for f in win), default=0.0)

    # [7/3 6차] 낙상 전용 지표 (오탐 3건 분석 -> '높이 하강' + '스파이크 지속폭' 추가)
    #  - h_desc: 도플러 피크 '이전' 평균높이 - '이후' 평균높이 (순서 있는 하강.
    #    실측: 낙상 +0.20~+0.70 / 정지·보행·앉은채 팔움직임 등은 ~0 이하)
    #  - ds_broad: dop_std>=0.8 프레임 수 (낙상=0.5초 사건이라 2~5개.
    #    한 프레임짜리 스파이크(팔 휘두름·노이즈 플래시)는 0~1개)
    _pk     = ds_list.index(dopstd_max)
    _h_list = [CEILING_H - c for c in cy_vals]
    _pre, _post = _h_list[:_pk], _h_list[_pk + 1:]
    h_desc  = (sum(_pre) / len(_pre) - sum(_post) / len(_post)) \
              if (len(_pre) >= 2 and len(_post) >= 3) else None
    ds_broad = sum(1 for d in ds_list if d >= 0.8)
    # 피크 이후 보행 여부: 지속 보행은 post n 중앙값 >=20 (실측 보행 n p25=23),
    # 낙상 충돌 직후의 '순간' 포인트 산란(1~2프레임 26개)은 중앙값이라 무시됨.
    _post_n  = n_list[_pk + 1:]
    post_walk = (len(_post_n) >= 3 and float(np.median(_post_n)) >= 20)

    excess = score / thr if thr > 0 else 1.0
    conf   = round(min(0.99, 0.55 + 0.20 * min(1.0, max(0.0, excess - 1.0))), 2)

    # 0) 빈 공간 / 노이즈: 포인트 거의 없음 -> 무조건 정상.
    #    (케이블이 한 프레임 튀어도 여기서 차단 -> 빈방 오경보 방지)
    if n_mean < 4:
        return {'event_type': 'normal', 'severity': 'normal', 'confidence': 0.0}

    # 1) 낙상 -- 격렬한 도플러 피크 + 스파이크 지속(>=2프레임) + 높이 하강.
    #    [7/3 6차] 기존 '피크+점수'만으론 앉은채 팔움직임(ds 2.0)·정지후 급기동(1.58)·
    #    노이즈 플래시(2.48)가 오탐됨(실측 3건). 낙상은 지속 스파이크 + 전후 높이가
    #    실제로 낮아지는 사건 -> 두 조건 추가 (실측 낙상 10/10 유지 검증).
    #    [7/3 7차 수정] h_desc·post_walk 조건 제거: 수집 데이터로 캘리브레이션한
    #    두 조건이 라이브에서 낙상 미검출 유발 (라이브 낙상 n 19~57 vs 수집 7~13
    #    분포 이동 + 걸어 들어와 넘어지면 pre 높이가 보행 높이라 하강 미측정).
    #    -> 견고한 조건만 유지: 피크 + 스파이크 지속(>=2프레임, 플래시 차단) + 2연속.
    #    h_desc/post_med는 판정에 안 쓰되 로그에 남겨 실측 재캘리브레이션 근거로 축적.
    #    [7/3 8차] 고밀도 보정 티어: 시야에 제2 인물/대형 반사체가 있으면(n>=35)
    #    정지 포인트들이 낙상 도플러를 희석함(20:40 실측 낙상 ds_max 1.05, broad 1;
    #    같은 밀도의 정지/이동은 ds_max<=0.71, broad 0). 단 원칙은 Zone당 1명 스코프.
    #    [7/3 9차] 낙상 '모양' 조건 결합 (전 세션 실측 낙상 18건 전부 통과 검증):
    #     - h_drop >= 0.43     : 창 내 높이 변화폭. 실측 낙상 최소 0.447 / 케이블 흔들림·
    #                            앉은채 팔휘두름(0.424)은 미달 -> 높이 조건 복원(이슈 5,1)
    #     - 임펄스비 >= 2.2    : ds_max / 전반부평균. 낙상=조용->격발(2.3~7.9) vs
    #                            달리기·지속활동=전반부부터 높아 비율 낮음(이슈 3)
    #     - ds_last <= 1.0    : 낙상 후엔 가라앉음(실측 fall 최대 0.96, fast_sit<=0.51,
    #                            walk<=0.51) vs 달리기는 지속. [7/4] 0.85->1.0 완화로
    #                            실측 낙상 10/10 회복(구 0.85는 fall#1,#6 누락)하되 앉기/보행 여전히 배제.
    #    [7/4 10차] 수평 성분 결합 (데모 버그 근본수정: 뛰기/빠른앉기 오탐):
    #     - horiz_range >= 0.6 : 낙상은 바닥평면 이동/확산(실측 fall min 0.75) vs
    #                            제자리 빠른앉기(수평 고정)는 미달 -> 라이브 도플러 스파이크에도 앉기 배제.
    #     - 검증: 수집 40샘플 혼동행렬 fall 10/10, fast_sit·walk·normal 0/10.
    #       합성 뛰기(지속고도플러·수평만)·제자리앉기(수직만) 전부 정상 판정.
    #     - z_accel(수직가속도)은 게이트 아님 -> 사건성 있을 때 confidence만 +0.05 가산.
    _impulse = dopstd_max >= 2.2 * max(0.15, ds_first)
    _horiz   = horiz_range >= 0.6                       # 수평: 무너짐/traverse
    _zacc    = zacc_amp >= FALL_ZACC_MIN                # [7/6] 수직가속 하한: 팔흔들기(<=155) 배제
    _shape   = h_drop >= 0.43 and _impulse and ds_last <= 1.0 and _horiz and _zacc
    if ((dopstd_max >= 1.2 and n_mean >= 5 and ds_broad >= 2 and _shape)
            or (n_mean >= 35 and dopstd_max >= 0.9 and ds_broad >= 1 and _shape)):
        # [7/6] RF 검증: 규칙이 낙상이라 해도 RF가 wave/기타로 보면 억제(팔흔들기 오탐 제거).
        #   RF가 fall이라 하거나 RF 없으면 그대로 낙상 확정. -> 아래 walk/vibration으로 안 흘림.
        if not _rf_veto(win):
            _acc_boost = 0.05 if zacc_amp >= 400 else 0.0
            return {'event_type': 'fall_detected', 'severity': 'critical',
                    'confidence': round(min(0.99, conf + 0.10 + _acc_boost), 2)}

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
    #    [7/3 패치] + h_drop < 0.5: 사람 이동/FOV 퇴장 전이 창은 h_drop 0.57~2.40
    #    (오늘 오탐 후보 6건 실측 전부) vs 고정 진동원은 위치 고정 -> 높이변화 작음.
    #    선풍기 VIB 수집 후 이 문턱 재검증 예정.
    if ds_first >= 0.40 and ds_last >= 0.40 and h_drop < 0.5:
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
    'detailed_sop':     '',   # [7/4] Gemma 생성 상세 SOP (팝업창 내용)
    'detailed_sop_ver': 0,    # 새 SOP 생성 시 증가 -> 메인 스레드가 팝업 갱신
    '_manual_ctx':      '',   # 검색된 매뉴얼 원문(상세 SOP 생성 컨텍스트 재사용)
    'sop_cache_status': 'SOP cache: waiting for LIVE...',  # [7/6] 화면 표시용 사전생성 진행상태
    'pre_alert':   '',   # 정지형 1차 PRE-ALERT 배너 텍스트 (노란색, 비latch, 카운트다운)
    'scan_left':   None, # 빈 방 클러터 스캔 남은 시간(초). None = 스캔 아님
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
# 4. RAG THREAD  (+ [7/4] Gemma 상세 SOP 팝업)
# ═══════════════════════════════════════════════════════════
def generate_detailed_sop(ev_type, zone, manual_ctx=''):
    """Ollama REST(/api/generate) 직접 호출로 상세 SOP 생성 (langchain 불필요, urllib).
    검색 매뉴얼 원문이 있으면 근거로 넣고, 없으면 이벤트만으로 생성."""
    import urllib.request
    label = EVENT_LABELS.get(ev_type, ev_type)
    if SOP_LANG == 'ko':
        ctx_block = (f'\n참고 안전매뉴얼 발췌:\n{manual_ctx[:1200]}\n' if manual_ctx else '')
        prompt = (
            f'너는 산업 현장 안전관리자다. 방금 "{label}"이(가) Zone {zone}에서 감지됐다.'
            f'{ctx_block}\n'
            f'현장 작업자가 지금 즉시 따라야 할 초동 조치를 한국어로 작성하라. '
            f'번호를 매긴 4~5단계, 각 단계는 짧은 한 문장. 서론·부연 없이 조치만.'
        )
    else:
        ctx_block = (f'\nSafety manual excerpt:\n{manual_ctx[:1200]}\n' if manual_ctx else '')
        prompt = (
            f'You are an industrial safety officer. "{label}" was just detected in Zone {zone}.'
            f'{ctx_block}\n'
            f'Write the immediate response actions the on-site worker must take now, '
            f'as a numbered 4-5 step list, one short sentence each. No preamble, actions only.'
        )
    body = json.dumps({
        'model': LLM_MODEL, 'prompt': prompt, 'stream': False,
        'keep_alive': '10m',   # [7/4 속도] 0->10m: 경보마다 재로드 안 함(첫 로드 후 상주). 여유 1.5GB.
        'options': {'num_ctx': 1024, 'num_predict': 200, 'temperature': 0.2},  # 400->200: 생성 2배 빠름
    }).encode('utf-8')
    req = urllib.request.Request(OLLAMA_URL, data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode('utf-8')).get('response', '').strip()


_sop_cache = {}   # [7/6] 이벤트 유형별 상세 SOP 사전생성 캐시 -> 경보 시 즉시 표시

def _prewarm_gemma():
    """LIVE 진입 후, 이벤트 유형별 상세 SOP를 '미리' 생성해 캐시.
    이유: 젯슨 Ollama가 CPU로 돌아 생성이 느림(GPU 미사용). 미리 만들어두면
    경보 순간엔 캐시에서 즉시 팝업 -> 데모 지연 0. (백그라운드라 UI 안 막음)"""
    for _ in range(600):                       # LIVE 될 때까지 최대 ~5분 대기
        with _lock:
            if state['phase'] == PH_LIVE:
                break
        time.sleep(0.5)
    add_log('상세 SOP 사전생성 시작 (백그라운드, 유형별 1회)...')
    _types = ('fall_detected', 'stationary_anomaly', 'vibration_anomaly')
    with _lock:
        state['sop_cache_status'] = 'SOP cache: generating 0/3...'
    for i, et in enumerate(_types, 1):
        try:
            txt = generate_detailed_sop(et, 'C', '')
            if txt:
                _sop_cache[et] = txt
                add_log(f'상세 SOP 캐시 완료: {et} ({i}/3)')
                with _lock:
                    done = len(_sop_cache)
                    state['sop_cache_status'] = (f'SOP cache READY {done}/3 (instant popup)'
                                                 if done >= 3 else f'SOP cache: generating {done}/3...')
        except Exception as e:
            add_log(f'상세 SOP 사전생성 중단 ({et}): {e} -- ollama/gemma2:2b 확인')
            with _lock:
                state['sop_cache_status'] = f'SOP cache FAILED ({e})'
            break   # ollama 연결 안 되면 나머지도 실패 -> 중단


def _sop_status(msg):
    """메인 SOP 패널 하단에 상세 SOP 진행 상태를 표시(폰트 무관 영어)."""
    with _lock:
        base = state.get('sop_text', '').split('\n>> [Detailed SOP]')[0].rstrip()
        state['sop_text'] = base + f'\n\n>> [Detailed SOP] {msg}'

def _make_detailed_sop(ev_type, zone):
    """캐시가 있으면 즉시 표시, 없으면 Gemma로 생성 후 캐시 (팝업은 메인 스레드가 갱신)."""
    # 1) 캐시 히트 -> 즉시 팝업 (데모 지연 0)
    cached = _sop_cache.get(ev_type)
    if cached:
        with _lock:
            state['detailed_sop']     = cached
            state['detailed_sop_ver'] = state.get('detailed_sop_ver', 0) + 1
        _sop_status('shown instantly (pre-generated)')
        add_log('detailed SOP: cache hit -> instant popup')
        return
    # 2) 캐시 미스 -> 생성 (첫 1회, 느릴 수 있음) 후 캐시
    try:
        with _lock:
            ctx = state.get('_manual_ctx', '')
        _sop_status('generating via Gemma (first time, CPU ~30-60s)...')
        add_log('detailed SOP: generating (no cache yet)...')
        txt = generate_detailed_sop(ev_type, zone, ctx)
        if txt:
            _sop_cache[ev_type] = txt      # 다음 경보부턴 즉시
            with _lock:
                state['detailed_sop']     = txt
                state['detailed_sop_ver'] = state.get('detailed_sop_ver', 0) + 1
            _sop_status('ready -> popup (cached for next time)')
            add_log('detailed SOP ready -> popup (cached)')
        else:
            _sop_status('Gemma returned empty response')
            add_log('detailed SOP empty')
    except Exception as e:
        _sop_status(f'FAILED: {e}  (check: ollama serve / gemma2:2b)')
        add_log(f'detailed SOP failed: {e}')


def run_rag(ev_type, zone):
    """검색(메인 패널) + Gemma 상세 SOP(팝업)를 한 스레드에서 순차 수행."""
    _rag_retrieve(ev_type, zone)
    if DETAILED_SOP_POPUP and not HEADLESS:
        _make_detailed_sop(ev_type, zone)


def _rag_retrieve(ev_type, zone):
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
            state['_manual_ctx'] = ' '.join(d.page_content for d in docs)[:1500]  # 상세 SOP 근거 재사용
            state['rag_running'] = False
        add_log(f'Manual retrieved ({len(docs)} chunk) - retrieval-only, no LLM')

        # ── (옵션) 경량 LLM 요약: 검색 원문 표시 "후"에 별도로 시도 ──
        # 실패해도 위 검색 결과는 이미 화면에 있으므로 시연에 영향 없음.
        # 켜는 조건: 젯슨에 gemma2:2b 설치(`ollama pull gemma2:2b`) + 단독 테스트 통과 + USE_LLM_SUMMARY=True.
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
    prev_zvel   = 0.0         # [9차원] 직전 프레임 수직속도 (z_accel 계산용)
    prev_ts     = None        # [9차원] 직전 프레임 시각 (dt 계산용)
    ema_zacc    = 0.0         # [9차원] 수직가속도 EMA 상태
    anom_streak = 0           # 연속 이상 프레임 수 (디바운스)
    pend_et     = None        # non-fall 경보 후보 (연속 판정 확인용)
    pend_cnt    = 0           # 같은 판정이 연속으로 나온 횟수
    stat_since  = None        # 위험 Zone 내 정지 시작 시각 (Zone+지속시간 게이트)
    stat_miss   = 0           # 정지 조건 연속 이탈 프레임 수
    stat_zone   = None        # 현재 정지 중인 Zone id
    stat_pre    = False       # 1차 PRE-ALERT 발화 여부 (2단계 경보)
    stat_log_t  = 0.0         # 게이트 상태 로그 rate-limit (~2초마다)
    stat_ax = stat_az = 0.0   # 정지 위치 앵커 (타이머 시작 시의 바닥평면 좌표)
    stat_hits = stat_tot = 0  # 타이머 진행 중 조건충족/전체 프레임 수 (히트비율용)
    stat_last_hit = 0.0       # 마지막 히트 시각 (중립 프레임만 이어질 때 타이머 정리용)
    last_motion_t = -1e9      # 마지막 '이동 프레임' 시각 (진입 게이트: 이동->정지 시퀀스 확인)
    clutter_spots = list(CLUTTER_SPOTS)   # 클러터 마스크 (스캔으로 학습됨)
    scan_buf      = []        # 빈 방 스캔 좌표 버퍼
    scan_until    = None      # 스캔 종료 시각 (None = 스캔 아님)
    read_offset = 0
    model       = None
    scaler      = None
    thr         = 0.01

    add_log('Pipeline started -- waiting for radar data')

    def _finish_scan():
        """빈 방 스캔 종료 -> 클러터 맵 학습."""
        nonlocal clutter_spots, scan_until
        learned = build_clutter_map(scan_buf)
        clutter_spots = learned + list(CLUTTER_SPOTS)
        scan_until = None
        with _lock:
            state['scan_left'] = None
        spots_txt = ', '.join(f'({x:+.2f},{z:+.2f})' for x, z, _ in learned) or 'none'
        add_log(f'Scan done: {len(learned)} clutter spot(s) learned [{spots_txt}]')
        add_log('>> NOW step IN and STAND STILL (baseline collection)')

    # ── 저장된 baseline 재사용 (7/3): 있으면 스캔/웜업/학습 건너뛰고 바로 LIVE ──
    if LOAD_BASELINE and os.path.exists(BASELINE_PATH):
        try:
            try:
                ck = torch.load(BASELINE_PATH, map_location=DEVICE, weights_only=False)
            except TypeError:                     # 구버전 torch: weights_only 인자 없음
                ck = torch.load(BASELINE_PATH, map_location=DEVICE)
            # [7/4 9차원] 차원 호환성 사전 점검 — 8차원 구 baseline은 9차원 모델에 로드 불가.
            _saved_dim = None
            try:
                _saved_dim = int(getattr(ck.get('scaler'), 'n_features_in_', None)
                                 or ck['model']['enc1.weight_ih_l0'].shape[1])
            except Exception:
                _saved_dim = None
            if _saved_dim is not None and _saved_dim != FEATURE_DIM:
                raise ValueError(
                    f'저장된 baseline은 {_saved_dim}차원인데 현재 모델은 {FEATURE_DIM}차원입니다 '
                    f'(z_accel 추가로 확장됨). 8차원 구 baseline은 재사용 불가 -> '
                    f'[RESET] 후 빈방 스캔+베이스라인 재수집+재학습 필요.')
            model = LSTM_AE(FEATURE_DIM, 16, SEQ_LEN).to(DEVICE)
            model.load_state_dict(ck['model'])
            model.eval()
            scaler = ck['scaler']
            thr    = float(ck['thr'])
            clutter_spots = [tuple(s) for s in ck.get('clutter', [])] or list(CLUTTER_SPOTS)
            with _lock:
                state['threshold'] = thr
                state['phase']     = PH_LIVE
            add_log(f'Baseline LOADED (thr={thr:.5f}, clutter {len(clutter_spots)} spots) '
                    f'-- LIVE now. Radar moved? press RESET.')
        except Exception as e:
            model, scaler, thr = None, None, 0.01
            add_log(f'⚠ Baseline load failed: {e}')
            add_log('>> 9차원 feature로 재학습이 필요합니다. [START] 눌러 재수집하세요.')
            print(f'[BASELINE] load 실패 -> 재학습 필요: {e}')

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
            prev_zvel   = 0.0    # [9차원] z_accel 상태 초기화
            prev_ts     = None
            ema_zacc    = 0.0
            anom_streak = 0
            pend_et     = None
            pend_cnt    = 0
            stat_since  = None
            stat_miss   = 0
            stat_zone   = None
            stat_pre    = False
            clutter_spots = list(CLUTTER_SPOTS)   # 클러터 맵도 재스캔 대상
            scan_buf    = []
            scan_until  = None
            model       = None
            scaler      = None
            thr         = 0.01
            read_offset = 0      # re-read JSONL stream from start
            with _lock:
                state['scan_left'] = None

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
                # 빈 방 스캔 중이면 타이머만 진행 (기록할 점 없음)
                if scan_until is not None:
                    if time.time() < scan_until:
                        with _lock:
                            state['scan_left'] = scan_until - time.time()
                    else:
                        _finish_scan()
                continue

            with _lock:
                state['latest_pts']  = frame_pts
                state['last_data_t'] = time.time()

            ys  = [p['y'] for p in frame_pts]
            cz  = CEILING_H - (float(np.mean(ys)) if ys else CEILING_H)  # 천장기준 높이(바닥 위 높이)
            n   = len(frame_pts)
            _now_t = time.time()
            _dt    = (_now_t - prev_ts) if prev_ts is not None else None
            feat = extract_features(frame_pts, prev_c, prev_zvel, _dt, ema_zacc)
            ref     = float(np.random.normal(0, 0.004))
            feat[3] = lms.filter(feat[3], ref)
            prev_c    = feat[:3].copy()
            prev_zvel = float(feat[7])    # [9차원] 다음 프레임 z_accel용
            ema_zacc  = float(feat[8])
            prev_ts   = _now_t

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
                    scan_buf   = []
                    scan_until = time.time() + SCAN_SEC   # 1단계: 빈 방 클러터 스캔
                    with _lock:
                        state['start_requested'] = False
                        state['phase']           = PH_WARMUP
                        state['scan_left']       = SCAN_SEC
                    add_log(f'STEP A: EMPTY-ROOM SCAN {int(SCAN_SEC)}s -- everyone OUT of view!')
                else:
                    with _lock:
                        state['sc_h'].append(0.0)
                    continue   # skip this frame, wait for button

            # ── WARMUP phase ───────────────────────────────
            if model is None:
                # STEP A: 빈 방 클러터 스캔 (사람 들어오기 전)
                if scan_until is not None:
                    if time.time() < scan_until:
                        scan_buf.append((float(feat[0]), float(feat[2])))
                        with _lock:
                            state['scan_left'] = scan_until - time.time()
                            state['sc_h'].append(0.0)
                        continue
                    _finish_scan()   # 스캔 종료 -> 클러터 맵 확정, 이후 웜업 진행

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

                    # baseline 자동 저장 (클러터 맵 포함) -> 다음 실행에서 전부 생략 (7/3)
                    try:
                        torch.save({'model': model.state_dict(),
                                    'scaler': scaler, 'thr': thr,
                                    'clutter': clutter_spots}, BASELINE_PATH)
                        add_log('Baseline saved (incl. clutter map) -- next run starts LIVE')
                    except Exception as e:
                        add_log(f'Baseline save failed: {e}')

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
            # [7/3 2차] 위치 앵커: 타이머 시작 지점에서 0.8m 밖 프레임은 히트 아님
            # (빈 방 노이즈는 방 전체를 점프 -> 앵커 유지 불가. 사람은 최대 0.67m 실측)
            _pos_ok = True
            if stat_since is not None:
                _pos_ok = (_cx - stat_ax)**2 + (_czf - stat_az)**2 <= STAT_POS_R**2
            # [7/3 3차] 클러터 스팟(빈 방 스캔으로 학습됨) 프레임 = 중립
            _clutter = any((_cx - _sx)**2 + (_czf - _sz)**2 <= _sr**2
                           for _sx, _sz, _sr in clutter_spots)
            # [7/3 4차] 이동 프레임 기록 (사람이 걸어 들어옴 -> 정지 타이머 시작 허가)
            if _n >= 14 or _ds >= 0.40:
                last_motion_t = time.time()

            if MAINT_MODE:
                stat_since = None; stat_zone = None; stat_pre = False   # 계획 정비: 억제
                stat_hits = stat_tot = 0
                with _lock:
                    state['pre_alert'] = ''
            elif _clutter:
                pass   # 중립: 카운터/타이머 유지 (사람 부재는 아래 hit-timeout이 정리)
            elif (_zone_hit and _n >= STAT_N_MIN and STAT_DS_MIN < _ds < STAT_DS_MAX and _pos_ok
                  and (stat_since is not None                              # 이미 진행 중이거나
                       or time.time() - last_motion_t <= STAT_ENTRY_SEC)): # 방금 걸어 들어왔을 때만
                if stat_since is None:
                    stat_since = time.time()
                    stat_zone  = _zone_hit
                    stat_ax, stat_az = _cx, _czf     # 정지 위치 고정(앵커)
                    stat_hits = stat_tot = 0
                stat_hits += 1; stat_tot += 1
                stat_last_hit = time.time()
                stat_miss = 0
                # 1차 PRE-ALERT (경고, 비latch): 움직이면 자동 취소됨
                # 히트비율 조건: 노이즈는 앵커/조건을 절반쯤 놓쳐(~50%) 발화 불가
                _dwell = time.time() - stat_since
                _ratio_ok = stat_hits >= STAT_HIT_RATIO * max(1, stat_tot)
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
                                'hit_ratio': round(stat_hits / max(1, stat_tot), 2),
                            }) + '\n')
                    except Exception:
                        pass
                if not stat_pre and _dwell >= STAT_PRE_SEC and _ratio_ok:
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
                if stat_since is not None:
                    stat_tot += 1        # 미스도 분모에 포함 -> 노이즈는 히트비율 못 채움
                stat_miss += 1
                if stat_miss >= STAT_MISS_TOL:
                    if stat_pre:
                        add_log(f'PRE-ALERT cleared Zone {stat_zone}: motion resumed')
                    stat_since = None; stat_zone = None; stat_pre = False
                    stat_hits = stat_tot = 0
                    with _lock:
                        state['pre_alert'] = ''

            # [7/3 3차] 신선한 히트 없이 타이머가 벽시계로만 자라는 것 방지
            # (클러터 중립 프레임만 계속되는 상황 = 사람이 떠난 것)
            if stat_since is not None and time.time() - stat_last_hit > STAT_HIT_TIMEOUT:
                if stat_pre:
                    add_log(f'PRE-ALERT cleared Zone {stat_zone}: presence lost')
                stat_since = None; stat_zone = None; stat_pre = False
                stat_hits = stat_tot = 0
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
                            _pk2 = int(_ds.argmax())
                            _hh  = CEILING_H - _w[:, 1]
                            _hd  = (round(float(_hh[:_pk2].mean() - _hh[_pk2+1:].mean()), 2)
                                    if (_pk2 >= 2 and len(_hh) - _pk2 - 1 >= 3) else None)
                            _pm  = (round(float(np.median(_n[_pk2+1:])), 1)
                                    if len(_n) - _pk2 - 1 >= 3 else None)
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
                                    # 낙상 재캘리브레이션용 (판정엔 broad만 사용 중)
                                    'broad': int((_ds >= 0.8).sum()),
                                    'h_desc': _hd, 'post_med': _pm,
                                    # [7/4 10차] 수평·수직가속 진단값
                                    'horiz': round(float(np.hypot(_w[:, 0].max() - _w[:, 0].min(),
                                                                  _w[:, 2].max() - _w[:, 2].min())), 3),
                                    'zacc': round(float(np.abs(_w[:, 8]).max()), 3),
                                }) + '\n')
                    except Exception:
                        pass   # 로깅 실패가 파이프라인을 죽이면 안 됨

                    # [2026-07-02 패치] 경보는 latch(수동 해제)라 오탐 1번이 계속
                    # 유지됨. 낙상(일회성 사건)은 즉시 latch, 나머지(진동/정지형
                    # = 지속 상태)는 같은 판정이 CONFIRM_EVENTS번 연속돼야 latch
                    # -> 보행/앉기 전이 창이 우연히 1번 걸려도 경보 안 됨.
                    if et == 'normal':
                        pend_et, pend_cnt = None, 0   # 정상 판정 -> 후보 리셋
                    else:
                        # 낙상=2연속, 나머지=3연속 동일 판정이어야 latch (오탐 억제)
                        _need = FALL_CONFIRM if et == 'fall_detected' else CONFIRM_EVENTS
                        if et == pend_et:
                            pend_cnt += 1
                        else:
                            pend_et, pend_cnt = et, 1
                        if pend_cnt < _need:
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
                        and time.time() - stat_since >= STAT_CRIT_SEC
                        and stat_hits >= STAT_HIT_RATIO * max(1, stat_tot)):
                    et2 = 'stationary_anomaly'
                    zn2 = stat_zone or EVENT_ZONE.get(et2, 'B')
                    dwell = time.time() - stat_since
                    _fr = stat_hits / max(1, stat_tot)   # 실측 히트비율 -> 신뢰도에 반영
                    stat_since = None; stat_zone = None; stat_miss = 0; stat_pre = False
                    stat_hits = stat_tot = 0
                    state['pre_alert'] = ''          # PRE-ALERT 배너 -> critical 경보로 승격
                    instant2 = instant_action(et2)
                    state.update({
                        'ev_active': True, 'ev_type': et2,
                        'ev_sev': 'critical',
                        # 신뢰도 = 존재 히트비율 기반 (0.65~1.0 -> 0.81~0.95). human-in-the-loop
                        'ev_conf': round(min(0.95, 0.55 + 0.40 * _fr), 2),
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
# 8. ANIMATION UPDATE  (+ [7/4] 상세 SOP 팝업)
# ═══════════════════════════════════════════════════════════
_sop_popup = {'fig': None, 'txt': None, 'ver': -1}
def _refresh_sop_popup():
    """detailed_sop_ver가 바뀌면 별도 팝업 창을 열거나 내용 갱신 (메인 스레드 전용).
    Gemma 생성이 백그라운드 스레드에서 끝나면 여기서 창을 띄운다(=Tk는 메인스레드에서만)."""
    if HEADLESS:
        return
    with _lock:
        ver  = state.get('detailed_sop_ver', 0)
        body = state.get('detailed_sop', '')
        ev_t = state.get('ev_type')
        ev_z = state.get('ev_zone', '')
    if ver == _sop_popup['ver'] or not body:
        return
    _sop_popup['ver'] = ver
    title   = f"상세 SOP (Gemma) — {EVENT_LABELS.get(ev_t, ev_t)} / Zone {ev_z}"
    wrapped = '\n'.join(textwrap.fill(ln, width=52) for ln in body.split('\n'))
    content = f"[ {title} ]\n\n{wrapped}\n\n(이 창을 닫아도 감시는 계속됩니다)"
    try:
        f = _sop_popup['fig']
        if f is None or not plt.fignum_exists(f.number):
            f = plt.figure('Detailed SOP', figsize=(6.4, 8.2), facecolor='#0a0a1e')
            ax = f.add_axes([0, 0, 1, 1]); ax.axis('off')
            ax.add_patch(mpatches.Rectangle((0.02, 0.02), 0.96, 0.96,
                         transform=ax.transAxes, facecolor='#0d1530',
                         edgecolor='#ff6644', linewidth=2, zorder=0))
            _sop_popup['txt'] = ax.text(0.06, 0.95, '', transform=ax.transAxes,
                         va='top', ha='left', color='#e6f0ff', fontsize=10.5,
                         family=(KOREAN_FONT or 'DejaVu Sans'), zorder=1)
            _sop_popup['fig'] = f
        _sop_popup['txt'].set_text(content)
        _sop_popup['txt'].set_color('#ffdddd' if ev_t == 'fall_detected' else '#e6f0ff')
        f.canvas.draw_idle()
        try:
            f.show()
        except Exception:
            pass
    except Exception as e:
        print(f'[SOP-POPUP] error: {e}')


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
        scan_left  = state.get('scan_left')
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
        _CAP = 28                              # [7/4] 3D 표시 포인트 상한 40->28 (젯슨 3D draw 부하↓,
                                               #   ~25~30이 인체 클러스터 셀링포인트 유지 스윗스팟)
        draw_pts = pts[::max(1, n // _CAP)][:_CAP]   # 하드 캡. 표시 전용 — 탐지는 전체 클라우드 사용(무영향)
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
    if scan_left is not None:   # STEP A: 빈 방 클러터 스캔 중 (보라색 표시)
        prog_fill.set_width(max(0.02, 1.0 - scan_left / max(1.0, SCAN_SEC)))
        prog_fill.set_facecolor('#cc66ff')
        prog_label.set_text(f'STEP A: EMPTY-ROOM SCAN  {scan_left:.0f}s left'
                            f'  --  keep everyone OUT of view!')
        prog_label.set_color('#dd99ff')

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
                f'|  score={sc_h[-1]:.5f}  thr={thr:.5f}  |  {state.get("sop_cache_status","")}')
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

    # [7/4] Gemma 상세 SOP 팝업 갱신 (백그라운드 생성 완료 시 창 표시)
    _refresh_sop_popup()

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

    # ── [7/4] HEADLESS: GUI 없이 탐지만 (메인 스레드 블로킹 실행) ──
    #   버튼이 없으므로 baseline 수집/학습은 저장된 baseline_model.pt 자동로드로
    #   바로 LIVE 진입하거나, 최초 1회는 GUI 모드로 baseline을 만든 뒤 headless 운용.
    #   (baseline 없으면 READY에서 대기 -> 환경변수/신호로 트리거하도록 확장 여지)
    if HEADLESS:
        print('  [HEADLESS] GUI 비활성 — 탐지/판정/로그/데이터셋 저장만 수행합니다.')
        print('  종료: Ctrl+C')
        print('=' * 65)
        try:
            pipeline_loop_safe()          # 메인 스레드에서 블로킹 실행 (렌더 루프 없음)
        except KeyboardInterrupt:
            print('\n[EXIT] headless 종료 -- bye')
        sys.exit(0)

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
                state['logs'].append(f'[{ts}] [BTN] Start Baseline -- EMPTY ROOM first (12s scan)!')
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
    # [7/4] Gemma 사전 로드 스레드 (첫 경보 SOP 지연 제거)
    if DETAILED_SOP_POPUP and not HEADLESS:
        threading.Thread(target=_prewarm_gemma, daemon=True).start()

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
