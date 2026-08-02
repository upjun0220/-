"""
Radar-Guard 통합 관제 시스템 v2 (week5-2.py)
=============================================

week5.py (유빈 RAG UI) + 성준 파트 신호 파이프라인 통합본.

레이아웃 (탭 없이 세로로 쭉):
┌──────────────────────────────────────────────────────────────┐
│ 헤더: 시스템명 + 상태 배지 + 실시간 시계                      │
├──────────────┬───────────────────────────────────────────────┤
│ [사이드바]    │ [좌] 3D Point Cloud  │ [우] 진동분석+EventLog│
│              ├──────────────────────────────────────────────┤
│              │ Facility Map (Zone A/B/C)                    │
│              ├──────────────────────────────────────────────┤
│              │ 📡 신호 분석 (성준 파트) ← NEW               │
│              │   파형 / FFT / 레이더 차트 / 특징 테이블      │
│              ├──────────────────────────────────────────────┤
│              │ 🔴 RAG 조치 가이드 (week5.py 동일)            │
└──────────────┴───────────────────────────────────────────────┘

실행 (PowerShell):
    streamlit run week5-2.py

필수 사전 조건:
    docker start radar-guard-db
    Ollama 실행 중 (qwen2.5:3b-instruct-q4_K_M, bge-m3)
"""

import numpy as np
import warnings
from datetime import datetime, timedelta

import streamlit as st
import plotly.graph_objects as go

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

warnings.filterwarnings("ignore")

