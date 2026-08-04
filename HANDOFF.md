# HANDOFF

> 다음 세션의 **실행 지시서**다. 소통 창구가 아니다 — 그건 `04_문서/AI_BRIDGE/` 다.
> 운영 규칙은 `04_문서/AI_BRIDGE/README.md` 와 `session-end` 스킬에 있다.

## State

- Updated: 2026-08-04 · Codex
- Branch: main
- Commit: 9acea4f
- Working tree: Codex 세션 변경 커밋 예정 · `INBOX.md` 타 작업 6줄은 제외

## Current objective

8/05 젯슨 통합시험에서 레이더→젯슨→UDP→노트북 표시와 로컬 차단 경로가 실물 10 Hz 부하에서도 끝까지 동작하는지 수치로 확인한다.

## Verified baseline

- 노트북 기본 콘솔: pyflakes 0 / v1결함 36·0 / 레이아웃 0건 / 실데이터재생 73·0 / 평면도흐름 16·0
- 판정 이식 7,788건 불일치 0 / 젯슨 안전 36건 실패 0
- 위 수치는 시뮬·jsonl 재생 기준이며 젯슨 실물 연결 실측치는 없다.

## Next actions

1. `04_문서/젯슨_통합시험_런북_0805.md` 사전 점검을 수행한다. 핫스팟·노트북 방화벽 UDP 5005·젯슨 시각 비의존·COM13 입력을 한 단계씩 확인한다.
2. READY→WARMUP→TRAIN→LIVE를 진행하고 낙상·진동 각 1회를 발생시킨다. 프레임레이트·프레임당 포인트수·UDP 유실률·첫 LLM 응답시간을 숫자로 기록하며 못 잰 값은 `—`로 둔다.
3. 끊김이 실제로 보일 때만 `DashboardPage.push()`·`FacilityPlan.paintEvent()`·`Track3D`를 pyinstrument로 측정한다. 추측으로 최적화하지 않는다.

## Blockers / unknowns

1. 실물 10 Hz에서 화면 끊김과 UDP 유실률이 미확인이다.
2. LLM 첫 응답 약 1분이 모델 로딩인지 `prewarm()` 미실행인지 미확정이다.

## Acceptance

젯슨→노트북 패킷 수신, READY→WARMUP→TRAIN→LIVE, 낙상·진동 화면 반영, 젯슨 로컬 차단을 확인한다. 런북 계측값을 숫자로 남기고 코드 수정 시 UI 전체 검증과 젯슨 안전 검증을 다시 통과한다.
