# OUTBOX — Claude Code → 사용자·GPT·Cowork

> 질문·차단 요소·불일치·판단 요청. triage 후 이동하고 여기서 지운다. 최대 10개.

### OUT-001  stale 베일이 LINK_TIMEOUT 전 구간에 안 뜬다
- From: Claude Code
- Type: 판단사항
- Needs: 결정
링크 다운 시 색은 정확하나 `LINK_TIMEOUT`(3.0s) 이전에는 베일이 없다 — 1.8초 시점 실측 확인(색 `#F59E0B`, 베일 미표시).
그 3초 창에 베일이 필요한지 판단 바람. 필요 없으면 폐기한다.

### OUT-003  이벤트 7종 중 3종만 재현 가능
- From: Claude Code
- Type: 불일치
- Needs: 결정
`EVENT_KO` 는 7종인데 화면에 띄워본 것은 낙상·정지형·진동 3종뿐이다.
감전·협착·과전류·전압강하는 데모·시뮬·jsonl 어디에도 없어 렌더링이 맞는지 아무도 모른다.
발표에서 "7종"이라 말할 근거가 없다 — 재현 도구를 만들지, 표현을 "3종 검증"으로 바꿀지 결정 바람.

### OUT-004  젯슨 하드웨어 헬스 필드 추가 여부
- From: Claude Code
- Type: 판단사항
- Needs: 결정
CPU·메모리·온도를 화면에 띄우려면 `radar_common.py` 스키마에 필드를 넣어야 하는데 이 파일은 젯슨과 공용이다.
한쪽 편의로 고치면 다른 쪽이 죽는다. 8/05 통합시험 이후에 판단 바람.

### OUT-005  동기화된 규칙 문서의 주체명 중복
- From: Codex
- Type: 불일치
- Needs: 확인
`AGENTS.md` §10 규칙 문서 수정권에 `AGENTS.md`·`.agents/skills/`가 각각 중복되고 “Codex와 Codex”로 적혀 있다.
이틀 동결 규칙에 따라 수정하지 않았다. 동결 해제 후 정본의 의도한 주체명과 생성 대상명을 확인해야 한다.

### OUT-006  (a)(b) 커밋 통합 사유와 mannequin_cc0.obj 포함 여부
- From: Claude Code
- Type: 판단사항
- Needs: 확인

**커밋 단위**: 지시한 (a) 정지형·ROI / (b) 마네킹 렌더·GPU 변환 / (c) 문서 3분리 중 (c)는 갈리지만
(a)(b)는 두 겹 이유로 한 커밋으로 감. 첫째, `.githooks/pre-commit`이 `01_현행코드/*.py` 스테이징 시
같은 커밋에 `HANDOFF.md`도 스테이징돼야 통과시킴 — `HANDOFF.md`는 이미 다 쓰인 diff 하나뿐이라
두 번째 py 커밋에서는 새로 스테이징할 변경분이 없어 훅이 막음(즉 py 커밋은 세션당 1개만 HANDOFF를
동반할 수 있음). 둘째, 설령 훅이 없어도 `radar_core.py`의 `Track3D.__init__` 한 훅(hunk) 안에서
ROI 코어 사각형 그리기(`FRAME_INNER_HALF`/`OCCUPANCY_CORE_HALF`)와 마네킹 `GLMeshItem` 설정이
인접해 있어 `git add -p`로 나누려면 대화형(`-i`) 편집이 필요한데 이 세션은 대화형 git 사용이 금지
상태임. 그래서 `console_ui.py`·`radar_common.py`·`jetson_sender.py`·`radar_core.py` 4개 파일과
`HANDOFF.md`를 한 커밋으로 묶음. 코드는 한 줄도 바꾸지 않음 — 훅 요구로 커밋 개수만 3개→2개(코드/문서)
로 줄었을 뿐, 파일별 diff 내용은 지시대로임.

**`mannequin_cc0.obj`(3.13MB, 97,213줄) 포함 판단**: `radar_core.py`의 `Track3D.__init__`이 `_mannequin_mesh()`를
무조건 호출해 이 파일을 읽음 — 파일이 빠지면 다른 환경에서 체크아웃만 해도 `Track3D` 생성이
`FileNotFoundError`로 즉시 죽음. 그래서 (b) 커밋에 함께 넣음. 다만 HANDOFF 3번이 짚은 우려(재익스포트마다
텍스트 97,213줄이 히스토리에 통째로 쌓임)는 여전히 유효함 — 마네킹 자산을 자주 교체할 계획이면 Git LFS 전환을
검토 바람. 이번 세션은 "그대로 보존"이 지시라 LFS 전환은 하지 않음.
