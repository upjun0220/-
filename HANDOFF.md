# HANDOFF

> 다음 세션의 **실행 지시서**다. 소통 창구가 아니다 — 그건 `04_문서/AI_BRIDGE/` 다.
> 운영 규칙은 `04_문서/AI_BRIDGE/README.md` 와 `session-end` 스킬에 있다.

## State

- Updated: 2026-08-04 · CW
- Branch: main
- Commit: 1263dbe
- Working tree: 문서·스킬·scripts 변경 미커밋

## Current objective

젯슨을 붙이기 전에 **표시 계층의 거짓 표시 3건을 없애고 검증 환경을 복구한다.** 실물 시험에서 센서 문제와 UI 문제가 한 화면에 섞이면 원인을 가릴 수 없다. 젯슨 통합시험은 8/05(수).

## Verified baseline

- `1263dbe` 기준: v1결함 35·0 / 레이아웃 0건 / 실데이터재생 64·0 / 평면도흐름 16·0 / pyflakes 0
- **⚠ 위 수치는 `PYTHONUTF8=1` 환경에서만 나온다.** 기본 cp949 콘솔에서는 첫 출력의 `—` 에서 죽는다.
- 젯슨 실물 연결 실측치 **없음**. 전부 시뮬·jsonl 재생 기준이다.

## Next actions

1. 검증 진입점에서 UTF-8 출력을 보장한다. `01_현행코드/테스트_*.py` 4종 + `replay_jsonl.py` 등 콘솔 출력이 있는 스크립트 상단에서 `sys.platform == 'win32'` 일 때 `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`. **이게 먼저다 — 검증이 안 돌면 아래 2·3 을 증명할 수 없다.** (`scripts/` 3종은 이미 반영됨)
2. 드로어 제목 RED 고정 → `sev_color(sev)`. `console_ui.py:1049`(`SopView.__init__` 생성 시 고정) · `:1150`(`EvidenceView.set_event` 매번 강제). 같은 파일에서 `on_alert`(2519)를 `_pump_state`(2559) **뒤에 다시 계산**해 `lost`(2571)에 반영한다 — 지금은 `sev` 만 갱신되고 `on_alert` 는 옛 값이라 주석의 주장과 코드가 어긋난다. 경보 첫 패킷에서 형상이 즉시 숨는 회귀검사를 추가한다.
3. `_set_auto_action`(2719)이 `breaker.state` 만 보고 "차단 신호 발신"이라 쓴다. 낙상으로 이미 내려간 뒤 warning 사건이 오면 거짓이다. `breaker.reason` 을 읽어 **이번 사건의 차단**과 **기존 차단 상태**를 다르게 표시한다.

## Blockers / unknowns

1. 10 Hz 실부하에서 화면이 끊기는지 미확인. 잠재 위험 3건(`DashboardPage.push()` setStyleSheet / `FacilityPlan` paintEvent / `Track3D` GL)은 **끊김이 실제로 보일 때만** pyinstrument 로 측정한다.
2. LLM 첫 응답 1분의 원인 미확정 — 모델 로딩인지 `prewarm()` 미실행인지 갈리지 않았다. LIVE 진입 후 "AI 요약 사전 생성 완료" 표시 여부로 판별한다.

## Acceptance

1·2·3 을 고친 뒤 `ui-verify` 전체를 **기본 콘솔에서** 통과(35·0 / 0건 / 64·0 / 16·0, pyflakes 0). `replay_still.png`·`replay_vib.png` 를 열어 드로어 제목이 주황인지 눈으로 확인. 차단 표시는 낙상 후 진동이 연달아 오는 시퀀스로 검사한다.
