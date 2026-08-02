import glob
import os
import time
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 1. PDF 로드 (하위 폴더까지 재귀적으로)
pdf_files = glob.glob(r"C:\radar-guard\**\*.pdf", recursive=True)
print(f"발견된 PDF: {len(pdf_files)}개")

all_documents = []
for pdf in pdf_files:
    category = os.path.basename(os.path.dirname(pdf))
    loader = PyPDFLoader(pdf)
    docs = loader.load()
    for doc in docs:
        doc.metadata["category"] = category
        doc.metadata["source_file"] = os.path.basename(pdf)
    all_documents.extend(docs)

print(f"총 페이지 수: {len(all_documents)}페이지")

# 2. 청킹
splitter = RecursiveCharacterTextSplitter(
    chunk_size=600,
    chunk_overlap=80
)
chunks = splitter.split_documents(all_documents)
print(f"총 청크 수: {len(chunks)}개")

# 3. NUL(\x00) 문자 제거 - PostgreSQL 거부 방지
for chunk in chunks:
    chunk.page_content = chunk.page_content.replace("\x00", "")
print("✅ NUL 문자 정리 완료")

# 4. 벡터 DB에 적재 (BGE-M3 임베딩 사용 - 오프라인)
print("\n🔄 임베딩 생성 + DB 적재 시작 (5~15분 예상, 끄지 마세요)...")
start_time = time.time()

embeddings = OllamaEmbeddings(model="bge-m3")
CONNECTION_STRING = "postgresql://admin:1234@localhost:5432/radar_guard"

vectorstore = PGVector.from_documents(
    documents=chunks,
    embedding=embeddings,
    connection_string=CONNECTION_STRING,
    collection_name="safety_manual",
    pre_delete_collection=True  # 기존 OpenAI 임베딩 자동 삭제 후 BGE-M3로 재구축
)

elapsed = time.time() - start_time
print(f"✅ 벡터 DB 적재 완료! (소요 시간: {elapsed:.1f}초)")

# 5. 유사도 검색 테스트
print("\n🔍 유사도 검색 테스트")
query = "감전사고 발생 시 응급조치"
results = vectorstore.similarity_search(query, k=3)
print(f"질문: {query}")
print("가장 관련있는 매뉴얼:")
for i, doc in enumerate(results):
    cat = doc.metadata.get("category", "미분류")
    src = doc.metadata.get("source_file", "?")
    print(f"  {i+1}. [{cat} | {src}]")
    print(f"     {doc.page_content[:100]}...")
