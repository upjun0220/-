# HANDOFF

> 다음 세션의 실행 지시서다. 소통 창구가 아니다.

## State

- Updated: 2026-08-10 · Cowork
- Branch: main
- Commit: `a841f65` (8/05) — 이후 9파일 1,067줄이 미커밋
- Working tree: 코드 4 · 문서 5 수정, `mannequin_cc0.obj`(3.13 MB) untracked

## Current objective

8/05 이후 쌓인 변경을 작업 단위로 나눠 커밋해 되돌림 지점과 `git log` 정본을 복구한다. **코드 내용은 바꾸지 않는다.**

## Verified baseline

- 8/10 세션 기준: pyflakes 0 · v1결함 47·0 · 실데이터재생 73·0 · 평면도흐름 16·0 · 4해상도 0건
- 마네킹 렌더 10 Hz 30초: CPU 28.4 → 4.83초(83.0% 감소) · 메모리 384~390 MB · 응답불량 0회
- ⚠ `verify_port.py` · `verify_jetson_safe.py` 는 `jetson_sender.py` · `radar_common.py` 수정 이후 미실행

## Next actions

1. 미커밋 변경을 작업 단위로 나눠 커밋한다. **직전 세션 결과물을 그대로 보존하고 리팩터링·이름 변경·정리를 하지 않는다.** 최소 분리 = (a) 정지형·ROI (b) 마네킹 렌더·GPU 변환 (c) 문서. `git diff` 로 경계가 안 갈리면 OUTBOX 에 적고 합쳐서 커밋한다.
2. 커밋 전 `verify_port.py` · `verify_jetson_safe.py` 를 다시 돌린다. 실패하면 커밋하지 말고 OUTBOX 에 적는다.
3. `mannequin_cc0.obj` 포함 여부를 판단한다. 재익스포트를 반복할 자산이면 텍스트라 매 버전이 통째로 저장된다.

## Blockers / unknowns

1. 원격 저장소가 없어 커밋해도 사본이 이 PC 뿐이다. OneDrive 가 `.git` 쓰기 중 동기화하면 손상 위험이 있다.
2. 실물 10 Hz 에서 화면 끊김과 UDP 유실률이 미확인이다. 위 CPU 수치는 재생 부하이지 젯슨 실물이 아니다.

## Acceptance

작업 단위로 분리된 커밋이 `git log` 에 남고 working tree 가 깨끗하다. pre-commit 훅 3종이 전부 통과한다. **커밋 과정에서 코드 동작 변경 0건** — `git diff a841f65..HEAD` 가 직전 세션 편집분과 일치해야 한다.
