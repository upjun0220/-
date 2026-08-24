# HANDOFF

> 다음 세션의 실행 지시서다. 소통 창구가 아니다.

## ⛔ 판정 코드 동결 (2026-08-24 ~ 해제 시까지)

**낙상 · 정지형(무동작) · PINCH 모션 · 판정값/임계값에 관여하는 코드는 건드리지 않는다.** UI 작업 포함 모든 작업에 적용된다. 고칠 이유가 생기면 먼저 홍유빈에게 허락을 받는다.
- 파일 전체 동결: `01_현행코드/jetson_sender.py` · `verify_jetson_safe.py` · `train_fall_safety.py` · `*.joblib` 3개
- `radar_common.py` 동결: `EVENT_SEV` `AUTO_TRIP_EVENTS` `CURR_LIMIT` `VOLT_MIN` `POWER_CONFIRM` `LEAK_LIMIT` `LEAK_CONFIRM` `VIB_DS_THRESH` `SEV_RANK` `CEILING_H` `FRAME_INNER_HALF` `ENTRY_BAND` `PH_*` `CMD_*` `ZONE_IDS` `EVENT_ZONE` + 모든 딕셔너리 키
- 수정 허용: `console_ui.py` · `radar_core.py` · `radar_common.py`의 표시 문구·색·폰트 **값만**(키 불변)
- SHA-256 기준값·검증 절차: `AGENTS.md`/`CLAUDE.md` 최상단, `04_문서/설계/판정코드_동결_0824.md`

## State

- Updated: 2026-08-24 · Cowork
- Branch: main
- Commit: `ac6fbbc` — `origin/main`보다 **6커밋 앞섬(미푸시)**
- Working tree: `01_현행코드/` 4개 파일이 M 으로 뜨지만 **코드 실변경 0줄**이다. CRLF/LF 혼재로 인한 줄바꿈 노이즈뿐 — `git diff --ignore-all-space HEAD -- 01_현행코드/` 가 빈 출력임을 확인했다.
- 문서 변경: `README.md` `AGENTS.md` `CLAUDE.md` `HANDOFF.md` `REVIEW.md` 최상단에 판정 동결 블록 삽입 · 신규 `04_문서/설계/판정코드_동결_0824.md` · 신규 `04_문서/진행보고/시연_런북_0824.md`

## Current objective

**판정 코드는 동결이다(위 블록). 이번 세션은 UI·시연 자료만 만진다.** 8/24 실물 시연에서 낙상·과전류·협착·감전모의 4경로가 전부 화면에 표시되는 것을 확인했고, 남은 일정은 판정 개선이 아니라 UI·영상 품질에 쓴다는 것이 사용자 결정이다. `jetson_sender.py` 는 열지 않는다.

## Verified baseline

- 8/24 실물 시연 4경로 표시 실패 0건(낙상 / 과전류+무동작 / 과전류+PINCH 모션 / 누설모의+무동작). 경보까지의 실측 경과시간은 측정하지 않았다.
- 낙상 `classify()` 실측·합성 9,580건 불일치 0건 · 젯슨 안전성 검사 87건 실패 0건.
- 협착 PINCH 는 **시연자 A 고정 규칙**이다. A 8/10·A 정상 30건 오탐 0. B 4/10 · C 1/10 으로 일반화되지 않는다. Cowork 재현에서 `still` 이 B 6/10 · C 9/10 통과 — 시연자가 A 가 아니면 오작동으로 보인다.
- 동결 기준 SHA-256 `jetson_sender.py` = `18d2ede32dda6148c44d61a4e169cf271069d020351444c5c05169478aa76a2a`.

## Next actions

1. UI 작업은 `console_ui.py` · `radar_core.py` 와 `radar_common.py` 의 표시 문구·색·폰트 **값**만. 딕셔너리 키와 판정 상수는 건드리지 않는다.
2. 작업 후 `sha256sum 01_현행코드/jetson_sender.py` 로 동결 확인. 값이 위와 다르면 커밋하지 말고 되돌린다.
3. 미푸시 6커밋과 문서 변경분 커밋·푸시 여부를 사용자에게 확인.

## Blockers

1. `01_현행코드/*.py` 줄바꿈 CRLF/LF 혼재 — `git diff` 가 실변경보다 25배 크게 나온다. 판단은 `--ignore-all-space` 와 SHA-256 으로 한다. `.gitattributes` 정규화는 별도 항목.
2. `INBOX.md` 10/10 포화 — 새 지시 항목을 넣으려면 기존 항목 정리가 먼저다.
3. INA226 #2 미도착 — 누설전류는 단일 INA 3구간 모의로 대체 중이다.

## Acceptance

`jetson_sender.py` SHA-256 불변 · `01_현행코드/` 실변경(공백 무시) 0줄 · `scripts/validate_ai_bridge.py` 와 `scripts/validate_handoff.py` 위반 0건.
