# AI_BRIDGE — 소통 창구

> **여기는 소통이고, `HANDOFF.md` 는 실행이다.** 섞지 않는다.
> **기본 세션 시작 시 읽지 않는다.** 명시적 sync 또는 `session-end` triage 때만 연다.

## 문서마다 정본이 하나다

| 문서 | 담는 것 | 읽는 쪽 |
|---|---|---|
| `AI_BRIDGE/REVIEW.md` | **GPT ↔ Cowork 검토 왕복.** 결론이 안 나도 되는 유일한 곳 | Cowork·GPT (**Claude Code 는 안 읽는다**) |
| `AI_BRIDGE/INBOX.md` | 사용자·GPT·Cowork → Claude Code. **검토를 거친** 요청·제안·판단사항 | triage 때만 |
| `AI_BRIDGE/OUTBOX.md` | Claude Code → 사용자·GPT·Cowork. 질문·차단 요소·불일치·판단 요청 | triage 때만 |
| `04_문서/BACKLOG.md` | 언젠가 처리할 **제품 작업과 개선 이슈** | Cowork |
| `HANDOFF.md` | triage 를 통과한 **다음 세션 실행 항목 최대 3개** | 세션 시작 시 항상 |
| `git log` | **완료 이력의 정본** | |
| `04_문서/*.md` | 설계 결정 근거(ADR) | 필요할 때 |

## 흐름

```
GPT ↔ Cowork 검토        REVIEW.md          대화형 · 결론 없어도 됨
        │ 합의
        ├──→ INBOX.md    실행 요청
        ├──→ 04_문서/    설계 결정(ADR)
        ├──→ BACKLOG.md  언젠가 할 이슈
        └──→ 폐기
                │ triage
                ▼
        HANDOFF.md       다음 세션 실행 항목 최대 3개
                │
                ▼
        Claude Code 실행 ──→ OUTBOX.md  질문 · 막힘 · 불일치
                                  │
                                  ▼
                        사용자·GPT·Cowork 가 읽고 REVIEW/INBOX 로 답한다
```

**GPT 는 INBOX 에 직접 쓰지 않는다.** REVIEW 를 거친다 — triage 없이 직통하면
이 구조를 만든 이유가 없어진다.

## 운영 규칙

1. **Claude Code 는 작업 도중 `HANDOFF.md` 를 수정하지 않는다.**
2. **Claude Code 의 막힘·판단 요청은 `OUTBOX.md` 에 쓴다.** `HANDOFF` 의 Blockers 에 직접 쓰지 않는다.
3. `HANDOFF.md` 는 `session-end` 과정에서만 **전체 재작성**한다. append 금지.
4. INBOX·OUTBOX 항목은 triage 후 다음 중 하나로 **이동하고 원본에서 지운다** — `HANDOFF` / `BACKLOG` / ADR / 폐기.
5. **완료 기록을 AI_BRIDGE 와 HANDOFF 에 남기지 않는다.**
6. 완료 이력의 정본은 git history 다.
7. INBOX·OUTBOX 는 각각 **열린 항목 최대 10개.** 넘치면 triage 를 미룬 것이다.
   `REVIEW.md` 는 개수 제한이 없다 — 대신 결론이 나면 즉시 옮기고 지운다.
8. `HANDOFF` 는 **다른 문서를 읽지 않아도 실행 가능하게** 쓴다.

## 항목 형식

```
### IN-003  제목
- From: 사용자 | GPT | Cowork
- Type: 요청 | 제안 | 판단사항 | 불일치
- Needs: 승인 | 결정 | 확인 | 검토
본문 — 무엇을, 왜. 3줄 이내.
```

OUTBOX 는 `OUT-001` 로 매긴다. **ID 는 재사용하지 않는다.**

## 검사

```powershell
python scripts\validate_ai_bridge.py
python scripts\validate_handoff.py
```
