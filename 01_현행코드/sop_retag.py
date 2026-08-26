r"""SOP 벡터DB 카테고리 재태깅 — 예방 문서와 대응 문서를 분리한다.

═══ 왜 만드나 ═══
  8/25 sop_doctor 실측: 낙상 질의에 M-59 "넘어짐 위험성 평가"가 1등으로 나온다.
  원인은 검색 알고리즘이 아니라 코퍼스 구성이다.
      03_낙상_응급처치 83청크 = M-59(예방) 42 + B-M-24(예방) 23 + H-187(대응) 18
      01_감전_LOTO   278청크 = OSHA3120 147 + E-105 75 + B-M-25 39 + E-14(대응) 17
      02_협착_끼임   138청크 = B-M-37 138 (대응 문서 0)
  사고 후 조치를 물었는데 후보의 94%가 예방 문서다. k를 늘려도 못 고친다.

  → 카테고리를 예방/대응으로 쪼개면 필터가 예방 문서를 구조적으로 배제한다.
    임베딩은 그대로 두고 cmetadata->>'category' 만 바꾼다. 초 단위로 끝나고
    되돌릴 수 있다. 추출 품질(공백 유실 등) 개선은 별건이며 재적재가 필요하다.

═══ 이 스크립트가 건드리지 않는 것 ═══
  jetson_sender.py · verify_jetson_safe.py · *.joblib · 판정 상수 · radar_common.py
  DB 의 cmetadata->>'category' 값 하나만 UPDATE 한다. 임베딩 벡터는 손대지 않는다.

═══ 검증 이력 ═══
  2026-08-25: 클라우드 컨테이너에 PostgreSQL 16.13 을 띄우고 실DB와 같은 스키마
    (langchain_pg_collection / langchain_pg_embedding, 634청크 13파일, 카테고리
    분포 278/138/83/73/62)를 시드해 dry → apply → rollback 전 구간 실행했다.
    · 재태깅 후 8개 카테고리 배분이 계획과 일치
    · rollback 후 원래 5개 카테고리 278/138/83/73/62 로 완전 복원 확인
    · cmetadata 가 json 인 경우와 jsonb 인 경우 모두에서 UPDATE 성공
    · pyflakes 경고 0건
  ⚠ 실제 radar-guard-db 에는 아직 실행하지 않았다. 위는 동형 스키마 재현 시험이다.

═══ 실행 환경: PowerShell (윈도우 노트북) ═══
  docker start radar-guard-db
  python C:\dev\radar-guard\01_현행코드\sop_retag.py            # 미리보기 (기본)
  python C:\dev\radar-guard\01_현행코드\sop_retag.py --apply    # 실제 변경 + 백업
  python C:\dev\radar-guard\01_현행코드\sop_retag.py --rollback sop_retag_backup_*.json
"""
import json
import os
import sys
import time

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 접속 문자열은 radar_common 의 것을 그대로 쓴다.
#   sop_doctor.py 는 'postgres:password' 를 하드코딩해 두고 실패하면 docker inspect 로
#   재시도하는데, 실제 계정은 admin 이라 매번 한 번씩 실패 로그를 찍는다. 정본을 쓴다.
try:
    from radar_common import pg_conn_str
    CONN = os.environ.get('RADAR_PG') or pg_conn_str()
except Exception:
    CONN = os.environ.get('RADAR_PG',
                          'postgresql://postgres:password@localhost:5432/radar_guard')

COLLECTION = 'safety_manual'

# ── 재태깅 계획 ────────────────────────────────────────────────────────
#  파일명은 부분 문자열로 매칭한다. sop_doctor 출력이 50자에서 잘려 표시되기 때문에
#  전체 파일명을 그대로 적으면 오타 한 글자에 0건 매칭이 되고 조용히 아무 일도
#  안 일어난다. 매칭 결과는 --apply 전에 반드시 화면으로 확인한다.
#
#  H-187 은 낙상·골절·화상·감전을 한 권에 담은 문서다. 한 카테고리에만 넣으면
#  다른 사고에서 못 쓴다 → 공통 카테고리로 두고 EVENT_CATEGORY 에서 튜플로 함께
#  조회한다. search_sop_documents() 는 이미 튜플을 지원한다(stationary_anomaly).
#
#  OSHA3120 은 미국 OSHA 가 2002 년에 낸 영문 발행물이다(2026-08-25 확인).
#  147청크로 01_감전_LOTO 의 53% 를 차지하는데, 질의는 전부 한글이고 뽑히면
#  시연 화면에 영어 원문이 뜬다 → 검색 대상에서 격리한다. 삭제가 아니라 격리이며
#  EVENT_CATEGORY 에 이 카테고리를 넣으면 즉시 되살아난다.
PLAN = [
    ('산업재해 형태별 응급처치',  '00_응급처치_공통'),
    ('감전시응급조치',            '01_감전_대응'),
    ('E-105-2011',                '01_감전_예방'),
    ('B-M-25-2026',               '01_감전_예방'),
    ('OSHA3120',                  '09_영문참고_검색제외'),
    ('B-M-37-2026',               '02_협착_예방'),
    ('M-59-2012',                 '03_낙상_예방'),
    ('B-M-24-2026',               '03_낙상_예방'),
]

