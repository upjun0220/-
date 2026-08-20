# HANDOFF

> 다음 세션의 실행 지시서다. 소통 창구가 아니다.

## State

- Updated: 2026-08-20 · Claude Code
- Branch: main
- Commit: `3150738` — `origin/main`보다 앞섬(미푸시). 이 세션 변경분은 아직 커밋 전
- Working tree: `jetson_sender.py`(낙상 선점 1차: `_can_latch`/`_log_dropped`)·`테스트_낙상선점_상태기계.py`(신규)·설계문서 2건(신규, Cowork) 수정

## Current objective

통합 지시서(2026-08-20, ADR `04_문서/설계/감전_협착_판정구조_0820.md` 근거)의 PHASE 1 진행 중: 경보 latch를 등급 배타 구조로 재설계(`_can_latch(new_et, new_sev)` — critical 떠 있으면 원칙 차단, 예외는 `electric_shock_risk_confirmed`뿐). 이전 세션에 만든 1차 `_can_latch(new_sev)`는 이 스펙보다 단순해 교체 필요. PHASE 2(감전·협착 이벤트·hazard 필드·화면 정리)는 PHASE 1 배포·검증 전까지 착수 금지(지시서 명시).

## Verified baseline

- PHASE 1 1차 구현(구 `_can_latch`) 상태기계 전용 테스트(`테스트_낙상선점_상태기계.py`) 14건 통과, 6종 회귀 스크립트 전부 0건.
- **젯슨 배포 전 네트워크 끊김** — 이 PC IP가 `172.20.10.12`(젯슨 핫스팟)에서 `10.28.29.204`(다른 망)로 바뀌어 젯슨(`172.20.10.10`) 접속 불가. PHASE 1 합격 기준(60초 대기 후 낙상 2초 이내, dt 중앙값 0.063~0.08, fnum diff 20초간 미증가, `[TIMING]`)은 **전부 미검증**.
- 팀 공유 문서(`04_문서/진행보고/팀공유_0820_...md`)에 팀원(승원)이 별도로 `n_jobs=1`·RF를 `_lock` 밖으로 옮겨 젯슨에서 실측(rf 118.1ms→67.9ms)했다는 기록 있음 — **이 저장소의 `jetson_sender.py`에 반영됐는지 미확인, 젯슨 재접속 후 대조 필요**.

## Next actions

1. `_can_latch`를 신규 스펙(critical 배타, 감전확정 예외, 등급승격은 별도 경로로 ev_id 유지)으로 교체하고 로컬 6종 회귀 통과.
2. 네트워크 복구 후 젯슨 현재 `jetson_sender.py` 상태를 먼저 diff로 확인(팀원 승원의 별도 수정과 충돌 여부) 후 배포.
3. PHASE 1 합격 기준 4개 실측 후에만 PHASE 2(감전·협착) 착수.

## Blockers

1. 젯슨 네트워크 접속 불가(핫스팟 재연결 필요) — PHASE 1 배포·실측 전부 막힘.
2. 젯슨의 실제 `jetson_sender.py`가 이 저장소 버전과 일치하는지 미확인(팀원 병행 수정 가능성).
3. INA226 #2(누설전류) 미도착 — PHASE 2 감전 확정 경로는 자리만 만들고 실동작 불가.

## Acceptance

PHASE 1: `_can_latch` 신규 스펙 반영, 6종 회귀 0건, sim_jetson.py 시나리오(경고 중 낙상 선점/critical 중 critical 차단/상황종료 후 정상 latch) 통과, 젯슨 배포 후 4개 실측 기준 충족. 이후에만 PHASE 2 시작.
