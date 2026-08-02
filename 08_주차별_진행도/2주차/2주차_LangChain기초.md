# ✅ 2주차 — OpenAI API 키 발급 & LangChain 기초 (Prompt / Chain)

| 항목 | 내용 |
|------|------|
| 프로젝트명 | Radar-Guard |
| 담당자 | 홍유빈 |
| 담당 역할 | 시스템 통합 / UI / RAG |
| 주차 | 2주차 |

---

## 학습 목표
- [ ] OpenAI 플랫폼에서 API 키 발급 및 `.env` 파일로 환경 변수 관리
- [ ] LangChain 설치 및 기본 구조 이해 (`langchain`, `langchain-openai` 패키지)
- [ ] `PromptTemplate` 사용법 실습 — 동적으로 프롬프트 생성하기
- [ ] `LLMChain` 구성 실습 — 프롬프트 → 모델 → 출력까지 체인으로 연결
- [ ] LangChain의 LCEL(LangChain Expression Language) 기본 문법 파악 (`|` 파이프 연산자)

---

## 핵심 개념 정리

| 개념 | 설명 |
|------|------|
| LangChain | LLM 기반 애플리케이션을 쉽게 개발할 수 있도록 도와주는 파이썬 프레임워크 |
| PromptTemplate | 변수 자리를 포함한 프롬프트 틀. 입력값에 따라 동적으로 프롬프트 생성 |
| Chain | 프롬프트 → LLM → 출력 파서 등 여러 컴포넌트를 순서대로 연결한 파이프라인 |
| LCEL | LangChain의 선언형 체인 표현 방식. `prompt | model | output_parser` 형태로 연결 |

---

## 실습 예정 코드 스니펫

```python
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate

# 프롬프트 템플릿 정의
prompt = PromptTemplate.from_template(
    "다음 산업 재해 상황에 맞는 초동 조치를 알려줘:\n\n상황: {situation}"
)

# 모델 초기화
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# LCEL 방식으로 체인 구성
chain = prompt | llm

# 실행
response = chain.invoke({"situation": "작업자가 고압 설비 근처에서 낙상 감지됨"})
print(response.content)
```

---

## 참고 자료
- 유튜브 "테디노트 랭체인(LangChain) 튜토리얼"
- LangChain 공식 문서: https://python.langchain.com/docs/introduction/

---

## 이전 / 다음 주차
> **1주차 완료**: Docker + PostgreSQL + pgvector 환경 세팅
> **3주차 예고**: 안전 매뉴얼 청킹 → 임베딩 → pgvector 적재 실습
