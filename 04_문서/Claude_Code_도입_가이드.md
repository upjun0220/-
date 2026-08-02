# Claude Code 도입 가이드 — Cowork와 병행하기

> 작성 2026-08-02 · Radar-Guard 프로젝트 기준
> 이 문서대로 따라 하면 Claude Code를 설치하고 Cowork와 충돌 없이 같이 쓸 수 있다.

---

## 0. 먼저 정리 — 무엇이 실제로 좋아지나

### 모델은 같다

Cowork도 Claude Code 엔진 위에서 돈다. **"Claude Code가 코딩을 더 잘한다"는 모델 성능 차이가 아니다.** 차이는 워크플로에 있다.

### 진짜 차이는 실행 환경

| | Cowork | Claude Code |
|---|---|---|
| 셸 | 격리된 **리눅스 샌드박스** | **내 PC의 PowerShell** |
| `python console_ui.py` | 불가 (PyQt 창을 띄울 수 없음) | 가능 |
| COM13 시리얼 (젯슨) | 불가 | 가능 |
| Ollama / PGVector (localhost) | 불가 | 가능 |
| 검증 스크립트 4종 | 불가 | 가능 |

지금까지 Cowork는 **코드를 쓰기만 하고 돌려보지 못했다.** 검증은 전부 홍유빈님이 대신 실행하고 결과를 붙여넣는 방식이었다. Claude Code는 스스로 실행 → 로그 확인 → 수정 루프를 돈다. **이게 도입 이유의 90%다.**

### 그 외 이득

- `CLAUDE.md` 자동 로드 — 매 세션 프로젝트 맥락을 다시 설명할 필요가 없다
- 프로젝트 스킬 (`.claude/skills/`) — "검증해줘" 한마디로 정해진 절차가 돈다
- hooks — 파일 저장할 때마다 pyflakes 자동 실행 같은 게 가능
- plan mode (Shift+Tab 두 번) — 큰 수정 전에 계획을 먼저 승인
- 서브에이전트 / git worktree — 여러 작업을 격리해서 병렬

---

## 1. freezing에 대한 정정 ⚠

**"코드가 길면 freezing이 난다"는 이 경우 맞지 않는다.**

코드를 검사한 결과, 아키텍처는 이미 잘 분리돼 있다. `RadarLink`는 `QThread`, `SopEngine`은 별도 `threading.Thread`, LLM 호출도 백그라운드다. LLM이 UI를 막고 있는 게 아니다.

### 실제 원인 후보 (정적 분석 기준 · 실측 필요)

**① `DashboardPage.push()`에서 10 Hz `setStyleSheet` — 가장 유력**

`console_ui.py:1408`. `on_packet` → `dash.push()` 경로가 패킷마다(초당 10회) 돌면서 라벨 4개에 `setStyleSheet()`를 새로 건다.

```python
self.side_metrics[k].setStyleSheet(f'color:{col};border:none;background:transparent;')
```

Qt의 `setStyleSheet`는 위젯과 그 자식들의 스타일 캐스케이드를 **전부 다시 계산**한다. 프레임 루프 안에서 부르면 안 되는 함수다.
→ **고치는 법**: 색만 바꾸는 것이므로 `QPalette` 또는 `setProperty` + `style().polish()` 로 교체하거나, **색이 실제로 바뀔 때만** 호출하도록 이전 색을 캐시한다.

같은 패턴이 `set_alarm_count()`(2회), `set_pose_text()`, `_sync_seg()`, `tick_ui()`(2회)에도 있다.

**② `self.plan.update()` 10 Hz — `FacilityPlan` 커스텀 페인트**

`console_ui.py:681~934`, 250줄짜리 `paintEvent`가 초당 10번 전체 재드로우.
→ 구역 상태가 바뀔 때만 `update()`하거나, 변경된 사각형만 `update(rect)`.

**③ `Track3D` — GLViewWidget on MX450 (드라이버 452)**

포인트 + 궤적 + 캡슐 + 머리를 매 프레임 `setData`. 구형 드라이버에서 OpenGL 스톨 가능성.

### 확인 방법 (환경: 내 PC PowerShell)

추측을 확정으로 바꾸려면 측정한다. Claude Code 도입 후 첫 작업으로 이걸 시키면 된다.

```powershell
cd "C:\Users\82102\OneDrive\문서\Claude\Projects\공모전\01_현행코드"
pip install pyinstrument
python -m pyinstrument --interval 0.001 -r html -o freeze.html console_ui.py --live 127.0.0.1
```

