"""
jetson_sender.py -- Radar-Guard [JETSON 측]  (radar_live_full.py 분할본 1/2)
===========================================================================
역할: 레이더 데이터 읽기 -> LMS -> LSTM-AE -> classify -> Zone/정지형 게이트
      -> 판정 결과 + 포인트클라우드 + 상태를 UDP로 노트북에 송신.
      GUI 없음. RAG/LLM 없음(노트북이 담당).

실행 (젯슨 터미널):
  [터미널 1]  python3 ~/radar_parser.py          <- 데이터 수집(기존 그대로)
  [터미널 2]  python3 ~/jetson_sender.py         <- 이 파일

노트북 IP를 여기 적을 필요 없음:
  노트북(console_ui.py)이 젯슨으로 HELLO를 계속 보내고, 젯슨은 그 주소로 회신한다.
  (고정하고 싶으면 아래 LAPTOP_IP를 채우거나 RADAR_LAPTOP_IP 환경변수 사용)

포트:  5005 = 젯슨 -> 노트북 (데이터)      5006 = 노트북 -> 젯슨 (제어/HELLO)
"""

import json, os, time, math, threading, warnings, sys, socket, traceback
from datetime import datetime
from collections import deque, Counter

import numpy as np

# [7/31] torch·sklearn 은 LSTM-AE 전용이다. 없으면 AE 만 끄고 규칙 판정으로 계속한다.
#   젯슨에는 당연히 있다. 이 방어는 (a) 노트북에서 --simulate 로 이 파일을 그대로
#   돌려보기 위해, (b) 젯슨에서 torch 가 깨졌을 때 통째로 죽지 않기 위해서다.
#   ⚠ AE 가 꺼지면 score=0 이므로 이상점수 게이트가 무력화된다. 규칙(classify)은 그대로.
try:
    import torch
    import torch.nn as nn
    from torch import optim
    from sklearn.preprocessing import MinMaxScaler
    TORCH_OK = True
except ImportError as _te:
    TORCH_OK = False
    torch = optim = MinMaxScaler = None

    class _NNStub:
        """LSTM_AE 클래스 '정의'만 통과시키는 껍데기. 인스턴스화하면 즉시 실패한다."""
        Module = object

        def __getattr__(self, _n):
            def _boom(*a, **k):
                raise RuntimeError('torch 없음 — LSTM-AE 사용 불가 (규칙 판정만 동작)')
            return _boom

    nn = _NNStub()
    sys.stderr.write(f'[경고] torch/sklearn 없음 ({_te}) → LSTM-AE 비활성, '
                     f'규칙 판정만 동작합니다. score=0 으로 고정됩니다.\n')

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════
# 0. NETWORK CONFIG
# ═══════════════════════════════════════════════════════════
# [7/31] 공용 상수는 radar_common.py 단일 소스에서 가져온다.
#   이전엔 CEILING_H·PH_*·EVENT_LABELS 가 sender/viewer 양쪽에 복붙돼 있어
#   한쪽만 고치면 조용히 어긋났다(특히 CEILING_H = 모든 높이 계산의 기준).
try:
    from radar_common import (  # noqa: F401  (아래 목록을 그대로 쓴다)
        SCHEMA_VERSION, DATA_PORT, CTRL_PORT, SEND_HZ, MAX_UDP, MIN_PTS, CLIENT_TTL,
        CMD_HELLO, CMD_START, CMD_TRAIN, CMD_RESET, CMD_RESOLVE, CMD_RESTORE,
        CMD_ENTER, CMD_EXIT,
        CEILING_H, FRAME_INNER_HALF, HISTORY_LEN,
        PH_READY, PH_WARMUP, PH_WAIT_TRAIN, PH_TRAINING, PH_WAIT_ARM, PH_LIVE,
        EVENT_LABELS, EVENT_ZONE, ZONE_IDS, RADAR_ZONE, EVENT_SEV,
        CURR_LIMIT, VOLT_MIN, VIB_DS_THRESH,
    )
except ImportError:
    sys.stderr.write(
        '\n'
        '════════════════════════════════════════════════════════════════\n'
        '  radar_common.py 를 찾을 수 없습니다.\n'
        '  이 파일은 jetson_sender.py 와 반드시 같은 폴더에 있어야 합니다.\n'
        '  (CEILING_H·포트·이벤트 라벨을 노트북과 공유하는 단일 소스)\n'
        '\n'
        '  노트북에서 젯슨으로 복사:\n'
        '     scp radar_common.py jetson_sender.py <젯슨계정>@<젯슨IP>:~/\n'
        '════════════════════════════════════════════════════════════════\n')
    raise

LAPTOP_IP = os.environ.get('RADAR_LAPTOP_IP', '')   # 비워두면 HELLO로 자동 발견

# ═══════════════════════════════════════════════════════════
# 1. CONFIG  (radar_live_full.py와 동일 -- 실측 튜닝값 유지)
# ═══════════════════════════════════════════════════════════
JSON_PATH     = '/home/project/stage1_filtered.json'
CLF_LOG_PATH  = '/home/project/clf_decisions.jsonl'   # classify 판정 로그(문턱 튜닝용)
SUSPECT_LOG_PATH = '/home/project/fall_suspected.jsonl'  # 확인 라벨 전 재학습 후보

DANGER_ZONES = {
    'A': {'x': (-FRAME_INNER_HALF, FRAME_INNER_HALF),
          'z': (-FRAME_INNER_HALF, FRAME_INNER_HALF), 'label': 'WORK-ZONE'},
}
EXCLUDE_REGIONS = []
NEAR_FIELD_MIN_RANGE = 0.5

# [8/06 제작도] 전체 1.50m, 3030 기둥 안쪽 1.44m. 바닥면도 같은 정사각형이다.
FRAME_ROI_X = (-FRAME_INNER_HALF, FRAME_INNER_HALF)
FRAME_ROI_Z = (-FRAME_INNER_HALF, FRAME_INNER_HALF)
FRAME_ROI_Y = (NEAR_FIELD_MIN_RANGE, CEILING_H + 0.25)

STAT_N_MIN    = 3
STAT_DS_MIN   = 0.04
STAT_DS_MAX   = 0.35
STAT_POS_R    = 0.8
STAT_HIT_RATIO = 0.75
STAT_HIT_FLOOR = 0.60
STAT_MIN_OBS   = 20
STAT_HIT_TIMEOUT = 5.0
STAT_ENTRY_SEC = 8.0

SCAN_SEC        = 12.0   # 빈 방 스캔 시간 (이 동안 전원 시야 밖!)
# [8/11] 퇴장 유예. 버튼을 누른 사람이 감지 구역 밖으로 나갈 시간.
#   왜: 이전엔 START 를 받는 즉시 빈방 스캔이 시작됐다. 노트북이 감지 구역 안에
#       있으면 구조적으로 빠져나갈 방법이 없어 사람이 배경으로 학습됐다
#       (2026-08-11 실측: 사람 몸통이 클러터 4개로 등록됨 —
#        (0.00,1.50,0.00) 외 3개가 0.6m x 0.6m 덩어리를 이뤘다).
#   입장에는 STEP_IN_SEC 유예가 있었는데 퇴장에는 없어 비대칭이었다.
STEP_OUT_SEC    = 5.0
STEP_IN_SEC     = 5.0    # 빈방 스캔 후 사람이 들어와 자리 잡을 카운트다운(초)
SCAN_GRID       = 0.30
SCAN_MIN_HITS   = 4
SCAN_MAX_SPOTS  = 30
CLUTTER_SPOT_R  = 0.35
SCAN_GRID_Y     = 0.30
CLUTTER_Y_BAND  = 0.35
CLUTTER_SPOTS   = []
CLUTTER_REMOVE_POINTS = True

# ⚠ [7/31 회귀 복구] 아래 두 값이 7/12 이전 값으로 되돌아가 있었다.
#   분리본이 7/12 수정 이전 버전에서 갈라져 나왔기 때문. radar_live_full.py 기준으로 복구.
STAT_PRE_SEC  = 10.0   # [7/12] 15->10: 데모 시 15s 완전정지 유지가 어려워(실측 dwell 최대 6.9s)
                       #   1차: Zone 내 정지 이만큼 지속 -> PRE-ALERT(경고, 비latch)
STAT_CRIT_SEC = 30.0   # 2차: 계속 무동작 -> stationary 경보(critical, latch)
MAINT_MODE    = False  # True = 계획 정비 중(LOTO/작업허가) -> 정지형 경보 억제
STAT_MISS_TOL = 3      # [7/12] 10->3: 이탈 프레임 10개 용인이 '이동 중 타이머 생존 ->
                       #   오발화'의 주원인. 3프레임(~0.3s)만 용인.

TRACK_ACQUIRE_FRAMES = 3
TRACK_MOTION_DS = 0.35
TRACK_LOST_SEC = 1.2
TRACK_COMPACT_R = 0.80
TRACK_MATCH_R = 1.20
TRACK_N_MIN = 15  # [8/05 무인 50프레임] ROI+클러터 후 최대 14점
TRACK_STILL_R = 0.35
TRACK_STILL_KEEP_SEC = 3.0

BASELINE_PATH = '/home/project/baseline_model.pt'
LOAD_BASELINE = False  # 설치 확정 전에는 매 실행마다 현장 기준을 다시 수집한다

N_WARMUP      = 150    # real frames for normal baseline (~15 sec at 10 fps)
# CEILING_H, HISTORY_LEN -> radar_common.py (노트북과 반드시 같아야 하는 값)
FEATURE_DIM   = 9      # [7/4 9차원] cx,cy,cz,mean_dop,dop_std,int_mean,n_pts,z_vel,z_accel
SEQ_LEN       = 5
CLF_WIN       = 20     # 규칙 classify 집계 창(~2s). 실측 문턱이 20프레임 기준
CONFIRM_FRAMES = 3
CONFIRM_EVENTS = 3
FALL_CONFIRM   = 1
FALL_WIN_SEC   = 1.0
POSTFALL_GATE  = True
POSTFALL_HOLD  = 1.2
RECOVER_NP75   = 15
RECOVER_DSLO   = 0.30
RECOVER_DSHI   = 0.90
RECOVER_FRAMES = 4
FALL_ZACC_MIN  = 0
POLL_SEC      = 0.4

DEVICE = (torch.device('cuda' if torch.cuda.is_available() else 'cpu')
          if TORCH_OK else 'none(torch 없음)')

# ── [7/31] 시뮬레이션 모드 ────────────────────────────────────────────
#   `python jetson_sender.py --simulate` 로 레이더·젯슨 없이 이 파일을 그대로 돌린다.
#   JSON_PATH 를 임시 파일로 바꾸고 합성 프레임을 같은 JSONL 포맷으로 흘려 넣는다.
#   → 파일 tail 읽기·파싱·피처추출·classify·차단기·패킷조립까지 실제 코드 경로가 돈다.
#   ⚠ 낙상 판정의 정확성을 재는 게 아니다. "코드가 실제로 도는가"를 재는 것이다.
#  ⚠ 이 이름은 조건과 무관하게 항상 존재해야 한다. 예전엔 SIMULATE 블록 안에서만
#    정의하고 `A if SIMULATE else B` 로 지연 평가에 의존했는데, 조건을 뒤집는 리팩터링
#    한 번에 NameError 로 젯슨이 즉사하는 구조였다. (verify_jetson_safe.py [5] 가 잡음)
RF_MODEL_PATH_OVERRIDE = None      # --simulate 에서만 채워진다
SIMULATE = '--simulate' in sys.argv
#  --fast : 스캔·웜업 시간을 줄여 한 사이클을 10초 안으로. UI 반복 작업용.
#           ⚠ 판정 품질 검증에는 쓰지 말 것 (베이스라인 표본이 30프레임뿐).
SIM_FAST = SIMULATE and '--fast' in sys.argv
if SIM_FAST:
    SCAN_SEC = 3.0
    STEP_IN_SEC = 2.0
    N_WARMUP = 30
if SIMULATE:
    import tempfile
    JSON_PATH = os.path.join(tempfile.gettempdir(), 'radar_sim_frames.jsonl')
    BASELINE_PATH = os.path.join(tempfile.gettempdir(), 'radar_sim_baseline.pt')
    RF_MODEL_PATH_OVERRIDE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        '02_레이더_원본코드', 'fall_classifier.joblib')
    try:
        open(JSON_PATH, 'w').close()
    except OSError:
        pass

