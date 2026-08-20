# HANDOFF

> 다음 세션의 실행 지시서다. 소통 창구가 아니다.

## State

- Updated: 2026-08-20 · Claude Code
- Branch: main
- Commit: `d6828c5` — `origin/main`보다 앞섬(미푸시). 이 세션 변경분은 아직 커밋 전
- Working tree: `jetson_sender.py`(`_can_latch(et,sev)` 신규 스펙 교체·`_upgrade_severity` 추가)·`테스트_낙상선점_상태기계.py`(시나리오 4·5 추가) 수정

## Current objective

통합 지시서(ADR `04_문서/설계/감전_협착_판정구조_0820.md`)의 PHASE 1 코드 반영: `_can_latch(et,sev)`를 critical 배타(감전확정만 예외) 구조로 교체, `_upgrade_severity()`(PHASE 2 예비, 호출부 없음) 추가. PHASE 2(감전·협착 이벤트·hazard 필드·화면 정리)는 PHASE 1 젯슨 배포·실측 4개 기준 통과 전까지 착수 금지(지시서 명시, 아직 미착수).

## Verified baseline

- 로컬 회귀 전부 0건: pyflakes(무관 사전경고 1건 제외)·verify_port 9,580건·verify_jetson_safe 61건·v1결함36·평면도경보흐름16.
- 상태기계 전용 테스트 17건 통과 — 정지형→낙상 선점, critical 상호배타(낙상↔낙상·낙상↔정지형), 감전확정 예외(critical 떠 있어도 선점), 감전확정 자기 자신은 배타.
- sim_jetson.py/replay_jsonl.py는 UDP 패킷을 흉내낼 뿐 jetson_sender.py의 `_can_latch`를 실제로 호출하지 않아 이 로직 검증에 못 쓴다 — 직접 함수 호출 테스트로 대체(위).
- **여전히 미검증**: 젯슨 배포·PHASE 1 합격 기준 4개(60초 대기 낙상 2초 이내 / dt 중앙값 0.063~0.08 / fnum diff 20초간 미증가 / `[TIMING]` 비용 미증가) — 네트워크 끊김으로 배포 자체를 못 함.

## Next actions

1. 네트워크(핫스팟) 복구 후 젯슨 현재 `jetson_sender.py`를 diff로 먼저 확인(팀원 승원이 n_jobs·RF-lock-분리를 별도로 실측했다는 기록이 있어 충돌 가능) 후 이 버전을 배포.
2. PHASE 1 합격 기준 4개 실측(위 목록) — 전부 통과해야 다음 단계.
3. 통과 후에만 PHASE 2(감전·협착: radar_common 스키마·hazard CLI·화면 정리) 착수.

## Blockers

1. 젯슨 네트워크 접속 불가 — PHASE 1 배포·실측 전부 막힘.
2. 젯슨의 실제 `jetson_sender.py`가 이 저장소 버전과 일치하는지 미확인(팀원 병행 수정 가능성, 승원 8/20 작업).
3. INA226 #2(누설전류) 미도착 — PHASE 2 감전 확정 경로는 자리만 가능.

## Acceptance

PHASE 1: 젯슨 배포 후 4개 실측 기준 충족. 이후에만 PHASE 2 시작 — `STATIONARY_ENABLED=True` 전환도 이때까지 금지.
