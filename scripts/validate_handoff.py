"""validate_handoff.py — HANDOFF.md 가 다시 로그로 변질되는 것을 막는다.

  실행: [내 PC PowerShell] — cd 불필요
      python scripts\validate_handoff.py

  ⚠ [8/03] 왜 만들었나:
    HANDOFF §1 이 규칙(10줄)의 7.7배인 77줄까지 불어났고, 8/02 에 이미 완료된
    지시가 그대로 남아 있었다. 다음 세션은 그걸 '해야 할 일'로 읽는다.
    줄 수만 줄이면 재발한다 — 누적이 구조적으로 불가능해야 한다.
    그래서 형태를 기계가 검사한다.

  종료코드 0 = 통과 / 1 = 위반
"""
import os
import re
import sys

# ⚠ [8/04] Windows 기본 콘솔(cp949)에서 '—' 같은 문자를 출력하면
#   UnicodeEncodeError 로 중간에 죽는다. 검증 절차가 숨은 환경변수
#   ($env:PYTHONUTF8)에 의존하면 안 되므로 진입점에서 보장한다.
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass


# 실행 위치와 무관하게 저장소 루트를 찾는다 (verify_port.py 와 같은 방식)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, 'HANDOFF.md')

MAX_LINES = 40          # 비어 있지 않은 줄
MAX_ACTIONS = 3
MAX_BLOCKERS = 3
REQUIRED = ['## State', '## Current objective', '## Verified baseline',
            '## Next actions', '## Blockers', '## Acceptance']
FIELDS = ['Updated:', 'Branch:', 'Commit:', 'Working tree:']

# 로그성 표현 — 완료 기록은 git log 가 정본이다
LOG_PAT = [
    (r'\[[xX]\]',            '완료 체크박스'),
    (r'완료',                 "'완료' — 끝난 일은 삭제한다"),
    (r'\bDone\b',            "'Done'"),
    (r'해결됨|처리됨|반영함',    '완료 표현'),
    (r'종료·커밋|커밋 완료',     '커밋 기록 (→ git log)'),
    (r'^\s*-\s*\[\d{1,2}/\d{1,2}',  '날짜 머리 항목 (로그 형태)'),
]

ng = []


def bad(msg):
    ng.append(msg)


def main():
    if not os.path.exists(PATH):
        print('NG  HANDOFF.md 없음')
        return 1
    raw = open(PATH, encoding='utf-8').read()
    lines = raw.split('\n')
    body = [l for l in lines if l.strip()]

    # 1. 분량
    if len(body) > MAX_LINES:
        bad(f'분량 {len(body)}줄 > {MAX_LINES}줄 — 오래된 것부터 지운다')

    # 2. 필수 섹션
    for s in REQUIRED:
        if s not in raw:
            bad(f'섹션 없음: {s}')

    # 3. State 필드
    for f in FIELDS:
        if f not in raw:
            bad(f'State 필드 없음: {f}')

    # 4. 코드 블록 금지 — 상세 코드는 파일 자체가 정본이다
    if '```' in raw:
        bad('코드 블록 사용 — 코드는 파일이 정본이다')

    # 5. 로그성 표현
    #   ⚠ 인용부호 안은 검사에서 뺀다. 화면에 뜨는 문구("AI 요약 사전 생성 완료")나
    #     파일명을 인용하는 것은 정당한데, 그것까지 잡으면 오탐이 나 검사기를 끄게 된다.
    #     로그로 쓸 때는 인용부호 없이 쓰므로 이 예외가 우회 수단이 되지는 않는다.
    quoted = re.compile(r'"[^"]*"|`[^`]*`|\u201c[^\u201d]*\u201d')
    for i, l in enumerate(lines, 1):
        if l.strip().startswith('>'):      # 머리말 안내는 예외
            continue
        bare = quoted.sub('', l)
        for pat, why in LOG_PAT:
            if re.search(pat, bare):
                bad(f'{i}행 로그성 표현 — {why}')
                break

    # 6. 항목 수
    def count_items(title):
        if title not in raw:
            return 0
        seg = raw.split(title, 1)[1]
        seg = seg.split('\n## ', 1)[0]
        return len(re.findall(r'^\s*\d+\.\s+\S', seg, re.M))

    n = count_items('## Next actions')
    if n > MAX_ACTIONS:
        bad(f'Next actions {n}개 > {MAX_ACTIONS}개 — 다음 세션에 실제로 할 것만')
    if n == 0:
        bad('Next actions 없음 — 다음 세션이 무엇을 할지 없다')

    b = count_items('## Blockers')
    if b > MAX_BLOCKERS:
        bad(f'Blockers {b}개 > {MAX_BLOCKERS}개')

    # 7. Current objective 는 하나
    if '## Current objective' in raw:
        seg = raw.split('## Current objective', 1)[1].split('\n## ', 1)[0]
        para = [p for p in seg.strip().split('\n\n') if p.strip()]
        if len(para) > 1:
            bad(f'Current objective 가 {len(para)}개 — 하나여야 한다')

    print(f'HANDOFF 검사  {len(body)}/{MAX_LINES}줄 · '
          f'actions {n}/{MAX_ACTIONS} · blockers {b}/{MAX_BLOCKERS}')
    if ng:
        for m in ng:
            print(f'  NG   {m}')
        print(f'\n{len(ng)}건 위반')
        return 1
    print('  OK   위반 0건')
    return 0


if __name__ == '__main__':
    sys.exit(main())
