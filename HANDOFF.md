# HANDOFF

> 다음 세션의 **실행 지시서**다. 소통 창구가 아니다 — 그건 `04_문서/AI_BRIDGE/` 다.
> 운영 규칙은 `04_문서/AI_BRIDGE/README.md` 와 `session-end` 스킬에 있다.

## State

- Updated: 2026-08-03 · CW
- Branch: main
- Commit: 1263dbe
- Working tree: 문서·스킬 변경 미커밋 (`04_문서/` 신규 4, `.claude/skills/radar-guard-hmi/` 신규, `scripts/` 신규, 런북 rename, `_구버전_laptop_viewer.py` 이동)

## Current objective

8/05(수) 젯슨 통합시험 — 레이더 → 젯슨 → UDP → 노트북 화면이 **끝까지 흐르는지** 확인한다.

## Verified baseline

- `1263dbe` 기준: v1결함 35·0 / 레이아웃 0건 / 실데이터재생 64·0 / 평면도흐름 16·0 / pyflakes 0
- 젯슨 실물 연결 실측치 **없음**. 위 수치는 전부 시뮬·jsonl 재생 기준이다.

## Next actions

1. 젯슨 통합시험 — `04_문서/젯슨_통합시험_런북_0805.md` 절차대로. 시작 전 방화벽 UDP 5005 인바운드 허용, 핫스팟 연결, 한 구간씩 연다. 결과를 숫자로 남긴다.
2. 드로어 제목 RED 고정 → `sev_color(sev)` 로 교체. `console_ui.py:1049`(`SopView.__init__` 생성 시 고정) · `:1150`(`EvidenceView.set_event` 매번 강제). 표시 계층만 건드린다. 고친 뒤 `replay_still.png`·`replay_vib.png` 를 열어 주황인지 확인.

## Blockers / unknowns

1. 10 Hz 실부하에서 화면이 끊기는지 미확인. 잠재 위험 3건(`DashboardPage.push()` setStyleSheet / `FacilityPlan` paintEvent / `Track3D` GL)은 **끊김이 실제로 보일 때만** pyinstrument 로 측정한다.
2. LLM 첫 응답 1분의 원인 미확정 — 모델 로딩인지 `prewarm()` 미실행인지 갈리지 않았다. LIVE 진입 후 "AI 요약 사전 생성 완료" 표시 여부로 판별한다.

## Acceptance

젯슨→노트북 패킷 수신 확인, READY→WARMUP→TRAIN→LIVE 진행, 낙상·진동 각 1회 화면 반영. 프레임레이트·프레임당 포인트수·유실률·LLM 응답시간을 숫자로 기록(못 잰 것은 `—`). 코드를 고쳤으면 `ui-verify` 전체 통과(35·0 / 0건 / 64·0 / 16·0).