# 재태깅 후 radar_common.EVENT_CATEGORY 에 넣을 값. 이 스크립트는 코드를 고치지
# 않는다 — DB 를 먼저 바꾸고 사람이 확인한 뒤 손으로 반영한다. 순서가 뒤집히면
# 필터가 DB 에 없는 값을 가리켜 검색이 조용히 0건이 된다(7/31 에 겪은 그 버그).
#
#  ⚠ 값의 형태가 검색 건수를 바꾼다 — radar_core.search_sop_documents() 751행:
#       count = 1 if isinstance(category, (list, tuple)) else 2
#     문자열이면 그 카테고리에서 2건, 튜플이면 원소당 1건이다.
#     원소 1개짜리 튜플은 1건만 가져오므로 문자열로 쓴다.
#
#  ⚠ 부작용 하나 — 이 값을 바꾸면 SOP_RESPONSE_SOURCE 의 키(옛 카테고리명)와
#     안 맞게 되어 sources.get(cat) 가 None 을 돌려준다. 그러면 낙상·협착·감전이
#     하드코딩 파일 지정 경로에서 **벡터 검색 경로로 자동 전환된다.**
#     그게 이 작업의 목적이지만, sop_doctor 로 검증하기 전에는 시연에 쓰지 않는다.
#     벡터가 이기면 SOP_RESPONSE_SOURCE 를 삭제하고, 지면 키를 새 카테고리명으로
#     고쳐 결정적 경로를 되살린다.
SUGGESTED_EVENT_CATEGORY = {
    'fall_detected':                 '00_응급처치_공통',
    'fall_suspected':                '03_낙상_예방',
    'electric_shock_risk':           ('01_감전_대응', '00_응급처치_공통'),
    'electric_shock_risk_confirmed': ('01_감전_대응', '00_응급처치_공통'),
    'leakage_current':               '01_감전_예방',
    'overcurrent':                   '01_감전_예방',
    'voltage_drop':                  '01_감전_예방',
    'pinching':                      ('00_응급처치_공통', '02_협착_예방'),
    'pinching_suspected':            '02_협착_예방',
    'stationary_anomaly':            ('01_감전_대응', '02_협착_예방'),
    'vibration_anomaly':             '04_예지보전',
}

try:
    import psycopg2
except ImportError:
    print('psycopg2 가 없습니다:  pip install psycopg2-binary')
    sys.exit(1)

MODE = 'dry'
BACKUP_PATH = None
# --dump <부분문자열> : 해당 파일의 청크 본문을 전부 찍는다(읽기 전용).
#   새로 색인한 문서가 실제로 어떻게 쪼개졌는지 눈으로 봐야 판단할 수 있다.
DUMP = None
# --quarantine : 조치 내용이 없는 '메타 청크'를 검색 대상에서 뺀다.
#   코덱스가 만든 프로젝트 SOP 에 "6. RAG 검색용 핵심어" 문단과 출처 목록이 있는데,
#   이 청크는 질의어를 그대로 담고 있어 코사인 거리가 가장 짧게 나온다. 즉 실제
#   점검 절차 청크를 이기고 1등으로 뽑힌다 → 화면에 단어 나열과 URL 이 뜬다.
#   삭제하지 않고 09_색인제외 로 옮긴다. 카테고리만 되돌리면 원상복구된다.
QUARANTINE = '--quarantine' in sys.argv
# 청크 '내용'으로 고른다. 파일 단위가 아니라 청크 단위여야 본문 절차는 살릴 수 있다.
QUARANTINE_PATTERNS = [
    '과전류, 과부하, 단락, 지락',   # 6절 핵심어 나열 본문
    '29 CFR 1910.147',              # 출처 목록 블록
]
EXCLUDE_CAT = '09_색인제외'
OLD_EXCLUDE_CAT = '09_영문참고_검색제외'   # 이름을 일반화한다(영문 전용이 아니게 됐다)
if '--dump' in sys.argv:
    _i = sys.argv.index('--dump')
    DUMP = sys.argv[_i + 1] if _i + 1 < len(sys.argv) else ''
