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
