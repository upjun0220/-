# OUTBOX — Claude Code → 사용자·GPT·Cowork

> 질문·차단 요소·불일치·판단 요청. triage 후 이동하고 여기서 지운다. 최대 10개.

### OUT-004  젯슨 하드웨어 헬스 필드 추가 여부 — 보류 유지 (2026-08-17 재확인)
- From: Claude Code
- Type: 판단사항
- Needs: 결정 (계속 보류)
CPU·메모리·온도를 화면에 띄우려면 `radar_common.py` 스키마에 필드를 넣어야 하는데 이 파일은 젯슨과 공용이다.
한쪽 편의로 고치면 다른 쪽이 죽는다. 사용자 결정(2026-08-17): 아직 통합시험 판단 시점이 아니므로 보류 유지.

### OUT-005  동기화된 규칙 문서의 주체명 중복
- From: Codex
- Type: 불일치
- Needs: 확인
`AGENTS.md` §10 규칙 문서 수정권에 `AGENTS.md`·`.agents/skills/`가 각각 중복되고 “Codex와 Codex”로 적혀 있다.
이틀 동결 규칙에 따라 수정하지 않았다. 동결 해제 후 정본의 의도한 주체명과 생성 대상명을 확인해야 한다.

### OUT-007  모델·판정 구조 변경 전 승인과 애매한 지시 확인을 상시 규칙으로 추가 요청
- From: Codex
- Type: 사용자 지침
- Needs: 정본 반영

사용자 요청(2026-08-14):
1. 모델 교체, 판정 구조 변경, 운영 임계값 변경처럼 결과를 크게 바꾸는 사항은 구현·배포 전에 반드시 사용자에게 먼저 묻고 승인받는다.
2. 사용자 의도나 작업 범위가 애매하면 임의로 해석하지 않고 반드시 질문한다.

Codex는 규칙 문서 수정권이 없으므로 `AGENTS.md` 및 필요한 스킬 정본에 위 두 항목을 반영해 달라.

### OUT-008  fast_sit 시나리오 임시 제외
- From: Codex
- Type: 사용자 결정
- Needs: 정본 반영

사용자 결정(2026-08-14): fast_sit은 실제 시연 계획이 없으므로 다음에 사용자가 다시 언급할 때까지 데이터 수집·학습·평가·시연 기준에서 제외한다. 8/13 A의 `fast_sit` 6건은 현장 메모상 실제 crouch이므로 crouch로만 사용한다.

### OUT-009  EVENT_KO 7종 중 3종만 검증 — 발표 표현 변경 필요 (Cowork)
- From: Claude Code
- Type: 결정사항 → 문서 반영 대기
- Needs: 정본 반영
사용자 결정(2026-08-17): 감전·협착·과전류·전압강하 4종은 데모·시뮬·jsonl 어디에도 재현 사례가 없어
렌더링 검증이 안 됐다. 발표·문서에서 "7종 지원" 대신 "낙상·정지형·진동 3종 실측 검증"으로 표현 변경.
재현 도구는 만들지 않는다. README/발표자료 수정은 Cowork 담당.

### OUT-011  events_still.jsonl 로컬 부재 — 검증 2종 보류
- From: Claude Code
- Type: 불일치
- Needs: 확인
`03_데이터/이벤트_학습용/`에 `events_fall_5people_20260813_1.jsonl`만 있고 `replay_jsonl.py`
기본값인 `events_still.jsonl`이 없다. HANDOFF 8/10 기록엔 이 파일로 73건 통과했다고 남아 있어
그 뒤 이동·정리된 것으로 보인다. 사용자 결정(2026-08-18): 지금은 보류, 파일을 찾으면 재검증.
`테스트_실데이터_재생.py`·`테스트_평면도_경보흐름.py` 실행 불가 상태.

### OUT-012  yubinhong1112-spec 병합으로 README.md 8건 함께 반영됨
- From: Claude Code
- Type: 불일치
- Needs: 확인
사용자 요청(2026-08-18)으로 `github.com/yubinhong1112-spec/radar-guard`를 `git merge`했다.
README.md §10 담당은 Cowork인데, 병합 특성상 8/15~8/17 일지 8건이 함께 들어왔다(커밋 `08dee59`).
형식·중복 여부 검토 바람.

### OUT-013  StationaryGate + RF30 판정 경로 병합 — 모델 미탑재로 비활성
- From: Claude Code
- Type: 판단사항
- Needs: 확인
사용자 결정(2026-08-18)으로 `jetson_sender.py`에 `StationaryGate`(점군 소실 후 마지막 신뢰 위치
유지)와 RF30(30프레임 배경제거 낙상분류기) 조건부 경로를 병합했다. `fall_classifier_hybrid30.joblib`
파일이 없어 RF30은 자동 폴백 중이며, `STAT_RESET_DS=0.38`은 원 저장소 README에도 "확정값 아님"으로
적혀 있다. `verify_port.py`(4,137건 0)·`verify_jetson_safe.py`(61/0, StationaryGate 9건 포함)는
통과했지만 실기 젯슨 검증은 0건.

### OUT-010  외부 CLAUDE.md(andrej-karpathy-skills) 반영 제안
- From: Claude Code
- Type: 판단사항
- Needs: 결정
사용자 요청: `https://raw.githubusercontent.com/forrestchang/andrej-karpathy-skills/main/CLAUDE.md`
내용을 현재 `CLAUDE.md`에 반영. 그 문서는 "가정 금지·최소 변경·목표 기반 검증"을 다루는 범용 코딩
지침으로, 이 프로젝트 `CLAUDE.md` §9(필요한 최소만, 추측 기반 추상화 금지) 및 설치된 `ponytail`
플러그인과 상당 부분 겹친다. §10에 따라 Claude Code는 `CLAUDE.md`를 직접 고치지 않는다.
Cowork가 §9와 중복 없이 반영할지, 폐기할지 결정 바람.
