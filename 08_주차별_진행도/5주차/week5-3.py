"""
Radar-Guard 통합 관제 시스템 v3  (week5-3.py)
==============================================
Industrial HMI / SCADA 스타일 UI 적용판.

week5-2.py 전체 기능 100% 유지:
  - 3D Point Cloud (mmWave)
  - 진동 분석 + Event Log
  - Facility Map (Zone A/B/C)
  - 신호 분석 (파형 / FFT / 레이더 차트 / 특징 테이블)
  - RAG 기반 조치 가이드

실행 (PowerShell):
    streamlit run week5-3.py

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
    page_title="RADAR-GUARD IMS v3",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===================================================================
# ◈ INDUSTRIAL HMI 테마 CSS
# ===================================================================
st.markdown("""
<style>
/* ── 전체 배경 / 폰트 ─────────────────────────────────────── */
.stApp { background-color: #07090D !important; color: #8BAFC8; }
html, body, [class*="css"] {
    font-family: 'Consolas', 'Courier New', 'Lucida Console', monospace !important;
}
.block-container { padding-top: 0.6rem !important; padding-bottom: 0.6rem !important; }

/* ── 사이드바 ────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #040608 !important;
    border-right: 1px solid #0E2233 !important;
}
[data-testid="stSidebar"] * { color: #607888 !important; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #00C853 !important;
    font-size: 0.78rem !important;
    letter-spacing: 2px;
    text-transform: uppercase;
}

/* ── 헤더 ────────────────────────────────────────────────── */
h1 { color: #00C853 !important; letter-spacing: 4px; font-size: 1.25rem !important;
     text-transform: uppercase; text-shadow: 0 0 12px rgba(0,200,83,0.35); }
h2 { color: #29B6F6 !important; letter-spacing: 2px; font-size: 0.95rem !important; }
h3 { color: #29B6F6 !important; letter-spacing: 1px; font-size: 0.85rem !important; }
h4 { color: #5AA8D0 !important; letter-spacing: 1px; font-size: 0.8rem  !important; }

/* ── 구분선 ────────────────────────────────────────────── */
hr { border-color: #0E2233 !important; margin: 0.5rem 0 !important; }

/* ── Metric 카드 ────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #060A10 !important;
    border: 1px solid #0E2233 !important;
    border-left: 3px solid #00C853 !important;
    border-radius: 0 !important;
    padding: 8px 12px !important;
}
[data-testid="stMetricLabel"] {
    color: #3A6880 !important;
    font-size: 0.68rem !important;
    letter-spacing: 2px;
    text-transform: uppercase;
}
[data-testid="stMetricValue"] { color: #B2DFDB !important; font-size: 1.35rem !important; }
[data-testid="stMetricDelta"]  { font-size: 0.72rem !important; }

/* ── 버튼 ────────────────────────────────────────────────── */
.stButton > button {
    background: #060A10 !important;
    color: #00C853 !important;
    border: 1px solid #00C853 !important;
    border-radius: 0 !important;
    font-family: 'Consolas', monospace !important;
    letter-spacing: 1px;
    text-transform: uppercase;
    font-size: 0.72rem !important;
    padding: 6px 12px !important;
    transition: all 0.15s !important;
}
.stButton > button:hover {
    background: #003015 !important;
    box-shadow: 0 0 10px rgba(0,200,83,0.5) !important;
    color: #00FF6A !important;
}
.stButton > button[kind="primary"] {
    background: #001A0A !important;
    color: #00FF6A !important;
    border: 1px solid #00FF6A !important;
    box-shadow: 0 0 8px rgba(0,255,106,0.25) !important;
}

/* ── Selectbox / Slider ──────────────────────────────────── */
[data-testid="stSelectbox"] > div > div {
    background: #060A10 !important;
    border-color: #0E2233 !important;
    border-radius: 0 !important;
    color: #8BAFC8 !important;
}
.stSlider > div { color: #3A6880 !important; }
.stSlider [data-testid="stThumbValue"] { color: #00C853 !important; }

/* ── Text Input ───────────────────────────────────────────── */
.stTextInput > div > div > input {
    background: #060A10 !important;
    color: #8BAFC8 !important;
    border: 1px solid #0E2233 !important;
    border-radius: 0 !important;
    font-family: 'Consolas', monospace !important;
    font-size: 0.82rem !important;
}
.stTextInput > div > div > input:focus {
    border-color: #00C853 !important;
    box-shadow: 0 0 6px rgba(0,200,83,0.3) !important;
}

/* ── Expander ─────────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: #060A10 !important;
    border: 1px solid #0E2233 !important;
    border-radius: 0 !important;
}
[data-testid="stExpander"] summary { color: #3A6880 !important; font-size: 0.78rem !important; }

/* ── DataFrame ────────────────────────────────────────────── */
[data-testid="stDataFrame"] { background: #060A10 !important; }
.stDataFrame iframe { filter: invert(0.88) hue-rotate(180deg); }

/* ── Info / Success / Warning / Error ─────────────────────── */
[data-testid="stAlert"] {
    background: #060A10 !important;
    border-radius: 0 !important;
    font-size: 0.8rem !important;
}

/* ── Spinner ──────────────────────────────────────────────── */
.stSpinner > div { color: #00C853 !important; }

/* ── Scrollbar ────────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; background: #040608; }
::-webkit-scrollbar-thumb { background: #0E2233; border-radius: 0; }
::-webkit-scrollbar-thumb:hover { background: #00C853; }

/* ── 알람 깜빡임 ───────────────────────────────────────────── */
@keyframes alarm_blink { 0%,100%{ opacity:1; } 50%{ opacity:0.3; } }
.alarm-blink { animation: alarm_blink 1.1s infinite; }

/* ── Caption ─────────────────────────────────────────────── */
.stCaption { color: #2A4A60 !important; font-size: 0.68rem !important; }
</style>
""", unsafe_allow_html=True)


# ===================================================================
# ◈ 유틸리티
# ===================================================================
def sec_header(icon: str, title: str, color: str = "#00C853", sub: str = ""):
    """산업 HMI 섹션 헤더"""
    sub_html = f'<span style="color:#2A5870;font-size:0.68rem;margin-left:10px;">{sub}</span>' if sub else ""
    st.markdown(f"""
    <div style="display:flex;align-items:center;
                border-left:3px solid {color};
                padding:4px 12px;margin:6px 0 10px 0;
                background:linear-gradient(90deg,#05080E 0%,transparent 80%);">
        <span style="color:{color};font-size:0.78rem;letter-spacing:2px;
                     text-transform:uppercase;font-weight:bold;">
            {icon}&nbsp;&nbsp;{title}
        </span>{sub_html}
    </div>""", unsafe_allow_html=True)


# Plotly 다크 레이아웃 기준값
_DL = dict(
    plot_bgcolor="#060A10",
    paper_bgcolor="#07090D",
    font=dict(color="#4A7090", family="Consolas, monospace", size=10),
    xaxis=dict(gridcolor="#0E2030", zerolinecolor="#0E2030",
               linecolor="#0E2030", tickfont=dict(color="#4A7090")),
    yaxis=dict(gridcolor="#0E2030", zerolinecolor="#0E2030",
               linecolor="#0E2030", tickfont=dict(color="#4A7090")),
    margin=dict(l=4, r=4, t=32, b=4),
)
_DL_LEGEND = dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#607888", size=10))


# ===================================================================
# ◈ 신호 생성 + 특징 추출 (성준 파트)
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
# ◈ 파이프라인 데이터 빌드 (캐싱)
# ===================================================================
_SCENARIOS = [
    {"scenario": "fall",             "event_type": "fall_detected",       "zone": "A", "recon_error": 0.082, "threshold": 0.021},
    {"scenario": "electric_shock",   "event_type": "electric_shock_risk", "zone": "B", "recon_error": 0.104, "threshold": 0.021},
    {"scenario": "pinching",         "event_type": "pinching",            "zone": "C", "recon_error": 0.071, "threshold": 0.021},
    {"scenario": "vibration_anomaly","event_type": "vibration_anomaly",   "zone": "C", "recon_error": 0.035, "threshold": 0.021},
]
_SEVERITY_MAP   = {"fall_detected":"critical","electric_shock_risk":"critical",
                   "pinching":"critical","vibration_anomaly":"warning"}
_CONFIDENCE_MAP = {"fall_detected":0.88,"electric_shock_risk":0.91,
                   "pinching":0.84,"vibration_anomaly":0.73}
_REASON_MAP = {
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
            "_signal":    sig.tolist(),
            "_timestamp": now.isoformat(),
            "event_type":           etype,
            "severity":             _SEVERITY_MAP[etype],
            "confidence":           _CONFIDENCE_MAP[etype],
            "reason":               _REASON_MAP[etype],
            "signal_features":      feat,
            "anomaly_score":        round(sc["recon_error"] / sc["threshold"], 3),
            "reconstruction_error": sc["recon_error"],
            "zone":                 zone,
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
                "anomaly_score":        round(sc["recon_error"] / sc["threshold"], 3),
                "reconstruction_error": sc["recon_error"],
            },
            "event_log": [
                {"time": now.strftime("%H:%M:%S"),
                 "msg":  f"ZONE-{zone}  LSTM-AE 이상 탐지 (score={round(sc['recon_error']/sc['threshold'],3)})"},
                {"time": (now + timedelta(milliseconds=120)).strftime("%H:%M:%S"),
                 "msg":  f"ZONE-{zone}  유형 분류 완료 → {etype}"},
                {"time": (now + timedelta(milliseconds=240)).strftime("%H:%M:%S"),
                 "msg":  f"ZONE-{zone}  알림 발송  sev={_SEVERITY_MAP[etype]}  conf={_CONFIDENCE_MAP[etype]}"},
            ],
        })
    return results


_pipeline   = build_pipeline_data()
LIVE_EVENTS = {r["event_type"]: r for r in _pipeline}
SIGNAL_DATA = {r["event_type"]: r for r in _pipeline}

# 신호 색 / 레이블
SIG_COLOR = {"fall_detected":"#FF3B30","electric_shock_risk":"#FF9500",
             "pinching":"#BF5AF2","vibration_anomaly":"#32ADE6"}
SIG_LABEL = {"fall_detected":"FALL","electric_shock_risk":"E-SHOCK",
             "pinching":"PINCH","vibration_anomaly":"VIB-ANOM"}

# ===================================================================
# ◈ 백엔드: DB / LLM
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
# ◈ 상수
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
# HMI 색 체계
SEV_LED   = {"normal":"#00C853", "warning":"#FF9500", "critical":"#FF3B30"}
SEV_LABEL = {"normal":"NORMAL",  "warning":"WARNING", "critical":"ALARM"}
SEV_BG    = {"normal":"#060A10", "warning":"#0D0A04", "critical":"#120404"}

CATEGORIES = {
    "전체":             None,
    "01_감전_LOTO":     "01_감전_LOTO",
    "02_협착_끼임":     "02_협착_끼임",
    "03_낙상_응급처치": "03_낙상_응급처치",
    "04_예지보전":      "04_예지보전",
    "05_위험성평가_비상":"05_위험성평가_비상",
}

# ===================================================================
# ◈ Session State
# ===================================================================
if "current_event"   not in st.session_state: st.session_state.current_event   = None
if "facility_status" not in st.session_state: st.session_state.facility_status = {"A":"normal","B":"normal","C":"normal"}
if "auto_run_rag"    not in st.session_state: st.session_state.auto_run_rag    = False

def load_scenario(event_type: str, facility: dict):
    st.session_state.current_event   = LIVE_EVENTS[event_type]
    st.session_state.facility_status = facility
    st.session_state.auto_run_rag    = True

def reset_state():
    st.session_state.current_event   = None
    st.session_state.facility_status = {"A":"normal","B":"normal","C":"normal"}
    st.session_state.auto_run_rag    = False

# ===================================================================
# ◈ SIDEBAR
# ===================================================================
with st.sidebar:
    st.markdown("""
    <div style="border-bottom:1px solid #0E2233;padding-bottom:10px;margin-bottom:12px;">
      <div style="color:#00C853;font-size:0.72rem;letter-spacing:3px;">⬡ RADAR-GUARD IMS</div>
      <div style="color:#2A4A60;font-size:0.65rem;letter-spacing:1px;margin-top:2px;">
        INDUSTRIAL MONITORING SYSTEM v3
      </div>
    </div>""", unsafe_allow_html=True)

    st.markdown('<div style="color:#3A6880;font-size:0.68rem;letter-spacing:2px;margin-bottom:6px;">▸ RAG SEARCH CONFIG</div>', unsafe_allow_html=True)

    default_idx = 0
    if st.session_state.current_event:
        auto_cat = EVENT_TYPE_TO_CATEGORY.get(st.session_state.current_event["event_type"])
        cat_list = list(CATEGORIES.keys())
        if auto_cat in cat_list:
            default_idx = cat_list.index(auto_cat)

    selected_category_label = st.selectbox(
        "CATEGORY", list(CATEGORIES.keys()),
        index=default_idx,
        help="이벤트 발생 시 자동 선택됩니다."
    )
    selected_category = CATEGORIES[selected_category_label]
    top_k = st.slider("TOP-K RESULTS", 1, 5, 3)

    st.markdown('<hr style="border-color:#0E2233;margin:12px 0;">', unsafe_allow_html=True)
    st.markdown('<div style="color:#3A6880;font-size:0.68rem;letter-spacing:2px;margin-bottom:8px;">▸ SCENARIO TRIGGER</div>', unsafe_allow_html=True)

    st.button("▶  SIM-1  낙상 / ZONE A",       use_container_width=True, on_click=load_scenario,
              args=("fall_detected",       {"A":"critical","B":"normal","C":"normal"}))
    st.button("▶  SIM-2  감전위험 / ZONE B",   use_container_width=True, on_click=load_scenario,
              args=("electric_shock_risk", {"A":"normal","B":"critical","C":"normal"}))
    st.button("▶  SIM-3  협착 / ZONE C",       use_container_width=True, on_click=load_scenario,
              args=("pinching",            {"A":"normal","B":"normal","C":"critical"}))
    st.button("▶  SIM-4  진동이상 / ZONE C",   use_container_width=True, on_click=load_scenario,
              args=("vibration_anomaly",   {"A":"normal","B":"normal","C":"warning"}))

    st.markdown('<hr style="border-color:#0E2233;margin:10px 0;">', unsafe_allow_html=True)
    st.button("◼  SYSTEM RESET", use_container_width=True, on_click=reset_state)

    st.markdown("""
    <div style="margin-top:14px;border-top:1px solid #0E2233;padding-top:10px;">
      <div style="color:#1A3A50;font-size:0.62rem;line-height:1.7;">
        LLM  : Qwen2.5-3B (Ollama)<br>
        EMBED: BGE-M3<br>
        SIG  : LSTM-AE (성준)<br>
        JETSON: Llama-3 이식 예정
      </div>
    </div>""", unsafe_allow_html=True)

# ===================================================================
# ◈ 전체 상태 계산
# ===================================================================
overall_status = "normal"
for s in st.session_state.facility_status.values():
    if s == "critical":
        overall_status = "critical"; break
    elif s == "warning" and overall_status != "critical":
        overall_status = "warning"

# ===================================================================
# ◈ ALARM BANNER (critical 시 표시)
# ===================================================================
if overall_status == "critical" and st.session_state.current_event:
    evt_korean = EVENT_TYPE_KOREAN.get(
        st.session_state.current_event["event_type"],
        st.session_state.current_event["event_type"]
    )
    zone_id = st.session_state.current_event.get("zone_id", "?")
    st.markdown(f"""
    <div class="alarm-blink" style="
        background:#150000;
        border:1px solid #FF3B30;
        border-left:5px solid #FF3B30;
        padding:10px 18px;
        margin-bottom:8px;
        display:flex;align-items:center;gap:14px;">
        <span style="color:#FF3B30;font-size:1rem;font-weight:bold;">⚠</span>
        <span style="color:#FF6B60;font-size:0.82rem;letter-spacing:2px;">
            CRITICAL ALARM &nbsp;─&nbsp; {evt_korean.upper()} &nbsp;─&nbsp; ZONE {zone_id}
        </span>
        <span style="margin-left:auto;color:#6A2020;font-size:0.68rem;">{datetime.now().strftime('%H:%M:%S')}</span>
    </div>""", unsafe_allow_html=True)

elif overall_status == "warning" and st.session_state.current_event:
    evt_korean = EVENT_TYPE_KOREAN.get(
        st.session_state.current_event["event_type"], ""
    )
    st.markdown(f"""
    <div style="
        background:#100A00;border:1px solid #FF9500;border-left:5px solid #FF9500;
        padding:8px 18px;margin-bottom:8px;display:flex;align-items:center;gap:14px;">
        <span style="color:#FF9500;font-size:0.9rem;">▲</span>
        <span style="color:#FFA830;font-size:0.8rem;letter-spacing:2px;">
            WARNING &nbsp;─&nbsp; {evt_korean.upper()} &nbsp;─&nbsp; ZONE {st.session_state.current_event.get('zone_id','?')}
        </span>
    </div>""", unsafe_allow_html=True)

# ===================================================================
# ◈ SYSTEM HEADER
# ===================================================================
led_color = SEV_LED[overall_status]
led_label = SEV_LABEL[overall_status]
blink_cls = "alarm-blink" if overall_status == "critical" else ""

hcol1, hcol2, hcol3 = st.columns([5, 2, 2])
with hcol1:
    st.markdown(f"""
    <div style="padding:4px 0 2px 0;">
        <div style="color:#00C853;font-size:1.15rem;font-weight:bold;
                    letter-spacing:4px;text-shadow:0 0 14px rgba(0,200,83,0.4);">
            ⬡ RADAR-GUARD  INDUSTRIAL MONITORING SYSTEM
        </div>
        <div style="color:#2A5060;font-size:0.68rem;letter-spacing:2px;margin-top:2px;">
            mmWave Radar · LSTM-AE · Offline RAG · Jetson Edge-Ready
        </div>
    </div>""", unsafe_allow_html=True)

with hcol2:
    st.markdown(f"""
    <div style="background:#060A10;border:1px solid #0E2233;
                border-left:3px solid {led_color};padding:10px 14px;text-align:center;">
        <div style="color:#2A4A60;font-size:0.62rem;letter-spacing:2px;">SYSTEM STATUS</div>
        <div class="{blink_cls}"
             style="color:{led_color};font-size:1.0rem;font-weight:bold;
                    letter-spacing:3px;margin-top:4px;
                    text-shadow:0 0 10px {led_color}55;">
            ● {led_label}
        </div>
    </div>""", unsafe_allow_html=True)

with hcol3:
    st.markdown(f"""
    <div style="background:#060A10;border:1px solid #0E2233;
                border-left:3px solid #29B6F6;padding:10px 14px;text-align:center;">
        <div style="color:#2A4A60;font-size:0.62rem;letter-spacing:2px;">LOCAL TIME</div>
        <div style="color:#5AB8E8;font-size:1.0rem;font-weight:bold;
                    letter-spacing:2px;margin-top:4px;">
            {datetime.now().strftime('%H:%M:%S')}
        </div>
        <div style="color:#1A3A50;font-size:0.62rem;margin-top:2px;">
            {datetime.now().strftime('%Y-%m-%d')}
        </div>
    </div>""", unsafe_allow_html=True)

st.markdown('<hr style="border-color:#0E2233;margin:8px 0;">', unsafe_allow_html=True)

# ===================================================================
# ◈ [구역 1]  3D POINT CLOUD  │  VIBRATION + EVENT LOG
# ===================================================================
left_col, right_col = st.columns([3, 2])

with left_col:
    sec_header("◈", "3D POINT CLOUD  [ mmWave ]", "#00C853",
               sub=f"ZONE {st.session_state.current_event['zone_id']} ACTIVE" if st.session_state.current_event else "STANDBY")

    np.random.seed(42)
    n_bg = 200
    x = np.random.uniform(-2, 2, n_bg)
    y = np.random.uniform(-2, 2, n_bg)
    z = np.random.uniform(0, 2.5, n_bg)
    intensity = np.random.uniform(0, 0.5, n_bg)

    if st.session_state.current_event:
        zone     = st.session_state.current_event["zone_id"]
        evt_type = st.session_state.current_event["event_type"]
        cx       = {"A": -1.5, "B": 0.0, "C": 1.5}.get(zone, 0)
        n_cl = 60
        cx_arr = np.random.normal(cx, 0.25, n_cl)
        cy_arr = np.random.normal(0, 0.25, n_cl)
        cz_arr = (np.random.uniform(0, 0.5, n_cl) if evt_type == "fall_detected"
                  else np.random.uniform(0.5, 1.7, n_cl))
        x         = np.concatenate([x, cx_arr])
        y         = np.concatenate([y, cy_arr])
        z         = np.concatenate([z, cz_arr])
        intensity = np.concatenate([intensity, np.ones(n_cl)])

    fig_3d = go.Figure(data=[go.Scatter3d(
        x=x, y=y, z=z, mode="markers",
        marker=dict(size=3, color=intensity,
                    colorscale=[[0,"#0E2A3A"],[0.5,"#00C853"],[1.0,"#FF3B30"]],
                    opacity=0.8, showscale=True,
                    colorbar=dict(
                                  title=dict(text="INT", font=dict(color="#3A6880", size=9)),
                                  thickness=10,
                                  tickfont=dict(color="#3A6880", size=9))),
    )])
    fig_3d.update_layout(
        **_DL,
        scene=dict(
            xaxis=dict(title="X (m)", gridcolor="#0E2030", backgroundcolor="#060A10",
                       tickfont=dict(color="#3A6880")),
            yaxis=dict(title="Y (m)", gridcolor="#0E2030", backgroundcolor="#060A10",
                       tickfont=dict(color="#3A6880")),
            zaxis=dict(title="Z (m)", gridcolor="#0E2030", backgroundcolor="#060A10",
                       tickfont=dict(color="#3A6880")),
            bgcolor="#060A10",
            aspectmode="cube",
        ),
        height=430,
    )
    st.plotly_chart(fig_3d, use_container_width=True)

with right_col:
    # ── 진동 분석 ──
    sec_header("◈", "VIBRATION ANALYSIS", "#29B6F6")

    vib_value, vib_delta = "0.02 μm/s", "-0.01"
    if (st.session_state.current_event
            and st.session_state.current_event["event_type"] == "vibration_anomaly"):
        feat = SIGNAL_DATA["vibration_anomaly"]["signal_features"]
        vib_value = f"{feat.get('peak_amplitude', 1.80):.2f} μm/s"
        vib_delta = "+1.78"

    st.metric("VIBRATION RMS", vib_value, delta=vib_delta, delta_color="inverse")

    freq            = np.linspace(0, 200, 200)
    normal_spectrum = 0.05 * np.exp(-((freq - 60) ** 2) / 200) + 0.02
    current_spectrum = normal_spectrum.copy()
    if (st.session_state.current_event
            and st.session_state.current_event["event_type"] == "vibration_anomaly"):
        feat = SIGNAL_DATA["vibration_anomaly"]["signal_features"]
        dom  = feat.get("dominant_freq_hz", 47.5)
        current_spectrum += 0.18 * np.exp(-((freq - dom) ** 2) / 30)

    fig_vib = go.Figure()
    fig_vib.add_trace(go.Scatter(x=freq, y=normal_spectrum, name="BASELINE",
                                  line=dict(color="#00C853", dash="dash", width=1.2)))
    fig_vib.add_trace(go.Scatter(x=freq, y=current_spectrum, name="CURRENT",
                                  line=dict(color="#FF3B30", width=1.8)))
    fig_vib.update_layout(
        **_DL,
        title=dict(text="FREQ SPECTRUM", font=dict(color="#29B6F6", size=10)),
        xaxis_title="Hz", yaxis_title="AMP",
        height=175,
        legend={**_DL_LEGEND, **dict(orientation="h", yanchor="bottom", y=1.02,
                                     xanchor="right", x=1)},
    )
    st.plotly_chart(fig_vib, use_container_width=True)

    # ── EVENT LOG ──
    sec_header("◈", "EVENT LOG", "#FF9500")

    if st.session_state.current_event:
        sev = st.session_state.current_event["severity"]
        log_color = "#FF3B30" if sev == "critical" else "#FF9500"
        log_lines = ""
        for log in st.session_state.current_event["event_log"]:
            log_lines += (
                f'<div style="margin:3px 0;color:{log_color};font-size:0.72rem;">'
                f'<span style="color:#2A5060;">[{log["time"]}]</span>&nbsp;'
                f'{log["msg"]}</div>'
            )
        st.markdown(f"""
        <div style="background:#060A10;border:1px solid #0E2233;
                    border-left:3px solid {log_color};
                    padding:10px 14px;font-family:Consolas,monospace;
                    max-height:200px;overflow-y:auto;">
            {log_lines}
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="background:#060A10;border:1px solid #0E2233;
                    padding:14px;color:#1A3A50;font-size:0.75rem;
                    letter-spacing:1px;text-align:center;">
            ─── NO ACTIVE EVENT ───<br>
            <span style="font-size:0.65rem;">사이드바에서 SIM 트리거</span>
        </div>""", unsafe_allow_html=True)

st.markdown('<hr style="border-color:#0E2233;margin:6px 0;">', unsafe_allow_html=True)

# ===================================================================
# ◈ [구역 2]  FACILITY MAP
# ===================================================================
sec_header("◈", "FACILITY MAP  [ ZONE STATUS ]", "#00C853")

zone_info = {
    "A": {"name": "ZONE A", "sub": "변전실", "worker": "NORMAL", "power": "NORMAL"},
    "B": {"name": "ZONE B", "sub": "가공실", "worker": "NORMAL", "power": "NORMAL"},
    "C": {"name": "ZONE C", "sub": "조립실", "worker": "NORMAL", "power": "NORMAL"},
}

if st.session_state.current_event:
    evt  = st.session_state.current_event
    zone = evt["zone_id"]
    et   = evt["event_type"]
    if et == "fall_detected":
        zone_info[zone]["worker"] = "!! FALL DETECTED"
        zone_info[zone]["power"]  = "!! E-STOP ACTIVE"
    elif et == "electric_shock_risk":
        zone_info[zone]["worker"] = "!! SHOCK RISK"
        zone_info[zone]["power"]  = "!! LOTO REQUIRED"
    elif et == "pinching":
        zone_info[zone]["worker"] = "!! PINCHING"
        zone_info[zone]["power"]  = "!! E-STOP ACTIVE"
    elif et == "vibration_anomaly":
        zone_info[zone]["worker"] = "NORMAL"
        zone_info[zone]["power"]  = "▲ MONITORING"

zone_cols = st.columns(3)
for i, (zid, info) in enumerate(zone_info.items()):
    status     = st.session_state.facility_status[zid]
    led        = SEV_LED[status]
    bg         = SEV_BG[status]
    label      = SEV_LABEL[status]
    blink      = "alarm-blink" if status == "critical" else ""
    w_color    = "#FF3B30" if "!!" in info["worker"] else "#3A6880"
    p_color    = "#FF3B30" if "!!" in info["power"] else ("#FF9500" if "▲" in info["power"] else "#3A6880")

    with zone_cols[i]:
        st.markdown(f"""
        <div style="background:{bg};padding:14px 16px;
                    border:1px solid #0E2233;
                    border-left:5px solid {led};
                    min-height:130px;">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <span class="{blink}"
                      style="color:{led};font-size:0.75rem;
                             text-shadow:0 0 8px {led}66;">● </span>
                <span style="color:{led};font-size:0.82rem;
                             font-weight:bold;letter-spacing:2px;">{info['name']}</span>
                <span style="color:#2A4A60;font-size:0.68rem;margin-left:4px;">{info['sub']}</span>
                <span style="margin-left:auto;color:{led};font-size:0.65rem;
                             letter-spacing:2px;">{label}</span>
            </div>
            <div style="border-top:1px solid #0E2233;padding-top:8px;">
                <div style="color:#2A4A60;font-size:0.65rem;margin-bottom:3px;">WORKER STATUS</div>
                <div style="color:{w_color};font-size:0.78rem;">{info['worker']}</div>
            </div>
            <div style="margin-top:6px;">
                <div style="color:#2A4A60;font-size:0.65rem;margin-bottom:3px;">POWER STATUS</div>
                <div style="color:{p_color};font-size:0.78rem;">{info['power']}</div>
            </div>
        </div>""", unsafe_allow_html=True)

st.markdown('<hr style="border-color:#0E2233;margin:8px 0;">', unsafe_allow_html=True)

# ===================================================================
# ◈ [구역 3]  SIGNAL ANALYSIS  (성준 파트 — LSTM-AE)
# ===================================================================
sec_header("◈", "SIGNAL ANALYSIS  [ LSTM-AE DETECTION ]", "#29B6F6",
           sub="WAVEFORM · FFT · RADAR CHART · FEATURE TABLE")

t_ms = np.linspace(0, 0.1, 128) * 1000

# ── 파형 ──
fig_wave = go.Figure()
for r in _pipeline:
    et  = r["event_type"]
    sig = np.array(r["_signal"])
    fig_wave.add_trace(go.Scatter(
        x=t_ms, y=sig, mode="lines",
        name=SIG_LABEL[et],
        line=dict(color=SIG_COLOR[et], width=1.8),
        opacity=0.9,
    ))
fig_wave.add_hline(y=0, line_dash="dot", line_color="#0E2030", line_width=1)
fig_wave.update_layout(
    **_DL,
    title=dict(text="RADAR SIGNAL WAVEFORM  [ by event type ]",
               font=dict(color="#29B6F6", size=11)),
    xaxis_title="TIME (ms)", yaxis_title="AMPLITUDE",
    height=280,
    legend={**_DL_LEGEND, **dict(orientation="h", yanchor="bottom", y=1.04, xanchor="right", x=1)},
)
st.plotly_chart(fig_wave, use_container_width=True)

# ── FFT + 레이더 차트 ──
sig_col1, sig_col2 = st.columns(2)

with sig_col1:
    fig_fft = go.Figure()
    for r in _pipeline:
        et  = r["event_type"]
        sig = np.array(r["_signal"])
        n   = len(sig)
        fft_mag = np.abs(np.fft.fft(sig))[: n // 2]
        freqs   = np.fft.fftfreq(n, d=1 / FS)[: n // 2]
        fig_fft.add_trace(go.Scatter(
            x=freqs[:200], y=fft_mag[:200], mode="lines",
            name=SIG_LABEL[et],
            line=dict(color=SIG_COLOR[et], width=1.6),
            opacity=0.9,
        ))
    fig_fft.add_vline(x=50, line_dash="dot", line_color="#FF9500",
                      annotation_text="50Hz", annotation_position="top right",
                      annotation_font=dict(color="#FF9500", size=9))
    fig_fft.update_layout(
        **_DL,
        title=dict(text="FFT FREQUENCY SPECTRUM",
                   font=dict(color="#29B6F6", size=11)),
        xaxis_title="Hz", yaxis_title="MAG",
        xaxis_range=[0, 200], height=280,
        legend={**_DL_LEGEND, **dict(orientation="h", yanchor="bottom", y=1.04)},
    )
    st.plotly_chart(fig_fft, use_container_width=True)

with sig_col2:
    categories_r = ["ENERGY", "HIGH-FREQ", "POWER-LINE", "ZCR", "PEAK"]
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
            line=dict(color=SIG_COLOR[et], width=1.8),
            fillcolor=SIG_COLOR[et], opacity=0.18,
        ))
    fig_rad.update_layout(
        **_DL,
        title=dict(text="SIGNAL FEATURE RADAR CHART",
                   font=dict(color="#29B6F6", size=11)),
        polar=dict(
            bgcolor="#060A10",
            radialaxis=dict(visible=True, range=[0, 1],
                            gridcolor="#0E2030", tickfont=dict(color="#2A4A60")),
            angularaxis=dict(gridcolor="#0E2030", tickfont=dict(color="#4A7090")),
        ),
        height=280,
        legend={**_DL_LEGEND, **dict(orientation="h", yanchor="bottom", y=-0.22)},
    )
    st.plotly_chart(fig_rad, use_container_width=True)

# ── 특징 테이블 ──
with st.expander("▸  SIGNAL FEATURE TABLE  [ 이벤트별 상세 비교 ]"):
    table_rows = []
    for r in _pipeline:
        feat = r["signal_features"]
        table_rows.append({
            "EVENT":       SIG_LABEL[r["event_type"]],
            "ZONE":        r["zone"],
            "ANOM-SCORE":  r["anomaly_score"],
            "CONFIDENCE":  f"{r['confidence']:.0%}",
            "ENERGY-RATIO":feat.get("energy_ratio"),
            "HF-RATIO":    feat.get("high_freq_ratio"),
            "PL-RATIO":    feat.get("power_line_ratio"),
            "ZCR":         feat.get("zcr"),
            "DOM-FREQ(Hz)":feat.get("dominant_freq_hz"),
        })
    st.dataframe(table_rows, use_container_width=True)

# ── 현재 이벤트 실시간 지표 ──
if st.session_state.current_event:
    et   = st.session_state.current_event["event_type"]
    feat = SIGNAL_DATA[et]["signal_features"]
    st.markdown(f"""
    <div style="background:#060A10;border:1px solid #0E2233;
                border-left:3px solid {SIG_COLOR[et]};
                padding:8px 14px;margin-top:8px;
                font-size:0.72rem;color:{SIG_COLOR[et]};letter-spacing:2px;">
        ACTIVE  ──  {SIG_LABEL[et]}
    </div>""", unsafe_allow_html=True)
    dc1, dc2, dc3, dc4 = st.columns(4)
    dc1.metric("CONFIDENCE",    f"{st.session_state.current_event['confidence']:.0%}")
    dc2.metric("ANOMALY SCORE", f"{st.session_state.current_event['details']['anomaly_score']:.3f}")
    dc3.metric("RECON ERROR",   f"{st.session_state.current_event['details']['reconstruction_error']:.3f}")
    dc4.metric("DOM FREQ",      f"{feat.get('dominant_freq_hz', '-')} Hz")

st.markdown('<hr style="border-color:#0E2233;margin:8px 0;">', unsafe_allow_html=True)

# ===================================================================
# ◈ [구역 4]  RAG RESPONSE GUIDE
# ===================================================================
sec_header("◈", "ANOMALY RESPONSE GUIDE  [ RAG · OFFLINE ]",
           "#FF3B30" if overall_status == "critical" else "#FF9500")

default_situation = "작업자 낙상 감지 (Zone A)"
if st.session_state.current_event:
    evt    = st.session_state.current_event
    korean = EVENT_TYPE_KOREAN.get(evt["event_type"], evt["event_type"])
    default_situation = f"{korean} (Zone {evt['zone_id']})"

situation      = st.text_input(
    "INCIDENT INPUT  ─  이벤트 발생 시 자동 입력 / 수정 가능",
    default_situation
)
manual_trigger = st.button("▶  GENERATE RESPONSE GUIDE", type="primary")
trigger        = manual_trigger or st.session_state.auto_run_rag

if st.session_state.auto_run_rag:
    st.session_state.auto_run_rag = False

if trigger:
    try:
        vectorstore = get_vectorstore()
        llm         = get_llm()
    except Exception as e:
        st.markdown(f"""
        <div style="background:#120404;border:1px solid #FF3B30;border-left:4px solid #FF3B30;
                    padding:12px 16px;color:#FF6B60;font-size:0.8rem;">
            ⚠ DB / LLM CONNECTION FAILED<br>
            <span style="color:#6A2020;font-size:0.72rem;">{e}</span><br><br>
            <span style="color:#4A3030;">
            [ PowerShell ]<br>
            &gt; docker start radar-guard-db<br>
            &gt; ollama serve
            </span>
        </div>""", unsafe_allow_html=True)
        st.stop()

    with st.spinner("▸ SEARCHING SAFETY MANUAL DATABASE ..."):
        if selected_category:
            docs = vectorstore.similarity_search(situation, k=top_k,
                                                  filter={"category": selected_category})
        else:
            docs = vectorstore.similarity_search(situation, k=top_k)

        if not docs:
            st.markdown(f"""
            <div style="background:#100A00;border:1px solid #FF9500;
                        border-left:4px solid #FF9500;padding:10px 16px;
                        color:#FFA830;font-size:0.8rem;">
                ▲ NO RESULTS — '{selected_category_label}' 카테고리에서 매뉴얼을 찾지 못했습니다.<br>
                <span style="color:#604020;">카테고리를 '전체'로 변경 후 재시도하세요.</span>
            </div>""", unsafe_allow_html=True)
            st.stop()

        context  = "\n\n---\n\n".join([d.page_content for d in docs])
        prompt   = PromptTemplate.from_template(
            "당신은 산업 안전 전문가입니다. 다음 안전 매뉴얼을 참고해서 "
            "아래 상황의 조치 가이드를 **반드시 한국어로** 단계별(1, 2, 3...)로 알려주세요. "
            "한자 사용 금지, 매뉴얼에 없는 내용은 추측하지 마세요.\n\n"
            "안전 매뉴얼:\n{context}\n\n"
            "감지된 상황: {situation}\n\n"
            "조치 가이드:"
        )
        chain    = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": context, "situation": situation})

    st.markdown("""
    <div style="background:#040A06;border:1px solid #00C853;border-left:4px solid #00C853;
                padding:6px 14px;color:#00C853;font-size:0.72rem;letter-spacing:2px;margin-bottom:4px;">
        ✓ RESPONSE GENERATED
    </div>""", unsafe_allow_html=True)

    st.markdown(f"""
    <div style="background:#060A10;border:1px solid #0E2233;
                padding:16px 20px;color:#9BB4C8;font-size:0.82rem;line-height:1.8;">
        {response.replace(chr(10), '<br>')}
    </div>""", unsafe_allow_html=True)

    st.markdown('<hr style="border-color:#0E2233;margin:10px 0;">', unsafe_allow_html=True)
    sec_header("▸", "REFERENCE MANUAL  [ SOURCE ]", "#29B6F6")

    for i, doc in enumerate(docs, 1):
        cat          = doc.metadata.get("category", "UNCLASSIFIED")
        src          = doc.metadata.get("source_file", "UNKNOWN")
        page         = doc.metadata.get("page", "?")
        page_display = page + 1 if isinstance(page, int) else page

        with st.expander(f"▸  [{i}]  {cat}  ──  {src}  (p.{page_display})"):
            st.markdown(f"""
            <div style="background:#060A10;padding:12px;color:#6A8BA0;
                        font-size:0.78rem;line-height:1.7;border-left:2px solid #0E2233;">
                {doc.page_content.replace(chr(10), '<br>')}
            </div>""", unsafe_allow_html=True)

# ── 하단 상태바 ──
st.markdown('<hr style="border-color:#0E2233;margin:8px 0;">', unsafe_allow_html=True)
st.markdown(f"""
<div style="display:flex;justify-content:space-between;align-items:center;
            padding:4px 0;color:#1A3A50;font-size:0.62rem;letter-spacing:1px;">
    <span>⬡ RADAR-GUARD IMS v3  ·  Offline RAG  ·  Jetson-Ready</span>
    <span>LLM: Qwen2.5-3B  ·  EMBED: BGE-M3  ·  SIG: LSTM-AE</span>
    <span>© 2025 RADAR-GUARD TEAM  ·  {datetime.now().strftime('%Y-%m-%d %H:%M')}</span>
</div>""", unsafe_allow_html=True)
