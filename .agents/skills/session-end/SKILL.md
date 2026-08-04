---
name: session-end
description: 코드 작업 세션을 마무리한다. 검증 → OUTBOX 기록 → HANDOFF.md 전체 재작성 → 형태 검사 → 커밋을 정해진 순서로 수행. 사용자가 "작업 종료", "세션 종료", "마무리해줘", "오늘 여기까지", "정리하고 커밋해줘"라고 하거나 /session-end 를 부를 때 사용한다. Cowork 가 다음 세션에 읽을 인계 노트를 남기는 것이 목적이다.
---

# 작업 세션 마무리

## 왜 필요한가

Codex 와 Cowork 는 **기억을 공유하지 않는다.** 이 세션에서 알아낸 것을 `HANDOFF.md` 에 남기지 않으면, 다음에 Cowork 는 아무것도 모르는 채로 문서를 쓴다. 그러면 README 와 보고서에 틀린 내용이 들어간다.

**`git log` 가 담는 것과 `HANDOFF.md` 가 담는 것은 다르다.** 무엇이 바뀌었는지는 git 이 정본이다. 여기엔 git 이 담을 수 없는 것만 쓴다 — 왜 그렇게 했는지, 무엇에 막혔는지, 다음에 뭘 해야 하는지.

## 순서 (건너뛰지 않는다)

### 1. 검증
`01_현행코드/` 의 `.py` 를 건드렸으면 `ui-verify` 스킬을 **먼저 끝까지** 돌린다. 통과하지 못한 채로 마무리하지 않는다.
NG 가 남았으면 고치거나, 못 고쳤으면 `AI_BRIDGE/OUTBOX.md` 에 명시한다. **조용히 넘어가지 않는다.**

### 2. 무엇이 바뀌었는지 확인
```powershell
git status --short
git diff --stat
```
사용자에게 변경 요약을 보여주고 커밋해도 되는지 확인받는다.

### 3. 막힘·판단 요청은 `AI_BRIDGE/OUTBOX.md` 에 쓴다

**`HANDOFF.md` 의 Blockers 에 직접 쓰지 않는다.** HANDOFF 는 실행 지시서고, OUTBOX 는 소통 창구다.

```
### OUT-005  제목
- From: Codex
- Type: 판단사항 | 불일치 | 질문
- Needs: 결정 | 승인 | 확인
본문 3줄 이내 — 무엇이 막혔고, 무엇을 결정해야 하는지.
```

ID 는 재사용하지 않는다. 열린 항목은 최대 10개다.
**지시와 다르게 한 것과 그 이유**도 여기 쓴다 — 말없이 다르게 하면 Cowork 가 틀린 문서를 쓴다.

### 3-1. `HANDOFF.md` **전체 재작성** — append 하지 않는다

**기존 내용에 덧붙이지 마라.** 처음부터 다시 쓴다. 이게 이 단계의 핵심이다 —
덧붙이면 완료된 지시가 남아 다음 세션이 그걸 '할 일'로 읽는다.
(실제로 §1 이 규칙 10줄의 7.7배인 77줄까지 불어난 적이 있다.)

**허용 섹션은 6개뿐이다.** 다른 섹션을 만들지 않는다.

`## State`(Updated/Branch/Commit/Working tree) · `## Current objective`(하나) ·
`## Verified baseline` · `## Next actions`(최대 3) · `## Blockers / unknowns`(최대 3) · `## Acceptance`

**HANDOFF 는 자족적이어야 한다.** 다른 문서를 읽지 않아도 실행할 수 있게 쓴다.
BACKLOG·INBOX·OUTBOX 를 참조하라고 쓰지 않는다.

**쓸 것**
- 다음 세션이 **실제로 수행할** 명령형 항목만 (최대 3)
- 검증 결과 **숫자** — Verified baseline 에 (예: "35·0 / 0건 / 64·0 / 16·0")
- 아직 답이 없는 **미지수** — Blockers 에. 판단 요청은 OUTBOX 로 간다

**쓰지 말 것 — 정보마다 정본이 하나다**
| 내용 | 정본 |
|---|---|
| 완료 이력 · 파일별 변경 | `git log` / `git diff` |
| 질문 · 판단 요청 | `04_문서/AI_BRIDGE/OUTBOX.md` |
| 언젠가 할 개선 이슈 | `04_문서/BACKLOG.md` |
| 설계 근거 · 장기 결정 | `04_문서/` |
| 프로젝트 규칙 | `AGENTS.md` · 스킬 |

**완료된 항목은 즉시 삭제한다.** 체크박스(`[x]`)·"완료"·날짜 머리 항목은 금지다.

### 3-2. 형태 검사 (환경: 내 PC PowerShell)

```powershell
python scripts\validate_handoff.py
python scripts\validate_ai_bridge.py
```

**둘 다 종료코드 0 이 아니면 커밋하지 않는다.**
NG 는 요약을 더 잘 쓰라는 뜻이 아니라 **끝난 것을 지우라는 뜻**이다.

### 4. 커밋
```powershell
git add -A
git commit -m "<무엇을 왜 바꿨는지, 한국어 한 줄>"
```

`01_현행코드/*.py` 를 고쳤는데 `HANDOFF.md` 를 안 고쳤으면 **pre-commit 훅이 커밋을 막는다.**
그건 오류가 아니라 3단계를 건너뛰었다는 뜻이다.
훅 우회(`--no-verify`)는 **사용자가 명시적으로 요청할 때만** 쓴다.

### 5. 마지막 보고
사용자에게 한두 문장으로: 무엇이 끝났고, 무엇이 남았고, 다음에 뭘 할지.

## 하지 말 것
- 검증을 안 돌리고 마무리
- 실행하지 않은 검증을 "통과"로 기재
- `HANDOFF.md` 를 **작업 도중에** 수정 (session-end 에서만 고친다)
- HANDOFF 에 append — **전체 재작성이 원칙이다**
- 변경 내역·완료 이력을 HANDOFF 에 나열
- 막힘·판단 요청을 HANDOFF 의 Blockers 에 직접 기재 (→ OUTBOX)
- 검사 스크립트를 안 돌리고 커밋
