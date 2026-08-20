# HANDOFF

> 다음 세션의 실행 지시서다. 소통 창구가 아니다.

## State

- Updated: 2026-08-20 · Claude Code
- Branch: main
- Commit: `09f7c10` — `origin/main`과 같음. 이 세션 변경분은 아직 커밋 전이다
- Working tree: `jetson_sender.py`(Modbus lock 분리·RECOVER_DSLO·계측)·`radar_parser.py`(t 필드, 젯슨에서 반입, 신규)·`train_fall_safety.py`(n_jobs)·`04_문서/AI_BRIDGE/INBOX.md` 수정

## Current objective

8/19 낙상 미검출 원인 2건 수정: ① Modbus(BREAKER.on_anomalies)가 프레임 루프 `_lock` 안에서 블로킹 → `power_monitor_loop()`로 분리(1차: 루프 밖 이동, 2차: lock도 밖으로). ② `POSTFALL_GATE`의 `RECOVER_DSLO=0.30`이 실측 잡음 바닥(0.319~0.327)보다 낮아 낙상 후 정지 상태가 늘 취소조건 충족 → 0.45로 임시조치(주석에 실측 아님 명시). 처리율 계측용 `fnum_first/fnum_last/dt`, 1초 주기 tick 로그, `[TIMING]` 구간별 소요시간을 jetson_sender.py에 추가.

## Verified baseline

- 6종 검증 스크립트(pyflakes·v1결함36·레이아웃·verify_port 9,580건·verify_jetson_safe 61건·실데이터재생73·평면도경보흐름16) 반복 통과, 전부 0건. pyflakes 사전경고 1건(`classify()`의 `post_walk` 미사용)은 무관·미수정.
- 젯슨 재배포·재기동 확인, `[RF]`/`[RF30]` 로드 OK.
- 2차 수정 후 실측: dt 중앙값 0.1315초(~7.3fps). 20초 직접측정(parser fnum vs sender fnum_last)에서 diff 1437→1484로 계속 증가 — **파서 9.96fps 대비 부족 상태 잔존, 원인 미확정**.

## Next actions

1. 낙상-정지형 latch 우선순위 역전 수정(`_can_latch`, `_SEV_RANK`) — 사용자 승인된 방침, 구현 대기.
2. `[TIMING]` 로그로 잔존 처리율 부족(t_lock 세부: rf_score·classify·file write 중 무엇이 큰지)을 실측 추가.
3. `STATIONARY_ENABLED=True` 전환은 1번 검증 통과 후에만.

## Blockers

1. Modbus 릴레이 하드웨어가 계속 무응답 — 백오프로 블로킹은 줄였으나 배선/주소 등 근본 원인 미확인.
2. 처리율이 파서 대비 완전히 회복되지 않음 — `[TIMING]` 계측 결과 대기 중.

## Acceptance

latch 우선순위 수정 후: 정지형 CRITICAL 중 낙상 발생 시 화면이 낙상으로 전환되고 `BREAKER.trip()` 호출됨. 낙상 중 정지형/낙상 재발생은 화면 유지·로그만. 6종 검증 스크립트 전부 0건. `[TIMING]` 프레임당 총비용이 수정 전 대비 유의미하게 늘지 않음.
