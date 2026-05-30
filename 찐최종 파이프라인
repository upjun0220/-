"""
=================================================================
Radar-Guard | run_scenario.py  (Point Cloud 버전 v2)
=================================================================
사용법:
    SCENARIO 변수만 바꾸면 됨
    "fall"           → 낙상         (Zone C)
    "electric_shock" → 감전         (Zone A — 변전실)
    "pinching"       → 협착         (Zone B — 가공실)
    "vibration"      → 진동이상     (Zone C)

파이프라인:
    민석 파트: mmWave Point Cloud 목데이터 생성 → radar_frame.json
    승원 파트: LMS 필터 + PC 피처 추출          → stage1_filtered.json
    성준 파트: LSTM-AE 이상 탐지 + 분류         → stage2_event.json
    재국 파트: 자동 대응 + 차단기               → ui_trigger.json
    유빈 파트: UI 미리보기 + 그래프
=================================================================
"""

# ======================================================
# ★ 여기만 바꾸면 됨 ★
SCENARIO = "electric_shock"   # "fall" | "electric_shock" | "pinching" | "vibration"
# ======================================================

try:
    from IPython.display import display
except ImportError:
    def display(fig): pass

import numpy as np
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
from torch import optim
from sklearn.preprocessing import MinMaxScaler
from datetime import datetime, timedelta
import json
import time

# ── 기본 설정 ─────────────────────────────────────────────────
FRAME_RATE  = 10          # 10 fps (100ms / frame)
N_FRAMES    = 200         # 총 프레임 수
FEATURE_DIM = 8           # PC 피처 차원 수
SEQ_LEN     = 5           # LSTM 시퀀스 길이
DEVICE      = torch.device("cuda" if torch.cuda.is_available() else "cpu")

SCENARIO_KR = {
    "fall":           "낙상",
    "electric_shock": "감전",
    "pinching":       "협착",
    "vibration":      "진동이상",
}
ZONE_MAP = {
    "fall": "C", "electric_shock": "A", "pinching": "B", "vibration": "C"
}


# ================================================================
# 민석 파트: mmWave Point Cloud 목데이터 생성
# ================================================================
# 좌표계: x=좌우, y=전후(깊이, 양수=레이더 앞), z=높이 (단위: m)
# doppler: 양수=레이더에서 멀어짐, 음수=가까워짐 (단위: m/s)
# ================================================================

def _person_points(n=5, x0=0.0, y0=2.0, z0=1.7,
                   dx=0.08, dy=0.08, dz=0.05,
                   dop_mean=0.0, dop_std=0.008,
                   int_lo=300, int_hi=500):
    """지정 위치에 작업자 포인트 클라우드 생성"""
    pts = []
    for _ in range(n):
        pts.append({
            "x":        float(x0 + np.random.normal(0, dx)),
            "y":        float(y0 + np.random.normal(0, dy)),
            "z":        float(z0 + np.random.normal(0, dz)),
            "doppler":  float(np.random.normal(dop_mean, dop_std)),
            "intensity":float(np.random.uniform(int_lo, int_hi)),
        })
    return pts


