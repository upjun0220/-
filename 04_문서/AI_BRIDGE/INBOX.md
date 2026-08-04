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

**세션 끝마다**: `session-end` — HANDOFF 전체 재작성(append 금지) → 검사 3종 종료코드 0 → 커밋.
의미 있는 세션은 `readme-log` 로 README 에 날짜 헤더 + 문제→해결 + 검증 숫자.

**Cowork 복귀 시 읽는 순서**: `git log` → README 최신 세션 → `HANDOFF.md` → `OUTBOX.md`.
