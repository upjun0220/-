import streamlit as st
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ===================================================================
# 페이지 설정
# ===================================================================
st.set_page_config(page_title="Radar-Guard 관제 대시보드", layout="wide")
st.title("🛡️ Radar-Guard 관제 대시보드")
st.caption("⚡ 완전 오프라인 RAG (Ollama + BGE-M3 + Qwen2.5 + pgvector)")

# ===================================================================
# 1) 캐싱: DB/LLM 연결을 한 번만 만들고 재사용
# ===================================================================
CONNECTION_STRING = "postgresql://admin:1234@localhost:5432/radar_guard"


@st.cache_resource
def get_vectorstore():
    """벡터 DB 연결을 캐싱 - 앱 실행 동안 1번만 생성"""
    embeddings = OllamaEmbeddings(model="bge-m3")
    return PGVector(
        connection_string=CONNECTION_STRING,
        embedding_function=embeddings,
        collection_name="safety_manual"
    )


@st.cache_resource
def get_llm():
    """로컬 LLM 연결도 캐싱"""
    return ChatOllama(
        model="qwen2.5:3b-instruct-q4_K_M",
        temperature=0
    )


vectorstore = get_vectorstore()
llm = get_llm()

# ===================================================================
# 2) 사이드바: 카테고리 필터
# ===================================================================
st.sidebar.header("🔍 검색 설정")

CATEGORIES = {
    "전체": None,
    "01_감전_LOTO": "01_감전_LOTO",
    "02_협착_끼임": "02_협착_끼임",
    "03_낙상_응급처치": "03_낙상_응급처치",
    "04_예지보전": "04_예지보전",
    "05_위험성평가_비상": "05_위험성평가_비상",
}

selected_category_label = st.sidebar.selectbox(
    "검색 카테고리",
    list(CATEGORIES.keys()),
    help="특정 카테고리로 좁혀서 검색하면 RAG 정확도가 올라갑니다"
)
selected_category = CATEGORIES[selected_category_label]

top_k = st.sidebar.slider("검색 결과 수 (k)", min_value=1, max_value=5, value=3)

st.sidebar.divider()
st.sidebar.caption("📌 시연 시나리오 예시")
st.sidebar.code(
    "작업자 낙상 감지 (Zone B)\n"
    "변전소 작업자 감전 의심\n"
    "회전기계 끼임 사고 발생\n"
    "설비 진동 이상 - 베어링 마모",
    language=None
)

# ===================================================================
# 3) 메인: 센서 상태 카드
# ===================================================================
st.subheader("📡 센서 상태")
col1, col2, col3 = st.columns(3)
col1.metric("작업자 상태", "정상", delta="낙상 없음")
col2.metric("설비 진동", "0.02mm", delta="-0.01mm")
col3.metric("전력 상태", "정상", delta="차단 없음")

st.divider()

# ===================================================================
# 4) RAG 조치 가이드
# ===================================================================
st.subheader("🔴 이상 감지 시 RAG 기반 조치 가이드")

situation = st.text_input(
    "감지된 상황 입력",
    "작업자 낙상 감지 (Zone B)"
)

if st.button("🔍 조치 가이드 생성", type="primary"):
    with st.spinner("매뉴얼 검색 중... (CPU 추론, 30초~2분 소요 예상)"):

        # 1. DB에서 관련 매뉴얼 검색 (카테고리 필터 적용)
        if selected_category:
            docs = vectorstore.similarity_search(
                situation,
                k=top_k,
                filter={"category": selected_category}
            )
        else:
            docs = vectorstore.similarity_search(situation, k=top_k)

        # 검색 결과 없을 때 안내
        if not docs:
            st.warning(
                f"⚠️ '{selected_category_label}' 카테고리에서 관련 매뉴얼을 찾지 못했습니다. "
                "다른 카테고리나 '전체'로 변경해보세요."
            )
            st.stop()

        # 2. 검색된 청크를 LLM에게 보낼 컨텍스트로 합치기
        context = "\n\n---\n\n".join([doc.page_content for doc in docs])

        # 3. 프롬프트 구성
        prompt = PromptTemplate.from_template(
            "당신은 산업 안전 전문가입니다. 다음 안전 매뉴얼을 참고해서 "
            "아래 상황의 조치 가이드를 **반드시 한국어로** 단계별(1, 2, 3...)로 알려주세요. "
            "한자 사용 금지, 매뉴얼에 없는 내용은 추측하지 마세요.\n\n"
            "안전 매뉴얼:\n{context}\n\n"
            "감지된 상황: {situation}\n\n"
            "조치 가이드:"
        )

        # 4. LCEL 체인 구성 및 실행
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({
            "context": context,
            "situation": situation
        })

    st.success("✅ 조치 가이드 생성 완료!")
    st.markdown(response)

    # ===================================================================
    # 5) 출처 표시 강화
    # ===================================================================
    st.divider()
    st.subheader("📚 참고한 매뉴얼 (출처)")

    for i, doc in enumerate(docs, 1):
        cat = doc.metadata.get("category", "미분류")
        src = doc.metadata.get("source_file", "알 수 없음")
        page = doc.metadata.get("page", "?")

        page_display = page + 1 if isinstance(page, int) else page

        with st.expander(f"📄 {i}. [{cat}] {src} (p.{page_display})"):
            st.write(doc.page_content)
