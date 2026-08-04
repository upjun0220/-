"""validate_ai_bridge.py — INBOX/OUTBOX 가 작업 일지로 변질되는 것을 막는다.

  실행: [내 PC PowerShell] — cd 불필요
      python scripts\validate_ai_bridge.py

  ⚠ [8/03] 왜 만들었나:
    HANDOFF 가 소통과 실행이 섞여 77줄까지 불어난 뒤 AI_BRIDGE 로 창구를 분리했다.
    그런데 창구를 만들면 이번엔 거기가 쌓인다 — 장소만 옮긴 같은 병이다.
    triage 를 미루면 항목 수로 즉시 드러나게 한다.

  종료코드 0 = 통과 / 1 = 위반
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, '04_문서', 'AI_BRIDGE')
HANDOFF = os.path.join(ROOT, 'HANDOFF.md')

MAX_ITEMS = 10
FILES = {'INBOX.md': 'IN', 'OUTBOX.md': 'OUT'}
FIELDS = ['From:', 'Type:', 'Needs:']

# 완료 로그 — 완료 이력의 정본은 git history 다
LOG_PAT = [
    (r'\[[xX]\]',                  '체크된 체크박스'),
    (r'완료|해결됨|처리됨|반영함',    '완료 기록 — triage 해서 지운다'),
    (r'\bDone\b|\bClosed\b',       '완료 표현'),
]
# 일지 패턴 — 소통이 아니라 '한 일 나열'
DIARY_PAT = [
    (r'^\s*-\s*\d{1,2}/\d{1,2}\s',      '날짜 머리 항목'),
    (r'했다\.|했음\.|하였다\.',            '과거 서술 (일지 형태)'),
]

ng, warn = [], []


def check_file(fname, prefix):
    path = os.path.join(DIR, fname)
    if not os.path.exists(path):
        ng.append(f'{fname} 없음')
        return [], ''
    raw = open(path, encoding='utf-8').read()
    lines = raw.split('\n')

    # 항목 = '### <ID>  제목'
    items = re.findall(r'^###\s+(' + prefix + r'-\d+)\b(.*)$', raw, re.M)
    ids = [i[0] for i in items]

    if len(ids) > MAX_ITEMS:
        ng.append(f'{fname} 열린 항목 {len(ids)}개 > {MAX_ITEMS}개 — triage 를 미뤘다')

    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        ng.append(f'{fname} ID 중복: {", ".join(sorted(dup))} — ID 는 재사용하지 않는다')

    # 항목별 필수 필드
    blocks = re.split(r'^###\s+', raw, flags=re.M)[1:]
    for b in blocks:
        head = b.split('\n', 1)[0].strip()
        for f in FIELDS:
            if f not in b.split('\n###')[0]:
                ng.append(f'{fname} [{head[:24]}] 필드 없음: {f}')

    # 완료 로그 / 일지 패턴
    quoted = re.compile(r'"[^"]*"|`[^`]*`|“[^”]*”')
    for i, l in enumerate(lines, 1):
        if l.strip().startswith('>'):
            continue
        bare = quoted.sub('', l)
        for pat, why in LOG_PAT:
            if re.search(pat, bare):
                ng.append(f'{fname}:{i} {why}')
                break
        for pat, why in DIARY_PAT:
            if re.search(pat, bare):
                warn.append(f'{fname}:{i} {why} — 소통 창구지 일지가 아니다')
                break
    return ids, raw


def main():
    if not os.path.isdir(DIR):
        print('NG  04_문서/AI_BRIDGE/ 없음')
        return 1

    counts, texts = {}, {}
    for fname, prefix in FILES.items():
        ids, raw = check_file(fname, prefix)
        counts[fname] = len(ids)
        texts[fname] = raw

    # HANDOFF 와 장문 중복 — 같은 내용이 두 곳에 있으면 하나는 반드시 낡는다
    if os.path.exists(HANDOFF):
        hv = open(HANDOFF, encoding='utf-8').read()
        hsent = {s.strip() for s in re.split(r'[.\n]', hv) if len(s.strip()) >= 40}
        for fname, raw in texts.items():
            for s in re.split(r'[.\n]', raw):
                if len(s.strip()) >= 40 and s.strip() in hsent:
                    warn.append(f'{fname} HANDOFF 와 장문 중복: "{s.strip()[:46]}…"')

    print('AI_BRIDGE 검사  ' + ' · '.join(
        f'{k.split(".")[0]} {v}/{MAX_ITEMS}' for k, v in counts.items()))
    for m in warn:
        print(f'  WARN {m}')
    if ng:
        for m in ng:
            print(f'  NG   {m}')
        print(f'\n{len(ng)}건 위반')
        return 1
    print(f'  OK   위반 0건' + (f' (경고 {len(warn)}건)' if warn else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