# ===================================================================
# 페이지 설정
# ===================================================================
st.set_page_config(
    page_title="Radar-Guard 관제 시스템 v2",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===================================================================
# ① 성준 파트: 신호 생성 + 특징 추출 (numpy 연산만, matplotlib 없음)
# ===================================================================
FS = 1000


def make_signal(scenario: str, n: int = 128) -> np.ndarray:
    t = np.linspace(0, 0.1, n)
    if scenario == "fall":
        return np.concatenate([
            np.sin(2 * np.pi * 50 * t[: n // 2]) * 3.0,
            np.zeros(n - n // 2),
        ])
    elif scenario == "electric_shock":
        return (
            np.sin(2 * np.pi * 50 * t) * 2.0
            + np.random.normal(0, 0.6, n)
            + np.sin(2 * np.pi * 63 * t) * 0.8
        )
    elif scenario == "pinching":
        return np.sin(2 * np.pi * 5 * t) * 2.5 + np.random.normal(0, 0.2, n)
    elif scenario == "vibration_anomaly":
        return (
            np.sin(2 * np.pi * 3 * t) * 1.5
            + np.sin(2 * np.pi * 7 * t) * 0.5
            + np.random.normal(0, 0.1, n)
        )
    return np.sin(2 * np.pi * 5 * t) + np.random.normal(0, 0.1, n)


def extract_signal_features(signal: np.ndarray, fs: int = FS) -> dict:
    n, eps = len(signal), 1e-10
    energy_front = float(np.mean(signal[: n // 2] ** 2)) + eps
    energy_back  = float(np.mean(signal[n // 2 :] ** 2)) + eps
    tail_energy  = float(np.mean(signal[int(n * 0.7) :] ** 2))
    peak_amp     = float(np.max(np.abs(signal))) + eps
    sustained_cnt = np.sum(np.abs(signal) > peak_amp * 0.5)

    fft_mag = np.abs(np.fft.fft(signal))[: n // 2]
    freqs   = np.fft.fftfreq(n, d=1 / fs)[: n // 2]
    dominant_freq    = float(freqs[np.argmax(fft_mag[1:]) + 1])
    high_freq_ratio  = float(np.sum(fft_mag[freqs > 20]) / (np.sum(fft_mag) + eps))
    mask_50 = (freqs >= 45) & (freqs <= 55)
    mask_60 = (freqs >= 55) & (freqs <= 65)
    power_line_ratio = float(
        (np.sum(fft_mag[mask_50]) + np.sum(fft_mag[mask_60])) / (np.sum(fft_mag) + eps)
    )
    zcr = float(len(np.where(np.diff(np.sign(signal)))[0]) / n)

    return {
        "energy_ratio":     round(energy_back / energy_front, 4),
        "tail_silence":     tail_energy < 0.05 * energy_front,
        "sustained_high":   (sustained_cnt / n) > 0.40,
        "peak_amplitude":   round(peak_amp, 4),
        "dominant_freq_hz": round(dominant_freq, 2),
        "high_freq_ratio":  round(high_freq_ratio, 4),
        "power_line_ratio": round(power_line_ratio, 4),
        "zcr":              round(zcr, 4),
        "signal_variance":  round(float(np.var(signal)), 6),
    }


# ===================================================================
# ② 파이프라인 데이터 생성 (앱 시작 시 1회, 캐싱)
#    이벤트 타입: 명세서 v1 기준 통일
# ===================================================================
_SCENARIOS = [
    {"scenario": "fall",             "event_type": "fall_detected",      "zone": "A", "recon_error": 0.082, "threshold": 0.021},
    {"scenario": "electric_shock",   "event_type": "electric_shock_risk","zone": "B", "recon_error": 0.104, "threshold": 0.021},
    {"scenario": "pinching",         "event_type": "pinching",           "zone": "C", "recon_error": 0.071, "threshold": 0.021},
    {"scenario": "vibration_anomaly","event_type": "vibration_anomaly",  "zone": "C", "recon_error": 0.035, "threshold": 0.021},
]
_SEVERITY_MAP    = {"fall_detected": "critical", "electric_shock_risk": "critical",
                    "pinching": "critical", "vibration_anomaly": "warning"}
_CONFIDENCE_MAP  = {"fall_detected": 0.88, "electric_shock_risk": 0.91,
                    "pinching": 0.84,  "vibration_anomaly": 0.73}
_REASON_MAP      = {
    "fall_detected":      "고주파 충격 후 신호 소멸 (high_freq=0.412, tail_silence=True)",
    "electric_shock_risk":"전력 주파수 성분 감지 (power_line_ratio=0.321) + 경련성 떨림 (ZCR=0.318)",
    "pinching":           "지속적 고에너지 유지 (energy_ratio=0.921, sustained=True)",
    "vibration_anomaly":  "저주파 지배 성분 (dominant=3.1Hz) — 기계 진동/마모 의심",
}
_DESCRIPTION_MAP = {
    "fall_detected":      "작업자 낙상 감지 — 자세 붕괴 및 신호 소멸 확인",
    "electric_shock_risk":"작업자 감전 위험 감지 — 전력 주파수 성분 및 경련 패턴 확인",
    "pinching":           "작업자 협착 감지 — 지속적 압박 신호 유지 확인",
    "vibration_anomaly":  "장비 진동 이상 감지 — 저주파 진동/드리프트 패턴 확인",
}


@st.cache_data
def build_pipeline_data():
    base_time = datetime.now()
    results = []
    for i, sc in enumerate(_SCENARIOS):
        sig   = make_signal(sc["scenario"])
        feat  = extract_signal_features(sig, FS)
        etype = sc["event_type"]
        now   = base_time + timedelta(minutes=i * 7)
        zone  = sc["zone"]
        event_id = f"evt_{now.strftime('%Y%m%d_%H%M%S')}_{zone}001"

        results.append({
            # 신호 원본 (시각화용)
            "_signal":    sig.tolist(),
            "_timestamp": now.isoformat(),
            # 성준 → 유빈 전달 필드
            "event_type":          etype,
            "severity":            _SEVERITY_MAP[etype],
            "confidence":          _CONFIDENCE_MAP[etype],
            "reason":              _REASON_MAP[etype],
            "signal_features":     feat,
            "anomaly_score":       round(sc["recon_error"] / sc["threshold"], 3),
            "reconstruction_error":sc["recon_error"],
            "zone":                zone,
            # week5.py MOCK_EVENTS 스키마 호환 (generate_report 통합)
            "schema_version": "1.0",
            "timestamp":  now.isoformat(),
            "event_id":   event_id,
            "zone_id":    zone,
            "details": {
                "description":     _DESCRIPTION_MAP[etype],
                "classify_reason": _REASON_MAP[etype],
                "signal_features": feat,
                "worker_pose": {
                    "posture": ("collapsed" if etype == "fall_detected"
                                else "shocked"  if etype == "electric_shock_risk"
                                else "pinned"   if etype == "pinching"
                                else "unknown"),
                    "tail_silence": feat.get("tail_silence"),
                    "sustained":    feat.get("sustained_high"),
                    "zcr":          feat.get("zcr"),
                },
                "anomaly_score":       round(sc["recon_error"] / sc["threshold"], 3),
                "reconstruction_error":sc["recon_error"],
            },
            "event_log": [
                {"time": now.strftime("%H:%M:%S"),
                 "msg":  f"Zone {zone} - LSTM-AE 이상 탐지 (score={round(sc['recon_error']/sc['threshold'],3)})"},
                {"time": (now + timedelta(milliseconds=120)).strftime("%H:%M:%S"),
                 "msg":  f"Zone {zone} - 유형 분류 완료: {etype}"},
                {"time": (now + timedelta(milliseconds=240)).strftime("%H:%M:%S"),
                 "msg":  f"Zone {zone} - 알림 발송 (severity={_SEVERITY_MAP[etype]}, confidence={_CONFIDENCE_MAP[etype]})"},
            ],
        })
    return results


_pipeline = build_pipeline_data()
LIVE_EVENTS  = {r["event_type"]: r for r in _pipeline}   # MOCK_EVENTS 대체
SIGNAL_DATA  = {r["event_type"]: r for r in _pipeline}

# 신호 시각화 색/레이블
SIG_COLOR = {"fall_detected": "#E74C3C", "electric_shock_risk": "#F39C12",
             "pinching": "#8E44AD", "vibration_anomaly": "#795548"}
SIG_LABEL = {"fall_detected": "🚨 낙상", "electric_shock_risk": "⚡ 감전위험",
             "pinching": "🔒 협착",   "vibration_anomaly": "⚙️ 진동이상"}

# ===================================================================
# 백엔드: DB/LLM (week5.py 동일)
# ===================================================================
CONNECTION_STRING = "postgresql://admin:1234@localhost:5432/radar_guard"

@st.cache_resource
def get_vectorstore():
    emb = OllamaEmbeddings(model="bge-m3")
    return PGVector(connection_string=CONNECTION_STRING,
                    embedding_function=emb,
                    collection_name="safety_manual")

@st.cache_resource
def get_llm():
    return ChatOllama(model="qwen2.5:3b-instruct-q4_K_M", temperature=0)

# ===================================================================
# 상수 (week5.py 동일)
# ===================================================================
EVENT_TYPE_TO_CATEGORY = {
    "fall_detected":      "03_낙상_응급처치",
    "electric_shock_risk":"01_감전_LOTO",
    "pinching":           "02_협착_끼임",
    "vibration_anomaly":  "04_예지보전",
}
EVENT_TYPE_KOREAN = {
    "fall_detected":      "작업자 낙상 감지",
    "electric_shock_risk":"감전 위험 감지",
    "pinching":           "협착 사고 감지",
    "vibration_anomaly":  "설비 진동 이상",
}
SEVERITY_EMOJI = {"normal": "🟢", "warning": "🟡", "critical": "🔴"}
SEVERITY_LABEL = {"normal": "정상", "warning": "경고", "critical": "위험"}
SEVERITY_BG    = {"normal": "#d4f4dd", "warning": "#fff3cd", "critical": "#f8d7da"}
CATEGORIES = {
    "전체": None,
    "01_감전_LOTO":         "01_감전_LOTO",
    "02_협착_끼임":         "02_협착_끼임",
    "03_낙상_응급처치":     "03_낙상_응급처치",
    "04_예지보전":          "04_예지보전",
    "05_위험성평가_비상":   "05_위험성평가_비상",
}

# ===================================================================
# Session State
# ===================================================================
if "current_event"    not in st.session_state: st.session_state.current_event    = None
if "facility_status"  not in st.session_state: st.session_state.facility_status  = {"A":"normal","B":"normal","C":"normal"}
if "auto_run_rag"     not in st.session_state: st.session_state.auto_run_rag     = False

def load_scenario(event_type: str, facility: dict):
    st.session_state.current_event   = LIVE_EVENTS[event_type]
    st.session_state.facility_status = facility
    st.session_state.auto_run_rag    = True

def reset_state():
    st.session_state.current_event   = None
    st.session_state.facility_status = {"A":"normal","B":"normal","C":"normal"}
    st.session_state.auto_run_rag    = False

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
    st.caption("성준 파트 신호 데이터 기반 이벤트 로드")
    st.button("▶ 1. 낙상 (Zone A)",       use_container_width=True, on_click=load_scenario,
              args=("fall_detected",       {"A":"critical","B":"normal","C":"normal"}))
    st.button("▶ 2. 감전 위험 (Zone B)",  use_container_width=True, on_click=load_scenario,
              args=("electric_shock_risk", {"A":"normal","B":"critical","C":"normal"}))
    st.button("▶ 3. 협착 (Zone C)",        use_container_width=True, on_click=load_scenario,
              args=("pinching",            {"A":"normal","B":"normal","C":"critical"}))
    st.button("▶ 4. 진동 이상 (Zone C)",  use_container_width=True, on_click=load_scenario,
              args=("vibration_anomaly",   {"A":"normal","B":"normal","C":"warning"}))
    st.divider()
    st.button("🔄 초기화 (정상 상태)", use_container_width=True, on_click=reset_state)
    st.divider()
    st.caption("📌 개발: Ollama + Qwen2.5 + BGE-M3\n"
               "📌 신호: 성준 파트 LSTM-AE 기반\n"
               "📌 젯슨 이식 시 LLM → Llama-3 교체")

# ===================================================================
# 헤더
# ===================================================================
overall_status = "normal"
for s in st.session_state.facility_status.values():
    if s == "critical": overall_status = "critical"; break
    elif s == "warning" and overall_status != "critical": overall_status = "warning"

hcol1, hcol2, hcol3 = st.columns([5, 2, 2])
with hcol1:
    st.title("🛡️ Radar-Guard 관제 시스템 v2")
    st.caption("⚡ 완전 오프라인 RAG + 성준 파트 신호 파이프라인 통합")
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
    np.random.seed(42)
    n_bg = 200
    x = np.random.uniform(-2, 2, n_bg)
    y = np.random.uniform(-2, 2, n_bg)
    z = np.random.uniform(0, 2.5, n_bg)
    intensity = np.random.uniform(0, 0.5, n_bg)

    if st.session_state.current_event:
        zone     = st.session_state.current_event["zone_id"]
        evt_type = st.session_state.current_event["event_type"]
        zone_x_map = {"A": -1.5, "B": 0.0, "C": 1.5}
        cx = zone_x_map.get(zone, 0)
        n_cl = 60
        cx_arr = np.random.normal(cx, 0.25, n_cl)
        cy_arr = np.random.normal(0, 0.25, n_cl)
        cz_arr = (np.random.uniform(0, 0.5, n_cl) if evt_type == "fall_detected"
                  else np.random.uniform(0.5, 1.7, n_cl))
        x = np.concatenate([x, cx_arr])
        y = np.concatenate([y, cy_arr])
        z = np.concatenate([z, cz_arr])
        intensity = np.concatenate([intensity, np.ones(n_cl)])

    fig_3d = go.Figure(data=[go.Scatter3d(
        x=x, y=y, z=z, mode="markers",
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
    vib_value, vib_delta = "0.02 μm/s", "-0.01"
    if (st.session_state.current_event
            and st.session_state.current_event["event_type"] == "vibration_anomaly"):
        feat = SIGNAL_DATA["vibration_anomaly"]["signal_features"]
        vib_value = f"{feat.get('peak_amplitude', 1.80):.2f} μm/s"
        vib_delta = "+1.78"
    st.metric("설비 진동 (RMS)", vib_value, delta=vib_delta, delta_color="inverse")

    freq = np.linspace(0, 200, 200)
    normal_spectrum  = 0.05 * np.exp(-((freq - 60) ** 2) / 200) + 0.02
    current_spectrum = normal_spectrum.copy()
    if (st.session_state.current_event
            and st.session_state.current_event["event_type"] == "vibration_anomaly"):
        feat = SIGNAL_DATA["vibration_anomaly"]["signal_features"]
        dom  = feat.get("dominant_freq_hz", 47.5)
        current_spectrum += 0.18 * np.exp(-((freq - dom) ** 2) / 30)

    fig_vib = go.Figure()
    fig_vib.add_trace(go.Scatter(x=freq, y=normal_spectrum,  name="정상 baseline",
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
# [구역 2] Facility Map
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

for i, (zid, info) in enumerate(zone_info.items()):
    col = st.columns(3)[i] if i == 0 else None  # columns 한 번에 생성

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
# [구역 3] 📡 신호 분석 — 성준 파트 (NEW)
# ===================================================================
st.subheader("📡 신호 분석 (성준 파트 — LSTM-AE 이상 탐지)")

t_ms = np.linspace(0, 0.1, 128) * 1000

# 파형
fig_wave = go.Figure()
for r in _pipeline:
    et  = r["event_type"]
    sig = np.array(r["_signal"])
    fig_wave.add_trace(go.Scatter(x=t_ms, y=sig, mode="lines",
                                   name=SIG_LABEL[et],
                                   line=dict(color=SIG_COLOR[et], width=2),
                                   opacity=0.85))
fig_wave.add_hline(y=0, line_dash="dash", line_color="#CCC", line_width=1)
fig_wave.update_layout(
    title="사고 유형별 레이더 신호 파형",
    xaxis_title="Time (ms)", yaxis_title="Amplitude",
    height=300, margin=dict(l=0, r=0, t=40, b=0),
    legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="right", x=1),
    plot_bgcolor="#FAFAFA",
)
st.plotly_chart(fig_wave, use_container_width=True)

# FFT + 레이더 차트 나란히
sig_col1, sig_col2 = st.columns(2)

with sig_col1:
    fig_fft = go.Figure()
    for r in _pipeline:
        et  = r["event_type"]
        sig = np.array(r["_signal"])
        n   = len(sig)
        fft_mag = np.abs(np.fft.fft(sig))[: n // 2]
        freqs   = np.fft.fftfreq(n, d=1 / FS)[: n // 2]
        fig_fft.add_trace(go.Scatter(x=freqs[:200], y=fft_mag[:200], mode="lines",
                                      name=SIG_LABEL[et],
                                      line=dict(color=SIG_COLOR[et], width=1.8),
                                      opacity=0.85))
    fig_fft.add_vline(x=50, line_dash="dot", line_color="gray",
                      annotation_text="50Hz (전력선)", annotation_position="top right")
    fig_fft.update_layout(
        title="주파수 스펙트럼 (FFT)",
        xaxis_title="Frequency (Hz)", yaxis_title="Magnitude",
        xaxis_range=[0, 200], height=300,
        margin=dict(l=0, r=0, t=40, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.05),
        plot_bgcolor="#FAFAFA",
    )
    st.plotly_chart(fig_fft, use_container_width=True)

with sig_col2:
    categories_r = ["에너지비율", "고주파비율", "전력주파수", "ZCR(경련)", "피크강도"]
    fig_rad = go.Figure()
    for r in _pipeline:
        et   = r["event_type"]
        feat = r["signal_features"]
        vals = [
            min(1.0, feat.get("energy_ratio", 0)),
            feat.get("high_freq_ratio", 0) * 3,
            feat.get("power_line_ratio", 0) * 5,
            feat.get("zcr", 0) * 3,
            min(1.0, feat.get("peak_amplitude", 0) / 4),
        ]
        fig_rad.add_trace(go.Scatterpolar(
            r=vals + [vals[0]],
            theta=categories_r + [categories_r[0]],
            fill="toself", name=SIG_LABEL[et],
            line=dict(color=SIG_COLOR[et], width=2),
            fillcolor=SIG_COLOR[et], opacity=0.25,
        ))
    fig_rad.update_layout(
        title="신호 특성 레이더 차트",
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        height=300, margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=-0.2),
    )
    st.plotly_chart(fig_rad, use_container_width=True)

# 신호 특징 비교 테이블
with st.expander("📋 이벤트별 신호 특징 상세 비교"):
    table_rows = []
    for r in _pipeline:
        feat = r["signal_features"]
        table_rows.append({
            "이벤트":         SIG_LABEL[r["event_type"]],
            "Zone":           r["zone"],
            "이상점수":        r["anomaly_score"],
            "신뢰도":          f"{r['confidence']:.0%}",
            "에너지비율":      feat.get("energy_ratio"),
            "고주파비율":      feat.get("high_freq_ratio"),
            "전력주파수비율":  feat.get("power_line_ratio"),
            "ZCR":             feat.get("zcr"),
            "지배주파수(Hz)":  feat.get("dominant_freq_hz"),
        })
    st.dataframe(table_rows, use_container_width=True)

# 현재 이벤트 신호 상세
if st.session_state.current_event:
    et   = st.session_state.current_event["event_type"]
    feat = SIGNAL_DATA[et]["signal_features"]
    st.markdown(f"**현재 감지 이벤트: {SIG_LABEL[et]}**")
    dc1, dc2, dc3, dc4 = st.columns(4)
    dc1.metric("신뢰도",     f"{st.session_state.current_event['confidence']:.0%}")
    dc2.metric("이상 점수",  f"{st.session_state.current_event['details']['anomaly_score']:.3f}")
    dc3.metric("복원 오차",  f"{st.session_state.current_event['details']['reconstruction_error']:.3f}")
    dc4.metric("지배 주파수", f"{feat.get('dominant_freq_hz', '-')} Hz")

st.divider()

# ===================================================================
# [구역 4] 🔴 RAG 조치 가이드 (week5.py 동일)
# ===================================================================
st.subheader("🔴 이상 감지 시 RAG 기반 조치 가이드")

default_situation = "작업자 낙상 감지 (Zone A)"
if st.session_state.current_event:
    evt     = st.session_state.current_event
    korean  = EVENT_TYPE_KOREAN.get(evt["event_type"], evt["event_type"])
    default_situation = f"{korean} (Zone {evt['zone_id']})"

situation     = st.text_input("감지된 상황 입력 (이벤트 발생 시 자동 입력, 수정 가능)",
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
            "PowerShell에서 다음을 확인하세요:\n"
            "  1. docker start radar-guard-db\n"
            "  2. Ollama가 시스템 트레이에서 실행 중"
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
