---
name: jetson-deploy
description: jetson_sender.py 등 젯슨 측 코드를 수정하거나 젯슨에 배포·접속할 때 사용한다. "젯슨에 올려줘", "젯슨 코드 고쳐줘", "젯슨 접속", "차단기", "classify 수정" 요청 시 사용. 판정 로직 무결성 증명과 젯슨 환경 제약(JetPack 7.2, COM13 시리얼, RTC 없음)을 함께 다룬다.
---

# 젯슨 측 작업

## 젯슨 환경 (사실 — 추측하지 말 것)

| 항목 | 값 |
|---|---|
| 플랫폼 | Jetson Orin Nano |
| JetPack | **7.2 (R39 / CUDA 13.2)** |
| GPU arch | **sm_87** — 이게 빠진 빌드를 쓰면 CPU로 떨어져 스왑이 터진다 |
| 접속 | **시리얼 COM13** |
| RTC | **없음.** 부팅마다 시계가 틀어진다 |
| 역할 | 판정(`classify()`, LSTM-AE) + 차단기 제어 **전용** |

- LLM 100% GPU 사용은 systemd 오버라이드로 확보돼 있다. 이 설정을 건드리면 스왑 문제가 재발한다.
- **젯슨에는 LLM을 올리지 않는다.** LLM·SOP DB·대시보드는 노트북 담당이다 (2026-07-28 확정).
- 시계가 틀어지므로 **경과시간을 젯슨 ts로 계산하지 않는다.** 모든 경과시간은 노트북 수신 시각 기준.

## 절대 규칙

1. **판정 로직은 `02_레이더_원본코드/radar_live_full.py`가 정본이다.** `jetson_sender.py`의 `classify()`는 거기서 통째로 복사한 것이다. 둘이 갈라지면 안 된다.
2. **판정 상수를 UI 편의로 바꾸지 않는다.** 바꿔야 하면 근거와 재학습 계획을 먼저 낸다.
3. **`radar_common.py`는 젯슨·노트북 공용이다.** 한쪽 편의로 고치면 다른 쪽이 죽는다.
4. **레이더 `.cfg`는 수정하지 않는다.** 포인트 수 부족은 각분해능 28° 병목이며 cfg로 해결되지 않는다.
5. **노트북이 끊겨도 판정과 차단은 젯슨에서 완결돼야 한다.** `CTRL_PORT` 명령은 로컬 제어의 보조이지 대체가 아니다.

## 수정 후 필수 검증 (환경: 내 PC PowerShell)

젯슨에 올리기 **전에** 노트북에서 먼저 돌린다. torch·레이더 없이 돌아간다.

```powershell
cd "C:\Users\82102\OneDrive\문서\Claude\Projects\공모전\01_현행코드"
python verify_port.py
python verify_jetson_safe.py
```

| 스크립트 | 증명하는 것 | 통과 |
|---|---|---|
| `verify_port.py` | `classify()` 이식이 무손실 — 실측 회귀 + 경계값 합성 회귀 + 상수 대조 | 종료코드 0 |
| `verify_jetson_safe.py` | 노트북용 수정(`--simulate`, torch 가드)이 젯슨 경로를 깨지 않음. 가짜 torch를 주입해 검사 | 종료코드 0 |

**둘 다 통과하기 전에는 젯슨에 올리지 않는다.**

`verify_jetson_safe.py`가 특히 잡는 것: `SIMULATE` 가드 안의 코드가 젯슨에서 실행되지 않는지. `RF_MODEL_PATH_OVERRIDE`는 정의되지 않은 이름이라 조건이 잘못되면 `NameError`로 즉사한다.

## 프로토콜 검증

젯슨 없이 UDP 스키마만 확인할 때 (PowerShell 창 2개):
```powershell
# 창1
python sim_jetson.py
# 창2
python console_ui.py --live 127.0.0.1
```
`SCHEMA_VERSION`을 올렸으면 노트북이 모르는 필드를 무시하고 계속 도는지 확인한다 (`RadarLink`에 경고 출력이 있다).

## 배포

젯슨 접속은 **시리얼 COM13**이다. 접속·전송 명령은 실행 전에 사용자에게 확인받는다 — 젯슨이 실기 데모 장비이므로 임의로 덮어쓰지 않는다.

배포 전 체크:
- [ ] `verify_port.py` 통과
- [ ] `verify_jetson_safe.py` 통과
- [ ] 기존 파일 백업 확보
- [ ] 되돌릴 방법 확인 (git commit 또는 원본 사본)