def make_point_cloud(scenario, n_frames=N_FRAMES):
    """
    시나리오별 Point Cloud 목데이터 생성.
    실제 TI IWR6843 레이더 출력을 시뮬레이션.

    반환: (frames, onset_frame)
        frames       : List[List[dict]]  — 프레임별 포인트 리스트
        onset_frame  : int               — 사고 발생 시작 프레임
    """
    onset = {
        "fall":           np.random.randint(90, 110),
        "electric_shock": np.random.randint(70, 88),
        "pinching":       np.random.randint(65, 85),
        "vibration":      np.random.randint(90, 108),
    }[scenario]

    frames = []

    for i in range(n_frames):
        t_since = max(0, i - onset)       # 사고 발생 후 경과 프레임

        # ──────────────────────────────────────────────────────
        if scenario == "fall":
            if i < onset:
                # 정상: 작업자 서있음
                pts = _person_points(n=np.random.randint(4, 7),
                                     y0=2.0, z0=1.7)
            elif t_since <= 8:
                # 낙상 중: Z 급강하 + 높은 음의 도플러(아래로 가속)
                frac    = t_since / 8.0
                cur_z   = 1.7 - frac * 1.4      # 1.7m → 0.3m
                cur_dop = -1.5 + np.random.normal(0, 0.3)
                pts = _person_points(n=np.random.randint(5, 9),
                                     y0=2.0, z0=cur_z, dz=0.10,
                                     dop_mean=cur_dop, dop_std=0.25,
                                     int_lo=450, int_hi=700)
            else:
                # 낙상 후: 바닥에 누운 상태, 거의 정지
                pts = _person_points(n=np.random.randint(2, 5),
                                     y0=1.9, z0=0.3, dz=0.06,
                                     dop_mean=0.0, dop_std=0.006,
                                     int_lo=180, int_hi=320)

        # ──────────────────────────────────────────────────────
        elif scenario == "electric_shock":
            if i < onset:
                # 변전실 접근 중: y 서서히 감소
                approach = min(1.0, i / onset)
                cur_y    = 2.5 - approach * 1.7   # 2.5m → 0.8m
                pts = _person_points(n=np.random.randint(4, 6),
                                     y0=cur_y, z0=1.7,
                                     dop_mean=-0.15*approach, dop_std=0.01)
            else:
                # 감전 중: 위치 고정 + 60Hz 불수의 근육 경련
                # 각 신체 부위가 서로 다른 위상으로 진동 → intra-frame dop_std 높음
                phase    = t_since * (2 * np.pi * 60 / FRAME_RATE)
                spasm    = np.sin(phase) * 0.075   # ±0.075 m/s 경련 진폭
                cur_z    = max(1.2, 1.7 - t_since * 0.005)
                pts = _person_points(n=np.random.randint(5, 9),
                                     x0=0.2, y0=0.8, z0=cur_z, dz=0.04,
                                     dop_mean=spasm, dop_std=0.065,
                                     int_lo=350, int_hi=560)

        # ──────────────────────────────────────────────────────
        elif scenario == "pinching":
            if i < onset:
                # 회전 장비로 접근 중: y 2.5m → 0.5m
                approach = min(1.0, i / onset)
                cur_y    = 2.5 - approach * 2.0
                cur_dop  = -0.4 * approach + np.random.normal(0, 0.04)
                pts = _person_points(n=np.random.randint(4, 7),
                                     y0=cur_y, z0=1.7,
                                     dop_mean=cur_dop, dop_std=0.012)
            else:
                # 협착 중: 위치 고정 + 30Hz 회전체 도플러
                # 신체 부위마다 회전체 접촉 정도가 달라 intra-frame dop_std 높음
                phase   = t_since * (2 * np.pi * 30 / FRAME_RATE)
                rot_dop = np.sin(phase) * 0.055
                pts = _person_points(n=np.random.randint(5, 8),
                                     y0=0.5, z0=1.5, dy=0.04, dz=0.05,
                                     dop_mean=rot_dop, dop_std=0.060,
                                     int_lo=400, int_hi=660)

        # ──────────────────────────────────────────────────────
        else:  # vibration
            if i < onset:
                # 정상 장비 가동 (고정 위치, 낮은 진동)
                pts = _person_points(n=np.random.randint(3, 6),
                                     x0=1.0, y0=1.5, z0=0.8,
                                     dx=0.04, dy=0.04, dz=0.03,
                                     dop_mean=0.0, dop_std=0.004,
                                     int_lo=250, int_hi=380)
            else:
                # 진동 이상: 5Hz 저주파, 진폭 서서히 증가
                amp   = min(0.10, 0.015 + t_since * 0.0008)
                phase = t_since * (2 * np.pi * 5 / FRAME_RATE)
                vib   = np.sin(phase) * amp
                pts = _person_points(n=np.random.randint(3, 6),
                                     x0=1.0, y0=1.5, z0=0.8,
                                     dx=0.04, dy=0.04, dz=0.03,
                                     dop_mean=vib, dop_std=amp*0.3 + 0.003,
                                     int_lo=250, int_hi=400)

        frames.append(pts)

    return frames, onset