다른 창에서 `python replay_jsonl.py`로 데이터를 흘리고, 멈추는 순간을 재현한 뒤 `freeze.html`을 열어 어느 함수가 시간을 먹는지 본다.

---

## 2. 설치 (환경: 내 PC PowerShell · 관리자 권한 불필요)

```powershell
irm https://claude.ai/install.ps1 | iex
```

설치 후 확인:

```powershell
claude doctor
```

**Git for Windows도 같이 설치하는 걸 권한다.** 있으면 Claude Code가 Bash 도구를 Git Bash로 쓰고, 없으면 PowerShell로만 셸을 돈다. 어느 쪽이든 동작하지만 Git 자체가 §4에 필요하다.

---

## 3. 첫 실행

```powershell
cd "C:\Users\82102\OneDrive\문서\Claude\Projects\공모전"
claude
```

처음 뜨면 로그인 안내가 나온다. 로그인하면 이 폴더의 `CLAUDE.md`와 `.claude/skills/`를 자동으로 읽는다.

### 이미 만들어 둔 것

| 파일 | 역할 |
|---|---|
| `CLAUDE.md` | 아키텍처·폴더구조·금지사항·검증절차·UI 원칙·물리한계 |
| `.claude/skills/ui-verify/` | UI 수정 후 pyflakes + 테스트 4종 |
| `.claude/skills/replay-regression/` | 실측 jsonl 재생 회귀 |
| `.claude/skills/readme-log/` | README 문제→해결 형식 일지 |
| `.claude/skills/jetson-deploy/` | 젯슨 코드 수정·배포 + 무결성 증명 |
| `.gitignore` | 대용량·실측 데이터 제외 |

### 첫날 해볼 것

```
> CLAUDE.md 읽고 이 프로젝트 구조를 요약해줘
> ui-verify 스킬로 지금 상태 검증 한번 돌려줘
```

두 번째 명령이 통과하면 설정이 제대로 붙은 것이다.

### 알아두면 좋은 조작

| 조작 | 효과 |
|---|---|
| `Shift+Tab` 두 번 | **plan mode** — 코드를 고치기 전에 계획을 먼저 보여주고 승인받는다. 큰 수정은 항상 이걸로 시작 |
| `/context` | **어떤 지침 파일이 실제로 로드됐는지 확인.** 설정이 먹었는지 볼 때 이걸 쓴다 |
| `/memory` | 지침 파일 목록 보기·편집, 자동 메모리 on/off |
| `/permissions` | 매번 승인 누르기 귀찮은 명령을 허용 목록에 넣기 |
| `/clear` | 대화 맥락 초기화 (`CLAUDE.md`는 유지됨) |
| `Esc` | 진행 중인 작업 중단 |
| `Esc` 두 번 | 이전 메시지로 되돌리기 |
| `/plugin` | 플러그인 설치 (§5) |

---

## 3.5 지침은 3층으로 나뉜다 — 어디에 무엇을 쓰나

**⚠ 설정 → 일반 → "Claude 지침"은 Claude Code에 적용되지 않는다.** 설정 화면에 "채팅 및 Cowork 전반에 걸쳐 기억합니다"라고 명시돼 있다. Claude Code는 별도 파일을 읽는다.

| 층 | 위치 | 적용 범위 | 이 프로젝트에서 쓸 파일 |
|---|---|---|---|
| **A. 앱 지침** | 설정 → 일반 → Claude 지침 | 채팅 + **Cowork** | `04_문서/설정/Claude지침_설정일반용.md` |
| **B. 사용자 지침** | `C:\Users\82102\.claude\CLAUDE.md` | **Claude Code 전체 프로젝트** | `04_문서/설정/CLAUDE_md_사용자전역.md` |
| **C. 프로젝트 지침** | `공모전\CLAUDE.md` | 이 프로젝트 (Claude Code + Cowork 둘 다) | 이미 있음 |

로드 순서는 **B → C**다. 뒤에 오는 게 더 구체적이라 충돌 시 프로젝트 쪽이 이긴다.

### 무엇을 어디에 쓰나

- **B(사용자)**: 프로젝트와 무관한 내 습관 — PowerShell 환경, 한국어, plan mode 기준, git 안전 규칙, "확인 안 하면 완료라고 쓰지 않기"
- **C(프로젝트)**: 이 코드베이스에만 해당하는 것 — 아키텍처, 금지사항, 검증 절차, 물리 한계

