---
name: ui-verify
description: console_ui.py / radar_core.py / radar_common.py / facility.py 를 수정한 뒤 반드시 돌리는 검증 묶음. pyflakes + 자동 테스트 4종을 순서대로 실행하고 결과를 표로 보고한다. UI·화면·팝업·평면도·경보 표시를 고쳤을 때, 또는 사용자가 "검증", "테스트 돌려줘", "확인해줘"라고 할 때 사용한다.
---

# UI 수정 검증

## 언제 쓰나
`01_현행코드/` 안의 다음 파일 중 **하나라도** 수정한 직후:
`console_ui.py`, `radar_core.py`, `radar_common.py`, `facility.py`

수정하고 이 스킬을 돌리지 않은 채 "완료"라고 보고하지 않는다.

## 실행 (환경: 내 PC PowerShell)

검증 스크립트들은 상대 경로(`../03_데이터/…`)를 쓰므로 **반드시 `01_현행코드/` 안에서** 실행한다.

```powershell
cd "C:\Users\82102\OneDrive\문서\Claude\Projects\공모전\01_현행코드"
```

### 1단계 — 정적 검사 (실패하면 여기서 멈춘다)
```powershell
python -m pyflakes console_ui.py radar_core.py radar_common.py facility.py
```
기준: **출력 없음**. 경고가 하나라도 나오면 고치고 다시 돌린다.

### 2단계 — 자동 테스트 4종
```powershell
python 테스트_v1결함_재발검사.py
python 테스트_레이아웃_검증.py
python 테스트_실데이터_재생.py
python 테스트_평면도_경보흐름.py
```

| 스크립트 | 무엇을 보나 | 통과 기준 |
|---|---|---|
| `테스트_v1결함_재발검사.py` | v1에서 고쳤던 결함이 되살아났는지 | NG 0건 |
| `테스트_레이아웃_검증.py` | 4해상도에서 텍스트 잘림·위젯 겹침 | FAIL 0건 |
| `테스트_실데이터_재생.py` | 실측 jsonl → UDP → 누적 → 자세추정 → 경보 색까지 전 경로 | NG 0건 |
| `테스트_평면도_경보흐름.py` | 사전경보 → latch → 1.5초 자동전환 → 종료 | NG 0건 |

전부 `QT_QPA_PLATFORM=offscreen`으로 돌아 **창이 뜨지 않는다.** 창이 안 뜬다고 실패가 아니다.

### 3단계 — 젯슨을 건드렸다면 추가
`jetson_sender.py` 또는 `radar_common.py`를 수정했으면:
```powershell
python verify_port.py
python verify_jetson_safe.py
```
기준: 둘 다 **종료코드 0**. `verify_port.py`는 `classify()` 이식이 무손실인지, `verify_jetson_safe.py`는 노트북용 수정이 젯슨을 깨지 않는지 증명한다.

## 결과 보고 형식

표로 낸다. 실측 숫자를 그대로 쓰고 추정하지 않는다.

```
| 검사 | 결과 |
|---|---|
| pyflakes | 경고 0 |
| v1 결함 재발 | 35항목 0건 |
| 레이아웃 (4해상도) | 잘림·겹침 0건 |
| 실데이터 재생 | 57항목 0건 |
| 평면도 경보흐름 | 16항목 0건 |
```

## NG가 나오면

1. **되돌리지 말고 원인부터 읽는다.** NG 메시지에 어느 항목인지 나온다.
2. 그 항목이 원래 무엇을 막으려던 검사인지 README에서 찾는다 (문제→해결 형식이라 검색된다).
3. 고친 뒤 **전체를 다시 돌린다.** 한 개만 다시 돌려 통과했다고 보고하지 않는다.
4. 검사 기준 자체가 틀렸다고 판단되면 **테스트를 고치기 전에 사용자에게 근거를 제시하고 확인받는다.** 통과시키려고 검사를 무르게 만드는 것은 금지다.

## 눈으로 볼 때

자동 테스트는 창을 안 띄운다. 실제 화면을 봐야 하면 PowerShell 창 2개:
```powershell
# 창1
python replay_jsonl.py
# 창2
python console_ui.py --live 127.0.0.1
```
젯슨 없이 프로토콜만 볼 때는 `replay_jsonl.py` 대신 `python sim_jetson.py`.