# Phase / EVENT_LABELS / EVENT_ZONE 은 radar_common.py 에서 import 함 (위 참조).
#   여기에 다시 정의하지 말 것 — 그게 7/31 이전의 어긋남 원인이었다.

# [7/6] RF 낙상/동작 분류기 (팔흔들기 오탐 억제). 파일 없으면 규칙만 사용(안전).
RF_MODEL_PATH = RF_MODEL_PATH_OVERRIDE or os.path.expanduser('~/fall_classifier.joblib')
try:
    import joblib
    _rf_ck    = joblib.load(RF_MODEL_PATH)
    RF_MODEL  = _rf_ck['model']
    RF_FEATURES = _rf_ck['features']
    RF_THRESHOLD = float(_rf_ck.get('threshold', 0.5))
    RF_OK     = True
    print(f'[RF] fall_classifier 로드 OK ({len(RF_FEATURES)} feats, '
          f'threshold={RF_THRESHOLD:.6f})')
except Exception as _rfe:
    RF_MODEL = None; RF_THRESHOLD = 1.0; RF_OK = False
    print(f'[RF] 모델 없음/로드실패 -> 규칙만 사용: {_rfe}')

# [8/15 실측] 30프레임 RF는 기존 20프레임 classify/RF veto와 입력 분포가 다르다.
# 기존 모델을 덮어쓰지 않고 직접 낙상 후보 전용으로 분리해 복원 가능성을 보존한다.
RF30_MODEL_PATH = os.path.expanduser(os.environ.get(
    'RADAR_RF30_MODEL', '~/fall_classifier_hybrid30.joblib'))
try:
    _rf30_ck = joblib.load(RF30_MODEL_PATH)
    if _rf30_ck.get('feature_mode') != 'raw_motion_height_bg10_low30':
        raise ValueError(f"지원하지 않는 feature_mode: {_rf30_ck.get('feature_mode')}")
    RF30_MODEL = _rf30_ck['model']
    RF30_THRESHOLD = float(_rf30_ck['threshold'])
    RF30_WINDOW = int(_rf30_ck['window_frames'])
    RF30_BG = {tuple(v) for v in _rf30_ck['height_background']}
    RF30_GRID = float(_rf30_ck['height_background_config']['grid_m'])
    RF30_Y_PERCENTILE = float(_rf30_ck['height_background_config']['y_percentile'])
    RF30_OK = RF30_WINDOW == 30 and bool(RF30_BG)
    if not RF30_OK:
        raise ValueError(f'window={RF30_WINDOW}, background={len(RF30_BG)}')
    print(f'[RF30] 용도분리 모델 로드 OK (window={RF30_WINDOW}, '
          f'background={len(RF30_BG)}, threshold={RF30_THRESHOLD:.6f})')
except Exception as _rf30e:
    RF30_MODEL = None; RF30_THRESHOLD = 1.0; RF30_WINDOW = 30
    RF30_BG = set(); RF30_GRID = 0.10; RF30_Y_PERCENTILE = 70.0; RF30_OK = False
    print(f'[RF30] 모델 없음/로드실패 -> 기존 20프레임 RF 유지: {_rf30e}')

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
        time.sleep(0.01)    # 송신 스레드에 GIL 양보

    model.eval()
    with torch.no_grad():
        r  = model(X)
        ls = torch.mean((r - X)**2, dim=(1, 2)).cpu().numpy()
        thr = float(np.mean(ls) + 3 * np.std(ls))
    return model, scaler, thr


def build_clutter_map(scan_frames):
    """빈방 각 프레임의 모든 점을 3D 복셀화해 반복 배경만 학습한다."""
    cnt = Counter()
    for frame in scan_frames:
        # 같은 프레임의 점 여러 개가 한 복셀에 몰려도 관측 1회로 센다.
        voxels = {(round(x / SCAN_GRID), round(y / SCAN_GRID_Y), round(z / SCAN_GRID))
                  for x, y, z in frame}
        cnt.update(voxels)
    # 점 단위 복셀은 중심점 방식보다 촘촘하므로 기존 35 cm 구를 쓰면 ROI 대부분이
    # 지워진다. 학습한 복셀 셀 자체만 제거해 사람의 인접 점을 보존한다.
    spots = [(gx * SCAN_GRID, gy * SCAN_GRID_Y, gz * SCAN_GRID,
              SCAN_GRID * 0.45, SCAN_GRID_Y * 0.45)
             for (gx, gy, gz), k in cnt.most_common(SCAN_MAX_SPOTS) if k >= SCAN_MIN_HITS]
    return spots


def _rule_fall_positive(clf):
    """classify 정본을 바꾸지 않고 규칙 양성/RF 음성 불일치만 복원한다."""
    ev = clf.get('evidence') or {}
    gates = clf.get('gates') or {}
    shape = all((gates.get(k) or {}).get('pass') for k in
                ('impulse', 'h_drop', 'horiz', 'ds_last'))
    ds_max, n_mean = float(ev.get('dopstd_max') or 0), float(ev.get('n_mean') or 0)
    broad = int(ev.get('ds_broad') or 0)
    return bool(shape and ((ds_max >= 1.2 and n_mean >= 5 and broad >= 2)
                           or (n_mean >= 35 and ds_max >= 0.9 and broad >= 1)))


def _save_fall_suspect(fw, clf):
    """LIVE 자가학습 대신 사람이 확인할 수 있는 무라벨 재학습 후보를 축적한다."""
    rec = {'t': round(time.time(), 2), 'label': None, 'source': 'rule_rf_disagreement',
           'features': np.asarray(fw, dtype=float).round(5).tolist(),
           'evidence': clf.get('evidence'), 'gates': clf.get('gates')}
    try:
        with open(SUSPECT_LOG_PATH, 'a') as f:
            f.write(json.dumps(rec, separators=(',', ':')) + '\n')
    except OSError as e:
        add_log(f'낙상 의심 데이터 저장 실패: {e}')


