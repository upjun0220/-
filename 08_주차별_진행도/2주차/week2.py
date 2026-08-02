# 필요한 라이브러리 불러오기
from langchain_ollama import ChatOllama
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 프롬프트 템플릿 정의
prompt = PromptTemplate.from_template(
    "다음 산업 재해 상황에 맞는 초동 조치를 한국어로 단계별(1, 2, 3...)로 알려줘.\n\n상황: {situation}"
)

# 로컬 LLM 연결 (Ollama 통해 Qwen2.5 호출)
llm = ChatOllama(
    model="qwen2.5:3b-instruct-q4_K_M",
    temperature=0
)

# LCEL 체인 연결 (프롬프트 → LLM → 텍스트 파싱)
chain = prompt | llm | StrOutputParser()

# 실행!
response = chain.invoke({"situation": "작업자가 고압 설비 근처에서 낙상 감지됨"})
print(response)
