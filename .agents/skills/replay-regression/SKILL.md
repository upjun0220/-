---
name: replay-regression
description: 실측 jsonl 데이터를 젯슨인 척 재생해 UI 전 경로를 회귀 검증한다. 판정 로직·상수·데이터 스키마를 바꿨을 때, 새 실측 데이터를 받았을 때, "실데이터로 확인", "재생해서 검증", "회귀 돌려줘" 요청 시 사용한다. sim_jetson(난수)과 replay_jsonl(실측)의 차이와 각각의 한계를 함께 안내한다.
---

# 실측 재생 회귀 검증

## 두 재생기의 차이 — 헷갈리면 안 된다

| | `sim_jetson.py` | `replay_jsonl.py` |
|---|---|---|
| 데이터 | **난수로 만든 가짜 점군** | **실제로 측정한 점군** (`03_데이터/이벤트_학습용/*.jsonl`) |
| 의존성 | numpy만 | numpy만 |
| 증명하는 것 | UDP 프로토콜·패킷 스키마가 어긋나지 않았다 | 누적·PCA 자세추정·머리추정·인체 도식·높이/움직임 수치·경보 화면이 실전과 같이 동작한다 |
| 증명 못 하는 것 | 표시 계층의 정확성 | **판정의 정확성** |

**둘 다 `classify()`를 돌리지 않는다.** `replay_jsonl.py`는 jsonl의 label을 그대로 통보한다. 낙상 판정이 맞는지는 젯슨 + torch로 따로 검증하는 것이고 이 스킬로는 증명되지 않는다. 보고할 때 이 구분을 흐리지 않는다.

LSTM-AE 이상점수는 학습된 baseline이 없어 `—`로 뜨는 것이 **정상**이다. 결함이 아니다.

## 실행 (환경: 내 PC PowerShell) — `cd` 불필요, 어디서 실행해도 자기 위치 기준으로 돈다.

### 자동 회귀 (창 안 뜸 · 기본으로 이걸 쓴다)
```powershell
python 01_현행코드\테스트_실데이터_재생.py
python 01_현행코드\테스트_평면도_경보흐름.py
```
기준: 양쪽 다 NG 0건.

### 눈으로 볼 때 (PowerShell 창 2개)
```powershell
# 창1 — 재생기
python 01_현행코드\replay_jsonl.py
# 창2 — 관제 화면
python 01_현행코드\console_ui.py --live 127.0.0.1
```

### replay_jsonl.py 옵션
```powershell
python 01_현행코드\replay_jsonl.py --list                 # 어느 파일에 뭐가 몇 건 있는지 먼저 확인
python 01_현행코드\replay_jsonl.py --seq fall,still,normal
python 01_현행코드\replay_jsonl.py --file 03_데이터\이벤트_학습용\events_final.jsonl
python 01_현행코드\replay_jsonl.py --fast                 # 2배속
python 01_현행코드\replay_jsonl.py --once                 # 한 바퀴만
```
`--file`은 **실행 위치(cwd) 기준 상대경로**다 — 프로젝트 루트에서 돌리면 위 예시처럼, `01_현행코드/` 안에서 돌리면 `..\03_데이터\...`로 써야 한다.

**새 상황을 검증하기 전에 항상 `--list`를 먼저 돌린다.** 없는 라벨을 재생하려 하면 조용히 0건이 흐른다.

### 판정 로직을 건드렸다면
```powershell
python 01_현행코드\verify_port.py
```
`jetson_sender.py`의 `classify()`와 `02_레이더_원본코드/radar_live_full.py`를 같은 입력에 돌려 출력이 한 건도 다르지 않음을 확인한다. 실측 회귀 + 경계값 합성 회귀 + 상수 대조 3단계. 종료코드 0이 통과.

이건 "낙상을 잘 잡는가"의 검증이 **아니다.** "옮기는 과정에서 아무것도 변하지 않았다"만 증명한다.

## 데이터 다룰 때 주의

- `03_데이터/`의 jsonl을 **덮어쓰지 않는다.** 재수집 비용이 크다.
- still/normal 계열 데이터에는 과거 케이블 흔들림 오염 이력이 있다. 이상한 결과가 나오면 코드를 의심하기 전에 어느 파일인지부터 확인한다.
- 실측에서 새로 알게 된 사실은 코드 주석에 `⚠ [날짜 실측] …` 형식으로 남기고 README에도 반영한다.
