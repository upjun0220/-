# INBOX — 사용자·GPT·Cowork → Claude Code

> 아직 **검토되지 않은** 것만 둔다. triage 후 이동하고 여기서 지운다. 최대 10개.

### IN-001  qt-ui-design 스킬 설치
- From: 사용자
- Type: 요청
- Needs: 확인
Qt 공식 `qt-development-skills` 중 `qt-ui-design` 하나만 `.claude/skills/` 에 복사한다.
나머지 11개는 QML·C++·Figma 전용이라 PyQt5 에 안 붙는다. 마켓플레이스명은 `qt-skills-and-tools`.
QML 예시는 복사하지 말고 QtWidgets/QSS 로 번역한다.

### IN-002  CLAUDE.md 축약 승인 대기
- From: Cowork
- Type: 제안
- Needs: 승인
202줄 중 스킬과 중복(§5 검증명령·§6 README형식·§7 UI원칙·§10 인계규칙),
매 세션 불필요(§1 젯슨 스펙·§3 파일 줄수·§3 도구표), 시점 상태(확정 날짜·모델 폐기 이력)를 정리하면 110~130줄.
**§4(절대 금지)와 §8(물리 한계)은 중복이어도 유지 권장.** 승인 전 삭제하지 않는다.

### IN-003  8/04~8/05 는 Codex 단독 진행 — 인계 방법
- From: 사용자
- Type: 요청
- Needs: 확인
Cowork·Claude Code 크레딧 소진으로 **8/05(화) 밤 10시까지 Codex 만 작업**한다.
읽는 규칙은 `AGENTS.md` + `.agents/skills/` 다(`.claude/` 쪽과 내용 동일, 8/04 동기화됨).

**규칙 문서는 이틀간 동결한다.** `AGENTS.md`·`.agents/skills/`·`CLAUDE.md`·`.claude/skills/` 를 고치면
정본과 어긋나 `sync_agent_docs.py --check` 가 커밋을 막는다. 고칠 것이 보이면 `OUTBOX.md` 에 제안만 쌓는다.
`HANDOFF.md`·`OUTBOX.md`·`README.md`·`BACKLOG.md` 는 규칙 문서가 아니므로 평소대로 쓴다.

**작업 순서**: HANDOFF Next actions 1→2→3 → 8/05 젯슨 통합시험(런북) → 그래도 남으면
`BACKLOG.md` A층에서 꺼내되 **사용자 승인 후**. `REVIEW.md` 에는 쓰지 않는다(읽는 쪽이 없다).

**세션 끝마다**: `session-end` — `ui-verify` **4종 먼저**(35·0 / 0건 / 64·0 / 16·0, pyflakes 0) →
HANDOFF 전체 재작성(append 금지) → `scripts/` 검사 3종 종료코드 0 → 커밋.
**⚠ `ui-verify` 를 화요일로 미루지 않는다.** pre-commit 은 HANDOFF 갱신만 강제하고 검증 통과는 강제하지 않는다.
그리고 Cowork 는 리눅스 샌드박스라 PyQt5 를 못 돌린다 — **검증은 Codex 만 할 수 있다.**
미뤘다가 NG 가 나면 커밋 여러 개 중 어느 것이 깨뜨렸는지 역추적해야 한다.
의미 있는 세션은 `readme-log` 로 README 에 날짜 헤더 + 문제→해결 + 검증 숫자.

**Cowork 복귀 시 읽는 순서**: `git log` → README 최신 세션 → `HANDOFF.md` → `OUTBOX.md`.

### IN-004  Cowork 세션이 남긴 잔여물 2건 삭제
- From: Cowork
- Type: 요청
- Needs: 확인
`.git/index.lock` (8/19 04:39, 0바이트) — Cowork 리눅스 VM 이 `git check-ignore` 중 만들고 삭제 권한이 없어 남겼다. 이게 있으면 모든 git 작업이 막힌다.
`Projects/공모전/` — 8/13 저장소 이전 잔여 빈 폴더. 옛 경로를 참조하는 스크립트가 `cd` 에 성공해 버려 오류가 늦게 드러난다. 삭제 전 git 추적 여부를 먼저 본다.

### IN-005  jetson-deploy 스킬의 경로와 접속 방식이 실제와 다르다
- From: Cowork
- Type: 불일치
- Needs: 확인
스킬 §검증의 `cd "C:\Users\82102\OneDrive\문서\Claude\Projects\공모전\01_현행코드"` — 저장소는 `C:\dev\radar-guard` 다. 이 스킬을 따르면 첫 줄에서 죽는다.
스킬 표와 `CLAUDE.md` §1 표가 `접속 = 시리얼 COM13` 만 적으나, README 의 실측 절차는 `scp … project@<젯슨IP>:~/` 인 SSH 다. COM13 은 네트워크 두절 시 콘솔 경로로 보인다 — 실제 운용 경로를 확인해 두 표를 고친다.
규칙 문서를 고친 뒤 `scripts/sync_agent_docs.py` 로 `.agents/` 쪽과 맞춘다.