def minseok_generate(scenario, n_frames=N_FRAMES):
    """
    민석 파트: Point Cloud 목데이터 생성 → radar_frame.json
    실제 레이더 연결 시 이 함수 대신 TLV 파서 출력이 들어옴
    """
    print(f"[민석] '{SCENARIO_KR[scenario]}' Point Cloud 목데이터 생성 중...")

    frames, onset = make_point_cloud(scenario, n_frames)
    zone          = ZONE_MAP[scenario]
    now           = datetime.now()

    radar_data = {
        "schema_version": "1.0",
        "timestamp":      now.isoformat(),
        "scenario":       scenario,
        "zone_id":        zone,
        "frame_rate":     FRAME_RATE,
        "n_frames":       n_frames,
        "onset_frame":    int(onset),
        "frames": [
            {
                "frame_id": i,
                "time_ms":  i * (1000 // FRAME_RATE),
                "points":   frames[i],
            }
            for i in range(n_frames)
        ],
        "metadata": {
            "sensor":     "TI IWR6843 (simulated)",
            "frequency":  "60GHz",
            "range_m":    4.0,
            "azimuth_deg": 120,
        },
    }

    with open("radar_frame.json", "w", encoding="utf-8") as f:
        json.dump(radar_data, f, ensure_ascii=False, indent=2)

    print(f"[민석] 완료 → radar_frame.json 저장  (onset: frame {onset})")
    return radar_data


# ================================================================
# 승원 파트: LMS 필터 + Point Cloud 피처 추출
# ================================================================

class LMSFilter:
    """LMS 적응 필터 — doppler 채널 노이즈 제거"""
    def __init__(self, order=8, mu=0.005):
        self.w   = np.zeros(order)
        self.buf = np.zeros(order)
        self.order, self.mu = order, mu

    def filter(self, x, ref):
        self.buf    = np.roll(self.buf, 1)
        self.buf[0] = ref
        y           = np.dot(self.w, self.buf)
        e           = x - y
        self.w     += 2 * self.mu * e * self.buf
        return float(e)


def extract_pc_features(frame_points, prev_centroid=None):
    """
    Point Cloud 한 프레임 → 8차원 피처 벡터

    피처 구성:
        [0] cx           — centroid X (m)
        [1] cy           — centroid Y / 깊이 (m)
        [2] cz           — centroid Z / 높이 (m)
        [3] mean_doppler — 평균 도플러 속도 (m/s)
        [4] doppler_std  — 도플러 표준편차 (진동/경련 지표)
        [5] intensity_mean — 평균 반사 강도
        [6] num_points   — 검출 포인트 수
        [7] z_velocity   — 프레임 간 Z 변화량 (낙상 지표)
    """
    if not frame_points:
        return np.zeros(FEATURE_DIM, dtype=np.float32)

    pts = np.array(
        [[p["x"], p["y"], p["z"], p["doppler"], p["intensity"]]
         for p in frame_points],
        dtype=np.float32,
    )

    centroid       = pts[:, :3].mean(axis=0)
    mean_doppler   = float(pts[:, 3].mean())
    doppler_std    = float(pts[:, 3].std() + 1e-8)
    intensity_mean = float(pts[:, 4].mean())
    num_points     = float(len(pts))
    z_velocity     = float(centroid[2] - prev_centroid[2]) \
                     if prev_centroid is not None else 0.0

    return np.array([
        centroid[0], centroid[1], centroid[2],
        mean_doppler, doppler_std, intensity_mean,
        num_points, z_velocity,
    ], dtype=np.float32)


def seungwon_process(radar_data):
    """
    승원 파트: radar_frame.json → LMS 필터 → 피처 추출 → stage1_filtered.json
    """
    scenario = radar_data["scenario"]
    zone     = radar_data["zone_id"]
    print(f"[승원] '{SCENARIO_KR[scenario]}' 피처 추출 중...")

    lms           = LMSFilter()
    features      = []
    prev_centroid = None

    for frame_data in radar_data["frames"]:
        pts  = frame_data["points"]
        feat = extract_pc_features(pts, prev_centroid)

        # LMS 필터: doppler 채널(idx=3)에서 환경 노이즈 제거
        ref     = float(np.random.normal(0, 0.004))
        feat[3] = lms.filter(feat[3], ref)

        prev_centroid = feat[:3].copy()
        features.append(feat.tolist())

    stage1 = {
        "schema_version": "1.0",
        "timestamp":      datetime.now().isoformat(),
        "scenario":       scenario,
        "n_frames":       len(features),
        "zone_id":        zone,
        "feature_names":  [
            "cx", "cy", "cz",
            "mean_doppler", "doppler_std", "intensity_mean",
            "num_points", "z_velocity",
        ],
        "features": features,
        "metadata": {
            "filter":      "LMS_adaptive",
            "feature_dim": FEATURE_DIM,
        },
    }

    with open("stage1_filtered.json", "w", encoding="utf-8") as f:
        json.dump(stage1, f, ensure_ascii=False, indent=2)
    print(f"[승원] 완료 → stage1_filtered.json 저장")
    return stage1


# ================================================================
# 성준 파트: LSTM-AE 이상 탐지 + 분류
# ================================================================

class LSTM_AE(nn.Module):
    def __init__(self, n_feat, emb_dim, seq_len):
        super().__init__()
        self.seq_len = seq_len
        self.enc1 = nn.LSTM(n_feat,      emb_dim,     batch_first=True)
        self.enc2 = nn.LSTM(emb_dim,     emb_dim//2,  batch_first=True)
        self.dec1 = nn.LSTM(emb_dim//2,  emb_dim//2,  batch_first=True)
        self.dec2 = nn.LSTM(emb_dim//2,  emb_dim,     batch_first=True)
        self.fc   = nn.Linear(emb_dim, n_feat)

    def forward(self, x):
        _, (h, _) = self.enc1(x)
        _, (h, _) = self.enc2(h.transpose(0, 1))
        x = h.transpose(0, 1).repeat(1, self.seq_len, 1)
        x, _ = self.dec1(x)
        x, _ = self.dec2(x)
        return self.fc(x)


def create_sequences(data, seq_len):
    return np.array([data[i:i+seq_len] for i in range(len(data)-seq_len)])


def train_model():
    """
    정상 패턴(작업자 서있는 상태)의 Point Cloud 피처로 LSTM-AE 학습.
    μ+3σ 이상 탐지 임계치 계산.
    """
    print("[성준] 정상 패턴 학습 중 (Point Cloud 목데이터)...")

    lms          = LMSFilter()
    normal_feat  = []
    prev_c       = None

    for idx in range(1000):
        # 70%: 정지한 작업자 / 30%: 천천히 이동하는 작업자 (정상 보행 포함)
        if idx % 10 < 7:
            # 정지 상태
            pts = _person_points(
                n        = np.random.randint(3, 7),
                y0       = np.random.uniform(1.5, 2.5),
                z0       = np.random.uniform(1.60, 1.80),
                dop_mean = np.random.uniform(-0.02, 0.02),
                dop_std  = np.random.uniform(0.004, 0.010),
            )
        else:
            # 정상 보행 (느린 접근/이탈, dop_mean 최대 ±0.25 m/s)
            pts = _person_points(
                n        = np.random.randint(3, 7),
                y0       = np.random.uniform(1.0, 3.0),
                z0       = np.random.uniform(1.60, 1.80),
                dop_mean = np.random.uniform(-0.25, 0.25),
                dop_std  = np.random.uniform(0.008, 0.018),
            )
        feat    = extract_pc_features(pts, prev_c)
        feat[3] = lms.filter(feat[3], np.random.normal(0, 0.004))
        prev_c  = feat[:3].copy()
        normal_feat.append(feat.tolist())

    scaler = MinMaxScaler()
    X = torch.from_numpy(
        create_sequences(scaler.fit_transform(normal_feat), SEQ_LEN)
    ).float().to(DEVICE)

    model = LSTM_AE(FEATURE_DIM, 16, SEQ_LEN).to(DEVICE)
    opt   = optim.AdamW(model.parameters(), lr=0.001)
    crit  = nn.MSELoss()

    model.train()
    for ep in range(121):
        opt.zero_grad()
        loss = crit(model(X), X)
        loss.backward()
        opt.step()
        if ep % 30 == 0:
            print(f"  Epoch {ep:3d} | Loss: {loss.item():.6f}")

    model.eval()
    with torch.no_grad():
        r = model(X)
        l = torch.mean((r - X)**2, dim=(1, 2)).cpu().numpy()
        threshold = float(np.mean(l) + 3 * np.std(l))

    print(f"[성준] 학습 완료 | 임계치(μ+3σ): {threshold:.6f}")
    return model, scaler, threshold


def classify_event(feat_window, recon_error, threshold, zone):
    """
    feat_window : shape (SEQ_LEN, FEATURE_DIM) — 피크 시점 피처 윈도우
    피처 인덱스: [cx, cy, cz, mean_doppler, doppler_std,
                 intensity_mean, num_points, z_velocity]

    분류 우선순위: 낙상 > 감전 > 협착 > 진동이상

    Zone 사전 확률:
        Zone A (변전실) → 감전 임계값 완화
        Zone B (가공실) → 협착 임계값 완화
    """
    peak     = feat_window[-1]   # 가장 최근 프레임 피처
    cy       = float(peak[1])
    mean_dop = float(peak[3])
    dop_std  = float(peak[4])
    z_vel    = float(peak[7])
    excess   = recon_error / threshold
    conf_base = round(min(0.99, 0.55 + 0.20 * min(1.0, excess - 1.0)), 2)

    print(f"  [분류] cy={cy:.2f} | mean_dop={mean_dop:.3f} | "
          f"dop_std={dop_std:.4f} | z_vel={z_vel:.3f} | excess={excess:.2f}")

    # ── 낙상: Z 급강하 + 높은 절대 도플러 ─────────────────────────
    if z_vel < -0.10 and abs(mean_dop) > 0.18:
        return {
            "event_type": "fall_detected",
            "severity":   "critical",
            "confidence": round(min(0.99, conf_base + 0.10), 2),
        }

    # ── 감전: Zone A(변전실) 전용 + 높은 doppler_std (60Hz 경련) ──────────────
    # Zone B(가공실)에서 dop_std가 높으면 협착으로 분류 — 혼동 방지
    if zone == "A" and dop_std > 0.030 and abs(z_vel) < 0.15:
        return {
            "event_type": "electric_shock_risk",
            "severity":   "critical",
            "confidence": round(min(0.99, conf_base + 0.08), 2),
        }

    # ── 협착: Zone B(가공실) 우선 + 장비 근접 + 도플러 진동 (30Hz 회전체) ──
    pinch_cy_thr = 0.85 if zone == "B" else 0.70
    if dop_std > 0.010 and abs(z_vel) < 0.15 and cy < pinch_cy_thr:
        return {
            "event_type": "pinching",
            "severity":   "critical",
            "confidence": conf_base,
        }

    # ── 진동이상: 저주파 도플러 진동, 위치 고정 ────────────────────
    if dop_std > 0.004:
        return {
            "event_type": "vibration_anomaly",
            "severity":   "warning",
            "confidence": round(min(0.99, 0.45 + 0.30 * min(1.0, excess - 1.0)), 2),
        }

    # 기본값
    return {
        "event_type": "fall_detected",
        "severity":   "warning",
        "confidence": round(min(0.75, 0.40 + 0.10 * excess), 2),
    }


def build_details(event_type, feat_window, recon_error, threshold, timing):
    """
    분류 결과 + 피처 → 유빈 RAG에 전달할 세부 정보 딕셔너리 생성
    """
    excess = recon_error / threshold
    peak   = feat_window[-1]
    cx, cy, cz = float(peak[0]), float(peak[1]), float(peak[2])
    mean_dop   = float(peak[3])
    dop_std    = float(peak[4])
    z_vel      = float(peak[7])

    base = {
        "anomaly_score":        round(excess, 3),
        "reconstruction_error": round(recon_error, 6),
        "centroid_xyz":         [round(cx, 2), round(cy, 2), round(cz, 2)],
        "timing":               timing,
    }

    if event_type == "fall_detected":
        base["description"] = "작업자 낙상 확정 (Z축 급강하 + 고속 도플러)"
        base["worker_pose"] = {
            "posture":       "collapsed",
            "fall_height_m": round(max(0.1, 1.7 - cz), 2),
            "velocity_m_s":  round(abs(mean_dop), 3),
            "z_velocity":    round(z_vel, 3),
        }
        base["equipment_anomaly"] = None

    elif event_type == "electric_shock_risk":
        base["description"]          = "감전 위험 — 60Hz 불수의 근육 경련 감지"
        base["spasm_doppler_std"]    = round(dop_std, 4)
        base["contact_position_m"]   = [round(cx, 2), round(cy, 2), round(cz, 2)]
        base["estimated_current_hz"] = 60          # 한국 전력선 주파수

    elif event_type == "pinching":
        base["description"]           = "협착 감지 (회전체 근접 + 압박 신호 지속)"
        base["equipment_proximity_m"] = round(cy, 2)
        base["rotation_doppler_std"]  = round(dop_std, 4)
        base["rotation_rpm"]          = int(min(dop_std * 2000, 3600))

    elif event_type == "vibration_anomaly":
        base["description"]           = "진동 이상 (저주파 드리프트 패턴)"
        base["vibration_doppler_std"] = round(dop_std, 4)
        base["estimated_freq_hz"]     = round(dop_std * 60, 1)

    return base


def seongjun_detect(stage1):
    features  = np.array(stage1["features"], dtype=np.float32)
    zone      = stage1["zone_id"]
    base_time = datetime.fromisoformat(stage1["timestamp"])
    scenario  = stage1["scenario"]

    model, scaler, threshold = train_model()

    scaled = scaler.transform(features)
    X_test = torch.from_numpy(
        create_sequences(scaled, SEQ_LEN)
    ).float().to(DEVICE)

    model.eval()
    with torch.no_grad():
        recon     = model(X_test)
        test_loss = torch.mean((recon - X_test)**2, dim=(1, 2)).cpu().numpy()
    is_anomaly = test_loss > threshold

    print(f"[성준] 임계치: {threshold:.6f} | "
          f"이상 탐지: {is_anomaly.sum()}건 / {len(is_anomaly)}건")

    if not is_anomaly.any():
        print("[성준] 이상 없음")
        return None, test_loss, is_anomaly, threshold, None, None

    # 사고 타이밍 계산
    anomaly_steps = np.where(is_anomaly)[0]
    start_step    = int(anomaly_steps[0])
    peak_step     = int(np.argmax(test_loss))
    duration      = int(len(anomaly_steps))
    ms_per_frame  = 1000 // FRAME_RATE          # 100ms
    elapsed_ms    = round(start_step * ms_per_frame, 1)

    timing = {
        "anomaly_start_step": start_step,
        "anomaly_peak_step":  peak_step,
        "anomaly_duration":   duration,
        "event_timestamp":    (base_time + timedelta(
                               milliseconds=elapsed_ms)).isoformat(),
        "elapsed_ms":         elapsed_ms,
    }

    # classify / build_details 는 원본 단위(m, m/s)가 필요하므로 raw 피처 사용
    feat_window_raw    = features[peak_step:peak_step + SEQ_LEN]
    feat_window_scaled = scaled[peak_step:peak_step + SEQ_LEN]
    peak_error  = float(test_loss[peak_step])
    clf         = classify_event(feat_window_raw, peak_error, threshold, zone)
    details     = build_details(
        clf["event_type"], feat_window_raw, peak_error, threshold, timing
    )

    now   = datetime.now()
    event = {
        "schema_version": "1.0",
        "timestamp":      now.isoformat(),
        "event_id":       f"evt_{now.strftime('%Y%m%d_%H%M%S')}_{zone}001",
        "event_type":     clf["event_type"],
        "zone_id":        zone,
        "severity":       clf["severity"],
        "confidence":     clf["confidence"],
        "details":        details,
        "event_log": [
            {"time": now.strftime("%H:%M:%S"),
             "msg":  f"Zone {zone} - LSTM-AE 이상 탐지"},
            {"time": now.strftime("%H:%M:%S"),
             "msg":  f"Zone {zone} - 유형: {clf['event_type']}"},
            {"time": now.strftime("%H:%M:%S"),
             "msg":  f"Zone {zone} - 알림 발송"},
        ],
    }
    with open("stage2_event.json", "w", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False, indent=2)
    print(f"[성준] 완료 → stage2_event.json 저장")
    return event, test_loss, is_anomaly, threshold, timing, clf


# ================================================================
# 재국 파트: 자동 대응 + ui_trigger.json 생성
# ================================================================
RESPONSE_MAP = {
    "fall_detected": {
        "action":         "EMERGENCY_ALERT",
        "description":    "비상 알림 발송 + 구조 요청",
        "breaker_status": "HOLD",
        "response_ms":    200,
        "notify_level":   "CRITICAL",
    },
    "electric_shock_risk": {
        "action":         "POWER_CUT",
        "description":    "전원 차단 실행 — 감전 위험 즉시 대응",
        "breaker_status": "OPEN",
        "response_ms":    50,
        "notify_level":   "CRITICAL",
    },
    "pinching": {
        "action":         "MACHINE_STOP",
        "description":    "회전체 긴급 정지 명령",
        "breaker_status": "OPEN",
        "response_ms":    100,
        "notify_level":   "CRITICAL",
    },
    "vibration_anomaly": {
        "action":         "WARNING_ALERT",
        "description":    "점검 경고 알림 발송",
        "breaker_status": "HOLD",
        "response_ms":    500,
        "notify_level":   "WARNING",
    },
}


def jaeguk_breaker(event):
    event_type = event.get("event_type", "unknown")
    severity   = event.get("severity", "warning")
    zone       = event.get("zone_id", "?")
    confidence = event.get("confidence", 0.0)
    timing     = event.get("details", {}).get("timing", {})

    resp = RESPONSE_MAP.get(event_type)
    if not resp:
        print(f"[재국] 알 수 없는 이벤트: {event_type} → 대응 없음")
        return

    print(f"\n{'='*55}")
    print(f"  ★ Radar-Guard 자동 대응 실행")
    print(f"{'='*55}")
    print(f"  사고 유형  : {event_type}")
    print(f"  구역       : Zone {zone}")
    print(f"  대응 명령  : {resp['action']}")
    print(f"  차단기 상태: {resp['breaker_status']}")
    print(f"  설명       : {resp['description']}")
    print(f"  응답 시간  : {resp['response_ms']}ms")

    time.sleep(resp["response_ms"] / 1000.0)

    now     = datetime.now()
    trigger = {
        "schema_version": "1.0",
        "trigger_time":   now.isoformat(),
        "event_id":       event.get("event_id", ""),
        "event_type":     event_type,
        "severity":       severity,
        "zone_id":        zone,
        "confidence":     confidence,
        "action":         resp["action"],
        "breaker_status": resp["breaker_status"],
        "notify_level":   resp["notify_level"],
        "description":    resp["description"],
        "response_ms":    resp["response_ms"],
        "timing":         timing,
        # ── 유빈 RAG 호출에 필요한 세부 정보 전달 ──────────────
        "details":        event.get("details", {}),
        "event_log":      event.get("event_log", []) + [
            {
                "time": now.strftime("%H:%M:%S"),
                "msg":  f"[Breaker] Zone {zone} — {resp['action']} 실행 완료",
            }
        ],
    }

    with open("ui_trigger.json", "w", encoding="utf-8") as f:
        json.dump(trigger, f, ensure_ascii=False, indent=2)

    print(f"[재국] 완료 → ui_trigger.json 저장 (유빈 파트로 전달)")
    print(f"{'='*55}\n")


# ================================================================
# 유빈 UI 미리보기
# ================================================================
def print_yubin_preview(event):
    EVENT_KR = {
        "fall_detected":       "🚨 낙상",
        "electric_shock_risk": "⚡ 감전 위험",
        "pinching":            "⚙️  협착",
        "vibration_anomaly":   "📳 진동이상",
    }
    SEVERITY_KR = {"critical": "즉각 대응", "warning": "주의"}

    label    = EVENT_KR.get(event["event_type"], event["event_type"])
    severity = SEVERITY_KR.get(event["severity"], event["severity"])
    timing   = event["details"]["timing"]
    det      = event["details"]

    print("\n" + "="*55)
    print("  ★ 유빈 UI에 표시될 내용 미리보기")
    print("="*55)
    print(f"  사고 유형  : {label}")
    print(f"  심각도     : {severity} ({event['severity']})")
    print(f"  신뢰도     : {event['confidence']:.0%}")
    print(f"  구역       : Zone {event['zone_id']}")
    print(f"  발생 시각  : {timing['event_timestamp']}")
    print(f"  사고 시작  : step {timing['anomaly_start_step']}")
    print(f"  피크 시점  : step {timing['anomaly_peak_step']}")
    print(f"  지속 구간  : {timing['anomaly_duration']} steps "
          f"({timing['elapsed_ms']} ms)")
    print(f"  centroid   : {det.get('centroid_xyz')}")

    et = event["event_type"]
    if et == "fall_detected":
        wp = det.get("worker_pose", {})
        print(f"  낙하 높이  : {wp.get('fall_height_m')} m")
        print(f"  낙하 속도  : {wp.get('velocity_m_s')} m/s")
    elif et == "electric_shock_risk":
        print(f"  경련 강도  : doppler_std={det.get('spasm_doppler_std')}")
        print(f"  추정 전류  : {det.get('estimated_current_hz')} Hz")
    elif et == "pinching":
        print(f"  장비 근접  : {det.get('equipment_proximity_m')} m")
        print(f"  회전수(추정): {det.get('rotation_rpm')} RPM")
    elif et == "vibration_anomaly":
        print(f"  진동 강도  : doppler_std={det.get('vibration_doppler_std')}")
        print(f"  이상 주파수: {det.get('estimated_freq_hz')} Hz")

    print("="*55)
    print(f"\n  → stage2_event.json 저장 완료 (유빈 파트로 전달)")


# ================================================================
# 그래프 시각화
# ================================================================
def plot_result(test_loss, is_anomaly, threshold, timing, clf,
                scenario, features_raw):
    """
    Left  : 재구성 오차 + 이벤트 타이밍
    Center: centroid Z 궤적 (낙상 감지용)
    Right : doppler_std 궤적 (감전/협착/진동 감지용)
    """
    DETECTED_EN = {
        "fall_detected":       "Fall",
        "electric_shock_risk": "Electric Shock",
        "pinching":            "Pinching",
        "vibration_anomaly":   "Vibration",
    }
    SCENARIO_EN = {
        "fall":           "Fall",
        "electric_shock": "Electric Shock",
        "pinching":       "Pinching",
        "vibration":      "Vibration",
    }
    CORRECT_MAP = {
        "fall":           "fall_detected",
        "electric_shock": "electric_shock_risk",
        "pinching":       "pinching",
        "vibration":      "vibration_anomaly",
    }

    input_label    = SCENARIO_EN[scenario]
    detected_label = DETECTED_EN.get(clf["event_type"], clf["event_type"])
    is_correct     = CORRECT_MAP[scenario] == clf["event_type"]
    tag            = "✓ Correct" if is_correct else "⚠ Misclassified"
    color          = "#2C3E50" if is_correct else "#C0392B"

    feat_arr = np.array(features_raw)   # (N_FRAMES, FEATURE_DIM)
    cz_trace   = feat_arr[:, 2]         # centroid Z
    dstd_trace = feat_arr[:, 4]         # doppler_std

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))
    fig.suptitle(
        f"Radar-Guard  |  Input: {input_label}  →  Detected: {detected_label}  {tag}",
        fontsize=12, fontweight="bold", color=color,
    )

    # ── (1) Reconstruction Error ──────────────────────────────
    ax = axes[0]
    ax.plot(test_loss, color="royalblue", lw=1.5, label="Recon Error (MSE)")
    ax.axhline(threshold, color="red", linestyle="--", lw=1.8,
               label=f"Threshold μ+3σ={threshold:.4f}")
    if timing:
        ax.axvspan(timing["anomaly_start_step"],
                   timing["anomaly_start_step"] + timing["anomaly_duration"],
                   color="orange", alpha=0.2, label="Accident Window")
        ax.axvline(timing["anomaly_start_step"], color="#F39C12",
                   lw=1.5, linestyle=":", label=f"Start {timing['anomaly_start_step']}")
        ax.axvline(timing["anomaly_peak_step"], color="red",
                   lw=2, linestyle="-.", label=f"Peak {timing['anomaly_peak_step']}")
    ax.set_title("(1) Recon Error + Event Timing", fontweight="bold")
    ax.set_xlabel("Frame"); ax.set_ylabel("MSE Loss")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)

    # ── (2) Centroid Z 궤적 (낙상 감지) ──────────────────────
    ax = axes[1]
    ax.plot(cz_trace, color="steelblue", lw=1.5, label="Centroid Z (m)")
    if timing:
        ax.axvline(timing["anomaly_start_step"], color="#F39C12",
                   lw=1.5, linestyle=":", alpha=0.8)
        ax.axvline(timing["anomaly_peak_step"], color="red",
                   lw=2, linestyle="-.", alpha=0.8)
    ax.axhline(0.5, color="gray", linestyle="--", alpha=0.5, label="Floor ~0.5m")
    ax.set_title("(2) Centroid Z — Fall Detection", fontweight="bold")
    ax.set_xlabel("Frame"); ax.set_ylabel("Z (m)")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)

    # ── (3) Doppler Std 궤적 (감전/협착/진동 감지) ───────────
    ax = axes[2]
    ax.plot(dstd_trace, color="darkorange", lw=1.5, label="Doppler Std")
    if timing:
        ax.axvline(timing["anomaly_start_step"], color="#F39C12",
                   lw=1.5, linestyle=":", alpha=0.8)
        ax.axvline(timing["anomaly_peak_step"], color="red",
                   lw=2, linestyle="-.", alpha=0.8)

    # 분류 결과 요약 박스
    if timing:
        summary = (
            f"event_type : {clf['event_type']}\n"
            f"severity   : {clf['severity']}\n"
            f"confidence : {clf['confidence']:.0%}\n"
            f"start_step : {timing['anomaly_start_step']}\n"
            f"peak_step  : {timing['anomaly_peak_step']}\n"
            f"duration   : {timing['anomaly_duration']} steps\n"
            f"elapsed_ms : {timing['elapsed_ms']} ms"
        )
        ax.text(0.02, 0.97, summary, transform=ax.transAxes,
                fontsize=8, va="top", fontfamily="monospace",
                bbox=dict(boxstyle="round,pad=0.4", facecolor="#FFF9C4",
                          edgecolor="#F39C12", alpha=0.9))

    ax.set_title("(3) Doppler Std — Shock / Pinching / Vibration", fontweight="bold")
    ax.set_xlabel("Frame"); ax.set_ylabel("Doppler Std (m/s)")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)

    plt.tight_layout()
    display(fig)
    fig.savefig(f"result_{scenario}.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[저장] result_{scenario}.png")
    return fig


# ================================================================
# 메인 실행
# ================================================================
print(f"\n{'='*55}")
print(f"  Radar-Guard 파이프라인 실행 (Point Cloud 버전)")
print(f"  선택 시나리오: {SCENARIO_KR[SCENARIO]} ({SCENARIO})")
print(f"  Zone: {ZONE_MAP[SCENARIO]}")
print(f"{'='*55}")

# 1. 민석 파트: Point Cloud 목데이터 생성
radar_data = minseok_generate(SCENARIO)

# 2. 승원 파트: LMS 필터 + 피처 추출
stage1 = seungwon_process(radar_data)

# 3. 성준 파트: LSTM-AE 탐지 + 분류
event, test_loss, is_anomaly, threshold, timing, clf = seongjun_detect(stage1)

# 4. 재국 파트: 자동 대응
if event:
    jaeguk_breaker(event)

# 5. 유빈 UI 미리보기 + 그래프
if event:
    print_yubin_preview(event)
    plot_result(
        test_loss, is_anomaly, threshold,
        timing, clf, SCENARIO,
        stage1["features"],
    )
else:
    print("\n[결과] 이상 없음 — 유빈 UI에 전달할 이벤트 없음")