if '--apply' in sys.argv:
    MODE = 'apply'
elif '--rollback' in sys.argv:
    MODE = 'rollback'
    i = sys.argv.index('--rollback')
    if i + 1 >= len(sys.argv):
        print('--rollback 뒤에 백업 파일 경로가 필요합니다')
        sys.exit(1)
    BACKUP_PATH = sys.argv[i + 1]

cn = psycopg2.connect(CONN)
cur = cn.cursor()
cur.execute("SELECT uuid FROM langchain_pg_collection WHERE name=%s", (COLLECTION,))
row = cur.fetchone()
if not row:
    print(f'컬렉션 {COLLECTION} 이 없습니다. 적재부터 하세요.')
    sys.exit(1)
CID = row[0]

# cmetadata 컬럼 타입은 langchain 버전에 따라 json 이거나 jsonb 다. 틀린 캐스트로
# UPDATE 하면 그 자리에서 타입 에러가 난다 → 실행 시점에 확인해 캐스트를 정한다.
cur.execute("""SELECT data_type FROM information_schema.columns
               WHERE table_name='langchain_pg_embedding' AND column_name='cmetadata'""")
_t = (cur.fetchone() or ['json'])[0]
CAST = '' if _t == 'jsonb' else '::json'

SET_CAT = ("SET cmetadata = jsonb_set(cmetadata::jsonb, '{category}', "
           "to_jsonb(%s::text))" + CAST)

BAR = '=' * 74


def cross_tab(title):
    """카테고리 x 파일 교차표. 재태깅 전후를 같은 형식으로 찍어 비교한다."""
    print(f'\n{BAR}\n  {title}\n{BAR}')
    cur.execute("""SELECT cmetadata->>'category', cmetadata->>'source_file', count(*)
                   FROM langchain_pg_embedding WHERE collection_id=%s
                   GROUP BY 1,2 ORDER BY 1, 3 DESC""", (CID,))
    last = None
    total = 0
    for cat, src, n in cur.fetchall():
        if cat != last:
            print(f'\n  [{cat or "(없음)"}]')
            last = cat
        print(f'      {(src or "?")[:56]:58s} {n:5,}')
        total += n
    print(f'\n  합계 {total:,}청크')


# ── 롤백 ──────────────────────────────────────────────────────────────
if MODE == 'rollback':
    with open(BACKUP_PATH, encoding='utf-8') as f:
        backup = json.load(f)
    print(f'백업 {BACKUP_PATH} 로 되돌립니다 ({len(backup["rows"])}개 파일)')
    for src, cat in backup['rows']:
        cur.execute('UPDATE langchain_pg_embedding ' + SET_CAT +
                    " WHERE collection_id=%s AND cmetadata->>'source_file'=%s",
                    (cat, CID, src))
        print(f'  {src[:56]:58s} → {cat}')
    cn.commit()
    cross_tab('롤백 후')
    cn.close()
    sys.exit(0)

