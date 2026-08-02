"""
Radar-Guard 통합 관제 시스템 (week5.py)
=========================================

week4_개선판.py의 RAG 코드를 그대로 활용하면서, 통합 관제 UI로 확장한 버전.

레이아웃 (옵션 B 적용 — 작업자/전력 카드는 Facility Map에 흡수):
┌─────────────────────────────────────────────────────────────────┐
│ 헤더: 시스템명 + 상태 배지 + 실시간 시계                          │
├──────────────┬──────────────────────────────────────────────────┤
│ [사이드바]    │ [좌측] 3D Point Cloud  │ [우상] 진동 분석 그래프 │
│ - 카테고리    │  (Plotly Scatter3d)   │  (정상 vs 현재 스펙트럼)│
│ - top_k       │                       ├─────────────────────────┤
│ - 시나리오 4종│                       │ [우중] Event Log         │
│ - 초기화      ├───────────────────────┴─────────────────────────┤
│              │ [중] Facility Map (Zone A/B/C: 상태+작업자+전력)│
│              ├──────────────────────────────────────────────────┤
│              │ [하] 🔴 RAG 조치 가이드 (week4 코드 통합)        │
└──────────────┴──────────────────────────────────────────────────┘

실행: PowerShell에서 `streamlit run week5.py`
필수 사전 조건: docker start radar-guard-db / Ollama 실행 중
"""

import streamlit as st
import plotly.graph_objects as go
import numpy as np
from datetime import datetime