같은 내용을 두 곳에 쓰면 안 된다. **모순되는 지침이 두 개 있으면 Claude가 임의로 하나를 고른다.**

### 적용 (환경: 내 PC PowerShell)

```powershell
# B — 사용자 전역 지침 설치
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude" | Out-Null
Copy-Item "C:\Users\82102\OneDrive\문서\Claude\Projects\공모전\04_문서\설정\CLAUDE_md_사용자전역.md" `
          "$env:USERPROFILE\.claude\CLAUDE.md" -Force
```

A는 파일 복사가 아니라 **설정 화면에 직접 붙여넣는다.** `Claude지침_설정일반용.md`를 열어 `---` 아래 본문만 복사.

확인:
```
> /context
```
**Memory files** 목록에 `~/.claude/CLAUDE.md`와 프로젝트 `CLAUDE.md`가 둘 다 떠야 한다. 안 뜨면 Claude가 못 보는 것이다.

### 왜 이런 문장으로 썼나

Anthropic 문서가 권하는 원칙을 따랐다.

- **검증 가능하게 구체적으로.** "코드를 잘 짜라" ✗ / "실행하지 않았으면 완료라고 쓰지 않는다" ✓
- **200줄 이내.** 길어지면 오히려 준수율이 떨어진다. 현재 프로젝트 `CLAUDE.md` 187줄, 사용자 지침 약 45줄.
- **모순 제거.** 세 층에 같은 규칙을 중복해 쓰지 않는다.
- **지침은 강제가 아니라 맥락이다.** 반드시 실행돼야 하는 것(예: 커밋 전 pyflakes)은 지침이 아니라 **hook**으로 만들어야 확실하다.

### 자동 메모리 (기본 켜짐)

Claude Code는 대화 중 배운 걸 `~/.claude/projects/<프로젝트>/memory/`에 스스로 적는다. Cowork의 메모리와는 **별개**다. `/memory`로 내용을 보고 지울 수 있다.

---

## 3.6 설치 직후 — 뭘 더 해야 하나

폴더만 지정하면 `CLAUDE.md`와 `.claude/skills/`는 **자동으로 읽는다.** 추가로 할 것은 이것뿐이다.

- [ ] `~/.claude/CLAUDE.md` 설치 (§3.5)
- [ ] 설정 → 일반 → Claude 지침에 A 붙여넣기 (Cowork용)
- [ ] `git init` + 첫 커밋 (§4)
- [ ] pyflakes 설치 확인 — 없으면 `ui-verify` 스킬 1단계가 실패한다
      ```powershell
      python -m pyflakes --version
      # 없으면
      pip install pyflakes
      ```
- [ ] `/context`로 지침 3층이 다 로드됐는지 확인
- [ ] (선택) 자주 쓰는 명령 승인 면제 — `/permissions`로 추가하는 게 안전하다.
      직접 쓰려면 `.claude/settings.local.json`:
      ```json
      {
        "permissions": {
          "allow": ["Bash(python 테스트_*)", "Bash(python verify_*)", "Bash(python -m pyflakes *)"],
          "deny": ["Bash(git push *)"]
        }
      }
      ```
      ⚠ Git for Windows가 없으면 셸이 Bash가 아니라 PowerShell로 잡혀 규칙 이름이 다를 수 있다. `/permissions`로 넣으면 알아서 맞는 규칙이 들어간다.

스킬은 따로 등록할 필요가 없다. `.claude/skills/<이름>/SKILL.md`가 있으면 Claude Code가 **description을 보고 필요할 때 알아서 불러온다.** 직접 부르고 싶으면 그냥 이름을 말하면 된다 — "ui-verify 돌려줘".

---

## 4. git 초기화 (환경: 내 PC PowerShell)

지금 이 폴더는 git 저장소가 아니다. Claude Code의 안전장치(diff 리뷰, 되돌리기, worktree)가 전부 git 전제라 **없이 쓰면 위험이 오히려 커진다.**

### ⚠ OneDrive 주의

이 폴더는 OneDrive 동기화 폴더 안에 있다. `.git/`은 파일을 매우 자주 쓰기 때문에 OneDrive와 충돌해 인덱스가 깨질 수 있다.

- 작업 전 **OneDrive 일시 중지**(트레이 아이콘 → 동기화 일시 중지 2시간)를 권한다
- 또는 나중에 저장소를 OneDrive 밖(`C:\dev\radar-guard`)으로 옮기는 것도 방법이다

### 명령

```powershell
cd "C:\Users\82102\OneDrive\문서\Claude\Projects\공모전"