def _rf_features(win):
    """classify의 win(9차원 벡터 리스트) -> train_fall_classifier.extract()와 동일 19피처.
    (샌드박스 검증: 수집 프레임 기반 추출과 0/70 불일치 = 라이브·오프라인 완전 일치)"""
    if len(win) < 4:
        return None
    cx = np.array([float(f[0]) for f in win]); cy = np.array([float(f[1]) for f in win])
    cz = np.array([float(f[2]) for f in win]); ds = np.array([float(f[4]) for f in win])
    n  = np.array([float(f[6]) for f in win]); dop = np.array([float(f[3]) for f in win])
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
    # [7/8 환경불변] extract()와 100% 동일: 절대높이/포인트수 -> cy 상대비율.
    span = float(cy.max() - cy.min()) + 1e-6
    cy_s = float(cy[:3].mean()); cy_e = float(cy[-3:].mean())
    end_low_ratio  = (cy_e - float(cy.min())) / span
    net_drop_ratio = (cy_e - cy_s) / span
    max_drop_ratio = (float(cy.max()) - cy_s) / span
    nm = float(n.mean()) + 1e-6
    nh = max(1, len(n) // 2)
    n_peak_ratio = float(n.max()) / nm
    n_cv         = float(n.std()) / nm
    n_trend      = (float(n[nh:].mean()) - float(n[:nh].mean())) / nm
    return [
        float(ds.max()), float(ds.mean()), float(ds_first), float(ds_last),
        float(ds.max() / max(0.15, ds_first)), int((ds >= 0.8).sum()),
        float(ds_last / (ds.max() + 1e-6)), _pk(ds), zsc,
        float(cy.max() - cy.min()),
        end_low_ratio, net_drop_ratio, max_drop_ratio,
        float(np.hypot(cx.max()-cx.min(), cz.max()-cz.min())),
        float(np.hypot(cx[pk:].mean()-cx[:max(1,pk)].mean(), cz[pk:].mean()-cz[:max(1,pk)].mean())),
        n_peak_ratio, n_cv, n_trend,
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


def _rf_fall_score(win):
    """19피처 RF의 낙상 점수. 확률 보정값이 아니라 운영 임계 비교용 점수다."""
    if not RF_OK:
        return None
    feats = _rf_features(win)
    if feats is None:
        return None
    classes = list(RF_MODEL.classes_)
    if 'fall' not in classes:
        raise ValueError(f'RF classes에 fall 없음: {classes}')
    return float(RF_MODEL.predict_proba([feats])[0, classes.index('fall')])


def _rf30_height_points(frame_pts):
    """RF30 학습 때 고정한 10 cm 배경 복셀만 높이·UI 경로에서 제거한다."""
    if not RF30_OK:
        return frame_pts
    return [p for p in frame_pts
            if (round(p['x'] / RF30_GRID), round(p['y'] / RF30_GRID),
                round(p['z'] / RF30_GRID)) not in RF30_BG]


def _rf30_feature(frame_pts, prev_c=None, prev_zvel=0.0, dt=None, ema_zacc=0.0,
                  ema_a=0.5):
    """도플러·세기·점수는 원본, 위치만 배경 제거 후 낮은 30%로 계산한다."""
    feat = extract_features(frame_pts)
    height_pts = _rf30_height_points(frame_pts)
    if not height_pts:
        return feat, frame_pts
    xyz = np.array([[p['x'], p['y'], p['z']] for p in height_pts], dtype=np.float32)
    c = np.array([np.median(xyz[:, 0]), np.percentile(xyz[:, 1], RF30_Y_PERCENTILE),
                  np.median(xyz[:, 2])], dtype=np.float32)
    z_vel = float(prev_c[1] - c[1]) if prev_c is not None else 0.0
    raw_acc = ((z_vel - float(prev_zvel)) / dt
               if dt is not None and dt > 1e-6 and prev_c is not None else 0.0)
    z_accel = float(ema_a * raw_acc + (1.0 - ema_a) * float(ema_zacc))
    feat[:3] = c; feat[7] = z_vel; feat[8] = z_accel
    return feat, height_pts


def _rf30_fall_score(win):
    if not RF30_OK:
        return None
    feats = _rf_features(win)
    classes = list(RF30_MODEL.classes_)
    if 'fall' not in classes:
        raise ValueError(f'RF30 classes에 fall 없음: {classes}')
    return float(RF30_MODEL.predict_proba([feats])[0, classes.index('fall')])


# ═══════════════════════════════════════════════════════════
# 3. SHARED STATE
# ═══════════════════════════════════════════════════════════
_lock = threading.RLock()
state = {
    'phase':             PH_READY,
    'warmup_count':      0,
    'start_requested':   False,
    'train_requested':   False,
    'reset_requested':   False,
    'arm_reset_requested': False,
    'resolve_requested': False,
    'latest_pts':       [],
    'cz_h':   deque([1.7] * HISTORY_LEN, maxlen=HISTORY_LEN),
    'sc_h':   deque([0.0] * HISTORY_LEN, maxlen=HISTORY_LEN),
    'ds_h':   deque([0.0] * HISTORY_LEN, maxlen=HISTORY_LEN),
    'ev_active':  False,
    'ev_type':    None,
    'ev_sev':     'normal',
    'ev_conf':    0.0,
    'ev_zone':    RADAR_ZONE,   # [7/31] 'C' 고정이었음 — 레이더는 A 에 있다
    'ev_id':      0,      # 새 경보 latch마다 +1 -> 노트북이 RAG 트리거 판단
    'threshold':  0.01,
    'pre_alert':   '',
    'scan_left':   None,
    'prepare_step': '',  # empty_scan / step_in / baseline / wait_train
    'logs': deque(maxlen=20),
    'incidents': deque(maxlen=20),
    'last_data_t': 0.0,
    'data_ok':     False,
    # ── [7/31] 판단 근거 (L2 카드 재료). classify() 가 채운 값을 그대로 보관 ──
    'ev_ts':        0.0,
    'ev_evidence':  None,     # ⚠ None 가능 — 소비측(노트북)은 반드시 방어할 것
    'ev_gates':     None,
    'ev_rejected':  [],
    # ── [7/31] 전기 설비. 하드 도착 전까지 _read_power() 가 모의값 생성 ──
    'power': {'curr': None, 'volt': None, 'src': 'unavailable'},
    # ── [7/31] 노트북 3D/수치 패널용 프레임 요약 ──
    'centroid':   None,
    'height':     None,
    'dop_std':    0.0,
    'zone_state': {},
    'occupied': False,       # 운영자가 입실/퇴실 버튼으로 확정한 재실 상태
    'occupancy_reset_requested': False,
    'track_state': 'absent', # UI 호환: occupied=True일 때만 tracking
    'track_anchor': None,
}


# ═══════════════════════════════════════════════════════════
# 3-B. BREAKER  [7/31 이관: 노트북 -> 젯슨]
# ═══════════════════════════════════════════════════════════
#  이전엔 console_ui.py(노트북)가 BreakerLogic 을 직접 돌렸다. 그러면
#  "링크가 끊겨도 젯슨은 판정·차단을 독립 수행한다"(데이터 인터페이스 명세 원칙 4)
#  가 코드로 거짓이 된다 — 노트북이 죽으면 차단도 안 됐다.
#  → 판정·차단 실행은 젯슨. 노트북은 상태 표시와 '재투입 요청'만.
#
#  ⚠ 미검증 구간: 스마트 차단기 하드웨어(Modbus) 미도착. 지금은 _read_power()
#    가 모의값을 만든다. 하드 도착 후 _read_power() 한 함수만 교체하면 된다.
#    (breaker_facility_sim.py 의 'PORTABLE 이식 경계' 구획을 그대로 가져옴)
#  ⚠ [8/01] VIB_ZONE 이 'C'(조립) 로 고정돼 있었다. 그런데 C 는 장비 미설치
#    구역이고, 진동은 이 레이더의 도플러(dop_std)로 재는 것이라 물리적으로
#    레이더가 설치된 구역의 값이다. radar_common.EVENT_ZONE 도 vibration_anomaly
#    를 RADAR_ZONE 으로 매핑하고 있어서 같은 사건이 경로에 따라 A 와 C 로
#    갈라져 보고됐다. → 둘 다 레이더 설치 구역으로 통일한다.
#    (레이더를 여러 대로 늘릴 때 구역별로 나누면 된다)
ELEC_ZONE = RADAR_ZONE      # 변전실 — 전류/전압 이상
VIB_ZONE  = RADAR_ZONE      # 진동은 이 레이더의 도플러로 잰다 = 레이더 설치 구역

RELAY_PORT = '/dev/ttyUSB2'
RELAY_BAUD = 9600
RELAY_ADDR = 1
RELAY_CH   = 0              # Modbus CH1. NO 배선: 코일 ON=정상 투입, OFF=차단
INA_BUS    = '/dev/i2c-7'
INA_ADDR   = 0x41
INA_SHUNT_OHM = 0.005       # M5Stack INA226 10A Isolated 공식 사양: 5 mΩ


class RelayRTU:
    """NO 접점 CH1을 쓰는 최소 Modbus RTU 릴레이 드라이버."""

    def __init__(self):
        self.connected = False
        self.error = None
        self._lk = threading.Lock()

    @staticmethod
    def _crc16(data):
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        return bytes((crc & 0xFF, crc >> 8))

    def _exchange(self, body, size):
        import serial
        frame = body + self._crc16(body)
        with serial.Serial(RELAY_PORT, RELAY_BAUD, timeout=0.5) as port:
            port.reset_input_buffer()
            port.write(frame)
            port.flush()
            reply = port.read(size)
        if len(reply) != size or reply[-2:] != self._crc16(reply[:-2]):
            raise OSError(f'Modbus 응답 오류: {reply.hex() or "없음"}')
        return reply

    def _read_unlocked(self):
        reply = self._exchange(bytes((RELAY_ADDR, 0x01, 0, RELAY_CH, 0, 1)), 6)
        if reply[:3] != bytes((RELAY_ADDR, 0x01, 0x01)):
            raise OSError(f'Modbus 상태 응답 불일치: {reply.hex()}')
        return bool(reply[3] & 0x01)

    def read(self):
        with self._lk:
            try:
                # NO 접점은 코일이 꺼지면 열린다. 무여자 상태를 차단으로 해석한다.
                tripped = not self._read_unlocked()
                self.connected, self.error = True, None
                return tripped
            except Exception as exc:
                self.connected, self.error = False, str(exc)
                return None

    def write(self, tripped):
        """NO 접점: True면 코일 OFF로 차단, False면 코일 ON으로 투입."""
        with self._lk:
            try:
                coil_on = not tripped
                value = 0xFF if coil_on else 0x00
                body = bytes((RELAY_ADDR, 0x05, 0, RELAY_CH, value, 0))
                reply = self._exchange(body, 8)
                if reply[:-2] != body or self._read_unlocked() != coil_on:
                    raise OSError(f'Modbus 쓰기 검증 실패: {reply.hex()}')
                self.connected, self.error = True, None
                return True
            except Exception as exc:
                self.connected, self.error = False, str(exc)
                print(f'[BREAKER ERROR] {exc}', flush=True)
                return False


RELAY = RelayRTU()


def classify_equipment(curr, volt, dop_std):
    """전기(전류/전압) + 기계(도플러 진동) 융합 판정 — 순수 함수."""
    out = []
    if curr > CURR_LIMIT:
        out.append({'event_type': 'overcurrent', 'zone_id': ELEC_ZONE,
                    'severity': 'critical', 'value': round(curr, 3), 'limit': CURR_LIMIT,
                    'msg': f'Overcurrent {curr:.2f} A (> {CURR_LIMIT} A)'})
    if volt < VOLT_MIN:
        out.append({'event_type': 'voltage_drop', 'zone_id': ELEC_ZONE,
                    'severity': 'critical', 'value': round(volt, 1), 'limit': VOLT_MIN,
                    'msg': f'Voltage drop {volt:.1f} V (< {VOLT_MIN} V)'})
    if dop_std > VIB_DS_THRESH:
        out.append({'event_type': 'vibration_anomaly', 'zone_id': VIB_ZONE,
                    'severity': 'critical', 'value': round(dop_std, 3),
                    'limit': VIB_DS_THRESH,
                    'msg': f'Abnormal vibration dop_std {dop_std:.3f} (> {VIB_DS_THRESH})'})
    return out


class BreakerLogic:
    """Zone별 스마트 차단기 상태머신.  'ON'(투입) | 'TRIPPED'(개방)

    LOTO: 이상 -> 자동 TRIP. 상황이 해소돼도 자동 복구하지 않는다.
          사람이 restore() 를 호출해야만 ON 복귀 (restart prevention).
    """

    def __init__(self):
        self.state = {z: 'ON' for z in ZONE_IDS}
        self.reason = {z: None for z in ZONE_IDS}
        self._lk = threading.Lock()
        actual = RELAY.read()
        if actual is True:
            self.state[RADAR_ZONE] = 'TRIPPED'
            self.reason[RADAR_ZONE] = 'startup_readback'

    def trip(self, zone, reason=''):
        """단일 Zone 차단. 새로 차단됐으면 True."""
        with self._lk:
            if self.state.get(zone) == 'ON':
                if zone != RADAR_ZONE or not RELAY.write(True):
                    return False
                self.state[zone] = 'TRIPPED'
                self.reason[zone] = reason
                return True
        return False

    def on_anomalies(self, anomalies):
        """이상 발생 Zone 자동 차단. 이번에 새로 TRIP 된 Zone 리스트 반환."""
        return [a['zone_id'] for a in anomalies
                if self.trip(a['zone_id'], a.get('event_type', ''))]

    def restore(self, zones=None):
        """사람이 직접 재투입. 복구된 Zone 반환."""
        with self._lk:
            tgt = zones or [z for z, s in self.state.items() if s == 'TRIPPED']
            done = [z for z in tgt if self.state.get(z) == 'TRIPPED']
            for z in done:
                if z != RADAR_ZONE or not RELAY.write(False):
                    continue
                self.state[z] = 'ON'
                self.reason[z] = None
            return [z for z in done if self.state.get(z) == 'ON']

    def tripped_zones(self):
        return [z for z, s in self.state.items() if s == 'TRIPPED']

    def any_tripped(self):
        return any(s == 'TRIPPED' for s in self.state.values())

    def snapshot(self):
        with self._lk:
            return {'state': dict(self.state), 'reason': dict(self.reason),
                    'src': 'modbus' if RELAY.connected else 'unavailable',
                    'connected': RELAY.connected, 'error': RELAY.error}


BREAKER = BreakerLogic()


def _read_power():
    """INA226의 버스 전압과 션트 전압을 읽어 12V LED 부하를 실측한다."""
    import fcntl
    fd = None
    try:
        fd = os.open(INA_BUS, os.O_RDWR)
        fcntl.ioctl(fd, 0x0703, INA_ADDR)  # I2C_SLAVE

        def _reg16(reg, signed=False):
            os.write(fd, bytes((reg,)))
            raw = os.read(fd, 2)
            if len(raw) != 2:
                raise OSError(f'INA226 register 0x{reg:02X} short read')
            value = (raw[0] << 8) | raw[1]
            return value - 0x10000 if signed and value & 0x8000 else value

        shunt_v = _reg16(0x01, signed=True) * 2.5e-6
        voltage = _reg16(0x02) * 1.25e-3
        current = shunt_v / INA_SHUNT_OHM
        return {'curr': round(current, 4), 'volt': round(voltage, 4),
                'watt': round(voltage * current, 3), 'src': 'ina226',
                'connected': True, 'error': None}
    except Exception as exc:
        print(f'[INA226 ERROR] {exc}', flush=True)
        return {'curr': None, 'volt': None, 'watt': None,
                'src': 'unavailable', 'connected': False, 'error': str(exc)}
    finally:
        if fd is not None:
            os.close(fd)


def add_log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    with _lock:
        state['logs'].append(f'[{ts}] {msg}')
    print(f'[LOG {ts}] {msg}')


def _latch_event(et, clf, zn, ts, score_x):
    """경보 latch. caller가 _lock 보유 가정 (RLock이라 재진입 안전).

    [7/31] classify() 가 채운 evidence/gates/rejected 를 state 에 보관한다.
      이 값들이 노트북 L2 '판단 근거' 카드의 재료다. 여기서 안 담으면
      노트북은 또 그래프밖에 못 그린다(README 7/27 A절).
    ⚠ RAG/LLM 은 호출하지 않는다 — 노트북 담당(7/28 아키텍처).
    """
    state.update({
        'ev_active': True, 'ev_type': et,
        'ev_sev': clf['severity'], 'ev_conf': clf['confidence'], 'ev_zone': zn,
        'ev_id': state.get('ev_id', 0) + 1,
        'ev_ts': time.time(),                       # 젯슨 시각(참고용). 경과시간은
                                                    #   노트북이 '수신 시각' 기준으로 센다.
        'ev_evidence': clf.get('evidence'),         # ⚠ None 일 수 있음(피처 계산 전 조기 return)
        'ev_gates':    clf.get('gates'),
        'ev_rejected': clf.get('rejected') or [],
    })
    lbl = EVENT_LABELS.get(et, et)
    state['logs'].append(
        f'[{ts}] ALERT Zone {zn}: {lbl} (conf={clf["confidence"]:.0%} score={score_x:.1f}x)')
    state['incidents'].append({'type': et, 'zone': zn, 'detected': ts, 'resolved': None})

    # ── 차단기: 판정과 차단은 젯슨이 실행한다 (fail-safe) ──
    #   링크가 끊겨도 차단은 이미 여기서 일어난 뒤다. 노트북은 결과를 볼 뿐이고
    #   재투입만 요청할 수 있다. 이것이 "노트북이 죽어도 안전하다"의 코드 근거다.
    # ⚠⚠ 이 한 줄이 '전원을 끊을지' 를 정한다. classify() 의 severity 다.
    #   radar_common.EVENT_SEV(표시 등급)와 절대 헷갈리지 말 것 —
    #   그쪽을 바꿔도 여기는 안 바뀌고, 여기를 바꾸면 차단이 바뀐다.
    if clf['severity'] == 'critical':
        tripped = BREAKER.trip(zn, reason=et)
        if tripped:
            state['logs'].append(f'[{ts}] BREAKER TRIP Zone {zn} <- {lbl}')
        else:
            state['logs'].append(
                f'[{ts}] BREAKER TRIP FAILED Zone {zn}: {RELAY.error or "미지원 구역"}')


# ═══════════════════════════════════════════════════════════
# 4. CLASSIFY  (실측 튜닝 규칙 -- 원본 그대로)
# ═══════════════════════════════════════════════════════════
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

    중요: 낙상은 '도플러 격렬함' + '수평 무너짐'으로 잡음(실측 확인).
          [7/8 재측정] 클러터 도입 후 clean 82샘플: 쓰러진 centroid 종료높이 중앙 0.75m,
          순간 최저 0.18m (구 주석 '~1.4m 유지'는 노이즈 시절 값이라 폐기).
          단 절대높이는 CEILING_H 의존이라 판정 피처로 안 쓰고 도플러/상대값 위주 유지.
    """
    win = [f for f in feat_win if float(f[6]) > 0]        # n_pts>0 프레임만 집계
    if not win:
        # ⚠ 유일하게 evidence가 None인 경로 — 피처 계산 전에 빠져나간다.
        #    소비측(노트북)은 evidence None을 반드시 방어할 것.
        return {'event_type': 'normal', 'severity': 'normal', 'confidence': 0.0,
                'evidence': None, 'gates': None, 'rejected': []}

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

    # ═══ [2026-07-29 신규] 판정 근거(evidence) 수집 — 판정 로직 무변경 ═══
    #  지금까지 아래 수치는 전부 계산된 뒤 return에서 버려졌다. L2 판단 근거 카드가
    #  이 값들로 만들어지므로(데이터_인터페이스_명세_v1.md 3장) 결과 dict에 실어 보낸다.
    #  ⚠ 이 블록은 어떤 조건문에도 관여하지 않는다. 값을 담기만 한다.
    _impulse_ratio = dopstd_max / max(0.15, ds_first)
    _ev = {
        'dopstd_max': round(dopstd_max, 3), 'dopstd_mean': round(dopstd_mean, 3),
        'ds_first': round(ds_first, 3),     'ds_last': round(ds_last, 3),
        'ds_broad': int(ds_broad),          'impulse_ratio': round(_impulse_ratio, 2),
        'h_drop': round(h_drop, 3),
        'h_desc': (round(h_desc, 3) if h_desc is not None else None),
        'horiz_range': round(horiz_range, 3), 'zacc_amp': round(zacc_amp, 1),
        'n_mean': round(n_mean, 1),           'n_p75': round(n_p75, 1),
        'height_start': round(CEILING_H - cy_vals[0], 2),
        'height_end':   round(CEILING_H - cy_vals[-1], 2),
        'ae_score': round(float(score), 4),   'ae_thr': round(float(thr), 4),
    }
    #  게이트 통과표 — LLM이 근거를 지어내지 않도록 젯슨이 사실로 확정해 보낸다.
    #  ⚠ zacc는 제외: FALL_ZACC_MIN=0 이라 게이트가 무력화 상태이고 주석 수치의
    #     스케일이 642행 zacc_amp>=400 과 맞지 않는다(실측 재확인 후 승격).
    _gates = {
        'impulse':  {'value': round(_impulse_ratio, 2), 'thr': 2.2,  'unit': '비율',
                     'cmp': '>=', 'pass': bool(_impulse_ratio >= 2.2)},
        'h_drop':   {'value': round(h_drop, 3),      'thr': 0.43, 'unit': 'm',
                     'cmp': '>=', 'pass': bool(h_drop >= 0.43)},
        'horiz':    {'value': round(horiz_range, 3), 'thr': 0.6,  'unit': 'm',
                     'cmp': '>=', 'pass': bool(horiz_range >= 0.6)},
        'ds_last':  {'value': round(ds_last, 3),     'thr': 1.0,  'unit': 'm/s',
                     'cmp': '<=', 'pass': bool(ds_last <= 1.0)},
        'ds_broad': {'value': int(ds_broad),         'thr': 2,    'unit': '프레임',
                     'cmp': '>=', 'pass': bool(ds_broad >= 2)},
    }
    def _mk(et, sev, cf, rejected=None):
        return {'event_type': et, 'severity': sev, 'confidence': cf,
                'evidence': _ev, 'gates': _gates, 'rejected': (rejected or [])}
    # ═══════════════════════════════════════════════════════════════════

    # 0) 빈 공간 / 노이즈: 포인트 거의 없음 -> 무조건 정상.
    #    (케이블이 한 프레임 튀어도 여기서 차단 -> 빈방 오경보 방지)
    if n_mean < 4:
        return _mk('normal', 'normal', 0.0)

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
            # 기각 후보 — L2 카드 "왜 다른 게 아닌가" 줄. 실측 근거를 사실로 확정해 전달.
            _rej = []
            if horiz_range >= 0.6:
                _rej.append({'candidate': 'fast_sit',
                             'reason': f'horiz_range {horiz_range:.2f} >= 0.6 '
                                       f'(제자리 앉기는 수평 고정, 실측 0.35~0.79)'})
            if h_drop >= 0.5:
                _rej.append({'candidate': 'vibration',
                             'reason': f'h_drop {h_drop:.2f} >= 0.5 '
                                       f'(고정 진동원은 위치 고정이라 높이변화 작음)'})
            return _mk('fall_detected', 'critical',
                       round(min(0.99, conf + 0.10 + _acc_boost), 2), _rej)

    # 2) [2026-07-02 3차 패치] 정지형(협착/감전) 규칙은 classify에서 제거됨.
    #    옛 규칙(dop_std<0.6, 8<=n_mean<18)은 라이브에서 n이 4~7로 잡혀 미달했고,
    #    n 하한을 내리면 '가만히 서있기'와 구분 불가(feature 동일 - 실측 확인).
    #    -> pipeline_loop의 Zone+지속시간 게이트(DANGER_ZONES, STAT_HOLD_SEC)가 담당.

    # 3) 보행 / 정상 활동 -> 경보 없음
    #    [2026-07-02 패치] n_mean>=18 -> n_p75>=15: 라이브에선 FOV 가장자리/전이
    #    프레임이 섞여 평균이 희석됨(실측 walk 24~38이 라이브에선 절반까지 하락).
    #    "일부 프레임이라도 포인트가 많으면 사람 활동"으로 인정.
    if n_p75 >= 15:
        return _mk('normal', 'normal', 0.0)

    # 4) 지속적 동요만 경고 -- 창 전반부/후반부 '둘 다' 0.40 이상이어야 진동.
    #    [2026-07-02 패치] 걷기 dop_std 평균(0.41~0.48)이 문턱 0.40 바로 위라
    #    보행/앉기 전이 창이 평균만으로 진동에 걸렸음. 진동은 정의상 지속적
    #    -> 창 양쪽 절반 모두에서 유지될 때만 인정 (앉기 등 일과성 동작 제외).
    #    [7/3 패치] + h_drop < 0.5: 사람 이동/FOV 퇴장 전이 창은 h_drop 0.57~2.40
    #    (오늘 오탐 후보 6건 실측 전부) vs 고정 진동원은 위치 고정 -> 높이변화 작음.
    #    선풍기 VIB 수집 후 이 문턱 재검증 예정.
    if ds_first >= 0.40 and ds_last >= 0.40 and h_drop < 0.5:
        return _mk('vibration_anomaly', 'warning',
                   round(min(0.75, 0.40 + 0.10 * excess), 2))

    # 5) 그 외 (미미한 움직임) -> 정상
    return _mk('normal', 'normal', 0.0)

# ═══════════════════════════════════════════════════════════
# 5. NETWORK  (제어 수신 + 상태 송신)
# ═══════════════════════════════════════════════════════════
_clients      = {}            # addr(tuple) -> last_seen(float)
_clients_lock = threading.Lock()


def _register(addr):
    with _clients_lock:
        _clients[(addr[0], DATA_PORT)] = time.time()


def _targets():
    now = time.time()
    with _clients_lock:
        for a in [a for a, t in _clients.items() if now - t > CLIENT_TTL]:
            _clients.pop(a, None)
        out = list(_clients.keys())
    if LAPTOP_IP:
        static = (LAPTOP_IP, DATA_PORT)
        if static not in out:
            out.append(static)
    return out


def control_listener():
    """노트북 버튼 명령 + HELLO 수신."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', CTRL_PORT))
    print(f'[NET] 제어 포트 {CTRL_PORT} 대기 중 (노트북 HELLO/버튼 명령)')
    known = set()
    while True:
        try:
            data, addr = sock.recvfrom(4096)
        except OSError as e:
            print('[NET] 제어 수신 에러:', e); time.sleep(0.5); continue
        try:
            msg = json.loads(data.decode('utf-8'))
        except Exception:
            continue
        _register(addr)
        if addr[0] not in known:
            known.add(addr[0])
            add_log(f'뷰어 연결됨: {addr[0]}')
        cmd = msg.get('cmd')
        if cmd in (None, CMD_HELLO):
            continue
        ts = datetime.now().strftime('%H:%M:%S')
        with _lock:
            phase = state['phase']
            if cmd == CMD_START:
                if phase == PH_READY:
                    state['start_requested'] = True
                    state['logs'].append(f'[{ts}] [BTN] Start Baseline -- EMPTY ROOM first (12s scan)!')
                elif phase == PH_WAIT_TRAIN:
                    state['train_requested'] = True
                    state['logs'].append(f'[{ts}] [BTN] Start Training -- stand still!')
                elif phase == PH_WAIT_ARM:
                    state['phase'] = PH_LIVE
                    state['arm_reset_requested'] = True
                    state['logs'].append(f'[{ts}] [BTN] Monitoring armed -- LIVE detection active')
            elif cmd == CMD_TRAIN:
                state['train_requested'] = True
            elif cmd == CMD_RESET:
                state['reset_requested'] = True
            elif cmd == CMD_ENTER:
                state['occupied'] = True
                state['occupancy_reset_requested'] = True
                state['track_state'] = 'tracking'
                state['track_anchor'] = None
                state['logs'].append(f'[{ts}] [BTN] 작업자 입실 확인')
            elif cmd == CMD_EXIT:
                state['occupied'] = False
                state['occupancy_reset_requested'] = True
                state['track_state'] = 'absent'
                state['track_anchor'] = None
                state['pre_alert'] = ''
                state['logs'].append(
                    f'[{ts}] [BTN] 작업자 퇴실 확인 — 신규 사고 판정 중지, 기존 경보·차단 유지')
            elif cmd == CMD_RESOLVE:
                state['resolve_requested'] = True
            elif cmd == CMD_RESTORE:
                # [7/31] 전력 재투입. 노트북은 '요청'만 하고 실행은 젯슨이 한다.
                #   노트북 UI 가 이미 LOTO 체크 3개를 받은 뒤에만 보낸다.
                zs = msg.get('zones') or None
                done = BREAKER.restore(zs)
                state['logs'].append(
                    f'[{ts}] BREAKER RESTORE {done or "(대상 없음)"} <- 노트북 {addr[0]}')
        print(f'[{ts}] [CMD] {cmd} from {addr[0]}')


def _slim(pts):
    """전송 크기 축소: 필요한 필드만, 반올림."""
    return [{'x': round(float(p['x']), 3),
             'y': round(float(p['y']), 3),
             'z': round(float(p['z']), 3),
             'i': round(float(p['intensity']), 1)} for p in pts]


def _pack(base, pts):
    """MAX_UDP 이하가 될 때까지 포인트를 절반씩 솎아내며 직렬화."""
    while True:
        base['points'] = pts
        payload = json.dumps(base, separators=(',', ':')).encode('utf-8')
        if len(payload) <= MAX_UDP or len(pts) <= MIN_PTS:
            return payload
        pts = pts[::2]


def sender_loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
    period = 1.0 / SEND_HZ
    seq = 0
    while True:
        time.sleep(period)
        tg = _targets()
        if not tg:
            continue
        seq += 1
        # [7/31] 히스토리(cz/ds/sc 각 120개) + logs + incidents 를 매 패킷에 실으면
        #   페이로드가 약 3.9 KB → 이더넷 MTU 1500 을 넘어 IP 단편화가 일어난다.
        #   유선이면 무해하지만 WiFi 에서는 조각 하나만 잃어도 패킷 전체가 사라진다.
        #   → 히스토리는 1초에 한 번만(full 패킷). 평시 패킷은 단일 프레임에 들어간다.
        #   stateless 복구 지연은 최대 1초 — 그래프 갱신 주기로 충분하다.
        full = (seq % max(1, int(SEND_HZ)) == 0)
        with _lock:
            # stateless 재전송: 패킷 하나 잃어도 다음 패킷이 상태를 복구한다.
            #   UDP 유실 약점을 이 설계로 상쇄한다.
            pkt = {
                'schema_version': SCHEMA_VERSION,
                'seq':          seq,
                'ts':           time.time(),
                'phase':        state['phase'],
                'warmup_count': state['warmup_count'],
                'threshold':    state['threshold'],
                'data_ok':      state['data_ok'],
                'data_age':     (time.time() - state['last_data_t']) if state['last_data_t'] else 1e9,
                'scan_left':    state['scan_left'],
                'prepare_step': state['prepare_step'],
                'pre_alert':    state['pre_alert'],
                'ev': {
                    'active': state['ev_active'], 'type': state['ev_type'],
                    'sev':    state['ev_sev'],    'conf': state['ev_conf'],
                    'zone':   state['ev_zone'],   'id':   state['ev_id'],
                    'ts':     state['ev_ts'],
                    # ── [7/31] L2 판단 근거. 이게 없으면 노트북은 그래프밖에 못 그린다 ──
                    'evidence': state['ev_evidence'],   # None 가능
                    'gates':    state['ev_gates'],      # None 가능
                    'rejected': state['ev_rejected'],
                },
                # ── [7/31] 전기 설비: 판정·차단은 젯슨이 했고 결과만 보낸다 ──
                'power':   dict(state['power']),
                'breaker': BREAKER.snapshot(),
                'full': full,
                'n_pts': len(state['latest_pts']),   # 다운샘플 전 실제 포인트 수
                'centroid': state.get('centroid'),
                'height':   state.get('height'),
                'dop_std':  state.get('dop_std', 0.0),
                'zone_state': state.get('zone_state') or {},
                'track_state': state.get('track_state', 'absent'),
                'track_anchor': state.get('track_anchor'),
                'occupied': state.get('occupied', False),
                'cfg': {'N_WARMUP': N_WARMUP, 'SCAN_SEC': SCAN_SEC,
                        'CEILING_H': CEILING_H, 'JSON_PATH': JSON_PATH,
                        'CURR_LIMIT': CURR_LIMIT, 'VOLT_MIN': VOLT_MIN,
                        'VIB_DS_THRESH': VIB_DS_THRESH},
            }
            if full:
                pkt.update({
                    'cz': [round(v, 3) for v in state['cz_h']],
                    'ds': [round(v, 3) for v in state['ds_h']],
                    'sc': [round(v, 7) for v in state['sc_h']],
                    'logs': list(state['logs']),
                    'incidents': list(state['incidents']),
                })
            pts = _slim(state['latest_pts'])
        payload = _pack(pkt, pts)
        for addr in tg:
            try:
                sock.sendto(payload, addr)
            except OSError as e:
                print('[NET] 송신 실패', e, 'size=', len(payload))


# ═══════════════════════════════════════════════════════════
# 6. PIPELINE THREAD
# ═══════════════════════════════════════════════════════════
def pipeline_loop():
    lms         = LMSFilter()
    feat_buf    = []
    clf_buf     = []
    rf30_buf    = []
    warmup_feat = []
    prev_c      = None
    prev_zvel   = 0.0
    prev_ts     = None
    ema_zacc    = 0.0
    # [8/11] classify 전용 계열(클러터 제거 전)의 이전 프레임 상태.
    prev_c_full    = None
    prev_zvel_full = 0.0
    ema_zacc_full  = 0.0
    prev_c_rf30    = None
    prev_zvel_rf30 = 0.0
    ema_zacc_rf30  = 0.0
    anom_streak = 0
    pend_et     = None
    pend_cnt    = 0
    fall_hits   = []
    fall_pending   = None
    recover_streak = 0
    stat_since  = None
    stat_miss   = 0
    stat_zone   = None
    stat_pre    = False
    stat_log_t  = 0.0
    stat_ax = stat_az = 0.0
    stat_hits = stat_tot = 0
    ae_error_logged = False
    stat_last_hit = 0.0
    track_log_t = 0.0
    last_motion_t = -1e9
    motion_run = 0
    def _track_log(points_n, centroid, now):
        """현장 진단용 수동 재실 상태를 1초에 한 번 즉시 출력한다."""
        nonlocal track_log_t
        if now - track_log_t < 1.0:
            return
        track_log_t = now
        ctext = ('none' if centroid is None else
                 f'({centroid[0]:.3f},{centroid[1]:.3f},{centroid[2]:.3f})')
        with _lock:
            occupied = state['occupied']
        print(f'[OCCUPANCY] state={"occupied" if occupied else "vacant"} '
              f'centroid={ctext} points={points_n}', flush=True)

    clutter_spots = list(CLUTTER_SPOTS)
    scan_buf      = []
    scan_until    = None
    step_out_until = None    # [8/11] 퇴장 유예 종료 시각 (None = 유예 중 아님)
    step_in_until = None
    # 기존 JSONL은 과거 기록이다. 재시작 때 100MB 전체를 재생하면 옛 사람으로
    # 트랙·정지 타이머가 즉시 생긴다. 시작 이후 추가되는 프레임만 읽는다.
    try:
        read_offset = os.path.getsize(JSON_PATH)
    except OSError:
        read_offset = 0
    model       = None
    scaler      = None
    ae_disabled = False          # [7/31] True = AE 학습 실패로 규칙 전용 LIVE 로 강등된 상태
    thr         = 0.01

    add_log('Pipeline started -- waiting for radar data')

    def _finish_scan():
        nonlocal clutter_spots, scan_until
        learned = build_clutter_map(scan_buf)
        clutter_spots = learned + list(CLUTTER_SPOTS)
        scan_until = None
        with _lock:
            state['scan_left'] = None
            state['prepare_step'] = 'step_in'
        spots_txt = ', '.join(f'(x{x:+.2f},y{y:+.2f},z{z:+.2f})' for x, y, z, _, _ in learned) or 'none'
        add_log(f'Scan done: {len(learned)} clutter spot(s) learned [{spots_txt}]')
        add_log(f'>> STEP IN NOW -- OFF-NADIR (to the SIDE). Collection starts in {int(STEP_IN_SEC)}s.')

    # ── 저장된 baseline 재사용: 있으면 스캔/웜업/학습 건너뛰고 바로 LIVE ──
    if LOAD_BASELINE and os.path.exists(BASELINE_PATH):
        try:
            try:
                ck = torch.load(BASELINE_PATH, map_location=DEVICE, weights_only=False)
            except TypeError:
                ck = torch.load(BASELINE_PATH, map_location=DEVICE)
            _saved_dim = None
            try:
                _saved_dim = int(getattr(ck.get('scaler'), 'n_features_in_', None)
                                 or ck['model']['enc1.weight_ih_l0'].shape[1])
            except Exception:
                _saved_dim = None
            if _saved_dim is not None and _saved_dim != FEATURE_DIM:
                raise ValueError(
                    f'저장된 baseline은 {_saved_dim}차원인데 현재 모델은 {FEATURE_DIM}차원입니다 '
                    f'-> [RESET] 후 빈방 스캔+베이스라인 재수집+재학습 필요.')
            model = LSTM_AE(FEATURE_DIM, 16, SEQ_LEN).to(DEVICE)
            model.load_state_dict(ck['model'])
            model.eval()
            scaler = ck['scaler']
            thr    = float(ck['thr'])
            _raw_clut = [tuple(s) for s in ck.get('clutter', [])]
            _old_fmt  = bool(_raw_clut) and any(len(s) != 5 for s in _raw_clut)
            if _old_fmt:
                _raw_clut = []
            clutter_spots = _raw_clut or list(CLUTTER_SPOTS)
            with _lock:
                state['threshold'] = thr
                state['phase']     = PH_LIVE
            add_log(f'Baseline LOADED (thr={thr:.5f}, clutter {len(clutter_spots)} spots) '
                    f'-- LIVE now. Radar moved? press RESET.')
            if _old_fmt:
                add_log('⚠ 구 클러터 포맷(2D) 감지 -> 무효화됨. [RESET] 후 재스캔 필요.')
        except Exception as e:
            model, scaler, thr = None, None, 0.01
            add_log(f'⚠ Baseline load failed: {e}')
            add_log('>> 9차원 feature로 재학습이 필요합니다. [START] 눌러 재수집하세요.')

    while True:
        # 수동 입·퇴실 전환 시 이전 사람의 판정 상태를 다음 사람에게 넘기지 않는다.
        # 기존에 이미 확정된 경보와 차단은 상황 종료/재투입 절차 전까지 유지한다.
        with _lock:
            occupancy_reset = state['occupancy_reset_requested']
            state['occupancy_reset_requested'] = False
        if occupancy_reset:
            feat_buf.clear(); clf_buf.clear(); rf30_buf.clear()
            prev_c = None; prev_zvel = 0.0; ema_zacc = 0.0
            prev_c_full = None; prev_zvel_full = 0.0; ema_zacc_full = 0.0
            prev_c_rf30 = None; prev_zvel_rf30 = 0.0; ema_zacc_rf30 = 0.0
            anom_streak = 0; pend_et = None; pend_cnt = 0
            fall_hits.clear(); fall_pending = None; recover_streak = 0
            stat_since = None; stat_zone = None; stat_miss = 0; stat_pre = False
            stat_hits = stat_tot = 0; motion_run = 0; last_motion_t = -1e9
            with _lock:
                state['pre_alert'] = ''

        # 준비 단계에서 만든 사람 트랙을 감시로 넘기면, 기준 수집 후 퇴장한 사람이
        # LIVE 시작과 동시에 lost_in_zone이 되어 빈방 무동작 경보를 만든다.
        with _lock:
            arm_reset = state['arm_reset_requested']
            state['arm_reset_requested'] = False
        if arm_reset:
            stat_since = None; stat_zone = None; stat_miss = 0; stat_pre = False
            stat_hits = stat_tot = 0
            with _lock:
                state['track_state'] = 'tracking' if state['occupied'] else 'absent'
                state['track_anchor'] = None
                state['latest_pts'] = []
                state['centroid'] = None
                state['pre_alert'] = ''

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
                state['ev_type']          = None
                state['ev_sev']           = 'normal'
                state['ev_conf']          = 0.0
                state['pre_alert']        = ''
                state['prepare_step']     = ''
                state['threshold']        = 0.01
                state['logs'].append(
                    f'[{datetime.now().strftime("%H:%M:%S")}] '
                    f'RESET -- click Start Baseline to recollect')
                do_reset = True

        if do_reset:
            try:
                os.remove(BASELINE_PATH)
                add_log(f'Baseline file deleted: {BASELINE_PATH}')
            except FileNotFoundError:
                add_log('Baseline file already absent')
            except OSError as e:
                add_log(f'Baseline file delete FAILED: {e}')
            lms         = LMSFilter()
            feat_buf    = []
            clf_buf     = []
            rf30_buf    = []
            warmup_feat = []
            prev_c      = None
            prev_zvel   = 0.0
            prev_ts     = None
            ema_zacc    = 0.0
            prev_c_full    = None
            prev_zvel_full = 0.0
            ema_zacc_full  = 0.0
            prev_c_rf30    = None
            prev_zvel_rf30 = 0.0
            ema_zacc_rf30  = 0.0
            anom_streak = 0
            pend_et     = None
            pend_cnt    = 0
            fall_hits   = []
            fall_pending   = None
            recover_streak = 0
            stat_since  = None
            stat_miss   = 0
            stat_zone   = None
            stat_pre    = False
            ae_error_logged = False
            clutter_spots = list(CLUTTER_SPOTS)
            scan_buf    = []
            scan_until  = None
            step_out_until = None
            step_in_until = None
            model       = None
            scaler      = None
            thr         = 0.01
            try:
                read_offset = os.path.getsize(JSON_PATH)
            except OSError:
                read_offset = 0
            with _lock:
                state['occupied'] = False
                state['scan_left'] = None
                state['track_state'] = 'absent'
                state['track_anchor'] = None
                state['latest_pts'] = []
                state['centroid'] = None

        time.sleep(POLL_SEC)

        # ── Load new frames (JSONL, offset-based tail read) ──
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
            read_offset = 0

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
            # 근거리 아티팩트 게이트
            if NEAR_FIELD_MIN_RANGE and frame_pts:
                frame_pts = [p for p in frame_pts if p['y'] >= NEAR_FIELD_MIN_RANGE]
            # 알루미늄 프레임 안쪽만 판정 입력으로 사용한다. 기둥·외부 가구의
            # 반사는 여기서 제거하며 UI에도 같은 필터 후 점만 전달한다.
            if frame_pts:
                frame_pts = [p for p in frame_pts
                             if (FRAME_ROI_X[0] <= p['x'] <= FRAME_ROI_X[1]
                                 and FRAME_ROI_Y[0] <= p['y'] <= FRAME_ROI_Y[1]
                                 and FRAME_ROI_Z[0] <= p['z'] <= FRAME_ROI_Z[1])]
            # 공간 배제
            if EXCLUDE_REGIONS and frame_pts:
                frame_pts = [p for p in frame_pts if not any(
                    r['x'][0] <= p['x'] <= r['x'][1] and r['z'][0] <= p['z'] <= r['z'][1]
                    for r in EXCLUDE_REGIONS)]
            if not frame_pts:
                _track_now = time.time()
                _track_log(0, None, _track_now)
                with _lock:
                    state['latest_pts'] = []
                    state['centroid'] = None
                    state['track_state'] = 'tracking' if state['occupied'] else 'absent'
                    state['track_anchor'] = None
                stat_miss += 1
                if stat_miss >= STAT_MISS_TOL:
                    stat_since = None; stat_zone = None; stat_pre = False
                # [8/11] 퇴장 유예도 여기서 만료시킨다.
                #   이 경로는 '포인트가 하나도 없는 프레임'이다. 사람이 나간 뒤
                #   조용한 방에서는 이쪽만 계속 타므로, 여기서 처리하지 않으면
                #   step_out 이 영원히 안 끝나고 스캔이 시작되지 않는다.
                if step_out_until is not None:
                    if time.time() < step_out_until:
                        with _lock:
                            state['scan_left'] = step_out_until - time.time()
                    else:
                        step_out_until = None
                        scan_until = time.time() + SCAN_SEC
                        with _lock:
                            state['prepare_step'] = 'empty_scan'
                            state['scan_left']    = SCAN_SEC
                        add_log(f'STEP A: EMPTY-ROOM SCAN {int(SCAN_SEC)}s -- everyone OUT of view!')
                elif scan_until is not None:
                    if time.time() < scan_until:
                        with _lock:
                            state['scan_left'] = scan_until - time.time()
                    else:
                        _finish_scan()      # prepare_step='step_in' 은 여기서 설정된다
                        # [8/11] 기존 버그: 이 경로에서 _finish_scan 만 하고
                        #   입장 카운트다운 타이머를 안 걸어 STEP B-0 가 스킵됐다.
                        step_in_until = time.time() + STEP_IN_SEC
                continue

            # [8/11] 클러터 제거 '전' 포인트를 따로 보관한다 -> classify 전용.
            #   왜: 학습된 클러터 스팟이 하필 사람 통행 영역(height 1.1~1.7m)에
            #       걸리면 낙상 순간의 고도플러 포인트까지 배경으로 오인해 지운다.
            #   실측(2026-08-11, stage1_recent.json frame 52350~52900 재계산):
            #       원본->ROI 까지 ds_max 1.108 (문턱 1.05 통과)
            #       -> 클러터 제거 후 0.849 (미달). ROI 안 포인트의 53.4% 가 사라졌다.
            #       clf_decisions.jsonl 기록값 0.849 와 정확히 일치 = 이 경로가 원인.
            #   AE(feat_buf)·정지형 게이트·화면 표시는 그대로 클러터 제거본을 쓴다.
            #   AE 는 클러터 제거된 데이터로 baseline 을 학습했으므로 전처리를
            #   바꾸면 학습/추론이 어긋난다. 정지형은 빈방 오탐 억제가 목적이다.
            frame_pts_full = frame_pts
            # 클러터 점 제거 (스캔 완료 후)
            if CLUTTER_REMOVE_POINTS and scan_until is None and clutter_spots:
                frame_pts = [p for p in frame_pts
                             if not any((p['x'] - _sx) ** 2 + (p['z'] - _sz) ** 2 <= _sr * _sr
                                        and abs(p['y'] - _sy) <= _dy
                                        for _sx, _sy, _sz, _sr, _dy in clutter_spots)]
                if not frame_pts:
                    _track_now = time.time()
                    _track_log(0, None, _track_now)
                    with _lock:
                        state['latest_pts'] = []
                        state['centroid'] = None
                        state['track_state'] = 'tracking' if state['occupied'] else 'absent'
                        state['track_anchor'] = None
                    stat_miss += 1
                    if stat_miss >= STAT_MISS_TOL:
                        stat_since = None; stat_zone = None; stat_pre = False
                    # 높이/AE용 큰 마스크가 전부 지워도 원본 frame_pts_full의
                    # 도플러·RF30 판정까지 버리면 용도 분리가 무효가 된다.
                    # 아래에서 AE는 0점 피처, RF30은 원본 피처로 각각 처리한다.

            with _lock:
                state['last_data_t'] = time.time()

            ys  = [p['y'] for p in frame_pts]
            cz  = CEILING_H - (float(np.mean(ys)) if ys else CEILING_H)
            _now_t = time.time()
            _dt    = (_now_t - prev_ts) if prev_ts is not None else None
            feat = extract_features(frame_pts, prev_c, prev_zvel, _dt, ema_zacc)
            # [8/11] classify 전용 피처. 클러터 제거 전 포인트로 계산한다.
            #   prev_* 를 별도로 추적하는 이유: z_vel/z_accel 은 이전 프레임 centroid
            #   에 의존한다. 클러터 제거본의 prev_c 를 그대로 쓰면 두 계열이 섞여
            #   수직 속도가 실제와 다르게 나온다.
            feat_full = extract_features(frame_pts_full, prev_c_full, prev_zvel_full,
                                         _dt, ema_zacc_full)
            prev_c_full    = feat_full[:3].copy()
            prev_zvel_full = float(feat_full[7])
            ema_zacc_full  = float(feat_full[8])
            feat_rf30, height_pts = _rf30_feature(
                frame_pts_full, prev_c_rf30, prev_zvel_rf30, _dt, ema_zacc_rf30)
            prev_c_rf30    = feat_rf30[:3].copy()
            prev_zvel_rf30 = float(feat_rf30[7])
            ema_zacc_rf30  = float(feat_rf30[8])
            _track_log(len(frame_pts), feat[:3], _now_t)
            ref     = float(np.random.normal(0, 0.004))
            feat[3] = lms.filter(feat[3], ref)
            prev_c    = feat[:3].copy()
            prev_zvel = float(feat[7])
            ema_zacc  = float(feat[8])
            prev_ts   = _now_t

            with _lock:
                state['cz_h'].append(cz)
                state['ds_h'].append(float(feat[4]))
                state['latest_pts'] = height_pts if RF30_OK and height_pts else frame_pts
                # ── [7/31] 노트북 3D/수치 패널용 프레임 요약 ──
                #   포인트 원본은 latest_pts 로 이미 나가고, 여기선 파생값만.
                #   누적·형상추정·렌더는 전부 노트북이 한다(명세 원칙 3).
                _display_feat = feat_rf30 if RF30_OK else feat
                state['centroid'] = {'cx': round(float(_display_feat[0]), 3),
                                     'cy': round(float(_display_feat[1]), 3),
                                     'cz': round(float(_display_feat[2]), 3)}
                state['height']   = round(CEILING_H - float(_display_feat[1]), 3)
                state['dop_std']  = round(float(feat[4]), 3)
                state['track_state'] = 'tracking' if state['occupied'] else 'absent'
                state['track_anchor'] = None
                # ── [7/31] 전기 설비 읽기 + 차단 판정 (젯슨이 실행) ──
                _pw = _read_power()
                state['power'] = _pw
                # ⚠ [7/31 버그수정] 두 가지를 고쳤다. 시뮬레이션에서 웜업 중에 차단기가
                #   내려가는 것을 보고 잡았다.
                #   (1) LIVE 에서만 판정한다. 웜업·학습 중 차단은 말이 안 된다.
                #   (2) dop_std 를 설비진동 게이트에 먹이지 않는다.
                #       VIB_DS_THRESH=0.20 은 '정지된 장면 속 기계 진동' 기준인데,
                #       걷는 사람의 dop_std 가 0.2~0.5 라서 사람이 걸을 때마다 차단됐다.
                #       설비 진동은 classify() 의 vibration_anomaly 가 담당한다
                #       (ds_first>=0.40 AND ds_last>=0.40 AND h_drop<0.5 — 지속성 요구).
                #       여기서는 전기 이상(과전류·전압강하)만 본다.
                if (state['phase'] == PH_LIVE and state['occupied']
                        and _pw['curr'] is not None and _pw['volt'] is not None):
                    _trip = BREAKER.on_anomalies(
                        classify_equipment(_pw['curr'], _pw['volt'], dop_std=0.0))
                    for _z in _trip:
                        state['logs'].append(
                            f"[{datetime.now().strftime('%H:%M:%S')}] BREAKER TRIP Zone {_z} (전기)")
                _zs = {z: 'NORMAL' for z in ZONE_IDS}
                if state['ev_active'] and state['ev_zone']:
                    _zs[state['ev_zone']] = 'ALERT'
                for _z in BREAKER.tripped_zones():
                    _zs[_z] = 'ALERT' if _zs.get(_z) == 'ALERT' else 'TRIPPED'
                state['zone_state'] = _zs

            # ── READY phase: wait for Start button ─────────
            with _lock:
                current_phase = state['phase']
                start_req     = state['start_requested']

            if current_phase == PH_READY:
                if start_req:
                    scan_buf   = []
                    # [8/11] 바로 스캔에 들어가지 않는다. 먼저 퇴장 유예를 준다.
                    #   scan_until 은 step_out 이 끝난 뒤에 설정한다.
                    step_out_until = time.time() + STEP_OUT_SEC
                    scan_until = None
                    with _lock:
                        state['start_requested'] = False
                        state['phase']           = PH_WARMUP
                        state['scan_left']       = STEP_OUT_SEC
                        state['prepare_step']    = 'step_out'
                    add_log(f'STEP A-0: GET OUT NOW -- empty-room scan starts in {int(STEP_OUT_SEC)}s')
                else:
                    with _lock:
                        state['sc_h'].append(0.0)
                    continue

            # ── WARMUP phase ───────────────────────────────
            #  ⚠ [7/31] ae_disabled 조건 필수. 규칙 전용 강등 시엔 model 이 계속 None 인데,
            #    이 조건이 없으면 매 프레임 웜업 블록으로 되돌아와 1188행이 phase 를
            #    LIVE -> WAIT_TRAIN 으로 되돌린다(실측 재현: 웜업 155->183 무한 증가).
            if model is None and not ae_disabled:
                # [8/11] STEP A-0: 퇴장 유예. 이 구간의 프레임은 버린다.
                #   사람이 아직 시야에 있으므로 scan_buf 에 넣으면 안 된다.
                if step_out_until is not None:
                    if time.time() < step_out_until:
                        with _lock:
                            state['scan_left'] = step_out_until - time.time()
                            state['sc_h'].append(0.0)
                        continue
                    step_out_until = None
                    scan_until = time.time() + SCAN_SEC
                    with _lock:
                        state['prepare_step'] = 'empty_scan'
                        state['scan_left']    = SCAN_SEC
                    add_log(f'STEP A: EMPTY-ROOM SCAN {int(SCAN_SEC)}s -- everyone OUT of view!')

                # STEP A: 빈 방 클러터 스캔
                if scan_until is not None:
                    if time.time() < scan_until:
                        scan_buf.append([(float(p['x']), float(p['y']), float(p['z']))
                                         for p in frame_pts])
                        with _lock:
                            state['scan_left'] = scan_until - time.time()
                            state['sc_h'].append(0.0)
                        continue
                    _finish_scan()
                    step_in_until = time.time() + STEP_IN_SEC

                # STEP B-0: 입장 카운트다운
                if step_in_until is not None:
                    if time.time() < step_in_until:
                        with _lock:
                            state['scan_left'] = step_in_until - time.time()
                            state['sc_h'].append(0.0)
                        continue
                    step_in_until = None
                    with _lock:
                        state['scan_left'] = None
                        state['prepare_step'] = 'baseline'
                    add_log('>> Collecting baseline NOW -- act NORMALLY (stand + small natural moves)')

                warmup_feat.append(feat.tolist())
                wc = len(warmup_feat)
                with _lock:
                    state['warmup_count'] = wc
                    if state['phase'] not in (PH_WAIT_TRAIN, PH_TRAINING,
                                               PH_WAIT_ARM, PH_LIVE):
                        state['phase'] = PH_WARMUP

                if wc % 30 == 0 or wc == 1:
                    print(f'  [WARMUP] {wc}/{N_WARMUP} frames ({int(wc/N_WARMUP*100)}%)')

                if wc >= N_WARMUP:
                    with _lock:
                        newly_done = state['phase'] != PH_WAIT_TRAIN
                        if newly_done:
                            state['phase'] = PH_WAIT_TRAIN
                            state['prepare_step'] = 'wait_train'
                    if newly_done:
                        add_log(f'Baseline complete ({N_WARMUP} frames). Click "Start Training" to proceed.')

                    with _lock:
                        train_req = state['train_requested']
                    if not train_req:
                        with _lock:
                            state['sc_h'].append(0.0)
                        continue

                    with _lock:
                        state['train_requested'] = False
                        state['phase'] = PH_TRAINING
                    add_log('Training LSTM-AE...')

                    _done = threading.Event()
                    _res  = {}

                    # ⚠ [7/31 버그수정] 이전 코드는 _train_worker 에 try/except 가 없어서
                    #   train_on_real_data 가 예외를 던지면 _done 이 영원히 set 되지 않고
                    #   아래 while 이 무한 대기했다. → TRAINING 화면에서 조용히 영구 정지.
                    #   pipeline_loop_safe 도 못 잡는다(메인 스레드에 예외가 없으므로).
                    #   torch 없음·OOM·데이터 부족 어느 것으로든 재현된다.
                    #   → 예외를 잡고, 대기에 상한을 두고, 실패 시 '규칙 전용 LIVE'로 강등한다.
                    #     정지보다 강등이 안전하다: 판정의 주 경로는 규칙(classify)이고
                    #     AE 는 score 로만 기여한다.
                    def _train_worker(feat_copy=warmup_feat[:]):
                        try:
                            m, s, t = train_on_real_data(feat_copy)
                            _res['model'] = m; _res['scaler'] = s; _res['thr'] = t
                        except Exception as e:
                            _res['error'] = f'{type(e).__name__}: {e}'
                        finally:
                            _done.set()

                    threading.Thread(target=_train_worker, daemon=True).start()

                    TRAIN_TIMEOUT = 180.0        # 실측 20~30초. 3분이면 확실히 이상.
                    _t_start = time.time()
                    while not _done.wait(timeout=0.3):
                        with _lock:
                            state['last_data_t'] = time.time()
                        if time.time() - _t_start > TRAIN_TIMEOUT:
                            _res['error'] = f'학습이 {TRAIN_TIMEOUT:.0f}초를 넘겨 중단'
                            break

                    model  = _res.get('model')
                    scaler = _res.get('scaler')
                    thr    = _res.get('thr')

                    if model is None or scaler is None:
                        # ── 강등: 규칙 전용 감시 대기 ──
                        #  ⚠ AE 는 '점수'가 아니라 classify() 앞의 게이트다
                        #    (is_anomaly = score > thr  →  anom_streak  →  classify).
                        #    따라서 thr 를 크게 잡으면 classify 가 아예 호출되지 않아
                        #    낙상을 하나도 못 잡는다. 게이트를 '항상 통과'로 열어야 한다.
                        #    score 는 AE 없으면 0.0 이므로 thr=-1 로 둔다.
                        ae_disabled = True
                        thr = -1.0
                        with _lock:
                            state['threshold'] = thr
                            state['phase']     = PH_WAIT_ARM
                        add_log(f"[학습 실패] {_res.get('error', '원인 불명')}")
                        add_log('규칙 전용 감시 대기 — AE 게이트를 개방해 classify 를 '
                                '상시 평가합니다. 낙상 규칙(도플러·높이·수평·정지)은 그대로 '
                                '동작하지만, AE 2차 확인이 없어 오탐이 늘 수 있습니다. '
                                '감시 시작 버튼을 눌러야 LIVE 로 전환됩니다.')
                    else:
                        with _lock:
                            state['threshold'] = thr
                            state['phase']     = PH_WAIT_ARM
                        add_log(f'Training done. Threshold={thr:.5f}. Waiting to arm monitoring.')
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
            with _lock:
                _is_live = (state['phase'] == PH_LIVE)
                _occupied = state['occupied']
            if not _is_live or not _occupied:
                continue
            feat_buf.append(feat.tolist())
            if len(feat_buf) > SEQ_LEN:
                feat_buf.pop(0)
            # [8/11] classify 입력만 클러터 제거 전 피처를 쓴다. (위 주석 참조)
            clf_buf.append(feat_full.tolist())
            if len(clf_buf) > CLF_WIN:
                clf_buf.pop(0)
            rf30_buf.append(feat_rf30.tolist())
            if len(rf30_buf) > RF30_WINDOW:
                rf30_buf.pop(0)

            # ── 낙상 지속확인 게이트 (매 프레임) ──
            if POSTFALL_GATE and fall_pending is not None:
                _nn, _dd = float(feat[6]), float(feat[4])
                if _nn >= RECOVER_NP75 and RECOVER_DSLO <= _dd <= RECOVER_DSHI:
                    recover_streak += 1
                else:
                    recover_streak = 0
                _pts = datetime.now().strftime('%H:%M:%S')
                if recover_streak >= RECOVER_FRAMES:
                    fall_pending = None; recover_streak = 0
                    with _lock:
                        state['logs'].append(f'[{_pts}] Fall 취소: 일어나 이동 감지 (postfall gate)')
                elif time.time() >= fall_pending['deadline']:
                    with _lock:
                        if not state['ev_active']:
                            _latch_event('fall_detected', fall_pending['clf'],
                                         fall_pending['zn'], _pts, fall_pending['score_x'])
                    fall_pending = None; recover_streak = 0

            # ── 정지형 Zone+지속시간 게이트 (매 프레임, AE와 독립) ──
            _n, _ds = float(feat[6]), float(feat[4])
            _cx, _cy, _czf = float(feat[0]), float(feat[1]), float(feat[2])
            _zone_hit = None
            for _zid, _zc in DANGER_ZONES.items():
                if _zc['x'][0] <= _cx <= _zc['x'][1] and _zc['z'][0] <= _czf <= _zc['z'][1]:
                    _zone_hit = _zid
                    break
            _pos_ok = True
            if stat_since is not None:
                _pos_ok = (_cx - stat_ax)**2 + (_czf - stat_az)**2 <= STAT_POS_R**2
            _clutter = any((_cx - _sx)**2 + (_czf - _sz)**2 <= _sr**2
                           and abs(_cy - _sy) <= _dy
                           for _sx, _sy, _sz, _sr, _dy in clutter_spots)
            if _n >= 14:
                motion_run += 1
                if motion_run >= 3:
                    last_motion_t = time.time()
            else:
                motion_run = 0

            # 트랙 기반 정지형으로 교체된 옛 저도플러 게이트. 아래 분기는 회귀 비교를
            # 위해 남기되 실행하지 않는다. 두 경로가 같은 타이머를 지우면 안 된다.
            if True:
                pass
            elif _clutter:
                pass   # 중립: 카운터/타이머 유지
            elif (False and _zone_hit
                  and _n >= STAT_N_MIN and STAT_DS_MIN < _ds < STAT_DS_MAX and _pos_ok
                  and (stat_since is not None
                       or time.time() - last_motion_t <= STAT_ENTRY_SEC)):
                if stat_since is None:
                    stat_since = time.time()
                    stat_zone  = _zone_hit
                    stat_ax, stat_az = _cx, _czf
                    stat_hits = stat_tot = 0
                stat_hits += 1; stat_tot += 1
                stat_last_hit = time.time()
                stat_miss = 0
                _dwell = time.time() - stat_since
                _ratio_ok = stat_hits >= STAT_HIT_RATIO * max(1, stat_tot)
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
                    _remain = max(0, int(STAT_CRIT_SEC - _dwell))
                    with _lock:
                        state['pre_alert'] = (f'PRE-ALERT  Zone {stat_zone}: no-motion {int(_dwell)}s'
                                              f'  --  MOVE to cancel  ({_remain}s to CRITICAL)')
            else:
                if stat_since is not None:
                    stat_tot += 1
                stat_miss += 1
                if stat_miss >= STAT_MISS_TOL:
                    if stat_pre:
                        add_log(f'PRE-ALERT cleared Zone {stat_zone}: motion resumed')
                    stat_since = None; stat_zone = None; stat_pre = False
                    stat_hits = stat_tot = 0
                    with _lock:
                        state['pre_alert'] = ''

            if False and stat_since is not None and time.time() - stat_last_hit > STAT_HIT_TIMEOUT:
                if stat_pre:
                    add_log(f'PRE-ALERT cleared Zone {stat_zone}: presence lost')
                stat_since = None; stat_zone = None; stat_pre = False
                stat_hits = stat_tot = 0
                with _lock:
                    state['pre_alert'] = ''

            if (False and stat_since is not None and stat_tot >= STAT_MIN_OBS
                    and stat_hits < STAT_HIT_FLOOR * stat_tot):
                if stat_pre:
                    add_log(f'PRE-ALERT cleared Zone {stat_zone}: scattered clutter (low hit-ratio)')
                stat_since = None; stat_zone = None; stat_pre = False
                stat_hits = stat_tot = 0
                with _lock:
                    state['pre_alert'] = ''

            # [8/05 실측] 정지 인체는 도플러 0으로 사라지고 빈방 반사가 남는다.
            # 저도플러 점을 계속 사람으로 요구하면 타이머가 매번 초기화된다.
            # 확인된 트랙이 경계 퇴실 없이 내부에서 소실된 시간으로 정지형을 판정한다.
            if MAINT_MODE:
                stat_since = None; stat_zone = None; stat_pre = False
                stat_hits = stat_tot = 0
                with _lock:
                    state['pre_alert'] = ''
            else:
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
                    ae_error_logged = False
                except Exception as e:
                    score = 0.0
                    if not ae_error_logged:
                        ae_error_logged = True
                        add_log(f'AE score 계산 실패 -- 판정 중지: {type(e).__name__}: {e}')

            with _lock:
                state['sc_h'].append(score)
                ts = datetime.now().strftime('%H:%M:%S')

                # ── 수동 해제 (노트북 Event Resolved 버튼) ──
                if state['resolve_requested']:
                    state['resolve_requested'] = False
                    if state['ev_active']:
                        et = state['ev_type']; zn = state['ev_zone']
                        lbl = EVENT_LABELS.get(et, et)
                        state.update({
                            'ev_active': False, 'ev_type': None,
                            'ev_sev': 'normal', 'ev_conf': 0.0,
                            # [7/31] 근거도 같이 비운다. 안 비우면 노트북 '판단 근거'
                            #   팝업이 해소된 옛 경보의 수치를 계속 보여준다.
                            'ev_evidence': None, 'ev_gates': None, 'ev_rejected': [],
                        })
                        for inc in reversed(state['incidents']):
                            if inc['resolved'] is None:
                                inc['resolved'] = ts
                                break
                        state['logs'].append(f'[{ts}] RESOLVED Zone {zn}: {lbl} (manual ack)')
                        # ⚠ 차단기는 복구하지 않는다 (LOTO / restart prevention).
                        #   재투입은 노트북에서 확인 3개를 받은 뒤 CMD_RESTORE 로만.
                        if BREAKER.any_tripped():
                            state['logs'].append(
                                f'[{ts}] 차단 유지 {BREAKER.tripped_zones()} — 재투입은 수동')

                fw = np.array(clf_buf, dtype=np.float32)
                rf30w = np.array(rf30_buf, dtype=np.float32)
                if RF30_OK and len(rf30w) == RF30_WINDOW:
                    rf_score = _rf30_fall_score(rf30w)
                    rf_threshold = RF30_THRESHOLD
                    rf_kind = 'hybrid30'
                else:
                    rf_score = _rf_fall_score(fw) if len(fw) == CLF_WIN else None
                    rf_threshold = RF_THRESHOLD
                    rf_kind = 'legacy20'
                rf_candidate = rf_score is not None and rf_score >= rf_threshold
                # [8/14 실측] RF는 AE와 기존 규칙이 놓친 약한 낙상을 직접 후보로 올린다.
                is_anomaly = score > thr or rf_candidate

                if rf_candidate and not state['ev_active']:
                    anom_streak = CONFIRM_FRAMES
                elif is_anomaly and not state['ev_active']:
                    anom_streak += 1
                else:
                    anom_streak = 0

                if anom_streak >= CONFIRM_FRAMES:
                    anom_streak = 0
                    clf = classify(fw, score, thr)
                    et  = clf['event_type']
                    raw_et = et

                    if rf_candidate:
                        clf = dict(clf)
                        evidence = dict(clf.get('evidence') or {})
                        evidence.update({'rf_score': round(rf_score, 6),
                                         'rf_threshold': round(rf_threshold, 6),
                                         'rf_model': rf_kind,
                                         'score_kind': 'rf_uncalibrated'})
                        clf.update({'event_type': 'fall_detected', 'severity': 'critical',
                                    'confidence': round(rf_score, 4), 'evidence': evidence})
                        et = raw_et = 'fall_detected'
                    # 규칙 낙상 양성인데 RF만 음성이면 정상으로 버리지 않는다.
                    # classify 정본과 차단 조건은 그대로 두고, 확인 경보와 학습 후보를 남긴다.
                    elif et == 'normal' and RF_OK and _rule_fall_positive(clf):
                        clf = dict(clf)
                        clf.update({'event_type': 'fall_suspected', 'severity': 'warning',
                                    'confidence': max(0.70, float(clf.get('confidence') or 0))})
                        et = raw_et = 'fall_suspected'
                        _save_fall_suspect(fw, clf)

                    # [판정 로그] 미검출/오탐 원인 확정용
                    try:
                        _w  = fw[fw[:, 6] > 0]
                        if len(_w) >= 2:
                            _dsl = _w[:, 4]; _nl = _w[:, 6]; _h = max(1, len(_dsl)//2)
                            _pk2 = int(_dsl.argmax())
                            _hh  = CEILING_H - _w[:, 1]
                            _hd  = (round(float(_hh[:_pk2].mean() - _hh[_pk2+1:].mean()), 2)
                                    if (_pk2 >= 2 and len(_hh) - _pk2 - 1 >= 3) else None)
                            _pm  = (round(float(np.median(_nl[_pk2+1:])), 1)
                                    if len(_nl) - _pk2 - 1 >= 3 else None)
                            with open(CLF_LOG_PATH, 'a') as _lf:
                                _lf.write(json.dumps({
                                    't': round(time.time(), 2),
                                    'verdict': raw_et, 'pend': f'{pend_et}:{pend_cnt}',
                                    'rf_score': (round(rf_score, 6) if rf_score is not None else None),
                                    'rf_thr': (round(rf_threshold, 6)
                                               if rf_score is not None else None),
                                    'rf_model': rf_kind,
                                    'ds_max': round(float(_dsl.max()), 3),
                                    'ds_first': round(float(_dsl[:_h].mean()), 3),
                                    'ds_last': round(float(_dsl[_h:].mean()), 3),
                                    'n_mean': round(float(_nl.mean()), 1),
                                    'n_p75': round(float(np.percentile(_nl, 75)), 1),
                                    'h_drop': round(float(_w[:, 1].max() - _w[:, 1].min()), 3),
                                    'score_x': round(score / thr if thr > 0 else 0, 2),
                                    'broad': int((_dsl >= 0.8).sum()),
                                    'h_desc': _hd, 'post_med': _pm,
                                    'horiz': round(float(np.hypot(_w[:, 0].max() - _w[:, 0].min(),
                                                                  _w[:, 2].max() - _w[:, 2].min())), 3),
                                    'zacc': round(float(np.abs(_w[:, 8]).max()), 3),
                                }) + '\n')
                    except Exception:
                        pass

                    if et == 'normal':
                        pend_et, pend_cnt = None, 0
                    elif et in ('fall_detected', 'fall_suspected'):
                        # 규칙의 2초 창을 통과한 낙상 후보는 RF 동의 여부와 무관하게
                        # FALL_CONFIRM 경로를 쓴다. 의심 경보를 일반 이상 3회 게이트로
                        # 보내면 짧은 실제 낙상이 사라진다(8/06 실측: 2회 뒤 normal).
                        _now = time.time()
                        fall_hits = [t for t in fall_hits if _now - t <= FALL_WIN_SEC]
                        fall_hits.append(_now)
                        if len(fall_hits) < FALL_CONFIRM:
                            et = 'normal'
                        else:
                            fall_hits = []
                            pend_et, pend_cnt = None, 0
                    else:
                        _need = CONFIRM_EVENTS
                        if et == pend_et:
                            pend_cnt += 1
                        else:
                            pend_et, pend_cnt = et, 1
                        if pend_cnt < _need:
                            et = 'normal'
                        else:
                            pend_et, pend_cnt = None, 0

                    if et == 'normal':
                        pass
                    elif et == 'fall_detected' and POSTFALL_GATE:
                        zn = EVENT_ZONE.get(et, RADAR_ZONE)
                        # 반복 RF 후보가 deadline을 매 프레임 연장하면 경보가 영원히 확정되지 않는다.
                        if fall_pending is None:
                            fall_pending = {'deadline': time.time() + POSTFALL_HOLD, 'clf': clf,
                                            'zn': zn, 'score_x': (score / thr if thr > 0 else 0.0)}
                            recover_streak = 0
                            state['logs'].append(
                                f'[{ts}] Fall 후보 -- 지속확인 중 ({POSTFALL_HOLD:.1f}s, 일어나 걸으면 취소)')
                    else:
                        zn = EVENT_ZONE.get(et, RADAR_ZONE)
                        _latch_event(et, clf, zn, ts, score / thr if thr > 0 else 0.0)

                # ── 정지형 2차 경보: critical latch ──
                if False:  # 수동 재실 전환 후 무동작 판정은 별도 실측 전까지 비활성
                    et2 = 'stationary_anomaly'
                    zn2 = stat_zone or EVENT_ZONE.get(et2, RADAR_ZONE)
                    dwell = time.time() - stat_since
                    _fr = stat_hits / max(1, stat_tot)
                    stat_since = None; stat_zone = None; stat_miss = 0; stat_pre = False
                    stat_hits = stat_tot = 0
                    state['pre_alert'] = ''
                    state.update({
                        'ev_active': True, 'ev_type': et2,
                        # [8/01] 'critical' 고정이었다. 낙상(게이트 5개 통과 = 확정)과
                        #   정지형 이상(라벨부터 'VERIFY' = 확인 필요)이 같은 강도로
                        #   울리면 빨강이 무시된다. → radar_common.EVENT_SEV 로 분리.
                        #   ⚠ 이 경로는 _latch_event() 를 거치지 않으므로 차단기와
                        #     무관하다. 등급을 바꿔도 차단 동작은 그대로다.
                        'ev_sev': EVENT_SEV.get(et2, 'critical'),
                        'ev_conf': round(min(0.95, 0.55 + 0.40 * _fr), 2),
                        'ev_zone': zn2,
                        'ev_id': state.get('ev_id', 0) + 1,
                    })
                    lbl2 = EVENT_LABELS.get(et2, et2)
                    state['logs'].append(
                        f'[{ts}] ALERT Zone {zn2}: {lbl2} (no-motion {dwell:.0f}s in danger zone)')
                    state['incidents'].append({
                        'type': et2, 'zone': zn2, 'detected': ts, 'resolved': None})
                # else: 경보 latch 유지 (자동 해제 없음)


def sim_radar_writer():
    """[--simulate 전용] radar_parser.py 를 대신해 합성 프레임을 JSONL 로 흘려 넣는다.

    포맷은 radar_parser.py 의 출력과 동일: 한 줄에 {"points":[{x,y,z,doppler,intensity}...]}.
    → jetson_sender 의 tail 읽기·파싱·피처추출·classify 경로가 실제로 돈다.

    시나리오(반복): 빈 방 14s → 보행 25s → 낙상 → 누움 유지 20s → 처음으로
    """
    import random
    t0 = time.time()
    # 구간 경계 (초). --fast 면 전체를 압축해 한 사이클 24초.
    #  ⚠ 낙상 구간은 0.5초여야 한다. 1.5초로 만들었더니 classify 가 '달리기'로 기각했다
    #    (임펄스비 = ds_max / 전반부평균 >= 2.2 게이트. 지속 고도플러는 비율이 1에 가까움).
    #    실측 낙상 서명 = 조용(보행 ds 0.15) → 0.5초 격발(ds 1.9) → 정지(ds 0.04).
    #    이 게이트가 제대로 동작한다는 증거이기도 하다.
    T_EMPTY, T_WALK, T_FALL, T_CYCLE = ((5.0, 13.0, 13.5, 24.0) if SIM_FAST
                                        else (14.0, 39.0, 39.5, 60.0))
    print(f'[SIM] 합성 프레임 기록 시작 → {JSON_PATH}  (사이클 {T_CYCLE:.0f}s)')
    while True:
        t = (time.time() - t0) % T_CYCLE
        if t < T_EMPTY:                   # 빈 방 (빈방 스캔용) — 클러터 1~2점만
            n, cx, cy, cz, sp = random.randint(0, 2), 0.9, 1.8, 0.9, (0.04, 0.04, 0.04)
            dop = 0.02
        elif t < T_WALK:                  # 보행 — 조용해야 임펄스비가 성립한다
            n, sp = 8, (0.10, 0.30, 0.10)
            cx, cz = 0.45 * math.sin(t * 0.7), 0.30 * math.cos(t * 0.5)
            cy, dop = 1.15, 0.15
        elif t < T_FALL:                  # 낙상 순간 — 도플러 격발 + 급하강 + 수평 확산
            n, sp = 14, (0.35, 0.30, 0.25)
            _p = (t - T_WALK) / max(T_FALL - T_WALK, 1e-6)
            cx, cz, cy, dop = 0.2 + 0.9 * _p, 0.1 + 0.6 * _p, 1.15 + 0.82 * _p, 1.9
        else:                             # 누움 유지
            n, sp = 8, (0.42, 0.08, 0.24)
            cx, cz, cy, dop = 1.1, 0.7, 1.98, 0.04
        pts = [{'x': round(cx + random.gauss(0, sp[0]), 4),
                'y': round(cy + random.gauss(0, sp[1]), 4),
                'z': round(cz + random.gauss(0, sp[2]), 4),
                'doppler': round(random.gauss(0, dop), 4),
                'intensity': round(random.uniform(120, 700), 1)} for _ in range(n)]
        try:
            with open(JSON_PATH, 'a', encoding='utf-8') as f:
                f.write(json.dumps({'points': pts}) + '\n')
            # 파일이 무한히 커지지 않게 주기적으로 비운다(tail 읽기는 offset 리셋을 처리함)
            if os.path.getsize(JSON_PATH) > 4_000_000:
                open(JSON_PATH, 'w').close()
        except OSError:
            pass
        time.sleep(0.1)                   # 10 Hz — 실제 레이더와 동일


def pipeline_loop_safe():
    """예외로 조용히 죽는 것 방지 -> 터미널에 출력 + 재시작."""
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
# 7. MAIN
# ═══════════════════════════════════════════════════════════
if __name__ == '__main__':
    print('=' * 65)
    print('  Radar-Guard | JETSON SENDER (detection only, no GUI)')
    print('=' * 65)
    print(f'  Radar data : {JSON_PATH}')
    print(f'  Device     : {DEVICE}')
    print(f'  Warmup     : {N_WARMUP} frames')
    print(f'  Baseline   : {BASELINE_PATH}')
    print(f'  UDP OUT    : *:{DATA_PORT}  (노트북 HELLO로 자동 발견'
          + (f', 고정={LAPTOP_IP}' if LAPTOP_IP else '') + ')')
    print(f'  UDP IN     : 0.0.0.0:{CTRL_PORT}  (버튼 명령)')
    print()
    if SIMULATE:
        print('  ⚠ --simulate : 레이더 없이 합성 프레임으로 이 파일을 그대로 구동합니다.')
        print(f'     AE(LSTM)  : {"동작" if TORCH_OK else "비활성 — torch 없음, 규칙 판정만"}')
        print(f'     RF 모델   : {"로드됨" if RF_OK else "없음 — 규칙만"}')
        print('     노트북 UI : python console_ui.py --live 127.0.0.1')
        print('     시나리오  : 빈방 14s → 보행 25s → 낙상 → 누움 20s (60s 주기)')
    else:
        print('  [터미널 1] python3 ~/radar_parser.py')
        print('  [터미널 2] python3 ~/jetson_sender.py   <- 이 창')
        print('  노트북    : python console_ui.py --live <젯슨IP>')
    print('  종료: Ctrl+C')
    print('=' * 65)
    print()
    if SIMULATE:
        threading.Thread(target=sim_radar_writer, daemon=True).start()

    threading.Thread(target=control_listener, daemon=True).start()
    threading.Thread(target=sender_loop, daemon=True).start()

    add_log('Jetson sender started -- waiting for radar data')
    try:
        pipeline_loop_safe()
    except KeyboardInterrupt:
        print('\n[EXIT] jetson sender 종료 -- bye')
        sys.exit(0)
