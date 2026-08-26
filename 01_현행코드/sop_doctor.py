r"""sop_doctor.py — SOP 벡터DB 진단. 무엇이 실제로 들어 있는지 읽어서 보여준다.

  실행: [내 PC PowerShell]   python 01_현행코드\sop_doctor.py
  의존성: pip install psycopg2-binary        (langchain 불필요 — SQL 로 직접 본다)

═══ 왜 이 파일이 필요한가 ═══
  2026-07-31 코드를 훑어보니 SOP 검색 경로에 불일치가 3개 있었다.

  1) 임베딩 모델이 적재와 검색에서 다르다
       적재 embed_jetson.py        nomic-embed-text  (768차원)
       검색 week5.py               bge-m3            (1024차원)
       검색 radar_live_full.py     nomic-embed-text
     → 차원이 다르면 유사도 검색이 에러거나 무의미한 결과를 낸다.

  2) 카테고리 값이 다르다  ← 이게 치명적
       DB(적재)  PDF 상위 폴더명.  week5 목록은 한글:  03_낙상_응급처치
       검색 필터 로마자:                              03_naksan_eunggeupcheo
     → filter={'category': ...} 가 영원히 0건. 코드는 예외를 삼키므로 조용히 실패한다.
       README 7/27 의 "LLM 생성 문장 0개" 의 실체가 이것일 가능성이 높다.

  3) 청킹 파라미터가 문서화돼 있지 않다 (embed_jetson.py: 600자 / 80 겹침)

  추측으로 고치면 또 어긋난다. 그래서 DB 를 직접 읽는다.
"""
import os
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CONN = os.environ.get('RADAR_PG',
                      'postgresql://postgres:password@localhost:5432/radar_guard')
COLLECTION = 'safety_manual'

# 현행 코드가 검색에 쓰는 값을 radar_common 에서 직접 가져온다.
#   여기에 다시 적으면 또 어긋난다 — 그게 애초의 버그였다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from radar_common import EVENT_CATEGORY, SOP_CATEGORIES
    _flat = []
    for _v in EVENT_CATEGORY.values():          # 값이 문자열 / 튜플 / None 세 형태
        if isinstance(_v, (list, tuple)):
            _flat += list(_v)
        elif _v:
            _flat.append(_v)
    EXPECTED_CATEGORIES = sorted(set(_flat))
except Exception:
    EXPECTED_CATEGORIES, SOP_CATEGORIES = [], []

EXPECTED_EMBED = 'bge-m3'
EXPECTED_DIM = 1024          # bge-m3 = 1024 / nomic-embed-text = 768
OLLAMA = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')

# 실검색 테스트 질의 (console_ui.SOP_QUERY 와 같은 성격)
TEST_QUERIES = [
    ('fall_detected', '추락 넘어짐 재해 발생 시 응급처치와 재해자 이송 방법'),
    ('electric_shock_risk', '감전 사고 발생 시 응급조치 및 전원 차단 잠금 표지'),
    ('pinching', '회전기계 끼임 협착 재해 발생 시 구조 및 정지 절차'),
    ('stationary_anomaly', '작업자 무응답 감전 협착 사고 발견 시 초동 대응'),
    # [8/25] 코덱스가 프로젝트 자체 SOP(설비 전기이상 대응)를 01_감전_예방 에 색인했다.
    #   이 두 이벤트가 실제로 그 문서를 뽑는지 확인해야 한다.
    ('overcurrent', '과전류 전기 설비 이상 시 차단 및 점검 절차'),
    ('leakage_current', '누설전류 전기 설비 이상 시 차단 및 절연 점검 절차'),
]


def ok(t, d=''):
    print(f'  ✓ {t}' + (f'   {d}' if d else ''))


def bad(t, d=''):
    print(f'  ✗ {t}' + (f'   {d}' if d else ''))


def warn(t, d=''):
    print(f'  ! {t}' + (f'   {d}' if d else ''))


print('=' * 72)
print('  SOP 벡터DB 진단')
print('=' * 72)
print(f'  접속: {CONN.split("@")[-1]}   컬렉션: {COLLECTION}')

try:
    import psycopg2
except ImportError:
    print('\npsycopg2 가 없습니다:  pip install psycopg2-binary')
    sys.exit(1)