git init
git branch -M main

# 무엇이 추적될지 먼저 확인 — 커밋 전에 반드시 본다
git add -A --dry-run | Measure-Object -Line

# 대용량이 안 섞였는지 확인
git status --short | Select-Object -First 50

# 문제 없으면
git add -A
git commit -m "초기 커밋 — UI v2 (console_ui + radar_core 분리), 검증 4종, CLAUDE.md"
```

`.gitignore`가 제외하는 것: `03_데이터/`(75MB 실측 jsonl), `05_발표자료/`, `07_중간보고서_7.14/`, `_구버전보관/`, `_삭제후보/`, `*.zip`, `*.stl`, `*.joblib`, `__pycache__/`

**제외한 것들은 OneDrive에 그대로 남는다.** git이 관리하지 않을 뿐 파일이 사라지지 않는다.

### 이후 습관

작업 단위마다 커밋한다. Claude Code에게 맡겨도 된다:

```
> 지금까지 변경사항 diff 보여주고, 문제 없으면 커밋해줘
```

되돌릴 때:
```powershell
git diff                    # 뭐가 바뀌었나
git checkout -- 파일명       # 그 파일만 되돌리기
git reset --hard HEAD       # 전부 되돌리기 (주의)
```

---

## 5. Ponytail — 쓰되 범위를 한정한다

### 무엇인가

`DietrichGebert/ponytail`. 에이전트가 **필요 최소한의 코드만 쓰도록** 유도하는 스킬이다. 추측 기반 추상화, "나중을 위한" 스캐폴딩, 한 줄이면 될 걸 50줄로 쓰는 걸 막는다.

### 검증된 것 / 검증 안 된 것

- **주장**: 코드 −54%, 토큰 −22%, 비용 −20%, 시간 −27%
- ⚠ **이건 저자 측 수치이지 독립 벤치마크가 아니다.** JetBrains 리뷰도 "과하게 만들 여지가 있던 곳에서만 줄어든다"는 단서를 단다.
- ✓ 다만 저자가 명시한 예외는 우리에게 중요하다: **신뢰 경계 검증, 데이터 손실 처리, 보안, 접근성은 잘라내지 않는다.** 안전 시스템에서 쓸 만한 선이다.

### 설치

**전제.** Node.js가 PATH에 있어야 한다. 없어도 스킬 자체는 동작하지만, 매 프롬프트마다 규칙을 자동으로 주입해 주는 라이프사이클 훅 2개가 안 붙는다.

```powershell
node --version
```
없으면 [nodejs.org](https://nodejs.org)에서 LTS 설치 후 PowerShell을 새로 연다.

**설치 — Claude Code 세션 안에서, 반드시 두 번 나눠서 입력한다.** 한 번에 붙여넣으면 안 된다.

```
/plugin marketplace add DietrichGebert/ponytail
```

엔터 → 완료 메시지 확인 → 그다음:

```
/plugin install ponytail@ponytail
```

**확인**
```
/plugin
```
설치 목록에 `ponytail`이 보이면 된다. 안 보이면 Claude Code를 껐다 켜고 다시 확인한다.

**강도 조절 (프롬프트에 입력)**
```
/ponytail lite      ← 이 프로젝트는 여기서 시작
/ponytail full
/ponytail ultra
/ponytail off       ← 판정·검증 경로 작업 시
```

이 밖에 `/ponytail-review`(방금 쓴 코드가 과했는지 검토), `/ponytail-audit`, `/ponytail-debt` 같은 명령도 같이 깔린다.

**데스크톱 앱의 Code 탭에서 쓸 때**도 같은 두 `/plugin` 명령을 프롬프트 창에 입력하면 된다. 또는 프롬프트 창 옆 **+** 버튼 → **Plugins** → **Add plugin**.

### 우리 프로젝트에서의 적용 범위 — 이게 중요하다

| 대상 | Ponytail |
|---|---|
| 새 UI 위젯·화면 기능 | ✓ 켠다 |
| 리팩터링 | ✓ 켠다 |
| **검증 스크립트 4종** | ✗ **끈다.** 중복이라도 남겨야 회귀를 잡는다 |
| **`jetson_sender.py` 판정 경로** | ✗ **끈다.** 방어 코드를 줄이면 안 된다 |
| **경보 상태기계** | ✗ **끈다.** "한 줄로 되는데"가 안전에서는 이유가 안 된다 |

끄는 법: `/ponytail off`. 강도는 `lite` / `full` / `ultra`가 있는데, **이 프로젝트에서는 `lite`로 시작**하고 결과를 보고 올린다.

이 규칙은 `CLAUDE.md` §9에도 이미 반영해 뒀다.

---

## 6. Cowork와 병행 — 충돌 없이

같은 폴더를 둘이 동시에 열 수 있다. 문제는 **같은 파일을 동시에 고치면 서로 덮어쓴다**는 것뿐이다.

### 역할 분리

| | Claude Code (PowerShell) | Cowork (데스크톱 앱) |
|---|---|---|
| **담당 폴더** | `01_현행코드/` | `04_문서/`, `05_발표자료/`, `06_부스_하우징/`, `README.md` |
| **잘하는 일** | 코드 작성·실행·디버깅, 검증 스크립트 실행, 젯슨 접속 | 문서·발표자료·보고서, 웹 조사, Notion, 파일 공유 |
| **못 하는 일** | 파일 카드로 보여주기, Notion 연동 | 코드 실행, 하드웨어 접속 |

### 지켜야 할 것

1. **한쪽이 작업 중인 파일을 다른 쪽에서 열지 않는다.**
2. **코드 세션이 끝나면 커밋한 뒤** 문서 작업으로 넘어간다.
3. `README.md`는 Cowork가 쓴다. 단 Claude Code가 검증 결과 숫자를 먼저 만들어야 하므로, **코드 → 커밋 → 문서** 순서를 지킨다.
4. 헷갈리면 **한 번에 하나만 켠다.** 병렬은 익숙해진 뒤에.

### 이 문서와 CLAUDE.md의 관계

`CLAUDE.md`는 양쪽 다 읽는다. 프로젝트 규칙이 바뀌면 `CLAUDE.md`만 고치면 되고, 두 곳에 따로 적을 필요가 없다.

---

## 7. 도입 순서 (권장)

1. [ ] Claude Code 설치 (`irm https://claude.ai/install.ps1 | iex`) + `claude doctor`
2. [ ] 지침 3층 적용 (§3.5) — 설정 붙여넣기 + `~/.claude/CLAUDE.md` 복사 → `/context`로 확인
3. [ ] OneDrive 일시 중지 → `git init` + 첫 커밋
4. [ ] `pip install pyflakes` (없으면)
5. [ ] `claude` 실행 → `ui-verify` 스킬로 현재 상태 검증 (여기까지 되면 설정 완료)
6. [ ] **freezing 원인 실측** — pyinstrument로 §1의 후보 ①②③ 중 무엇인지 확정
7. [ ] 확정된 원인 수정 → `ui-verify`로 회귀 확인 → 커밋
8. [ ] Ponytail 설치 (`/ponytail lite`) — 새 기능 작업에만
9. [ ] Cowork로 README 일지 작성

**4번을 첫 실전 작업으로 추천한다.** Claude Code의 이점(실행 → 측정 → 수정 루프)이 가장 잘 드러나고, 결과가 8/17 멘토링 자료로도 쓰인다.

---

## 출처

- [Set up Claude Code — Claude Docs](https://docs.claude.com/en/docs/claude-code/setup)
- [How Claude remembers your project (CLAUDE.md · 자동 메모리) — Claude Code Docs](https://docs.claude.com/en/docs/claude-code/memory)
- [Configure permissions — Claude Code Docs](https://code.claude.com/docs/en/permissions)
- [Prompt engineering overview — Claude Platform Docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
- [Your first day in Claude Code — Claude Help Center](https://support.claude.com/en/articles/14552382-your-first-day-in-claude-code)
- [Claude Code cheatsheet — Claude Help Center](https://support.claude.com/en/articles/14553413-claude-code-cheatsheet)
- [DietrichGebert/ponytail — GitHub](https://github.com/DietrichGebert/ponytail)
- [Ponytail Skill for Claude Code: Does It Really Cut Tokens — JetBrains Blog](https://blog.jetbrains.com/ai/2026/07/ponytail-skill-claude-tested/)
