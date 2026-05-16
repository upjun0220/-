"""
=================================================================
Radar-Guard | 통합 관제 파이프라인 + Streamlit UI
=================================================================
실행 (PowerShell):
    streamlit run radar_guard_pipeline.py

실행하면:
    1. 승원 파트 : 목데이터 생성 + LMS 필터링
    2. 성준 파트 : LSTM-AE 이상 탐지 + 사고 분류
    3. 재국 파트 : 자동 대응 (차단기/알림)
    4. 유빈 파트 : Streamlit 관제 UI + RAG 조치 가이드

필수 사전 조건:
    docker start radar-guard-db
    Ollama 실행 중 (qwen2.5:3b-instruct-q4_K_M, bge-m3)
=================================================================
"""

# ================================================================
# 공통 임포트
# ================================================================
import numpy as np
import json
import time
import warnings
from datetime import datetime, timedelta

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import torch
import torch.nn as nn
from torch import optim
from sklearn.preprocessing import MinMaxScaler

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

warnings.filterwarnings("ignore")

# ================================================================
# 페이지 설정 (반드시 최상단)
# ================================================================
st.set_page_config(
    page_title="Radar-Guard 관제 시스템",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ================================================================
# 파이프라인 상수
# ================================================================
FS           = 1000
SEQ_LENGTH   = 3
FEATURE_SIZE = 64
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

SCENARIO_KR = {
    "fall":           "낙상",
    "electric_shock": "감전",
    "pinching":       "협착",
    "vibration":      "진동이상",
}
ZONE_MAP = {
    "fall": "A", "electric_shock": "B", "pinching": "C", "vibration": "C"
}
EVENT_KR = {
    "fall_detected":       "🚨 낙상",
    "electric_shock_risk": "⚡ 감전 위험",
    "pinching":            "🔒 협착",
    "vibration_anomaly":   "📳 진동이상",
}
CORRECT_MAP = {
    "fall": "fall_detected",
    "electric_shock": "electric_shock_risk",
    "pinching": "pinching",
    "vibration": "vibration_anomaly",
}
SIG_COLOR = {
    "fall_detected":       "#E74C3C",
    "electric_shock_risk": "#F39C12",
    "pinching":            "#8E44AD",
    "vibration_anomaly":   "#795548",
}
SEVERITY_EMOJI = {"normal": "🟢", "warning": "🟡", "critical": "🔴"}
SEVERITY_LABEL = {"normal": "정상", "warning": "경고", "critical": "위험"}
SEVERITY_BG    = {"normal": "#d4f4dd", "warning": "#fff3cd", "critical": "#f8d7da"}

RESPONSE_MAP = {
    "electric_shock_risk": {"action": "POWER_CUT",      "description": "전원 차단 — 감전 위험 즉시 대응", "breaker_status": "OPEN",  "response_ms": 50,  "notify_level": "CRITICAL"},
    "fall_detected":       {"action": "EMERGENCY_ALERT","description": "비상 알림 발송 + 구조 요청",      "breaker_status": "HOLD",  "response_ms": 200, "notify_level": "CRITICAL"},
    "pinching":            {"action": "MACHINE_STOP",   "description": "회전체 긴급 정지 명령",           "breaker_status": "OPEN",  "response_ms": 100, "notify_level": "CRITICAL"},
    "vibration_anomaly":   {"action": "WARNING_ALERT",  "description": "점검 경고 알림 발송",             "breaker_status": "HOLD",  "response_ms": 500, "notify_level": "WARNING"},
}

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
CATEGORIES = {
    "전체": None,
    "01_감전_LOTO":       "01_감전_LOTO",
    "02_협착_끼임":       "02_협착_끼임",
    "03_낙상_응급처치":   "03_낙상_응급처치",
    "04_예지보전":        "04_예지보전",
    "05_위험성평가_비상": "05_위험성평가_비상",
}
CONNECTION_STRING = "postgresql://admin:1234@localhost:5432/radar_guard"


# ================================================================
# 승원 파트 — LMS 필터 + 특징 추출
# ================================================================
class RadarSignalProcessor:
    def __init__(self, order=32, mu=0.01):
        self.weights = np.zeros(order)
        self.buffer  = np.zeros(order)
        self.order, self.mu = order, mu

    def lms_filter(self, input_sample, ref_sample):
        self.buffer    = np.roll(self.buffer, 1)
        self.buffer[0] = ref_sample
        output         = np.dot(self.weights, self.buffer)
        error          = input_sample - output
        self.weights  += 2 * self.mu * error * self.buffer
        return error

    def extract_features(self, sig):
        n   = len(sig)
        w   = np.hanning(n)
        fft = np.fft.fft(sig * w)
        frq = np.fft.fftfreq(n, d=1/FS)
        mag = np.abs(fft) / (n / 2)
        return mag[np.where(frq >= 0)][:FEATURE_SIZE]


def make_mock_data(scenario, n_samples=200):
    signals = []
    onset = {
        "fall":           np.random.randint(95, 108),
        "electric_shock": np.random.randint(75, 88),
        "pinching":       np.random.randint(75, 90),
        "vibration":      np.random.randint(92, 108),
    }[scenario]

    for i in range(n_samples):
        t          = np.arange(128) / FS
        base_noise = np.random.normal(0, 0.18, 128)

        if scenario == "fall":
            if onset < i < onset + 10:
                amp  = np.random.uniform(2.2, 3.8)
                base = np.sin(2*np.pi*50*t) * amp + np.random.normal(0, 0.4, 128)
            elif i >= onset + 10:
                base = np.random.normal(0, 0.05, 128)
            else:
                base = np.sin(2*np.pi*5*t) * np.random.uniform(0.8, 1.2)
        elif scenario == "electric_shock":
            if onset <= i <= onset + 50:
                amp1  = np.random.uniform(1.4, 2.6)
                amp2  = np.random.uniform(0.5, 1.1)
                phase = np.random.uniform(0, 2*np.pi)
                base  = (np.sin(2*np.pi*50*t + phase) * amp1
                         + np.sin(2*np.pi*63*t) * amp2
                         + np.random.normal(0, 0.6, 128))
            else:
                base = np.sin(2*np.pi*5*t) * np.random.uniform(0.8, 1.2)
        elif scenario == "pinching":
            if i >= onset:
                ramp = min(1.0, (i - onset) / 25.0)
                amp  = np.random.uniform(1.8, 3.0) * ramp
                freq = np.random.uniform(28, 32)
                base = np.sin(2*np.pi*freq*t) * amp + np.random.normal(0, 0.35, 128)
            else:
                base = np.sin(2*np.pi*5*t) * np.random.uniform(0.8, 1.2)
        else:  # vibration
            if i >= onset:
                amp   = np.random.uniform(1.0, 2.2)
                freq1 = np.random.uniform(2.5, 3.5)
                freq2 = np.random.uniform(6.0, 8.0)
                base  = (np.sin(2*np.pi*freq1*t) * amp
                         + np.sin(2*np.pi*freq2*t) * amp * np.random.uniform(0.3, 0.6)
                         + np.random.normal(0, 0.25, 128))
            else:
                base = np.sin(2*np.pi*5*t) * np.random.uniform(0.8, 1.2)

        signals.append(base + base_noise)
    return signals


def seungwon_process(scenario, n_samples=200):
    features = []
    for raw in make_mock_data(scenario, n_samples):
        proc    = RadarSignalProcessor()
        noise   = np.random.normal(0, 0.1, len(raw))
        cleaned = np.array([proc.lms_filter(r, n*0.8) for r, n in zip(raw, noise)])
        features.append(proc.extract_features(cleaned).tolist())

    stage1 = {
        "schema_version": "1.0",
        "timestamp":      datetime.now().isoformat(),
        "scenario":       scenario,
        "n_samples":      n_samples,
        "zone_id":        ZONE_MAP[scenario],
        "features":       features,
        "metadata":       {"filter_method": "LMS_adaptive", "signal_quality": 0.95},
    }
    with open("stage1_filtered.json", "w", encoding="utf-8") as f:
        json.dump(stage1, f, ensure_ascii=False, indent=2)
    return stage1


# ================================================================
# 성준 파트 — LSTM-AE 이상 탐지 + 사고 분류
# ================================================================
class LSTM_Autoencoder(nn.Module):
    def __init__(self, n_features, embedding_dim, seq_len):
        super().__init__()
        self.seq_len  = seq_len
        self.encoder1 = nn.LSTM(n_features, embedding_dim, batch_first=True)
        self.encoder2 = nn.LSTM(embedding_dim, embedding_dim//2, batch_first=True)
        self.decoder1 = nn.LSTM(embedding_dim//2, embedding_dim//2, batch_first=True)
        self.decoder2 = nn.LSTM(embedding_dim//2, embedding_dim, batch_first=True)
        self.fc       = nn.Linear(embedding_dim, n_features)

    def forward(self, x):
        _, (h, _) = self.encoder1(x)
        _, (h, _) = self.encoder2(h.transpose(0,1))
        x = h.transpose(0,1).repeat(1, self.seq_len, 1)
        x, _ = self.decoder1(x)
        x, _ = self.decoder2(x)
        return self.fc(x)


def create_sequences(data, seq_len):
    return np.array([data[i:i+seq_len] for i in range(len(data)-seq_len)])


def _train_model_impl():
    """내부 학습 로직 (Streamlit 의존 없음)"""
    normal_feat = []
    for _ in range(600):
        proc  = RadarSignalProcessor()
        t     = np.arange(128) / FS
        raw   = np.sin(2*np.pi*5*t) + np.random.normal(0, 0.2, 128)
        noise = np.random.normal(0, 0.2, 128)
        cleaned = np.array([proc.lms_filter(r, n*0.8) for r, n in zip(raw, noise)])
        normal_feat.append(proc.extract_features(cleaned).tolist())

    scaler = MinMaxScaler()
    X      = torch.from_numpy(
        create_sequences(scaler.fit_transform(normal_feat), SEQ_LENGTH)
    ).float().to(DEVICE)

    model     = LSTM_Autoencoder(FEATURE_SIZE, 32, SEQ_LENGTH).to(DEVICE)
    optimizer = optim.AdamW(model.parameters(), lr=0.001)
    criterion = nn.MSELoss()

    model.train()
    for epoch in range(101):
        optimizer.zero_grad()
        loss = criterion(model(X), X)
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        recon     = model(X)
        losses    = torch.mean((recon - X)**2, dim=(1,2)).cpu().numpy()
        threshold = float(np.mean(losses) + 3*np.std(losses))
    return model, scaler, threshold


@st.cache_resource(show_spinner=False)
def get_trained_model():
    """정상 패턴 학습 — 최초 1회만 실행, 이후 캐시 사용"""
    return _train_model_impl()


def classify_event(time_signal, freq_signal, recon_error, threshold):
    n_t, eps = len(time_signal), 1e-10
    energy_front  = float(np.mean(time_signal[:n_t//2]**2)) + eps
    energy_back   = float(np.mean(time_signal[n_t//2:]**2)) + eps
    tail_energy   = float(np.mean(time_signal[int(n_t*0.7):]**2))
    peak_amp      = float(np.max(np.abs(time_signal))) + eps
    sustained_cnt = int(np.sum(np.abs(time_signal) > peak_amp * 0.5))
    tail_silence  = tail_energy < 0.05 * energy_front
    sustained_high = (sustained_cnt / n_t) > 0.40

    freqs = np.fft.fftfreq(128, d=1/FS)[:FEATURE_SIZE]
    total = float(np.sum(freq_signal)) + eps
    dom_idx  = int(np.argmax(freq_signal[1:])) + 1
    dom_freq = float(freqs[dom_idx])
    hf_mask  = freqs > 20
    hf_ratio = float(np.sum(freq_signal[hf_mask]) / total)
    pl_mask_a = (freqs >= 45) & (freqs <= 55)
    pl_mask_b = (freqs >= 55) & (freqs <= 65)
    energy_a  = float(np.sum(freq_signal[pl_mask_a]))
    energy_b  = float(np.sum(freq_signal[pl_mask_b]))
    pl_ratio  = (energy_a + energy_b) / total
    dual_band = energy_b / (energy_a + eps)
    excess    = recon_error / threshold

    if pl_ratio > 0.15 and dual_band > 0.10:
        return {"event_type": "electric_shock_risk", "severity": "critical",
                "confidence": round(min(0.99, 0.55+0.25*min(1, dual_band/0.30)), 2)}
    elif dom_freq > 40.0 and hf_ratio > 0.20:
        return {"event_type": "fall_detected", "severity": "critical",
                "confidence": round(min(0.99, 0.55+0.20*min(1, excess-1)+0.15*hf_ratio), 2)}
    elif 25.0 < dom_freq <= 40.0:
        return {"event_type": "pinching", "severity": "critical",
                "confidence": round(min(0.99, 0.55+0.20*min(1, excess-1)+0.10*hf_ratio), 2)}
    elif dom_freq < 20.0:
        return {"event_type": "vibration_anomaly", "severity": "warning",
                "confidence": round(min(0.99, 0.45+0.30*min(1, excess-1)), 2)}
    else:
        return {"event_type": "fall_detected", "severity": "warning",
                "confidence": round(min(0.75, 0.40+0.10*excess), 2)}


def build_details(event_type, time_signal, freq_signal, recon_error, threshold, timing):
    eps      = 1e-10
    excess   = recon_error / threshold
    freqs    = np.fft.fftfreq(128, d=1/FS)[:FEATURE_SIZE]
    total    = float(np.sum(freq_signal)) + eps
    dom_idx  = int(np.argmax(freq_signal[1:])) + 1
    dom_freq = float(freqs[dom_idx])
    pl_mask  = ((freqs >= 45) & (freqs <= 55)) | ((freqs >= 55) & (freqs <= 65))
    pl_ratio = float(np.sum(freq_signal[pl_mask]) / total)
    peak_amp = float(np.max(np.abs(time_signal)))
    rms      = float(np.sqrt(np.mean(time_signal**2)))

    base = {"anomaly_score": round(excess, 3),
            "reconstruction_error": round(recon_error, 6),
            "timing": timing}

    if event_type == "fall_detected":
        base["description"] = "작업자 낙상 확정 (자세 붕괴 + 속도 임계 초과)"
        base["worker_pose"] = {"posture": "collapsed",
                               "velocity_m_s": round(min(peak_amp*0.03, 2.0), 3),
                               "height_m":     round(max(0.1, 1.8-peak_amp*0.4), 2)}
        base["equipment_anomaly"] = None
    elif event_type == "electric_shock_risk":
        base["description"]          = "감전 위험 감지 (전력주파수 + 경련 패턴)"
        base["proximity_m"]          = round(max(0.05, 1.0-pl_ratio*3.0), 2)
        base["equipment_voltage_kv"] = 22.9
        base["approach_speed_m_s"]   = round(min(pl_ratio*4.0, 3.0), 2)
    elif event_type == "pinching":
        base["description"]           = "협착 감지 (회전체 근접 + 압박 신호 지속)"
        base["equipment_id"]          = "rotor_detected"
        base["body_part_proximity_m"] = round(max(0.02, 0.3-peak_amp*0.05), 3)
        base["rotation_rpm"]          = min(int(abs(dom_freq)*60), 3600)
    elif event_type == "vibration_anomaly":
        base["description"]             = "진동 이상 (저주파 드리프트/마모 패턴)"
        base["equipment_id"]            = "motor_detected"
        base["rms_vibration_um_s"]      = round(rms*1000, 2)
        base["frequency_anomaly_hz"]    = round(dom_freq, 1)
        base["bearing_fault_suspected"] = (15.0 < dom_freq < 50.0)
    return base


def seongjun_detect(stage1):
    features  = np.array(stage1["features"], dtype=np.float32)
    zone      = stage1["zone_id"]
    base_time = datetime.fromisoformat(stage1["timestamp"])

    model, scaler, threshold = get_trained_model()

    scaled = scaler.transform(features)
    X_test = torch.from_numpy(create_sequences(scaled, SEQ_LENGTH)).float().to(DEVICE)
    model.eval()
    with torch.no_grad():
        recon     = model(X_test)
        test_loss = torch.mean((recon - X_test)**2, dim=(1,2)).cpu().numpy()
    is_anomaly = test_loss > threshold

    if not is_anomaly.any():
        return None, test_loss, is_anomaly, threshold, None, None

    anomaly_steps = np.where(is_anomaly)[0]
    start_step    = int(anomaly_steps[0])
    peak_step     = int(np.argmax(test_loss))
    duration      = int(len(anomaly_steps))
    ms_per_step   = (128/FS)*1000
    elapsed_ms    = round(start_step*ms_per_step, 1)
    timing = {
        "anomaly_start_step": start_step,
        "anomaly_peak_step":  peak_step,
        "anomaly_duration":   duration,
        "event_timestamp":    (base_time + timedelta(milliseconds=elapsed_ms)).isoformat(),
        "elapsed_ms":         elapsed_ms,
    }

    time_signal = scaled[peak_step:peak_step+SEQ_LENGTH].flatten()
    freq_signal = features[peak_step]
    peak_error  = float(test_loss[peak_step])
    clf         = classify_event(time_signal, freq_signal, peak_error, threshold)
    details     = build_details(clf["event_type"], time_signal, freq_signal,
                                peak_error, threshold, timing)

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
            {"time": now.strftime('%H:%M:%S'), "msg": f"Zone {zone} - LSTM-AE 이상 탐지 (threshold={threshold:.4f})"},
            {"time": now.strftime('%H:%M:%S'), "msg": f"Zone {zone} - 유형 분류: {clf['event_type']}"},
            {"time": now.strftime('%H:%M:%S'), "msg": f"Zone {zone} - 알림 발송 (severity={clf['severity']}, confidence={clf['confidence']})"},
        ],
    }
    with open("stage2_event.json", "w", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False, indent=2)
    return event, test_loss, is_anomaly, threshold, timing, clf


# ================================================================
# 재국 파트 — 자동 대응
# ================================================================
def jaeguk_breaker(event):
    resp       = RESPONSE_MAP.get(event["event_type"])
    zone       = event.get("zone_id", "?")
    timing     = event.get("details", {}).get("timing", {})
    now        = datetime.now()

    trigger = {
        "schema_version": "1.0",
        "trigger_time":   now.isoformat(),
        "event_id":       event.get("event_id", ""),
        "event_type":     event["event_type"],
        "severity":       event["severity"],
        "zone_id":        zone,
        "confidence":     event["confidence"],
        "action":         resp["action"],
        "breaker_status": resp["breaker_status"],
        "notify_level":   resp["notify_level"],
        "description":    resp["description"],
        "response_ms":    resp["response_ms"],
        "timing":         timing,
        "details":        event.get("details", {}),
        "event_log":      event.get("event_log", []) + [
            {"time": now.strftime("%H:%M:%S"),
             "msg":  f"[Breaker] Zone {zone} — {resp['action']} 실행 완료"}
        ],
    }
    with open("ui_trigger.json", "w", encoding="utf-8") as f:
        json.dump(trigger, f, ensure_ascii=False, indent=2)
    return trigger


# ================================================================
# RAG 백엔드
# ================================================================
@st.cache_resource
def get_vectorstore():
    emb = OllamaEmbeddings(model="bge-m3")
    return PGVector(connection_string=CONNECTION_STRING,
                    embedding_function=emb,
                    collection_name="safety_manual")

@st.cache_resource
def get_llm():
    return ChatOllama(model="qwen2.5:3b-instruct-q4_K_M", temperature=0)


# ================================================================
# Session State 초기화
# ================================================================
if "event"            not in st.session_state: st.session_state.event            = None
if "test_loss"        not in st.session_state: st.session_state.test_loss        = None
if "is_anomaly"       not in st.session_state: st.session_state.is_anomaly       = None
if "threshold"        not in st.session_state: st.session_state.threshold        = None
if "timing"           not in st.session_state: st.session_state.timing           = None
if "clf"              not in st.session_state: st.session_state.clf              = None
if "trigger"          not in st.session_state: st.session_state.trigger          = None
if "facility_status"  not in st.session_state: st.session_state.facility_status  = {"A":"normal","B":"normal","C":"normal"}
if "auto_run_rag"     not in st.session_state: st.session_state.auto_run_rag     = False
if "scenario_ran"     not in st.session_state: st.session_state.scenario_ran     = None


def reset_state():
    st.session_state.event           = None
    st.session_state.test_loss       = None
    st.session_state.is_anomaly      = None
    st.session_state.threshold       = None
    st.session_state.timing          = None
    st.session_state.clf             = None
    st.session_state.trigger         = None
    st.session_state.facility_status = {"A":"normal","B":"normal","C":"normal"}
    st.session_state.auto_run_rag    = False
    st.session_state.scenario_ran    = None


# ================================================================
# 사이드바
# ================================================================
with st.sidebar:
    st.header("🎬 파이프라인 실행")

    scenario_choice = st.selectbox(
        "시나리오 선택",
        options=["fall", "electric_shock", "pinching", "vibration"],
        format_func=lambda x: f"{SCENARIO_KR[x]} ({x})",
    )

    run_btn = st.button("▶ 파이프라인 실행", type="primary", use_container_width=True)
    st.button("🔄 초기화", use_container_width=True, on_click=reset_state)

    st.divider()
    st.header("🔍 RAG 검색 설정")

    default_idx = 0
    if st.session_state.event:
        auto_cat = EVENT_TYPE_TO_CATEGORY.get(st.session_state.event["event_type"])
        cat_list = list(CATEGORIES.keys())
        if auto_cat in cat_list:
            default_idx = cat_list.index(auto_cat)

    selected_category_label = st.selectbox("검색 카테고리", list(CATEGORIES.keys()),
                                           index=default_idx,
                                           help="이벤트 발생 시 자동 선택됩니다.")
    selected_category = CATEGORIES[selected_category_label]
    top_k = st.slider("검색 결과 수 (k)", 1, 5, 3)

    st.divider()
    st.caption("📌 승원: LMS 필터\n"
               "📌 성준: LSTM-AE 탐지\n"
               "📌 재국: 자동 차단기\n"
               "📌 유빈: RAG + Streamlit UI\n"
               "📌 젯슨 이식 시 LLM → Llama-3 교체")


# ================================================================
# 파이프라인 실행 (버튼 클릭 시)
# ================================================================
if run_btn:
    scenario = scenario_choice

    # 모델 사전 학습 (최초 1회)
    with st.spinner("🧠 LSTM-AE 정상 패턴 학습 중... (최초 1회만 실행)"):
        get_trained_model()

    progress = st.progress(0, text="파이프라인 시작...")

    # 1. 승원 파트
    progress.progress(10, text="[1/3] 승원 파트: LMS 필터링 중...")
    stage1 = seungwon_process(scenario)
    progress.progress(35, text="[1/3] 승원 파트 완료 ✓")

    # 2. 성준 파트
    progress.progress(40, text="[2/3] 성준 파트: LSTM-AE 이상 탐지 중...")
    event, test_loss, is_anomaly, threshold, timing, clf = seongjun_detect(stage1)
    progress.progress(75, text="[2/3] 성준 파트 완료 ✓")

    # 3. 재국 파트
    trigger = None
    if event:
        progress.progress(80, text="[3/3] 재국 파트: 자동 대응 처리 중...")
        time.sleep(RESPONSE_MAP[event["event_type"]]["response_ms"] / 1000.0)
        trigger = jaeguk_breaker(event)
        progress.progress(100, text="✅ 파이프라인 완료!")

        # facility_status 갱신
        zone = event["zone_id"]
        new_status = {"A": "normal", "B": "normal", "C": "normal"}
        new_status[zone] = event["severity"]
        st.session_state.facility_status = new_status
        st.session_state.auto_run_rag    = True
    else:
        progress.progress(100, text="✅ 완료 — 이상 없음")

    # 결과 저장
    st.session_state.event        = event
    st.session_state.test_loss    = test_loss.tolist() if test_loss is not None else None
    st.session_state.is_anomaly   = is_anomaly.tolist() if is_anomaly is not None else None
    st.session_state.threshold    = threshold
    st.session_state.timing       = timing
    st.session_state.clf          = clf
    st.session_state.trigger      = trigger
    st.session_state.scenario_ran = scenario


# ================================================================
# 헤더
# ================================================================
overall_status = "normal"
for s in st.session_state.facility_status.values():
    if s == "critical": overall_status = "critical"; break
    elif s == "warning" and overall_status != "critical": overall_status = "warning"

hcol1, hcol2, hcol3 = st.columns([5, 2, 2])
with hcol1:
    st.title("🛡️ Radar-Guard 관제 시스템")
    st.caption("⚡ 완전 오프라인 RAG · 승원(LMS) → 성준(LSTM-AE) → 재국(차단기) → 유빈(RAG UI)")
with hcol2:
    st.markdown("##### 시스템 상태")
    st.markdown(f"<h3 style='margin:0'>{SEVERITY_EMOJI[overall_status]} [{SEVERITY_LABEL[overall_status]}]</h3>",
                unsafe_allow_html=True)
with hcol3:
    st.markdown("##### 현재 시각")
    st.markdown(f"<h3 style='margin:0'>🕐 {datetime.now().strftime('%H:%M:%S')}</h3>",
                unsafe_allow_html=True)

if st.session_state.scenario_ran:
    st.info(f"마지막 실행 시나리오: **{SCENARIO_KR[st.session_state.scenario_ran]}** ({st.session_state.scenario_ran})")

st.divider()

# ================================================================
# [구역 1] 3D Point Cloud | 진동 분석 + Event Log
# ================================================================
left_col, right_col = st.columns([3, 2])

with left_col:
    st.subheader("📡 3D Point Cloud (mmWave)")
    np.random.seed(42)
    n_bg = 200
    x_pt = np.random.uniform(-2, 2, n_bg)
    y_pt = np.random.uniform(-2, 2, n_bg)
    z_pt = np.random.uniform(0, 2.5, n_bg)
    intensity = np.random.uniform(0, 0.5, n_bg)

    if st.session_state.event:
        zone     = st.session_state.event["zone_id"]
        evt_type = st.session_state.event["event_type"]
        zone_x_map = {"A": -1.5, "B": 0.0, "C": 1.5}
        cx  = zone_x_map.get(zone, 0)
        n_cl = 60
        cx_arr = np.random.normal(cx, 0.25, n_cl)
        cy_arr = np.random.normal(0, 0.25, n_cl)
        cz_arr = (np.random.uniform(0, 0.5, n_cl) if evt_type == "fall_detected"
                  else np.random.uniform(0.5, 1.7, n_cl))
        x_pt = np.concatenate([x_pt, cx_arr])
        y_pt = np.concatenate([y_pt, cy_arr])
        z_pt = np.concatenate([z_pt, cz_arr])
        intensity = np.concatenate([intensity, np.ones(n_cl)])

    fig_3d = go.Figure(data=[go.Scatter3d(
        x=x_pt, y=y_pt, z=z_pt, mode="markers",
        marker=dict(size=3, color=intensity, colorscale="Viridis",
                    opacity=0.75, showscale=True,
                    colorbar=dict(title="Intensity", thickness=12)),
    )])
    fig_3d.update_layout(
        scene=dict(xaxis_title="X (m)", yaxis_title="Y (m)", zaxis_title="Z (m)",
                   aspectmode="cube"),
        height=440, margin=dict(l=0, r=0, t=0, b=0),
    )
    st.plotly_chart(fig_3d, use_container_width=True)

with right_col:
    st.subheader("📊 진동 분석")

    # 진동 수치
    vib_value, vib_delta = "0.02 μm/s", "-0.01"
    if st.session_state.event and st.session_state.event["event_type"] == "vibration_anomaly":
        rms = st.session_state.event["details"].get("rms_vibration_um_s", 1.80)
        vib_value = f"{rms:.2f} μm/s"
        vib_delta = f"+{rms-0.02:.2f}"
    st.metric("설비 진동 (RMS)", vib_value, delta=vib_delta, delta_color="inverse")

    # 진동 스펙트럼
    freq = np.linspace(0, 200, 200)
    normal_spec  = 0.05 * np.exp(-((freq - 60)**2) / 200) + 0.02
    current_spec = normal_spec.copy()
    if st.session_state.event and st.session_state.event["event_type"] == "vibration_anomaly":
        dom = st.session_state.event["details"].get("frequency_anomaly_hz", 47.5)
        current_spec += 0.18 * np.exp(-((freq - dom)**2) / 30)

    fig_vib = go.Figure()
    fig_vib.add_trace(go.Scatter(x=freq, y=normal_spec,  name="정상 baseline",
                                  line=dict(color="green", dash="dash")))
    fig_vib.add_trace(go.Scatter(x=freq, y=current_spec, name="현재",
                                  line=dict(color="red")))
    fig_vib.update_layout(xaxis_title="주파수 (Hz)", yaxis_title="진폭", height=180,
                           margin=dict(l=0, r=0, t=10, b=0),
                           legend=dict(orientation="h", yanchor="bottom", y=1.02,
                                       xanchor="right", x=1))
    st.plotly_chart(fig_vib, use_container_width=True)

    st.subheader("📋 Event Log")
    if st.session_state.event:
        for log in st.session_state.event.get("event_log", []):
            icon = "⚠️" if st.session_state.event["severity"] == "critical" else "📌"
            st.markdown(f"`[{log['time']}]` {icon} {log['msg']}")
    else:
        st.info("이벤트 대기 중... (사이드바에서 시나리오 선택 후 실행)")

st.divider()

# ================================================================
# [구역 2] Facility Map
# ================================================================
st.subheader("🗺️ Facility Map")
zone_info = {
    "A": {"name": "Zone A (변전실)", "worker": "정상", "power": "정상"},
    "B": {"name": "Zone B (가공실)", "worker": "정상", "power": "정상"},
    "C": {"name": "Zone C (조립실)", "worker": "정상", "power": "정상"},
}
if st.session_state.event:
    zone = st.session_state.event["zone_id"]
    et   = st.session_state.event["event_type"]
    resp = RESPONSE_MAP.get(et, {})
    if et == "fall_detected":
        zone_info[zone]["worker"] = "🔴 낙상"; zone_info[zone]["power"] = "정상"
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

# ================================================================
# [구역 3] 파이프라인 분석 결과 (성준 파트 — LSTM-AE)
# ================================================================
st.subheader("📡 파이프라인 분석 결과 (성준 파트 — LSTM-AE)")

if st.session_state.test_loss is not None:
    test_loss  = np.array(st.session_state.test_loss)
    is_anomaly = np.array(st.session_state.is_anomaly)
    threshold  = st.session_state.threshold
    timing     = st.session_state.timing
    clf        = st.session_state.clf

    # 분류 정확도 배지
    if clf and st.session_state.scenario_ran:
        is_correct = CORRECT_MAP[st.session_state.scenario_ran] == clf["event_type"]
        if is_correct:
            st.success(f"✓ 분류 정확 | 입력: {SCENARIO_KR[st.session_state.scenario_ran]} → 탐지: {EVENT_KR.get(clf['event_type'], clf['event_type'])}")
        else:
            st.warning(f"⚠ 오분류 | 입력: {SCENARIO_KR[st.session_state.scenario_ran]} → 탐지: {EVENT_KR.get(clf['event_type'], clf['event_type'])}")

    ana_col1, ana_col2 = st.columns(2)

    with ana_col1:
        # 복원 오차 + 임계치 + 이상 구간
        fig_err = go.Figure()
        fig_err.add_trace(go.Scatter(
            y=test_loss, mode="lines", name="복원 오차 (MSE)",
            line=dict(color="royalblue", width=1.8)
        ))
        fig_err.add_hline(y=threshold, line_dash="dash", line_color="red",
                           annotation_text=f"임계치 μ+3σ = {threshold:.4f}",
                           annotation_position="top right")
        if timing:
            s, dur = timing["anomaly_start_step"], timing["anomaly_duration"]
            fig_err.add_vrect(x0=s, x1=s+dur, fillcolor="orange",
                               opacity=0.2, line_width=0, annotation_text="사고 구간")
            fig_err.add_vline(x=s, line_dash="dot", line_color="#F39C12",
                               annotation_text=f"시작 step {s}")
            fig_err.add_vline(x=timing["anomaly_peak_step"], line_dash="dashdot",
                               line_color="red",
                               annotation_text=f"피크 step {timing['anomaly_peak_step']}")
        fig_err.update_layout(title="(1) 복원 오차 + 이상 탐지 구간",
                               xaxis_title="Time Step", yaxis_title="MSE Loss",
                               height=300, margin=dict(l=0, r=0, t=40, b=0),
                               plot_bgcolor="#FAFAFA")
        st.plotly_chart(fig_err, use_container_width=True)

    with ana_col2:
        # 이상 포인트 + 결과 요약
        fig_pts = go.Figure()
        fig_pts.add_trace(go.Scatter(y=test_loss, mode="lines", name="오차",
                                      line=dict(color="gray", width=1), opacity=0.4))
        anomaly_idx = np.where(is_anomaly)[0]
        fig_pts.add_trace(go.Scatter(
            x=anomaly_idx, y=test_loss[anomaly_idx],
            mode="markers", name=f"이상 포인트 ({len(anomaly_idx)}개)",
            marker=dict(color="red", size=6, symbol="circle")
        ))
        fig_pts.add_hline(y=threshold, line_dash="dash", line_color="red", opacity=0.5)
        fig_pts.update_layout(title="(2) 이상 포인트",
                               xaxis_title="Time Step", yaxis_title="MSE Loss",
                               height=300, margin=dict(l=0, r=0, t=40, b=0),
                               plot_bgcolor="#FAFAFA")
        st.plotly_chart(fig_pts, use_container_width=True)

    # 탐지 수치 요약
    if clf and timing:
        mc1, mc2, mc3, mc4, mc5 = st.columns(5)
        mc1.metric("탐지 유형",  EVENT_KR.get(clf["event_type"], clf["event_type"]))
        mc2.metric("신뢰도",     f"{clf['confidence']:.0%}")
        mc3.metric("이상 점수",  f"{st.session_state.event['details']['anomaly_score']:.3f}" if st.session_state.event else "-")
        mc4.metric("발생 step",  timing["anomaly_start_step"])
        mc5.metric("지속 구간",  f"{timing['anomaly_duration']} steps")

    # 재국 파트 결과
    if st.session_state.trigger:
        resp = RESPONSE_MAP.get(st.session_state.trigger["event_type"], {})
        breaker_color = "🔴" if st.session_state.trigger["breaker_status"] == "OPEN" else "🟡"
        st.markdown(
            f"""<div style="background:#fff3cd;padding:12px;border-radius:8px;
                border-left:5px solid #F39C12;margin-top:8px;">
              <b>⚡ 재국 파트 자동 대응 완료</b><br>
              명령: <b>{resp.get('action','')}</b> &nbsp;|&nbsp;
              차단기: {breaker_color} <b>{st.session_state.trigger['breaker_status']}</b> &nbsp;|&nbsp;
              응답: <b>{resp.get('response_ms','')}ms</b> &nbsp;|&nbsp;
              설명: {resp.get('description','')}
            </div>""",
            unsafe_allow_html=True,
        )

    with st.expander("📄 stage2_event.json 전체 보기"):
        st.json(st.session_state.event)
else:
    st.info("좌측 사이드바에서 시나리오를 선택하고 **▶ 파이프라인 실행** 을 눌러주세요.")

st.divider()

# ================================================================
# [구역 4] RAG 조치 가이드 (유빈 파트 — week5.py 동일)
# ================================================================
st.subheader("🔴 이상 감지 시 RAG 기반 조치 가이드")

default_situation = "작업자 낙상 감지 (Zone A)"
if st.session_state.event:
    korean = EVENT_TYPE_KOREAN.get(st.session_state.event["event_type"],
                                    st.session_state.event["event_type"])
    default_situation = f"{korean} (Zone {st.session_state.event['zone_id']})"

situation      = st.text_input("감지된 상황 입력 (이벤트 발생 시 자동 입력, 수정 가능)",
                                default_situation)
manual_trigger = st.button("🔍 조치 가이드 생성", type="primary")
rag_trigger    = manual_trigger or st.session_state.auto_run_rag

if st.session_state.auto_run_rag:
    st.session_state.auto_run_rag = False

if rag_trigger:
    try:
        vectorstore = get_vectorstore()
        llm         = get_llm()
    except Exception as e:
        st.error(f"❌ DB/LLM 연결 실패: {e}\n\n"
                 "PowerShell에서 확인:\n  1. docker start radar-guard-db\n"
                 "  2. Ollama 실행 중")
        st.stop()

    with st.spinner("매뉴얼 검색 중... (CPU 추론, 30초~2분 소요)"):
        docs = (vectorstore.similarity_search(situation, k=top_k,
                                               filter={"category": selected_category})
                if selected_category
                else vectorstore.similarity_search(situation, k=top_k))

        if not docs:
            st.warning(f"⚠️ '{selected_category_label}' 카테고리에서 관련 매뉴얼을 찾지 못했습니다.")
            st.stop()

        context = "\n\n---\n\n".join([d.page_content for d in docs])
        prompt  = PromptTemplate.from_template(
            "당신은 산업 안전 전문가입니다. 다음 안전 매뉴얼을 참고해서 "
            "아래 상황의 조치 가이드를 **반드시 한국어로** 단계별(1, 2, 3...)로 알려주세요. "
            "한자 사용 금지, 매뉴얼에 없는 내용은 추측하지 마세요.\n\n"
            "안전 매뉴얼:\n{context}\n\n"
            "감지된 상황: {situation}\n\n조치 가이드:"
        )
        chain    = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": context, "situation": situation})

    st.success("✅ 조치 가이드 생성 완료!")
    st.markdown(response)

    st.divider()
    st.subheader("📚 참고한 매뉴얼 (출처)")
    for i, doc in enumerate(docs, 1):
        cat  = doc.metadata.get("category", "미분류")
        src  = doc.metadata.get("source_file", "알 수 없음")
        page = doc.metadata.get("page", "?")
        page_display = page + 1 if isinstance(page, int) else page
        with st.expander(f"📄 {i}. [{cat}] {src} (p.{page_display})"):
            st.write(doc.page_content)