def from_docker(container='radar-guard-db'):
    """컨테이너 환경변수에서 실제 계정 정보를 읽어 접속 문자열을 만든다.

    비밀번호는 컨테이너 생성 시 POSTGRES_PASSWORD 로 박힌다. 코드에 하드코딩한
    'password' 와 다를 수 있으니 추측하지 말고 실물에서 읽는다.
    """
    import subprocess
    try:
        out = subprocess.run(
            ['docker', 'inspect', container,
             '--format', '{{range .Config.Env}}{{println .}}{{end}}'],
            capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return None, out.stderr.strip()[:120]
        env = dict(l.split('=', 1) for l in out.stdout.splitlines() if '=' in l)
        u = env.get('POSTGRES_USER', 'postgres')
        pw = env.get('POSTGRES_PASSWORD', '')
        db = env.get('POSTGRES_DB', u)
        if not pw:
            return None, 'POSTGRES_PASSWORD 가 컨테이너 env 에 없음'
        return f'postgresql://{u}:{pw}@localhost:5432/{db}', None
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'


cn = None
try:
    cn = psycopg2.connect(CONN)
except Exception as e:
    first = str(e).strip().splitlines()[0]
    print(f'\n! 기본 접속 실패: {first}')
    print('  → 컨테이너에서 실제 계정 정보를 읽어 재시도합니다…')
    alt, why = from_docker()
    if alt:
        shown = alt.split('://')[1].split(':')[0] + ':***@' + alt.split('@')[1]
        print(f'    docker inspect 결과: {shown}')
        try:
            cn = psycopg2.connect(alt)
            CONN = alt
            ok('컨테이너 계정으로 접속 성공')
        except Exception as e2:
            print(f'  ✗ 재시도도 실패: {str(e2).strip().splitlines()[0]}')
    else:
        print(f'  ✗ 컨테이너 정보를 못 읽음: {why}')

if cn is None:
    print('\n  확인 순서:')
    print('    1) docker ps                              컨테이너가 떠 있나')
    print('    2) docker inspect radar-guard-db --format '
          '"{{range .Config.Env}}{{println .}}{{end}}"')
    print('       → POSTGRES_PASSWORD / POSTGRES_DB 값 확인')
    print('    3) $env:RADAR_PG = "postgresql://postgres:<암호>@localhost:5432/<DB>"')
    print('       후 다시 실행')
    sys.exit(1)

cur = cn.cursor()
print('\n[1] 컬렉션')
try:
    cur.execute("SELECT name, uuid FROM langchain_pg_collection ORDER BY name")
    cols = cur.fetchall()
except Exception as e:
    bad('langchain_pg_collection 테이블 없음', str(e)[:80])
    print('    → 적재가 한 번도 안 됐습니다. embed_jetson.py 를 먼저 돌려야 합니다.')
    sys.exit(1)

if not cols:
    bad('컬렉션이 없음 — 적재 필요')
    sys.exit(1)
for name, uid in cols:
    mark = ok if name == COLLECTION else warn
    mark(f'컬렉션 {name}', str(uid))
target = [u for n, u in cols if n == COLLECTION]
if not target:
    bad(f'{COLLECTION} 컬렉션이 없음')
    sys.exit(1)
cid = target[0]

print('\n[2] 청크 수 · 임베딩 차원')
cur.execute("SELECT count(*) FROM langchain_pg_embedding WHERE collection_id=%s", (cid,))
n = cur.fetchone()[0]
(ok if n else bad)(f'청크 {n:,}개')

cur.execute("""SELECT vector_dims(embedding) FROM langchain_pg_embedding
               WHERE collection_id=%s LIMIT 1""", (cid,))
row = cur.fetchone()
dim = row[0] if row else None
if dim == EXPECTED_DIM:
    ok(f'임베딩 차원 {dim}', f'{EXPECTED_EMBED} 와 일치')
elif dim == 768:
    bad(f'임베딩 차원 {dim}', 'nomic-embed-text 로 적재됨 — 현행 검색은 bge-m3(1024)')
    print('    → 차원이 다르면 검색이 동작하지 않습니다. 둘 중 하나를 고르세요:')
    print('       (A) bge-m3 로 재적재  (권장 — 한국어 성능이 낫고 7/29 결정사항)')
    print('       (B) console_ui.py 의 EMBED_MODEL 을 nomic-embed-text 로 되돌리기')
else:
    warn(f'임베딩 차원 {dim}', '예상 밖의 값')

print('\n[3] 카테고리 — 검색 필터가 실제로 맞나  ★가장 중요')
cur.execute("""SELECT cmetadata->>'category' AS c, count(*)
               FROM langchain_pg_embedding WHERE collection_id=%s
               GROUP BY 1 ORDER BY 2 DESC""", (cid,))
rows = cur.fetchall()
have = {(c or '(없음)'): k for c, k in rows}
print('    DB 에 실제로 들어 있는 값:')
for c, k in rows:
    print(f'      {c or "(없음)":34s} {k:5,}개')
print('    현행 코드가 필터에 쓰는 값:')
miss = 0
for c in EXPECTED_CATEGORIES:
    hit = c in have
    print(f'      {c:34s} {"매칭 " + str(have[c]) + "개" if hit else "★ DB 에 없음 → 검색 0건"}')
    miss += (0 if hit else 1)
if miss:
    bad(f'카테고리 {miss}/{len(EXPECTED_CATEGORIES)} 개가 DB 와 불일치')
    print('    → 이 상태면 filter 를 건 검색은 항상 0건이고, 코드가 예외를 삼켜')
    print('       화면에는 조용히 아무것도 안 나옵니다. radar_common.EVENT_CATEGORY 를')
    print('       위 "DB 에 실제로 들어 있는 값" 으로 맞추면 됩니다.')
else:
    ok('카테고리 전부 일치')

print('\n[4] 출처 파일')
cur.execute("""SELECT cmetadata->>'source_file' AS f, count(*)
               FROM langchain_pg_embedding WHERE collection_id=%s
               GROUP BY 1 ORDER BY 2 DESC LIMIT 12""", (cid,))
for f, k in cur.fetchall():
    print(f'      {f or "(없음)":50s} {k:5,}청크')

print('\n[5] 청크 샘플 (길이 분포로 청킹 설정을 역추정)')
cur.execute("""SELECT length(document), left(document, 90)
               FROM langchain_pg_embedding WHERE collection_id=%s LIMIT 3""", (cid,))
for ln, txt in cur.fetchall():
    print(f'      {ln:4d}자  {" ".join(txt.split())[:78]}')
cur.execute("""SELECT round(avg(length(document))), min(length(document)),
                      max(length(document))
               FROM langchain_pg_embedding WHERE collection_id=%s""", (cid,))
a, mn, mx = cur.fetchone()
print(f'      평균 {a}자 / 최소 {mn} / 최대 {mx}   '
      f'(embed_jetson.py 설정: 600자, 겹침 80)')

print('\n[6] 실검색 테스트 — 고친 카테고리로 실제로 결과가 나오나')
#  langchain 없이 검증한다: ollama /api/embeddings 로 벡터를 만들고
#  pgvector 의 <=> (코사인 거리) 로 직접 조회한다. 현행 코드와 같은 경로다.
def embed(text):
    import json as _j
    import urllib.request
    body = _j.dumps({'model': EXPECTED_EMBED, 'prompt': text}).encode()
    req = urllib.request.Request(f'{OLLAMA}/api/embeddings', data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return _j.loads(r.read().decode())['embedding']


search_ok = None
try:
    embed('연결 확인')
    search_ok = True
except Exception as e:
    warn('ollama 임베딩 호출 실패 — 실검색 테스트 생략', f'{type(e).__name__}')
    print(f'    → ollama serve 확인 후 다시 실행. (모델: ollama pull {EXPECTED_EMBED})')

if search_ok:
    for et, q in TEST_QUERIES:
        cat = EVENT_CATEGORY.get(et)
        vec = embed(q)
        vlit = '[' + ','.join(f'{x:.6f}' for x in vec) + ']'
        # [8/25] EVENT_CATEGORY 값이 튜플일 수 있다(감전·협착·정지형).
        #   현행 radar_core.search_sop_documents() 와 같은 의미로 맞춘다:
        #     문자열 → 그 카테고리에서 2건 / 튜플 → 원소당 1건.
        #   예전엔 튜플을 그대로 %s 에 넣어 psycopg2 가 `= ('a','b')` 로 펼치는 바람에
        #   튜플 이벤트를 검사할 수 없었다.
        cats = list(cat) if isinstance(cat, (list, tuple)) else ([cat] if cat else [None])
        per = 1 if isinstance(cat, (list, tuple)) else 2
        hits = []
        for c in cats:
            if c:
                cur.execute("""SELECT cmetadata->>'source_file', embedding <=> %s::vector AS d,
                                      left(document, 62)
                               FROM langchain_pg_embedding
                               WHERE collection_id=%s AND cmetadata->>'category'=%s
                               ORDER BY d LIMIT %s""", (vlit, cid, c, per))
            else:
                cur.execute("""SELECT cmetadata->>'source_file', embedding <=> %s::vector AS d,
                                      left(document, 62)
                               FROM langchain_pg_embedding
                               WHERE collection_id=%s
                               ORDER BY d LIMIT %s""", (vlit, cid, per))
            hits += cur.fetchall()
        shown = cat if cat else '없음 — 전체'
        head = f'{et}  (필터 {shown})'
        if hits:
            ok(f'{head} → {len(hits)}건')
            for f, d, txt in hits:
                print(f'        거리 {d:.3f}  {(f or "?")[:40]:42s} {" ".join(txt.split())[:44]}')
        else:
            bad(f'{head} → 0건')

print('\n' + '=' * 72)
print('  판정')
issues = []
if dim != EXPECTED_DIM:
    issues.append('임베딩 차원 불일치 → 검색 불가')
if miss:
    issues.append('카테고리 불일치 → 필터 검색 0건')
if not n:
    issues.append('청크 없음 → 적재 필요')
if issues:
    for i in issues:
        print(f'    ✗ {i}')
    print('\n  → 위 항목을 고치기 전까지 SOP 검색은 화면에 아무것도 띄우지 못합니다.')
else:
    print('    ✓ SOP 검색 경로에 구조적 문제 없음')
print('=' * 72)
cur.close()
cn.close()
