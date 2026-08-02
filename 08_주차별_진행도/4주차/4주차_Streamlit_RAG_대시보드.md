# ✅ 4주차 — Streamlit 통합 대시보드 구현 (센서 모니터링 + RAG 가이드)

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Radar-Guard |
| 담당자 | 홍유빈 |
| 담당 역할 | 시스템 통합 / UI / RAG |
| 주차 | 4주차 |

---

## 학습 목표
- [ ] Streamlit 기본 구조 파악 및 설치 (`st.title`, `st.sidebar`, `st.columns` 등 레이아웃 컴포넌트)
- [ ] 센서 상태(정상/경고/위험) 실시간 모니터링 UI 프로토타입 구현
- [ ] 3주차에서 구축한 pgvector DB와 연동하여 RAG 기반 조치 가이드 출력 기능 구현
- [ ] 전체 End-to-End 흐름 검증: 이상 감지 입력 → 벡터 검색 → LLM 가이드 생성 → 화면 출력

---

## 핵심 개념 정리

| 개념 | 설명 |
|------|------|
| Streamlit | 파이썬 코드만으로 웹 대시보드를 빠르게 만들 수 있는 프레임워크 |
| RAG (Retrieval-Augmented Generation) | 검색(Retrieval) + 생성(Generation)의 결합. LLM이 벡터 DB에서 관련 문서를 검색한 뒤, 그 내용을 바탕으로 답변 생성. 할루시네이션을 줄이고 도메인 특화 응답 가능 |
| RetrievalQA Chain | LangChain에서 RAG를 구현하는 대표적인 체인. 질문 → 벡터 검색 → LLM 응답 흐름을 자동화 |
| st.session_state | Streamlit에서 사용자 인터랙션 간 상태를 유지하기 위한 딕셔너리 |

---

## 대시보드 구성 계획

```
┌─────────────────────────────────────────────────┐
│  🛡️ Radar-Guard 관제 대시보드                    │
├──────────────┬──────────────────────────────────┤
│  [사이드바]   │  [메인 영역]                      │
│  - 구역 선택  │  ┌─────────┬─────────┬─────────┐ │
│  - 센서 상태  │  │ 작업자  │ 진동    │ 전력    │ │
│  - 경고 로그  │  │ 상태    │ 분석    │ 상태    │ │
│              │  └─────────┴─────────┴─────────┘ │
│              │  ┌───────────────────────────────┐│
│              │  │  🔴 이상 감지: 낙상 의심       ││
│              │  │  RAG 기반 조치 가이드:         ││
│              │  │  1. 즉시 전력 차단             ││
│              │  │  2. 구조대 출동 요청           ││
│              │  │  3. ...                       ││
│              │  └───────────────────────────────┘│
└──────────────┴──────────────────────────────────┘
```

---

## 실습 예정 코드 스니펫

```python
import streamlit as st
from langchain.chains import RetrievalQA
from langchain_openai import ChatOpenAI
# (3주차에서 만든 vectorstore 재사용)

st.set_page_config(page_title="Radar-Guard 관제 대시보드", layout="wide")
st.title("🛡️ Radar-Guard 관제 대시보드")

# 센서 상태 카드
col1, col2, col3 = st.columns(3)
col1.metric("작업자 상태", "정상", delta="낙상 없음")
col2.metric("설비 진동", "0.02mm", delta="-0.01mm")
col3.metric("전력 상태", "정상", delta="차단 없음")

# RAG 조치 가이드
st.subheader("🔴 이상 감지 시 RAG 기반 조치 가이드")
situation = st.text_input("감지된 상황 입력", "작업자 낙상 감지 (Zone B)")

if st.button("조치 가이드 생성"):
    qa_chain = RetrievalQA.from_chain_type(
        llm=ChatOpenAI(model="gpt-4o-mini"),
        retriever=vectorstore.as_retriever(search_kwargs={"k": 3})
    )
    with st.spinner("매뉴얼 검색 중..."):
        response = qa_chain.invoke(situation)
    st.success(response["result"])
```

---

## 참고 자료
- Streamlit 공식 문서: https://docs.streamlit.io/
- LangChain 공식 문서 — Q&A with RAG: https://python.langchain.com/docs/tutorials/rag/

---

## 4주차 완료 목표

> **"이상 감지 입력 → 벡터 DB 검색 → LLM 조치 가이드 생성 → 대시보드 출력"** 전체 흐름이 동작하는 End-to-End 프로토타입 완성

```
1주차: Docker + PostgreSQL + pgvector 환경 세팅
    ↓
2주차: LangChain 기초 (Prompt, Chain, LCEL)
    ↓
3주차: SOP 문서 청킹 → 임베딩 → pgvector 적재 → 유사도 검색
    ↓
4주차: Streamlit 대시보드 + RAG 연동 → End-to-End 완성 ✅
```
