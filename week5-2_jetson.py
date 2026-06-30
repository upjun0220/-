"""
Radar-Guard 통합 관제 시스템 v2-Jetson (week5-2_jetson.py)
===========================================================
week5-2_pc.py 를 Jetson Orin Nano 환경에 맞게 수정한 버전.

PC → Jetson 변경 사항:
  - 임베딩 모델:  bge-m3  →  nomic-embed-text
  - LLM 모델:     qwen2.5:3b-instruct-q4_K_M  →  llama3:8b
  - DB 연결:      admin:1234  →  postgres:password

실행 (Jetson 터미널 or VS Code Remote SSH 터미널):
    python3 -m streamlit run ~/week5-2_jetson.py

필수 사전 조건:
    sudo docker start radar-guard-db
    ollama serve  (또는 이미 실행 중)  → 모델: llama3:8b, nomic-embed-text
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
from datetime import datetime, timedelta

import streamlit as st
import plotly.graph_objects as go

import torch
import torch.nn as nn
from torch import optim
from sklearn.preprocessing import MinMaxScaler

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ===================================================================
# 페이지 설정 (week5-2.py 동일)
# ===================================================================
st.set_page_config(
    page_title="Radar-Guard 관제 시스템 v2-Jetson",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===================================================================
# ══════════════════════════════════════════════════════════════════
# 민석 파트: mmWave Point Cloud 목데이터 생성
# ══════════════════════════════════════════════════════════════════
# ===================================================================

FRAME_RATE  = 10
N_FRAMES    = 200
FEATURE_DIM = 8
SEQ_LEN     = 5
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


def _person_points(n=5, x0=0.0, y0=2.0, z0=1.7,
                   dx=0.08, dy=0.08, dz=0.05,
                   dop_mean=0.0, dop_std=0.008,
                   int_lo=300, int_hi=500):
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


def make_point_cloud(scenario, n_frames=N_FRAMES, seed=42):
    np.random.seed(seed)
    onset = {
        "fall":           np.random.randint(90, 110),
        "electric_shock": np.random.randint(70, 88),
        "pinching":       np.random.randint(65, 85),
        "vibration":      np.random.randint(90, 108),
    }[scenario]

    frames = []
    for i in range(n_frames):
        t_since = max(0, i - onset)

        if scenario == "fall":
            if i < onset:
                pts = _person_points(n=np.random.randint(4, 7), y0=2.0, z0=1.7)
            elif t_since <= 8:
                frac    = t_since / 8.0
                cur_z   = 1.7 - frac * 1.4
                cur_dop = -1.5 + np.random.normal(0, 0.3)
                pts = _person_points(n=np.random.randint(5, 9), y0=2.0, z0=cur_z, dz=0.10,
                                     dop_mean=cur_dop, dop_std=0.25, int_lo=450, int_hi=700)
            else:
                pts = _person_points(n=np.random.randint(2, 5), y0=1.9, z0=0.3, dz=0.06,
                                     dop_mean=0.0, dop_std=0.006, int_lo=180, int_hi=320)

        elif scenario == "electric_shock":
            if i < onset:
                approach = min(1.0, i / onset)
                cur_y    = 2.5 - approach * 1.7
                pts = _person_points(n=np.random.randint(4, 6), y0=cur_y, z0=1.7,
                                     dop_mean=-0.15*approach, dop_std=0.01)
            else:
                phase    = t_since * (2 * np.pi * 60 / FRAME_RATE)
                spasm    = np.sin(phase) * 0.075
                cur_z    = max(1.2, 1.7 - t_since * 0.005)
                pts = _person_points(n=np.random.randint(5, 9), x0=0.2, y0=0.8, z0=cur_z, dz=0.04,
                                     dop_mean=spasm, dop_std=0.065, int_lo=350, int_hi=560)

        elif scenario == "pinching":
            if i < onset:
                approach = min(1.0, i / onset)
                cur_y    = 2.5 - approach * 2.0
                cur_dop  = -0.4 * approach + np.random.normal(0, 0.04)
                pts = _person_points(n=np.random.randint(4, 7), y0=cur_y, z0=1.7,
                                     dop_mean=cur_dop, dop_std=0.012)
            else:
                phase   = t_since * (2 * np.pi * 30 / FRAME_RATE)
                rot_dop = np.sin(phase) * 0.055
                pts = _person_points(n=np.random.randint(5, 8), y0=0.5, z0=1.5, dy=0.04, dz=0.05,
                                     dop_mean=rot_dop, dop_std=0.060, int_lo=400, int_hi=660)

        else:  # vibration
            if i < onset:
                pts = _person_points(n=np.random.randint(3, 6), x0=1.0, y0=1.5, z0=0.8,
                                     dx=0.04, dy=0.04, dz=0.03,
                                     dop_mean=0.0, dop_std=0.004, int_lo=250, int_hi=380)
            else:
                amp   = min(0.10, 0.015 + t_since * 0.0008)
                phase = t_since * (2 * np.pi * 5 / FRAME_RATE)
                vib   = np.sin(phase) * amp
                pts = _person_points(n=np.random.randint(3, 6), x0=1.0, y0=1.5, z0=0.8,
                                     dx=0.04, dy=0.04, dz=0.03,
                                     dop_mean=vib, dop_std=amp*0.3 + 0.010, int_lo=250, int_hi=400)

        frames.append(pts)
    return frames, onset


# ===================================================================
# 승원 파트: LMS 필터 + Point Cloud 피처 추출
# ===================================================================

class LMSFilter:
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
    if not frame_points:
        return np.zeros(FEATURE_DIM, dtype=np.float32)
    pts = np.array(
        [[p["x"], p["y"], p["z"], p["doppler"], p["intensity"]] for p in frame_points],
        dtype=np.float32,
    )
    centroid       = pts[:, :3].mean(axis=0)
    mean_doppler   = float(pts[:, 3].mean())
    doppler_std    = float(pts[:, 3].std() + 1e-8)
    intensity_mean = float(pts[:, 4].mean())
    num_points     = float(len(pts))
    z_velocity     = float(centroid[2] - prev_centroid[2]) if prev_centroid is not None else 0.0
    return np.array([
        centroid[0], centroid[1], centroid[2],
        mean_doppler, doppler_std, intensity_mean,
        num_points, z_velocity,
    ], dtype=np.float32)


# ===================================================================
# 성준 파트: LSTM-AE 이상 탐지 + 분류
# ===================================================================

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
        x, _ = self.dec1(x)
        x, _ = self.dec2(x)
        return self.fc(x)


def create_sequences(data, seq_len):
    return np.array([data[i:i+seq_len] for i in range(len(data)-seq_len)])


@st.cache_resource(show_spinner="🧠 LSTM-AE 정상 패턴 학습 중... (최초 1회)")
def get_trained_model():
    """정상 패턴으로 LSTM-AE 학습 → (model, scaler, threshold) 반환. 캐싱되어 재학습 없음."""
    np.random.seed(0)
    torch.manual_seed(0)

    lms         = LMSFilter()
    normal_feat = []
    prev_c      = None

    for idx in range(1000):
        if idx % 10 < 7:
            pts = _person_points(n=np.random.randint(3, 7),
                                 y0=np.random.uniform(1.5, 2.5),
                                 z0=np.random.uniform(1.60, 1.80),
                                 dop_mean=np.random.uniform(-0.02, 0.02),
                                 dop_std=np.random.uniform(0.004, 0.010))
        else:
            pts = _person_points(n=np.random.randint(3, 7),
                                 y0=np.random.uniform(1.0, 3.0),
                                 z0=np.random.uniform(1.60, 1.80),
                                 dop_mean=np.random.uniform(-0.25, 0.25),
                                 dop_std=np.random.uniform(0.008, 0.018))
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
    for _ in range(100):   # 121 → 100으로 단축 (속도)
        opt.zero_grad()
        loss = crit(model(X), X)
        loss.backward()
        opt.step()

    model.eval()
    with torch.no_grad():
        r = model(X)
        l = torch.mean((r - X)**2, dim=(1, 2)).cpu().numpy()
        threshold = float(np.mean(l) + 3 * np.std(l))

    return model, scaler, threshold


def classify_event(feat_window, recon_error, threshold, zone):
    peak     = feat_window[-1]
    cy       = float(peak[1])
    mean_dop = float(peak[3])
    dop_std  = float(peak[4])
    z_vel    = float(peak[7])
    excess   = recon_error / threshold
    conf_base = round(min(0.99, 0.55 + 0.20 * min(1.0, excess - 1.0)), 2)

    if z_vel < -0.10 and abs(mean_dop) > 0.18:
        return {"event_type": "fall_detected", "severity": "critical",
                "confidence": round(min(0.99, conf_base + 0.10), 2)}
    if zone == "A" and dop_std > 0.030 and abs(z_vel) < 0.15:
        return {"event_type": "electric_shock_risk", "severity": "critical",
                "confidence": round(min(0.99, conf_base + 0.08), 2)}
    pinch_cy_thr = 0.85 if zone == "B" else 0.70
    if dop_std > 0.010 and abs(z_vel) < 0.15 and cy < pinch_cy_thr:
        return {"event_type": "pinching", "severity": "critical",
                "confidence": conf_base}
    if dop_std > 0.002:
        return {"event_type": "vibration_anomaly", "severity": "warning",
                "confidence": round(min(0.99, 0.45 + 0.30 * min(1.0, excess - 1.0)), 2)}
    return {"event_type": "fall_detected", "severity": "warning",
            "confidence": round(min(0.75, 0.40 + 0.10 * excess), 2)}


def build_details(event_type, feat_window, recon_error, threshold, timing):
    excess = recon_error / threshold
    peak   = feat_window[-1]
    cx, cy, cz = float(peak[0]), float(peak[1]), float(peak[2])
    mean_dop   = float(peak[3])
    dop_std    = float(peak[4])

    base = {
        "anomaly_score":        round(excess, 3),
        "reconstruction_error": round(recon_error, 6),
        "centroid_xyz":         [round(cx, 2), round(cy, 2), round(cz, 2)],
        "timing":               timing,
    }
    if event_type == "fall_detected":
        base["description"] = "작업자 낙상 확정 (Z축 급강하 + 고속 도플러)"
        base["worker_pose"] = {
            "posture": "collapsed",
            "fall_height_m": round(max(0.1, 1.7 - cz), 2),
            "velocity_m_s":  round(abs(mean_dop), 3),
        }
        base["equipment_anomaly"] = None
    elif event_type == "electric_shock_risk":
        base["description"]          = "감전 위험 — 60Hz 불수의 근육 경련 감지"
        base["spasm_doppler_std"]    = round(dop_std, 4)
        base["contact_position_m"]   = [round(cx, 2), round(cy, 2), round(cz, 2)]
        base["estimated_current_hz"] = 60
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


def run_detection(scenario, model, scaler, threshold):
    """파이프라인 전체 실행 → 결과 dict 반환"""
    zone      = ZONE_MAP[scenario]
    base_time = datetime.now()

    # 민석: Point Cloud 생성
    frames, onset = make_point_cloud(scenario)

    # 승원: LMS 필터 + 피처 추출
    lms           = LMSFilter()
    features      = []
    prev_centroid = None
    for frame_pts in frames:
        feat    = extract_pc_features(frame_pts, prev_centroid)
        ref     = float(np.random.normal(0, 0.004))
        feat[3] = lms.filter(feat[3], ref)
        prev_centroid = feat[:3].copy()
        features.append(feat.tolist())
    features_raw = np.array(features, dtype=np.float32)

    # 성준: LSTM-AE 탐지
    scaled = scaler.transform(features_raw)
    X_test = torch.from_numpy(create_sequences(scaled, SEQ_LEN)).float().to(DEVICE)

    with torch.no_grad():
        recon     = model(X_test)
        test_loss = torch.mean((recon - X_test)**2, dim=(1, 2)).cpu().numpy()
    is_anomaly = test_loss > threshold

    if not is_anomaly.any():
        return None  # 이상 없음

    anomaly_steps = np.where(is_anomaly)[0]
    start_step    = int(anomaly_steps[0])
    peak_step     = int(np.argmax(test_loss))
    duration      = int(len(anomaly_steps))
    elapsed_ms    = round(start_step * (1000 // FRAME_RATE), 1)

    timing = {
        "anomaly_start_step": start_step,
        "anomaly_peak_step":  peak_step,
        "anomaly_duration":   duration,
        "event_timestamp":    (base_time + timedelta(milliseconds=elapsed_ms)).isoformat(),
        "elapsed_ms":         elapsed_ms,
    }

    feat_window_raw = features_raw[peak_step:peak_step + SEQ_LEN]
    peak_error      = float(test_loss[peak_step])
    clf             = classify_event(feat_window_raw, peak_error, threshold, zone)
    details         = build_details(clf["event_type"], feat_window_raw, peak_error, threshold, timing)

    now      = datetime.now()
    event_id = f"evt_{now.strftime('%Y%m%d_%H%M%S')}_{zone}001"

    return {
        # 파이프라인 raw
        "_test_loss":    test_loss,
        "_is_anomaly":   is_anomaly,
        "_features_raw": features_raw,
        "_frames":       frames,
        "_onset":        onset,
        "_threshold":    threshold,
        "_timing":       timing,
        "_clf":          clf,
        # 이벤트 메타
        "schema_version": "1.0",
        "timestamp":      now.isoformat(),
        "event_id":       event_id,
        "event_type":     clf["event_type"],
        "zone_id":        zone,
        "severity":       clf["severity"],
        "confidence":     clf["confidence"],
        "details":        details,
        "event_log": [
            {"time": now.strftime("%H:%M:%S"),
             "msg":  f"Zone {zone} - LSTM-AE 이상 탐지 (score={round(peak_error/threshold,3)})"},
            {"time": now.strftime("%H:%M:%S"),
             "msg":  f"Zone {zone} - 유형 분류: {clf['event_type']}"},
            {"time": now.strftime("%H:%M:%S"),
             "msg":  f"Zone {zone} - 알림 발송 (severity={clf['severity']}, conf={clf['confidence']:.0%})"},
        ],
        # week5-2 호환 필드
        "zone": zone,
        "anomaly_score": round(peak_error / threshold, 3),
        "reconstruction_error": round(peak_error, 6),
    }


@st.cache_data(show_spinner="📡 Point Cloud 파이프라인 실행 중... (최초 1회)")
def build_pipeline_data():
    model, scaler, threshold = get_trained_model()
    results = {}
    for scenario in ["fall", "electric_shock", "pinching", "vibration"]:
        np.random.seed(scenario.__hash__() % 2**31)
        res = run_detection(scenario, model, scaler, threshold)
        # 탐지 실패 시 강제 기본값
        if res is None:
            continue
        # event_type을 시나리오에서 derive (분류 결과 우선, 폴백)
        results[scenario] = res
    return results


# ===================================================================
# 상수 / 매핑 (week5-2.py 동일)
# ===================================================================
EVENT_TYPE_TO_CATEGORY = {
    "fall_detected":       "03_낙상_응급처치",
    "electric_shock_risk": "01_감전_LOTO",
    "pinching":            "02_협착_끼임",
    "vibration_anomaly":   "04_예지보전",
}
EVENT_TYPE_KOREAN = {
    "fall_detected":       "작업자 낙상 감지",
    "electric_shock_risk": "감전 위험 감지",
    "pinching":            "협착 사고 감지",
    "vibration_anomaly":   "설비 진동 이상",
}
SEVERITY_EMOJI = {"normal": "🟢", "warning": "🟡", "critical": "🔴"}
SEVERITY_LABEL = {"normal": "정상", "warning": "경고", "critical": "위험"}
SEVERITY_BG    = {"normal": "#d4f4dd", "warning": "#fff3cd", "critical": "#f8d7da"}
CATEGORIES = {
    "전체": None,
    "01_감전_LOTO":       "01_감전_LOTO",
    "02_협착_끼임":       "02_협착_끼임",
    "03_낙상_응급처치":   "03_낙상_응급처치",
    "04_예지보전":        "04_예지보전",
    "05_위험성평가_비상": "05_위험성평가_비상",
}
SIG_COLOR = {
    "fall_detected":       "#E74C3C",
    "electric_shock_risk": "#F39C12",
    "pinching":            "#8E44AD",
    "vibration_anomaly":   "#795548",
}
SIG_LABEL = {
    "fall_detected":       "🚨 낙상",
    "electric_shock_risk": "⚡ 감전위험",
    "pinching":            "🔒 협착",
    "vibration_anomaly":   "⚙️ 진동이상",
}
# 시나리오 버튼 → event_type 기본 매핑 (분류 실패 폴백용)
SCENARIO_TO_EVENT = {
    "fall":           "fall_detected",
    "electric_shock": "electric_shock_risk",
    "pinching":       "pinching",
    "vibration":      "vibration_anomaly",
}

# ===================================================================
# 파이프라인 데이터 로드 (앱 시작 시)
# ===================================================================
_pipeline = build_pipeline_data()   # { scenario: result_dict }

# event_type → result_dict (RAG / event log 조회용)
LIVE_EVENTS = {}
for sc, res in _pipeline.items():
    LIVE_EVENTS[res["event_type"]] = res
    # 폴백: 시나리오 기본 event_type도 등록
    LIVE_EVENTS.setdefault(SCENARIO_TO_EVENT[sc], res)

CONNECTION_STRING = "postgresql://postgres:password@localhost:5432/radar_guard"

@st.cache_resource
def get_vectorstore():
    emb = OllamaEmbeddings(model="nomic-embed-text")
    return PGVector(connection_string=CONNECTION_STRING,
                    embedding_function=emb,
                    collection_name="safety_manual")

@st.cache_resource
def get_llm():
    return ChatOllama(model="llama3:8b", temperature=0)

# ===================================================================
# Session State
# ===================================================================
if "current_event"   not in st.session_state: st.session_state.current_event   = None
if "current_scenario" not in st.session_state: st.session_state.current_scenario = None
if "facility_status" not in st.session_state: st.session_state.facility_status = {"A":"normal","B":"normal","C":"normal"}
if "auto_run_rag"    not in st.session_state: st.session_state.auto_run_rag    = False


def load_scenario(scenario: str, facility: dict):
    res = _pipeline.get(scenario)
    if res:
        st.session_state.current_event    = res
        st.session_state.current_scenario = scenario
    st.session_state.facility_status = facility
    st.session_state.auto_run_rag    = True


def reset_state():
    st.session_state.current_event    = None
    st.session_state.current_scenario = None
    st.session_state.facility_status  = {"A":"normal","B":"normal","C":"normal"}
    st.session_state.auto_run_rag     = False

# ===================================================================
# 사이드바
# ===================================================================
with st.sidebar:
    st.header("🔍 검색 설정")
    default_idx = 0
    if st.session_state.current_event:
        auto_cat = EVENT_TYPE_TO_CATEGORY.get(st.session_state.current_event["event_type"])
        cat_list = list(CATEGORIES.keys())
        if auto_cat in cat_list:
            default_idx = cat_list.index(auto_cat)

    selected_category_label = st.selectbox("검색 카테고리", list(CATEGORIES.keys()),
                                           index=default_idx,
                                           help="이벤트 발생 시 자동 선택됩니다.")
    selected_category = CATEGORIES[selected_category_label]
    top_k = st.slider("검색 결과 수 (k)", 1, 5, 3)

    st.divider()
    st.subheader("🎬 시나리오 트리거")
    st.caption("Point Cloud 파이프라인 기반 이벤트 로드")
    st.button("▶ 1. 낙상 (Zone C)",       use_container_width=True, on_click=load_scenario,
              args=("fall",           {"A":"normal","B":"normal","C":"critical"}))
    st.button("▶ 2. 감전 위험 (Zone A)",  use_container_width=True, on_click=load_scenario,
              args=("electric_shock", {"A":"critical","B":"normal","C":"normal"}))
    st.button("▶ 3. 협착 (Zone B)",       use_container_width=True, on_click=load_scenario,
              args=("pinching",       {"A":"normal","B":"critical","C":"normal"}))
    st.button("▶ 4. 진동 이상 (Zone C)",  use_container_width=True, on_click=load_scenario,
              args=("vibration",      {"A":"normal","B":"normal","C":"warning"}))
    st.divider()
    st.button("🔄 초기화 (정상 상태)", use_container_width=True, on_click=reset_state)
    st.divider()
    st.caption("📌 민석: Point Cloud 목데이터 (TI IWR6843 시뮬)\n"
               "📌 승원: LMS 필터 + PC 피처 추출\n"
               "📌 성준: LSTM-AE 이상 탐지 + 분류\n"
               "📌 재국: 자동 대응 (ui_trigger 기반)\n"
               "📌 유빈: UI + RAG (Ollama + Llama3, Jetson)")

# ===================================================================
# 헤더
# ===================================================================
overall_status = "normal"
for s in st.session_state.facility_status.values():
    if s == "critical": overall_status = "critical"; break
    elif s == "warning" and overall_status != "critical": overall_status = "warning"

hcol1, hcol2, hcol3 = st.columns([5, 2, 2])
with hcol1:
    st.title("🛡️ Radar-Guard 관제 시스템 v2-Jetson")
    st.caption("⚡ Point Cloud 파이프라인 통합 (민석/승원/성준/재국/유빈)")
with hcol2:
    st.markdown("##### 시스템 상태")
    st.markdown(f"<h3 style='margin:0'>{SEVERITY_EMOJI[overall_status]} [{SEVERITY_LABEL[overall_status]}]</h3>",
                unsafe_allow_html=True)
with hcol3:
    st.markdown("##### 현재 시각")
    st.markdown(f"<h3 style='margin:0'>🕐 {datetime.now().strftime('%H:%M:%S')}</h3>",
                unsafe_allow_html=True)

st.divider()

# ===================================================================
# [구역 1] 3D Point Cloud | 진동 분석 + Event Log
# ===================================================================
left_col, right_col = st.columns([3, 2])

with left_col:
    st.subheader("📡 3D Point Cloud (mmWave)")

    if st.session_state.current_event and st.session_state.current_scenario:
        # 실제 파이프라인 프레임 사용: onset 직전 10프레임 + onset 후 40프레임
        res    = st.session_state.current_event
        frames = res["_frames"]
        onset  = res["_onset"]
        timing = res["_timing"]

        # 시각화할 프레임 범위 (onset -10 ~ onset+40)
        f_start = max(0, onset - 10)
        f_end   = min(len(frames), onset + 40)
        x_arr, y_arr, z_arr, intensity_arr, frame_arr = [], [], [], [], []
        for fi in range(f_start, f_end):
            for pt in frames[fi]:
                x_arr.append(pt["x"])
                y_arr.append(pt["y"])
                z_arr.append(pt["z"])
                intensity_arr.append(pt["intensity"])
                frame_arr.append(fi - f_start)

        color_arr = np.array(intensity_arr)
        fig_3d = go.Figure(data=[go.Scatter3d(
            x=x_arr, y=y_arr, z=z_arr, mode="markers",
            marker=dict(size=3, color=color_arr, colorscale="Viridis",
                        opacity=0.75, showscale=True,
                        colorbar=dict(title="Intensity", thickness=12)),
            customdata=frame_arr,
            hovertemplate="X:%{x:.2f} Y:%{y:.2f} Z:%{z:.2f}<br>Frame+%{customdata}<extra></extra>",
        )])
        # onset 라인 표시용 박스 (onset 위치 강조)
        fig_3d.add_trace(go.Scatter3d(
            x=[0], y=[0], z=[1.7], mode="markers",
            marker=dict(size=8, color="red", symbol="diamond"),
            name="작업자 기준점",
        ))
    else:
        # 정상 상태: 배경 노이즈
        np.random.seed(42)
        n_bg = 200
        x_arr = np.random.uniform(-2, 2, n_bg).tolist()
        y_arr = np.random.uniform(0.5, 3.5, n_bg).tolist()
        z_arr = np.random.uniform(0, 2.5, n_bg).tolist()
        intensity_arr = np.random.uniform(0, 0.5, n_bg).tolist()
        fig_3d = go.Figure(data=[go.Scatter3d(
            x=x_arr, y=y_arr, z=z_arr, mode="markers",
            marker=dict(size=3, color=intensity_arr, colorscale="Viridis",
                        opacity=0.75, showscale=True,
                        colorbar=dict(title="Intensity", thickness=12)),
        )])

    fig_3d.update_layout(
        scene=dict(xaxis_title="X (m)", yaxis_title="Y / 깊이 (m)", zaxis_title="Z / 높이 (m)",
                   aspectmode="cube"),
        height=440, margin=dict(l=0, r=0, t=0, b=0),
    )
    st.plotly_chart(fig_3d, use_container_width=True)

with right_col:
    st.subheader("📊 진동 분석")
    vib_value, vib_delta = "0.02 μm/s", "-0.01"
    if (st.session_state.current_event
            and st.session_state.current_event["event_type"] == "vibration_anomaly"):
        res = st.session_state.current_event
        dop_std  = float(res["_features_raw"][:, 4].max())
        vib_value = f"{dop_std:.4f} m/s (dop_std)"
        vib_delta = f"+{dop_std:.4f}"
    st.metric("설비 진동 (도플러 std)", vib_value, delta=vib_delta, delta_color="inverse")

    freq = np.linspace(0, 200, 200)
    normal_spectrum  = 0.05 * np.exp(-((freq - 60)**2) / 200) + 0.02
    current_spectrum = normal_spectrum.copy()
    if (st.session_state.current_event
            and st.session_state.current_event["event_type"] == "vibration_anomaly"):
        det = st.session_state.current_event["details"]
        dom = det.get("estimated_freq_hz", 5.0)
        current_spectrum += 0.18 * np.exp(-((freq - dom)**2) / 30)

    fig_vib = go.Figure()
    fig_vib.add_trace(go.Scatter(x=freq, y=normal_spectrum, name="정상 baseline",
                                  line=dict(color="green", dash="dash")))
    fig_vib.add_trace(go.Scatter(x=freq, y=current_spectrum, name="현재",
                                  line=dict(color="red")))
    fig_vib.update_layout(xaxis_title="주파수 (Hz)", yaxis_title="진폭", height=180,
                           margin=dict(l=0, r=0, t=10, b=0),
                           legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                       xanchor="right", x=1))
    st.plotly_chart(fig_vib, use_container_width=True)

    st.subheader("📋 Event Log")
    if st.session_state.current_event:
        for log in st.session_state.current_event["event_log"]:
            sev  = st.session_state.current_event["severity"]
            icon = "⚠️" if sev == "critical" else "📌"
            st.markdown(f"`[{log['time']}]` {icon} {log['msg']}")
    else:
        st.info("이벤트 대기 중... (사이드바에서 시나리오 트리거)")

st.divider()

# ===================================================================
# [구역 2] Facility Map (week5-2.py 동일)
# ===================================================================
st.subheader("🗺️ Facility Map")
zone_info = {
    "A": {"name": "Zone A (변전실)", "worker": "정상", "power": "정상"},
    "B": {"name": "Zone B (가공실)", "worker": "정상", "power": "정상"},
    "C": {"name": "Zone C (조립실)", "worker": "정상", "power": "정상"},
}
if st.session_state.current_event:
    evt  = st.session_state.current_event
    zone = evt["zone_id"]
    et   = evt["event_type"]
    if et == "fall_detected":
        zone_info[zone]["worker"] = "🔴 낙상"; zone_info[zone]["power"] = "🔴 차단"
    elif et == "electric_shock_risk":
        zone_info[zone]["worker"] = "🔴 감전 위험"; zone_info[zone]["power"] = "🔴 차단"
    elif et == "pinching":
        zone_info[zone]["worker"] = "🔴 협착"; zone_info[zone]["power"] = "🔴 차단"
    elif et == "vibration_anomaly":
        zone_info[zone]["worker"] = "정상"; zone_info[zone]["power"] = "🟡 모니터링 중"

zone_cols = st.columns(3)
for i, (zid, info) in enumerate(zone_info.items()):
    with zone_cols[i]:
        status = st.session_state.facility_status[zid]
        bg = SEVERITY_BG[status]
        st.markdown(
            f"""<div style="background-color:{bg};padding:16px;border-radius:8px;
                border-left:6px solid #555;min-height:120px;">
              <h4 style="margin:0 0 8px 0;">{SEVERITY_EMOJI[status]} {info['name']}</h4>
              <p style="margin:2px 0;"><b>상태:</b> {SEVERITY_LABEL[status]}</p>
              <p style="margin:2px 0;"><b>작업자:</b> {info['worker']}</p>
              <p style="margin:2px 0;"><b>전력:</b> {info['power']}</p>
            </div>""",
            unsafe_allow_html=True,
        )

st.divider()

# ===================================================================
# [구역 3] Point Cloud 파이프라인 분석 시각화
# ===================================================================
st.subheader("📡 Point Cloud 파이프라인 분석 (민석→승원→성준 파트)")

# ── (1) 재구성 오차 + 이벤트 타이밍 ──────────────────────────────
fig_recon = go.Figure()
for sc, res in _pipeline.items():
    et         = res["event_type"]
    test_loss  = res["_test_loss"]
    timing     = res["_timing"]
    threshold  = res["_threshold"]
    frames_x   = list(range(len(test_loss)))

    fig_recon.add_trace(go.Scatter(
        x=frames_x, y=test_loss, mode="lines",
        name=SIG_LABEL.get(et, et),
        line=dict(color=SIG_COLOR.get(et, "#999"), width=2),
        opacity=0.85,
    ))

# 임계값 선 (첫 번째 시나리오 기준)
first_res = next(iter(_pipeline.values()))
threshold_val = first_res["_threshold"]
fig_recon.add_hline(
    y=threshold_val, line_dash="dash", line_color="red", line_width=1.8,
    annotation_text=f"임계치 μ+3σ={threshold_val:.4f}", annotation_position="top right"
)

# 현재 이벤트 onset 강조
if st.session_state.current_event:
    timing = st.session_state.current_event["_timing"]
    fig_recon.add_vrect(
        x0=timing["anomaly_start_step"], x1=timing["anomaly_start_step"] + timing["anomaly_duration"],
        fillcolor="orange", opacity=0.15, line_width=0,
        annotation_text="사고 구간", annotation_position="top left",
    )
    fig_recon.add_vline(x=timing["anomaly_peak_step"], line_color="red",
                        line_dash="dashdot", line_width=2,
                        annotation_text=f"피크 {timing['anomaly_peak_step']}",
                        annotation_position="top right")

fig_recon.update_layout(
    title="(1) LSTM-AE 재구성 오차 (Reconstruction Error)",
    xaxis_title="Frame", yaxis_title="MSE Loss",
    height=300, margin=dict(l=0, r=0, t=40, b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1),
    plot_bgcolor="#FAFAFA",
)
st.plotly_chart(fig_recon, use_container_width=True)

# ── (2) Centroid Z + Doppler Std 궤적 ────────────────────────────
pc_col1, pc_col2 = st.columns(2)

with pc_col1:
    fig_cz = go.Figure()
    for sc, res in _pipeline.items():
        et         = res["event_type"]
        feat_arr   = res["_features_raw"]
        cz_trace   = feat_arr[:, 2]   # centroid Z
        fig_cz.add_trace(go.Scatter(
            x=list(range(len(cz_trace))), y=cz_trace.tolist(),
            mode="lines", name=SIG_LABEL.get(et, et),
            line=dict(color=SIG_COLOR.get(et, "#999"), width=2),
            opacity=0.85,
        ))
    if st.session_state.current_event:
        timing = st.session_state.current_event["_timing"]
        fig_cz.add_vline(x=timing["anomaly_start_step"], line_color="orange",
                         line_dash="dot", line_width=1.5)
        fig_cz.add_vline(x=timing["anomaly_peak_step"], line_color="red",
                         line_dash="dashdot", line_width=2)
    fig_cz.add_hline(y=0.5, line_color="gray", line_dash="dash",
                     annotation_text="바닥 ~0.5m", annotation_position="right")
    fig_cz.update_layout(
        title="(2) Centroid Z — 낙상 감지 지표",
        xaxis_title="Frame", yaxis_title="Z (m)",
        height=300, margin=dict(l=0, r=0, t=40, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.05),
        plot_bgcolor="#FAFAFA",
    )
    st.plotly_chart(fig_cz, use_container_width=True)

with pc_col2:
    fig_dstd = go.Figure()
    for sc, res in _pipeline.items():
        et         = res["event_type"]
        feat_arr   = res["_features_raw"]
        dstd_trace = feat_arr[:, 4]   # doppler_std
        fig_dstd.add_trace(go.Scatter(
            x=list(range(len(dstd_trace))), y=dstd_trace.tolist(),
            mode="lines", name=SIG_LABEL.get(et, et),
            line=dict(color=SIG_COLOR.get(et, "#999"), width=2),
            opacity=0.85,
        ))
    if st.session_state.current_event:
        timing = st.session_state.current_event["_timing"]
        clf    = st.session_state.current_event["_clf"]
        fig_dstd.add_vline(x=timing["anomaly_start_step"], line_color="orange",
                           line_dash="dot", line_width=1.5)
        fig_dstd.add_vline(x=timing["anomaly_peak_step"], line_color="red",
                           line_dash="dashdot", line_width=2)
        # 분류 결과 요약 박스
        summary = (
            f"event_type : {clf['event_type']}<br>"
            f"severity   : {clf['severity']}<br>"
            f"confidence : {clf['confidence']:.0%}<br>"
            f"peak_step  : {timing['anomaly_peak_step']}<br>"
            f"duration   : {timing['anomaly_duration']} steps<br>"
            f"elapsed_ms : {timing['elapsed_ms']} ms"
        )
        fig_dstd.add_annotation(
            x=0.02, y=0.97, xref="paper", yref="paper",
            text=summary, showarrow=False, align="left",
            font=dict(family="monospace", size=11),
            bgcolor="#FFF9C4", bordercolor="#F39C12",
            borderwidth=1, borderpad=6,
        )
    fig_dstd.update_layout(
        title="(3) Doppler Std — 감전/협착/진동 감지 지표",
        xaxis_title="Frame", yaxis_title="Doppler Std (m/s)",
        height=300, margin=dict(l=0, r=0, t=40, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.05),
        plot_bgcolor="#FAFAFA",
    )
    st.plotly_chart(fig_dstd, use_container_width=True)

# ── 이벤트별 Point Cloud 피처 비교 테이블 ────────────────────────
with st.expander("📋 이벤트별 Point Cloud 피처 상세 비교"):
    table_rows = []
    for sc, res in _pipeline.items():
        timing    = res["_timing"]
        details   = res["details"]
        feat_peak = res["_features_raw"][timing["anomaly_peak_step"]]
        table_rows.append({
            "이벤트":        SIG_LABEL.get(res["event_type"], res["event_type"]),
            "Zone":          res["zone_id"],
            "이상 점수":     res["anomaly_score"],
            "신뢰도":        f"{res['confidence']:.0%}",
            "cx (m)":        round(float(feat_peak[0]), 3),
            "cy / 깊이 (m)": round(float(feat_peak[1]), 3),
            "cz / 높이 (m)": round(float(feat_peak[2]), 3),
            "mean_doppler":  round(float(feat_peak[3]), 4),
            "doppler_std":   round(float(feat_peak[4]), 4),
            "z_velocity":    round(float(feat_peak[7]), 4),
            "peak_step":     timing["anomaly_peak_step"],
            "duration":      timing["anomaly_duration"],
        })
    st.dataframe(table_rows, use_container_width=True)

# ── 현재 이벤트 상세 메트릭 ──────────────────────────────────────
if st.session_state.current_event:
    evt     = st.session_state.current_event
    timing  = evt["_timing"]
    details = evt["details"]
    feat_pk = evt["_features_raw"][timing["anomaly_peak_step"]]

    st.markdown(f"**현재 감지 이벤트: {SIG_LABEL.get(evt['event_type'], evt['event_type'])}**")
    dc1, dc2, dc3, dc4, dc5 = st.columns(5)
    dc1.metric("신뢰도",       f"{evt['confidence']:.0%}")
    dc2.metric("이상 점수",    f"{evt['anomaly_score']:.3f}")
    dc3.metric("복원 오차",    f"{evt['reconstruction_error']:.6f}")
    dc4.metric("Centroid Z",   f"{float(feat_pk[2]):.2f} m")
    dc5.metric("Doppler Std",  f"{float(feat_pk[4]):.4f} m/s")

st.divider()

# ===================================================================
# [구역 4] 🔴 RAG 조치 가이드 (week5-2.py 동일)
# ===================================================================
st.subheader("🔴 이상 감지 시 RAG 기반 조치 가이드")

default_situation = "작업자 낙상 감지 (Zone C)"
if st.session_state.current_event:
    evt     = st.session_state.current_event
    korean  = EVENT_TYPE_KOREAN.get(evt["event_type"], evt["event_type"])
    default_situation = f"{korean} (Zone {evt['zone_id']})"

situation      = st.text_input("감지된 상황 입력 (이벤트 발생 시 자동 입력, 수정 가능)",
                                default_situation)
manual_trigger = st.button("🔍 조치 가이드 생성", type="primary")
trigger        = manual_trigger or st.session_state.auto_run_rag

if st.session_state.auto_run_rag:
    st.session_state.auto_run_rag = False

if trigger:
    try:
        vectorstore = get_vectorstore()
        llm         = get_llm()
    except Exception as e:
        st.error(
            f"❌ DB/LLM 연결 실패: {e}\n\n"
            "Jetson 터미널에서 다음을 확인하세요:\n"
            "  1. sudo docker start radar-guard-db\n"
            "  2. ollama serve (별도 터미널) 또는 이미 실행 중인지 확인"
        )
        st.stop()

    with st.spinner("매뉴얼 검색 중... (CPU 추론, 30초~2분 소요 예상)"):
        if selected_category:
            docs = vectorstore.similarity_search(situation, k=top_k,
                                                  filter={"category": selected_category})
        else:
            docs = vectorstore.similarity_search(situation, k=top_k)

        if not docs:
            st.warning(f"⚠️ '{selected_category_label}' 카테고리에서 관련 매뉴얼을 찾지 못했습니다. "
                       "다른 카테고리나 '전체'로 변경해보세요.")
            st.stop()

        context = "\n\n---\n\n".join([d.page_content for d in docs])
        prompt  = PromptTemplate.from_template(
            "당신은 산업 안전 전문가입니다. 다음 안전 매뉴얼을 참고해서 "
            "아래 상황의 조치 가이드를 **반드시 한국어로** 단계별(1, 2, 3...)로 알려주세요. "
            "한자 사용 금지, 매뉴얼에 없는 내용은 추측하지 마세요.\n\n"
            "안전 매뉴얼:\n{context}\n\n"
            "감지된 상황: {situation}\n\n"
            "조치 가이드:"
        )
        chain    = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": context, "situation": situation})

    st.success("✅ 조치 가이드 생성 완료!")
    st.markdown(response)

    st.divider()
    st.subheader("📚 참고한 매뉴얼 (출처)")
    for i, doc in enumerate(docs, 1):
        cat          = doc.metadata.get("category", "미분류")
        src          = doc.metadata.get("source_file", "알 수 없음")
        page         = doc.metadata.get("page", "?")
        page_display = page + 1 if isinstance(page, int) else page
        with st.expander(f"📄 {i}. [{cat}] {src} (p.{page_display})"):
            st.write(doc.page_content)