from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ===================================================================
# 페이지 설정
# ===================================================================
st.set_page_config(
    page_title="Radar-Guard 관제 시스템",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ===================================================================
# 백엔드: DB/LLM 캐싱 (week4와 동일)
#  - 추후 젯슨 이식 시 get_llm()의 model만 llama3로 교체
# ===================================================================
CONNECTION_STRING = "postgresql://admin:1234@localhost:5432/radar_guard"


@st.cache_resource
def get_vectorstore():
    """벡터 DB 연결 캐싱 - 앱 실행 동안 1번만 생성"""
    embeddings = OllamaEmbeddings(model="bge-m3")
    return PGVector(
        connection_string=CONNECTION_STRING,
        embedding_function=embeddings,
        collection_name="safety_manual",
    )


@st.cache_resource
def get_llm():
    """로컬 LLM 연결 캐싱 (개발: qwen2.5 / 젯슨 이식 시 llama3 교체)"""
    return ChatOllama(
        model="qwen2.5:3b-instruct-q4_K_M",
        temperature=0,
    )


# ===================================================================
# 상수: 이벤트 타입 ↔ 카테고리 ↔ 한국어 매핑
# ===================================================================
EVENT_TYPE_TO_CATEGORY = {
    "fall_detected": "03_낙상_응급처치",
    "electric_shock_risk": "01_감전_LOTO",
    "pinching": "02_협착_끼임",
    "vibration_anomaly": "04_예지보전",
}

EVENT_TYPE_KOREAN = {
    "fall_detected": "작업자 낙상 감지",
    "electric_shock_risk": "감전 위험 감지",
    "pinching": "협착 사고 감지",
    "vibration_anomaly": "설비 진동 이상",
}

SEVERITY_EMOJI = {"normal": "🟢", "warning": "🟡", "critical": "🔴"}
SEVERITY_LABEL = {"normal": "정상", "warning": "경고", "critical": "위험"}
SEVERITY_BG = {"normal": "#d4f4dd", "warning": "#fff3cd", "critical": "#f8d7da"}

CATEGORIES = {
    "전체": None,
    "01_감전_LOTO": "01_감전_LOTO",
    "02_협착_끼임": "02_협착_끼임",
    "03_낙상_응급처치": "03_낙상_응급처치",
    "04_예지보전": "04_예지보전",
    "05_위험성평가_비상": "05_위험성평가_비상",
}

# ===================================================================
# Mock 이벤트 데이터 (stage2_event.json 합의 전 임시)
#  - 향후 팀협업/샘플데이터/scenario_XX/stage2_event.json 파일로 대체 예정
# ===================================================================
MOCK_EVENTS = {
    "fall_detected": {
        "schema_version": "1.0",
        "timestamp": "2026-06-05T12:01:05.456Z",
        "event_id": "evt_20260605_120105_C001",
        "event_type": "fall_detected",
        "zone_id": "C",
        "severity": "critical",
        "confidence": 0.92,
        "details": {
            "description": "작업자 낙상 확정 (자세 붕괴 + 속도 임계 초과)",
            "worker_pose": {"posture": "collapsed", "velocity_m_s": 0.05, "height_m": 0.3},
            "anomaly_score": 0.87,
        },
        "event_log": [
            {"time": "12:01:03", "msg": "Zone C - Body posture collapse detected"},
            {"time": "12:01:04", "msg": "Zone C - Velocity drop below threshold"},
            {"time": "12:01:05", "msg": "Zone C - Fall event confirmed"},
        ],
    },
    "electric_shock_risk": {
        "schema_version": "1.0",
        "timestamp": "2026-06-05T12:05:12.123Z",
        "event_id": "evt_20260605_120512_A001",
        "event_type": "electric_shock_risk",
        "zone_id": "A",
        "severity": "critical",
        "confidence": 0.88,
        "details": {
            "description": "고압 설비 접근 거리 임계 초과",
            "proximity_m": 0.15,
            "equipment_voltage_kv": 22.9,
            "approach_speed_m_s": 1.2,
        },
        "event_log": [
            {"time": "12:05:08", "msg": "Zone A - Worker approaching high-voltage panel"},
            {"time": "12:05:10", "msg": "Zone A - Proximity < 30cm warning"},
            {"time": "12:05:12", "msg": "Zone A - Critical: <15cm to 22.9kV equipment"},
        ],
    },
    "pinching": {
        "schema_version": "1.0",
        "timestamp": "2026-06-05T12:10:45.789Z",
        "event_id": "evt_20260605_121045_B001",
        "event_type": "pinching",
        "zone_id": "B",
        "severity": "critical",
        "confidence": 0.85,
        "details": {
            "description": "회전기계 5cm 이내 신체 접근",
            "equipment_id": "rotor_03",
            "body_part_proximity_m": 0.05,
            "rotation_rpm": 1800,
        },
        "event_log": [
            {"time": "12:10:42", "msg": "Zone B - Body part near rotor_03"},
            {"time": "12:10:44", "msg": "Zone B - Proximity drop to 8cm"},
            {"time": "12:10:45", "msg": "Zone B - Pinching risk confirmed (5cm @ 1800RPM)"},
        ],
    },
    "vibration_anomaly": {
        "schema_version": "1.0",
        "timestamp": "2026-06-05T12:15:30.234Z",
        "event_id": "evt_20260605_121530_C002",
        "event_type": "vibration_anomaly",
        "zone_id": "C",
        "severity": "warning",
        "confidence": 0.79,
        "details": {
            "description": "베어링 결함 의심 (RMS 진동 임계 초과)",
            "equipment_id": "motor_02",
            "rms_vibration_um_s": 1.8,
            "threshold_um_s": 1.0,
            "frequency_anomaly_hz": 47.5,
            "bearing_fault_suspected": True,
        },
        "event_log": [
            {"time": "12:15:20", "msg": "Zone C - motor_02 RMS rising (0.9 → 1.4 μm/s)"},
            {"time": "12:15:25", "msg": "Zone C - 47.5Hz peak detected"},
            {"time": "12:15:30", "msg": "Zone C - Bearing fault suspected (RMS=1.8 μm/s)"},
        ],
    },
}

# ===================================================================
# Session State 초기화
# ===================================================================
if "current_event" not in st.session_state:
    st.session_state.current_event = None
if "facility_status" not in st.session_state:
    st.session_state.facility_status = {"A": "normal", "B": "normal", "C": "normal"}
if "auto_run_rag" not in st.session_state:
    st.session_state.auto_run_rag = False


def load_scenario(event_type: str, facility: dict):
    """시나리오 트리거 버튼 핸들러"""
    st.session_state.current_event = MOCK_EVENTS[event_type]
    st.session_state.facility_status = facility
    st.session_state.auto_run_rag = True


def reset_state():
    st.session_state.current_event = None
    st.session_state.facility_status = {"A": "normal", "B": "normal", "C": "normal"}
    st.session_state.auto_run_rag = False


# ===================================================================
# 사이드바: 검색 설정 + 시나리오 트리거
# ===================================================================
with st.sidebar:
    st.header("🔍 검색 설정")

    # 이벤트 발생 시 카테고리 자동 선택
    default_idx = 0
    if st.session_state.current_event:
        evt_type = st.session_state.current_event["event_type"]
        auto_cat = EVENT_TYPE_TO_CATEGORY.get(evt_type)
        cat_list = list(CATEGORIES.keys())
        if auto_cat in cat_list:
            default_idx = cat_list.index(auto_cat)

    selected_category_label = st.selectbox(
        "검색 카테고리",
        list(CATEGORIES.keys()),
        index=default_idx,
        help="이벤트 발생 시 자동 선택됩니다. 수동 변경도 가능합니다.",
    )
    selected_category = CATEGORIES[selected_category_label]

    top_k = st.slider("검색 결과 수 (k)", 1, 5, 3)

    st.divider()
    st.subheader("🎬 시나리오 트리거")
    st.caption("Mock stage2_event.json 로드 → 6개 영역 자동 갱신")

    st.button(
        "▶ 1. 낙상 (Zone C)",
        use_container_width=True,
        on_click=load_scenario,
        args=("fall_detected", {"A": "normal", "B": "normal", "C": "critical"}),
    )
    st.button(
        "▶ 2. 감전 위험 (Zone A)",
        use_container_width=True,
        on_click=load_scenario,
        args=("electric_shock_risk", {"A": "critical", "B": "normal", "C": "normal"}),
    )
    st.button(
        "▶ 3. 협착 (Zone B)",
        use_container_width=True,
        on_click=load_scenario,
        args=("pinching", {"A": "normal", "B": "critical", "C": "normal"}),
    )
    st.button(
        "▶ 4. 진동 이상 (Zone C)",
        use_container_width=True,
        on_click=load_scenario,
        args=("vibration_anomaly", {"A": "normal", "B": "normal", "C": "warning"}),
    )

    st.divider()
    st.button("🔄 초기화 (정상 상태)", use_container_width=True, on_click=reset_state)

    st.divider()
    st.caption(
        "📌 개발: Ollama + Qwen2.5 + BGE-M3\n"
        "📌 추후 젯슨 이식 시 LLM만 Llama-3로 교체"
    )

# ===================================================================
# 헤더: 시스템명 + 상태 배지 + 실시간 시계
# ===================================================================
overall_status = "normal"
for s in st.session_state.facility_status.values():
    if s == "critical":
        overall_status = "critical"
        break
    elif s == "warning" and overall_status != "critical":
        overall_status = "warning"

hcol1, hcol2, hcol3 = st.columns([5, 2, 2])
with hcol1:
    st.title("🛡️ Radar-Guard 관제 시스템")
    st.caption("⚡ 완전 오프라인 RAG (Ollama + BGE-M3 + Qwen2.5 + pgvector)")
with hcol2:
    st.markdown("##### 시스템 상태")
    st.markdown(
        f"<h3 style='margin:0'>{SEVERITY_EMOJI[overall_status]} "
        f"[{SEVERITY_LABEL[overall_status]}]</h3>",
        unsafe_allow_html=True,
    )
with hcol3:
    st.markdown("##### 현재 시각")
    st.markdown(
        f"<h3 style='margin:0'>🕐 {datetime.now().strftime('%H:%M:%S')}</h3>",
        unsafe_allow_html=True,
    )

st.divider()

# ===================================================================
# 상단: [좌] 3D Point Cloud | [우] 진동 분석 + Event Log
# ===================================================================
left_col, right_col = st.columns([3, 2])

# --- 좌측: 3D Point Cloud --------------------------------------------------
with left_col:
    st.subheader("📡 3D Point Cloud (mmWave)")

    np.random.seed(42)
    n_bg = 200
    x = np.random.uniform(-2, 2, n_bg)
    y = np.random.uniform(-2, 2, n_bg)
    z = np.random.uniform(0, 2.5, n_bg)
    intensity = np.random.uniform(0, 0.5, n_bg)

    # 이벤트 발생 시 해당 Zone에 클러스터 추가
    if st.session_state.current_event:
        zone = st.session_state.current_event["zone_id"]
        evt_type = st.session_state.current_event["event_type"]
        zone_x_map = {"A": -1.5, "B": 0.0, "C": 1.5}
        cx = zone_x_map.get(zone, 0)

        # 낙상이면 낮은 높이(z<0.5), 그 외엔 작업자 정상 높이
        n_cluster = 60
        cluster_x = np.random.normal(cx, 0.25, n_cluster)
        cluster_y = np.random.normal(0, 0.25, n_cluster)
        if evt_type == "fall_detected":
            cluster_z = np.random.uniform(0, 0.5, n_cluster)
        else:
            cluster_z = np.random.uniform(0.5, 1.7, n_cluster)
        cluster_intensity = np.ones(n_cluster)

        x = np.concatenate([x, cluster_x])
        y = np.concatenate([y, cluster_y])
        z = np.concatenate([z, cluster_z])
        intensity = np.concatenate([intensity, cluster_intensity])

    fig_3d = go.Figure(
        data=[
            go.Scatter3d(
                x=x, y=y, z=z,
                mode="markers",
                marker=dict(
                    size=3,
                    color=intensity,
                    colorscale="Viridis",
                    opacity=0.75,
                    showscale=True,
                    colorbar=dict(title="Intensity", thickness=12),
                ),
            )
        ]
    )
    fig_3d.update_layout(
        scene=dict(
            xaxis_title="X (m)",
            yaxis_title="Y (m)",
            zaxis_title="Z (m)",
            aspectmode="cube",
        ),
        height=440,
        margin=dict(l=0, r=0, t=0, b=0),
    )
    st.plotly_chart(fig_3d, use_container_width=True)

# --- 우측 상단: 진동 분석 --------------------------------------------------
with right_col:
    st.subheader("📊 진동 분석")

    vib_value, vib_delta = "0.02 μm/s", "-0.01"
    if (
        st.session_state.current_event
        and st.session_state.current_event["event_type"] == "vibration_anomaly"
    ):
        vib_value, vib_delta = "1.80 μm/s", "+1.78"
    st.metric("설비 진동 (RMS)", vib_value, delta=vib_delta, delta_color="inverse")

    freq = np.linspace(0, 200, 200)
    normal_spectrum = 0.05 * np.exp(-((freq - 60) ** 2) / 200) + 0.02
    current_spectrum = normal_spectrum.copy()
    if (
        st.session_state.current_event
        and st.session_state.current_event["event_type"] == "vibration_anomaly"
    ):
        current_spectrum = current_spectrum + 0.18 * np.exp(-((freq - 47.5) ** 2) / 30)

    fig_vib = go.Figure()
    fig_vib.add_trace(
        go.Scatter(
            x=freq, y=normal_spectrum,
            name="정상 baseline",
            line=dict(color="green", dash="dash"),
        )
    )
    fig_vib.add_trace(
        go.Scatter(x=freq, y=current_spectrum, name="현재", line=dict(color="red"))
    )
    fig_vib.update_layout(
        xaxis_title="주파수 (Hz)",
        yaxis_title="진폭",
        height=180,
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_vib, use_container_width=True)

    # --- 우측 중단: Event Log ----------------------------------------------
    st.subheader("📋 Event Log")
    if st.session_state.current_event:
        for log in st.session_state.current_event["event_log"]:
            severity = st.session_state.current_event["severity"]
            icon = "⚠️" if severity == "critical" else "📌"
            st.markdown(f"`[{log['time']}]` {icon} {log['msg']}")
    else:
        st.info("이벤트 대기 중... (사이드바에서 시나리오 트리거)")

st.divider()

# ===================================================================
# 중단: Facility Map (Zone A/B/C — 작업자/전력 흡수, 옵션 B)
# ===================================================================
st.subheader("🗺️ Facility Map")

zone_info = {
    "A": {"name": "Zone A (변전실)", "worker": "정상", "power": "정상"},
    "B": {"name": "Zone B (가공실)", "worker": "정상", "power": "정상"},
    "C": {"name": "Zone C (조립실)", "worker": "정상", "power": "정상"},
}

# 이벤트 반영: 작업자/전력 상태 갱신
if st.session_state.current_event:
    evt = st.session_state.current_event
    zone = evt["zone_id"]
    evt_type = evt["event_type"]
    if evt_type == "fall_detected":
        zone_info[zone]["worker"] = "🔴 낙상"
        zone_info[zone]["power"] = "🔴 차단"
    elif evt_type == "electric_shock_risk":
        zone_info[zone]["worker"] = "🔴 감전 위험"
        zone_info[zone]["power"] = "🔴 차단"
    elif evt_type == "pinching":
        zone_info[zone]["worker"] = "🔴 협착"
        zone_info[zone]["power"] = "🔴 차단"
    elif evt_type == "vibration_anomaly":
        zone_info[zone]["worker"] = "정상"
        zone_info[zone]["power"] = "🟡 모니터링 중"

zone_cols = st.columns(3)
for i, (zid, info) in enumerate(zone_info.items()):
    with zone_cols[i]:
        status = st.session_state.facility_status[zid]
        emoji = SEVERITY_EMOJI[status]
        label = SEVERITY_LABEL[status]
        bg = SEVERITY_BG[status]

        st.markdown(
            f"""
            <div style="background-color:{bg};
                        padding:16px;
                        border-radius:8px;
                        border-left:6px solid #555;
                        min-height:120px;">
              <h4 style="margin:0 0 8px 0;">{emoji} {info['name']}</h4>
              <p style="margin:2px 0;"><b>상태:</b> {label}</p>
              <p style="margin:2px 0;"><b>작업자:</b> {info['worker']}</p>
              <p style="margin:2px 0;"><b>전력:</b> {info['power']}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.divider()

# ===================================================================
# 하단: 🔴 RAG 조치 가이드 (week4 코드 통합)
# ===================================================================
st.subheader("🔴 이상 감지 시 RAG 기반 조치 가이드")

# 상황 텍스트 자동 채움
default_situation = "작업자 낙상 감지 (Zone B)"
if st.session_state.current_event:
    evt = st.session_state.current_event
    korean = EVENT_TYPE_KOREAN.get(evt["event_type"], evt["event_type"])
    default_situation = f"{korean} (Zone {evt['zone_id']})"

situation = st.text_input(
    "감지된 상황 입력 (이벤트 발생 시 자동 입력, 수정 가능)",
    default_situation,
)

# 자동 트리거 또는 수동 클릭
manual_trigger = st.button("🔍 조치 가이드 생성", type="primary")
trigger = manual_trigger or st.session_state.auto_run_rag

# 자동 실행은 한 번만
if st.session_state.auto_run_rag:
    st.session_state.auto_run_rag = False

if trigger:
    # DB/LLM 연결 확인
    try:
        vectorstore = get_vectorstore()
        llm = get_llm()
    except Exception as e:
        st.error(
            f"❌ DB/LLM 연결 실패: {e}\n\n"
            "PowerShell에서 다음을 확인하세요:\n"
            "  1. docker start radar-guard-db\n"
            "  2. Ollama가 시스템 트레이에서 실행 중"
        )
        st.stop()

    with st.spinner("매뉴얼 검색 중... (CPU 추론, 30초~2분 소요 예상)"):
        # 1. DB에서 관련 매뉴얼 검색
        if selected_category:
            docs = vectorstore.similarity_search(
                situation, k=top_k, filter={"category": selected_category}
            )
        else:
            docs = vectorstore.similarity_search(situation, k=top_k)

        if not docs:
            st.warning(
                f"⚠️ '{selected_category_label}' 카테고리에서 관련 매뉴얼을 찾지 못했습니다. "
                "다른 카테고리나 '전체'로 변경해보세요."
            )
            st.stop()

        # 2. 검색된 청크를 LLM에게 보낼 컨텍스트로 합치기
        context = "\n\n---\n\n".join([d.page_content for d in docs])

        # 3. 프롬프트 (week4와 동일)
        prompt = PromptTemplate.from_template(
            "당신은 산업 안전 전문가입니다. 다음 안전 매뉴얼을 참고해서 "
            "아래 상황의 조치 가이드를 **반드시 한국어로** 단계별(1, 2, 3...)로 알려주세요. "
            "한자 사용 금지, 매뉴얼에 없는 내용은 추측하지 마세요.\n\n"
            "안전 매뉴얼:\n{context}\n\n"
            "감지된 상황: {situation}\n\n"
            "조치 가이드:"
        )

        # 4. LCEL 체인 실행
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": context, "situation": situation})

    st.success("✅ 조치 가이드 생성 완료!")
    st.markdown(response)

    # 출처 표시 (week4와 동일)
    st.divider()
    st.subheader("📚 참고한 매뉴얼 (출처)")
    for i, doc in enumerate(docs, 1):
        cat = doc.metadata.get("category", "미분류")
        src = doc.metadata.get("source_file", "알 수 없음")
        page = doc.metadata.get("page", "?")
        page_display = page + 1 if isinstance(page, int) else page

        with st.expander(f"📄 {i}. [{cat}] {src} (p.{page_display})"):
            st.write(doc.page_content)
