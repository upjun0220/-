import glob
import os
import time
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores import PGVector
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 1. PDF 로드
pdf_files = glob.glob("/home/project/radar-guard/**/*.pdf", recursive=True)
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

# 3. NUL(\x00) 문자 제거
for chunk in chunks:
    chunk.page_content = chunk.page_content.replace("\x00", "")
print("✅ NUL 문자 정리 완료")

# 4. 벡터 DB 적재 (nomic-embed-text)
print("\n🔄 임베딩 생성 + DB 적재 시작 (10~20분 예상, 끄지 마세요)...")
start_time = time.time()

embeddings = OllamaEmbeddings(model="nomic-embed-text")
CONNECTION_STRING = "postgresql://postgres:password@localhost:5432/radar_guard"

vectorstore = PGVector.from_documents(
    documents=chunks,
    embedding=embeddings,
    connection_string=CONNECTION_STRING,
    collection_name="safety_manual",
    pre_delete_collection=True
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