# ── --quarantine : 메타 청크 격리 ──────────────────────────────────────
if QUARANTINE:
    print(f'\n{BAR}\n  격리 대상 청크 (조치 내용이 없는 메타 청크)\n{BAR}')
    targets = []
    for pat in QUARANTINE_PATTERNS:
        cur.execute("""SELECT uuid, cmetadata->>'source_file', cmetadata->>'category',
                              length(document), left(document, 150)
                       FROM langchain_pg_embedding
                       WHERE collection_id=%s AND document LIKE %s""",
                    (CID, f'%{pat}%'))
        for u, src, cat, ln, head in cur.fetchall():
            if u not in [t[0] for t in targets]:
                targets.append((u, src, cat, ln, head))
                print(f'\n  · {src}  [{cat}] {ln}자   (패턴 "{pat}")')
                print(f'    {" ".join(head.split())[:140]}')
    cur.execute("SELECT count(*) FROM langchain_pg_embedding "
                "WHERE collection_id=%s AND cmetadata->>'category'=%s",
                (CID, OLD_EXCLUDE_CAT))
    n_old = cur.fetchone()[0]
    print(f'\n  격리 대상 {len(targets)}청크')
    print(f'  더불어 {OLD_EXCLUDE_CAT} {n_old}청크를 {EXCLUDE_CAT} 로 이름 통일한다'
          f' (영문 전용이 아니게 됐다)')
    if MODE != 'apply':
        print('\n  미리보기입니다. 적용하려면:  sop_retag.py --quarantine --apply')
        cn.close()
        sys.exit(0)
    cur.execute("""SELECT DISTINCT uuid::text, cmetadata->>'category'
                   FROM langchain_pg_embedding WHERE collection_id=%s
                     AND (cmetadata->>'category'=%s OR uuid = ANY(%s::uuid[]))""",
                (CID, OLD_EXCLUDE_CAT, [str(t[0]) for t in targets]))
    bk = {'collection_id': str(CID), 'mode': 'quarantine',
          'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
          'chunks': [[u, c] for u, c in cur.fetchall()]}
    bpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         f'sop_quarantine_backup_{time.strftime("%Y%m%d_%H%M%S")}.json')
    with open(bpath, 'w', encoding='utf-8') as f:
        json.dump(bk, f, ensure_ascii=False, indent=2)
    print(f'\n  백업 저장: {bpath}  ({len(bk["chunks"])}청크)')
    cur.execute('UPDATE langchain_pg_embedding ' + SET_CAT +
                ' WHERE collection_id=%s AND cmetadata->>\'category\'=%s',
                (EXCLUDE_CAT, CID, OLD_EXCLUDE_CAT))
    cur.execute('UPDATE langchain_pg_embedding ' + SET_CAT +
                ' WHERE collection_id=%s AND uuid = ANY(%s::uuid[])',
                (EXCLUDE_CAT, CID, [str(t[0]) for t in targets]))
    cn.commit()
    cross_tab('격리 후')
    print(f'\n  되돌리려면 백업의 chunks 를 참고해 category 를 원복한다: {bpath}')
    cn.close()
    sys.exit(0)

# ── --dump : 지정 파일의 청크 전문 (읽기 전용) ──────────────────────────
if DUMP is not None:
    cross_tab('현재 상태')
    print(f'\n{BAR}\n  "{DUMP}" 청크 전문\n{BAR}')
    cur.execute("""SELECT cmetadata->>'source_file', cmetadata->>'category',
                          length(document), document
                   FROM langchain_pg_embedding
                   WHERE collection_id=%s AND cmetadata->>'source_file' LIKE %s""",
                (CID, f'%{DUMP}%'))
    rows = cur.fetchall()
    if not rows:
        print('  0건 — 이 이름으로 색인된 청크가 없습니다.')
    for k, (src, cat, ln, doc) in enumerate(rows, 1):
        print(f'\n  [{k}] {src}  · {cat} · {ln}자')
        print('      ' + ' '.join(doc.split()))
    cn.close()
    sys.exit(0)

# ── 현재 상태 ─────────────────────────────────────────────────────────
cross_tab('현재 상태')

# ── H-187 청크 목록 ───────────────────────────────────────────────────
#  H-187 이 낙상·감전·협착 중 무엇을 실제로 담고 있는지가 협착 대응 문서 공백을
#  메울 수 있느냐를 가른다. 18청크뿐이라 전부 찍어 사람이 눈으로 판단한다.
print(f'\n{BAR}\n  H-187 산업재해 형태별 응급처치 — 청크 앞부분\n{BAR}')
cur.execute("""SELECT document FROM langchain_pg_embedding
               WHERE collection_id=%s AND cmetadata->>'source_file' LIKE %s""",
            (CID, '%산업재해 형태별 응급처치%'))
h187 = [r[0] for r in cur.fetchall()]
for i, txt in enumerate(h187, 1):
    print(f'  {i:2d}. {" ".join(txt.split())[:300]}')
if not h187:
    print('  ★ 0건 — 파일명 매칭 실패. PLAN 의 검색어를 위 교차표에 맞게 고치세요.')