### IN-006  젯슨 IP 가 코드 기본값과 문서에서 어긋난다
- From: Cowork
- Type: 불일치
- Needs: 결정
`radar_core.py:1730` 기본값은 `192.168.0.50`, README 실측 기록은 `192.168.35.217` 이다. 핫스팟 DHCP 라 접속마다 바뀐다.
현재 IP 를 확인해 대조하고, 데모 당일 대비로 이더넷 직결 고정 IP 로 갈지 사용자 판단을 `OUTBOX.md` 에 올린다. 코드 기본값은 판단 전에 바꾸지 않는다.

### IN-007  젯슨 배포와 회수를 한 명령으로 묶는 스크립트
- From: Cowork
- Type: 제안
- Needs: 승인
`scripts/jetson_snapshot.ps1` — SSH 확인 → 원본 백업 → `scp` 배포 → 젯슨에서 재학습과 4종 시험(낙상·팔흔들기·쪼그리기·난음성) → `clf_decisions.jsonl` 과 모델 로드 로그를 `03_데이터/` 로 회수. 사용자가 치는 명령을 1개로 줄이고, 회수한 파일은 Cowork 가 분석한다.
`jetson-deploy` 규칙을 그대로 따른다 — 접속·전송 명령은 실행 전 사용자 승인을 받고, `verify_port.py`·`verify_jetson_safe.py` 종료코드 0 전에는 전송하지 않는다.
IN-005 의 접속 방식 확인이 선행 조건이다. SSH 가 아니라면 이 제안은 성립하지 않으니 `OUTBOX.md` 로 되돌린다.

### IN-008  낙상 미검출 1순위 — 현재 낙상 모델의 재현율이 54.9%다
- From: Cowork
- Type: 불일치
- Needs: 결정
`01_현행코드/fall_classifier.joblib` 안에 학습 지표가 그대로 들어 있다 — `tp 56 / fn 102-56=46`, 즉 낙상 재현율 **56/102 = 54.9%**. `threshold=0.7846`, 정책은 `LOSO max recall with wave FP=0`. 팔 흔들기 오탐 0을 지키려고 낙상 절반을 버린 임계값이다. 라이브에서 절반이 안 잡히는 것은 설계대로 도는 결과다.
`maint mode` 가설은 성립하지 않는다 — `jetson_sender.py:140` `MAINT_MODE = False` 이고, 참조 2곳(1298·1987)이 전부 정지형 경보 전용이다. 낙상 경로에 관여하지 않는다.
젯슨의 `~/fall_classifier.joblib` 이 저장소 사본과 같은 파일인지 sha256 대조가 먼저다. 다르면 위 수치는 무효다.

### IN-009  개선된 hybrid30 모델이 파일명 불일치로 로드되지 않는다
- From: Cowork
- Type: 불일치
- Needs: 확인
`jetson_sender.py:227` 은 `~/fall_classifier_hybrid30.joblib` 을 찾는데 저장소 파일명은 `fall_classifier_hybrid30.candidate.joblib` 이다. 없으면 `RF30_OK=False` 로 조용히 legacy20 으로 내려가고 콘솔에 `[RF30] 모델 없음/로드실패` 한 줄만 남는다.
그 hybrid30 후보의 재현율은 **36/50 = 72.0%** (threshold 0.5925, wave 오탐 0/26) 로 legacy20 보다 17.1%p 높다. 다만 `height_background` 10복셀이 특정 빈방 녹화(`empty_sha256`)에 묶여 있어 환경이 바뀌면 무효다 — 젯슨 재학습이 HANDOFF Next action 1 인 이유가 이것이다.
학습 제외 표본에 `E:fall:10` 이 들어 있다. HANDOFF Blocker 2 의 "E 낙상 1/10건" 과 같은 표본이다.

### IN-010  정지형 죽은 코드 4겹과 동일분기 제거
- From: Cowork
- Type: 요청
- Needs: 승인
`jetson_sender.py` 정지형 경로가 네 겹으로 꺼져 있다 — `STATIONARY_ENABLED=False`(139행), `if True: pass` + elif 사슬(1913~1965, 53줄), `if False and ...`(1967·1975), `if False:`(2168~2191, 24줄). 도달 불가 코드 약 90줄이다.
1987~1997 의 `if MAINT_MODE:` / `else:` 는 **양쪽 본문이 완전히 같다.** 어느 쪽으로 가도 결과가 같으므로 편집 사고로 보인다.
`jetson_sender.py:903` `post_walk` 는 계산만 하고 쓰이지 않는다(pyflakes 유일 경고). `console_ui.py:2825` `visible` 도 같다. 삭제 전후로 `verify_port.py`·`verify_jetson_safe.py` 종료코드 0 을 확인한다.
