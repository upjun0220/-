# HANDOFF

> 다음 세션의 실행 지시서다. 소통 창구가 아니다.

## State

- Updated: 2026-08-20 · Claude Code
- Branch: main
- Commit: `620eec6` — `origin/main`보다 앞섬(미푸시). 이 세션 변경분은 아직 커밋 전
- Working tree: `jetson_sender.py`·`console_ui.py`·`radar_core.py`·`radar_common.py`(차단 범위 문구를 `BREAKER_SCOPE='작업 대상 설비 회로'`로 통일, 판정 로직 무변경)·문서 4건 수정

## Current objective

차단 범위 표현 정정(문구·문서만, 판정 로직 무변경) — `radar_common.BREAKER_SCOPE` 신설, "구역 전원" 계열 문구 전부 "설비 회로"로 교체. PHASE 1(낙상 선점) 젯슨 배포는 이미 끝났고, **PHASE 1 실측 4개 기준은 아직 사람이 확인 안 함** — 이게 다음 세션의 최우선 순위다.

## Verified baseline

- 젯슨 배포 마침(2026-08-20, IP `172.20.10.4`): 배포 전 발견한 문제 — 기존에 떠 있던 `radar_parser.py`가 `stage1_filtered.json`이 아니라 `stage1_filtered_0820.json`(팀원 흔적 추정)에 쓰고 있어 sender가 데이터를 못 읽었다. 재시작으로 해결, `[RF]`/`[RF30]` 로드 OK, UI 연결·WARMUP 진행 확인.
- 이번 문구 변경 검증: pyflakes(무관 경고 1건 제외)·verify_jetson_safe 61건·validate_ai_bridge 전부 0건. `grep -rn "구역 전원" 01_현행코드/` 0건. `_can_latch` 7건·`_SEV_RANK` 3건·`severity']=='critical'` 존재 — 전부 지시서 예상치와 일치(로직 미변경 증명).
- **PHASE 1 실측 4개 기준은 아직 미확인**: 60초 대기 후 낙상 2초 이내 / `dt` 중앙값 0.063~0.08 / fnum diff 20초간 미증가 / `[TIMING]` 비용 미증가. 배포는 됐지만 실제 낙상 시연을 아직 안 함.

## Next actions

1. **입실 60초 대기 → 낙상**으로 PHASE 1 4개 기준 실측(위 목록). 통과해야 PHASE 2(감전·협착) 착수 가능.
2. 이번 문구 변경분(4개 코드 파일 + 문서 4건) 커밋.
3. 통과 후 PHASE 2: `radar_common` 스키마(`electric_shock_risk_confirmed`/`insulation_fault`)·`--hazard` CLI·화면 정리(관심영역 삭제).

## Blockers

1. PHASE 1 실측 4개 기준이 사람의 실시연 없이는 확인 불가 — 다음 세션 최우선.
2. INA226 #2(누설전류) 미도착 — PHASE 2 감전 확정 경로는 자리만 가능.

## Acceptance

PHASE 1: 위 4개 실측 기준 충족. 이후에만 PHASE 2 착수 — `STATIONARY_ENABLED=True` 전환도 이때까지 금지.