# H-187 이 협착 대응까지 커버하는지가 02_협착_대응 공백을 메울 수 있느냐를 가른다.
#   (8/25 조사: 끼임 사고 '발생 후' 구조 절차를 다룬 KOSHA 전용 지침을 못 찾았다)
#   본문에 어느 재해 형태가 실제로 나오는지 단어 빈도로 본다. 판단은 사람이 한다.
if h187:
    print('\n  H-187 본문 키워드 출현 횟수 — 협착 대응 매핑 가능 여부 판단용')
    body = '\n'.join(h187)
    for kw in ('끼임', '협착', '압좌', '절단', '골절', '척추', '출혈',
               '감전', '화상', '심폐소생', '119', '이송', '지혈'):
        n = body.count(kw)
        flag = '' if n else '   ← 없음'
        print(f'      {kw:6s} {n:4d}회{flag}')

# ── 변경 계획 ─────────────────────────────────────────────────────────
print(f'\n{BAR}\n  변경 계획\n{BAR}')
changes = []
for needle, new_cat in PLAN:
    cur.execute("""SELECT cmetadata->>'source_file', cmetadata->>'category', count(*)
                   FROM langchain_pg_embedding
                   WHERE collection_id=%s AND cmetadata->>'source_file' LIKE %s
                   GROUP BY 1,2""", (CID, f'%{needle}%'))
    hits = cur.fetchall()
    if not hits:
        print(f'  ★ "{needle}" → 매칭 0건. 검색어를 확인하세요.')
        continue
    for src, old_cat, n in hits:
        mark = ' ' if old_cat != new_cat else '=(변화없음)'
        print(f'  {src[:50]:52s} {n:4,}청크  {old_cat} → {new_cat} {mark}')
        changes.append((src, old_cat, new_cat, n))

covered = sum(c[3] for c in changes)
cur.execute("SELECT count(*) FROM langchain_pg_embedding WHERE collection_id=%s", (CID,))
total = cur.fetchone()[0]
print(f'\n  계획이 덮는 청크 {covered:,} / 전체 {total:,}'
      f'  (나머지 {total - covered:,}청크는 04_예지보전·05_위험성평가_비상 — 유지)')

print(f'\n{BAR}\n  재태깅 후 radar_common.EVENT_CATEGORY 에 반영할 값\n{BAR}')
print('  ⚠ 이 스크립트는 코드를 고치지 않는다. DB 를 먼저 바꾸고, 위 교차표를 확인한 뒤')
print('    사람이 손으로 반영한다. 코드를 먼저 고치면 필터가 DB 에 없는 값을 가리켜')
print('    검색이 조용히 0건이 된다.')
for k, v in SUGGESTED_EVENT_CATEGORY.items():
    print(f"    {k + ':':34s} {v!r},")

if MODE == 'dry':
    print(f'\n{BAR}')
    print('  미리보기입니다. DB 는 바뀌지 않았습니다.')
    print('  적용하려면:  python sop_retag.py --apply')
    print(BAR)
    cn.close()
    sys.exit(0)

# ── 적용 ──────────────────────────────────────────────────────────────
cur.execute("""SELECT DISTINCT cmetadata->>'source_file', cmetadata->>'category'
               FROM langchain_pg_embedding WHERE collection_id=%s""", (CID,))
backup = {'collection_id': str(CID),
          'saved_at': time.strftime('%Y-%m-%d %H:%M:%S'),
          'rows': [[s, c] for s, c in cur.fetchall()]}
bpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     f'sop_retag_backup_{time.strftime("%Y%m%d_%H%M%S")}.json')
with open(bpath, 'w', encoding='utf-8') as f:
    json.dump(backup, f, ensure_ascii=False, indent=2)
print(f'\n  백업 저장: {bpath}')

for src, old_cat, new_cat, n in changes:
    if old_cat == new_cat:
        continue
    cur.execute('UPDATE langchain_pg_embedding ' + SET_CAT +
                " WHERE collection_id=%s AND cmetadata->>'source_file'=%s",
                (new_cat, CID, src))
    print(f'  적용 {src[:50]:52s} {n:4,}청크 → {new_cat}')
cn.commit()

cross_tab('재태깅 후')
print(f'\n{BAR}')
print('  다음 순서:')
print('   1) radar_common.EVENT_CATEGORY 를 위 제안값으로 반영 (키는 그대로, 값만)')
print('   2) python sop_doctor.py 로 실검색 재측정')
print('   3) 결과가 SOP_RESPONSE_SOURCE 매핑과 일치하면 매핑 제거 검토')
print(f'  되돌리려면:  python sop_retag.py --rollback {os.path.basename(bpath)}')
print(BAR)
cn.close()
