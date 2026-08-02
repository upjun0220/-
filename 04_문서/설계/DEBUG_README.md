# Radar-Guard 디버그 로그 & 현재 상태

## 프로젝트 개요

**시스템:** TI IWR6843ISK-ODS mmWave 레이더 + Jetson Orin Nano  
**파이프라인:** 실레이더 데이터 → LMS 필터 → LSTM-AE 이상 탐지 → 이벤트 분류 → RAG SOP 생성  
**환경:** 완전 오프라인 (고보안 산업현장, 네트워크 없음)  
**RAG 모델:** Llama3:8b + nomic-embed-text (Ollama, 오프라인)  
**DB:** postgresql://postgres:password@localhost:5432/radar_guard (pgvector Docker)  
**디스플레이:** matplotlib TkAgg, 젯슨 HDMI 연결 모니터

---

## 파일 구조

```
~/radar_parser.py          # 레이더 데이터 수신 및 저장
~/radar_live_full.py       # 통합 관제 UI (메인 파일)
/home/project/stage1_filtered.json  # 파서가 저장하는 포인트클라우드 데이터
/home/project/radar_guard.cfg       # 레이더 설정 파일
```

---

## radar_parser.py 스펙

- ttyUSB0 (config, 115200bps) / ttyUSB1 (data, 921600bps)
- TLV Type 1: x,y,z,doppler (float32×4 = 16bytes)
- TLV Type 7: SNR → intensity (2 shorts × 2bytes = 4bytes)
- MAGIC_WORD: `b'\x02\x01\x04\x03\x06\x05\x08\x07'`
- 10프레임마다 중간 저장 (중간 저장 중 partial read 가능)
- 프레임당 보통 50~200 포인트, ~10fps

## radar_live_full.py 스펙 (v3 현재)

### 5단계 페이즈
```
READY → (Start Baseline 버튼) → WARMUP → (300프레임 완료) →
WAIT_TRAIN → (Start Training 버튼) → TRAINING → LIVE
```

### CONFIG
```python
JSON_PATH  = '/home/project/stage1_filtered.json'
N_WARMUP   = 300      # 정상 베이스라인 프레임 수
FEATURE_DIM = 8
SEQ_LEN    = 5
N_RESET    = 15       # 연속 정상 프레임 → 자동 이벤트 해제
POLL_SEC   = 0.4
UPDATE_MS  = 800
FALL_Z_THR = 0.6
```

### 8차원 피처 벡터
`[cx, cy, cz, mean_dop, dop_std, intensity_mean, n_pts, z_vel]`

### 스레드 구조
- **메인 스레드:** matplotlib FuncAnimation (UPDATE_MS=800ms)
- **데몬 스레드:** pipeline_loop() — LMS+피처추출+WARMUP+LSTM-AE
- **데몬 스레드:** run_rag() — Llama3 추론 (이상 감지 시 별도 실행)

### UI 레이아웃
```
[Step Guide: ① Radar ON → ② Baseline → ③ Training → ④ LIVE]
[Status Bar - 단일 라인, 전체 폭]
[Progress Bar - WARMUP/TRAINING 중 표시]
---
[3D Point Cloud]  [Centroid Z]  [Anomaly Score]
[Event Log]       [Action Guide / SOP (2칸)]
---
[START Baseline / Training 버튼]    [RESET 버튼]
```

---

## 발생한 버그 및 수정 이력

### ✅ Bug 1: status_box가 3D subplot에 가려짐
**증상:** UI 실행해도 상태 텍스트 아무것도 안 보임  
**원인:** `fig.text(0.015, 0.68, ...)` → y=0.68이 3D subplot 내부 좌표라 덮임  
**수정:** `fig.text(0.5, 0.948, ...)` → 화면 중앙 상단으로 이동

---

### ✅ Bug 2: struct.error로 radar_parser.py 크래시
**에러:**
```
struct.error: unpack requires a buffer of 16 bytes
File "radar_parser.py", line 100, in parse_frame
    x, y, z, dop = struct.unpack('<4f', tlv_data[i*16:(i+1)*16])
```
**원인:** 잘린 패킷(partial TLV)이 들어올 때 buffer 크기 미검증  
**수정:**
```python
# Type 1 (x,y,z,doppler)
chunk = tlv_data[i*16:(i+1)*16]
if len(chunk) < 16:
    break  # 잘린 패킷 무시
x, y, z, dop = struct.unpack('<4f', chunk)

# Type 7 (SNR)
chunk4 = tlv_data[i*4:(i+1)*4]
if len(chunk4) < 4:
    break
snr, _ = struct.unpack('<2H', chunk4)
```
**추가 수정:** parse_frame 전체를 try/except로 감싸서 어떤 에러도 파서 종료 안 되게:
```python
try:
    result = parse_frame(frame_data)
except Exception as e:
    print(f"  [SKIP] 파싱 오류 무시: {e}")
    result = None
```

---

### ✅ Bug 3: TRAINING 중 UI 완전 동결 (GIL 문제)
**증상:** TRAINING 페이즈 진입 시 matplotlib 애니메이션 완전 정지, NO DATA 표시  
**원인:** PyTorch 학습 120 에폭이 Python GIL을 잡고 메인 스레드(matplotlib) 차단  
**수정 1:** 에폭마다 GIL 해제
```python
for epoch in range(120):
    opt.zero_grad()
    loss = crit(model(X), X)
    loss.backward(); opt.step()
    time.sleep(0.01)  # every epoch: release GIL
```
**수정 2:** 학습을 별도 스레드로 분리, pipeline_loop은 Event.wait()로 대기 (GIL 해제됨)
```python
_done = threading.Event()
_res  = {}

def _train_worker(feat_copy=warmup_feat[:]):
    m, s, t = train_on_real_data(feat_copy)
    _res['model'] = m; _res['scaler'] = s; _res['thr'] = t
    _done.set()

threading.Thread(target=_train_worker, daemon=True).start()

while not _done.wait(timeout=0.3):
    with _lock:
        state['last_data_t'] = time.time()  # prevent stale warning
```

---

### ✅ Bug 4: WAIT_TRAIN 페이즈가 WARMUP으로 계속 덮어써짐
**증상:** 300프레임 도달해도 버튼 레이블이 "Collecting baseline..."에서 변경 안 됨  
**원인:** 매 프레임마다 `state['phase'] = PH_WARMUP` 무조건 설정
```python
# 기존 (버그)
with _lock:
    state['warmup_count'] = wc
    state['phase'] = PH_WARMUP  # 매번 덮어씀!
```
**수정:**
```python
with _lock:
    state['warmup_count'] = wc
    if state['phase'] not in (PH_WAIT_TRAIN, PH_TRAINING, PH_LIVE):
        state['phase'] = PH_WARMUP  # 이미 넘어간 페이즈는 유지
```

---

### ✅ Bug 5: Reset 후 proc_idx 유지로 JSON 읽기 위치 꼬임
**증상:** Reset 후 Start Baseline 눌러도 warmup이 ~290프레임에서 멈춤  
**원인:** Reset 시 proc_idx를 초기화 안 해서 이전 실행 JSON 위치부터 읽음.
이전 실행 데이터가 700+프레임이면 새로 수집되는 300프레임이 범위 밖  
**수정:**
```python
if do_reset:
    lms = LMSFilter()
    feat_buf = []
    warmup_feat = []
    prev_c = None
    model = None
    scaler = None
    thr = 0.01
    proc_idx = -1      # ← 추가: JSON 처음부터 다시 읽기
    last_mtime = 0.0   # ← 추가: 강제 재읽기
```
**추가 조치:** 재시작 전 JSON 파일 삭제 필수
```bash
rm -f /home/project/stage1_filtered.json
```

---

## ❌ 현재 미해결 이슈: WARMUP ~90-96%에서 UI 동결

**증상:**
- WARMUP 약 270~290/300 프레임에서 matplotlib 애니메이션 완전 정지
- Reset 버튼도 클릭 안 됨, 그래프도 안 움직임
- radar_parser.py는 계속 정상 동작 중 (터미널에 프레임 출력됨)

**확인된 것:**
- 파서 크래시 아님 (터미널 계속 출력)
- Bug 4, Bug 5 수정 적용 후에도 동일 증상
- Z=0.01~0.02m (사람 높이가 거의 0에 가까움 - 레이더 위치 문제 가능성)

**가능한 원인 (미확정):**
1. JSON 파일이 커지면서 (1000+프레임) `json.load()` 소요시간 증가 → 뭔가 차단
2. threading.Lock() 데드락 가능성
3. 메인 스레드에서 예상치 못한 블로킹 발생
4. matplotlib TkAgg 백엔드 자체 이슈 (Jetson 환경)

**시도한 것:**
- stage1_filtered.json 삭제 후 재시작 → 동일 증상
- `time.sleep(0.01)` GIL 해제 → 효과 없음 (TRAINING 전에 이미 동결)

**아직 시도 안 한 것:**
- blit=True로 변경 (성능 향상)
- UPDATE_MS를 1200~1500으로 늘려서 부하 감소
- matplotlib 애니메이션 대신 while True + plt.pause() 방식으로 교체
- JSON 파일 대신 ring buffer나 최근 N프레임만 저장하는 방식

---

## 실행 방법

### 사전 준비 (젯슨)
```bash
sudo docker start radar-guard-db   # pgvector DB
ollama serve                        # 이미 실행중이면 "address already in use" 뜨는데 정상
```

### 매번 실행 전
```bash
sudo fuser -k /dev/ttyUSB0 /dev/ttyUSB1   # 포트 점유 해제
rm -f /home/project/stage1_filtered.json   # JSON 초기화 (중요)
```

### 실행
```bash
# 터미널 1
python3 ~/radar_parser.py

# 터미널 2
python3 ~/radar_live_full.py
```

### UI 조작 순서
1. **START Baseline Collection** 버튼 클릭 → 가만히 서 있기 30초
2. 300프레임 완료 → 버튼이 **START Training** 으로 자동 변경
3. **START Training** 버튼 클릭 → 가만히 서 있기 ~30초
4. LIVE 자동 진입 → 이상 감지 시 SOP 자동 생성

### USB 포트 순서가 바뀐 경우
```python
# radar_parser.py에서 스왑
CFG_PORT  = '/dev/ttyUSB1'   # 기본값 0
DATA_PORT = '/dev/ttyUSB0'   # 기본값 1
```

---

## 환경 정보

- **Jetson 사용자:** project  
- **Jetson IP:** 172.20.10.2  
- **matplotlib 버전:** 3.6.3 (시스템 패키지)  
- **Python:** python3 (system)  
- **PyTorch:** CPU 모드 (DEVICE = cuda 없으면 cpu 자동 선택)  
- **파일 전송:** Windows PowerShell에서 scp 사용

```powershell
# Windows PowerShell에서 파일 전송
scp "C:\Users\82102\OneDrive\문서\Claude\Projects\공모전\radar_live_full.py" project@172.20.10.2:~/radar_live_full.py
scp "C:\Users\82102\OneDrive\문서\Claude\Projects\공모전\radar_parser.py" project@172.20.10.2:~/radar_parser.py
```

---

## 코드 핵심 구조 요약

### LMSFilter
```python
class LMSFilter:
    def __init__(self, order=8, mu=0.005): ...
    def filter(self, x, ref): ...  # ref = np.random.normal(0, 0.004)
```

### LSTM_AE
```python
class LSTM_AE(nn.Module):  # enc1→enc2→dec1→dec2→fc
    # n_feat=8, emb_dim=16, seq_len=5
```

### 이상 분류 (classify)
- `z_vel < -0.10 and abs(mean_dop) > 0.18` → fall_detected
- `dop_std > 0.030 and abs(z_vel) < 0.15` → electric_shock_risk  
- `dop_std > 0.010 and cy < 0.85` → pinching
- `dop_std > 0.002` → vibration_anomaly

### 공유 상태 (state dict)
```python
state = {
    'phase': PH_READY,          # READY/WARMUP/WAIT_TRAIN/TRAINING/LIVE
    'warmup_count': 0,
    'start_requested': False,
    'train_requested': False,
    'reset_requested': False,
    'latest_pts': [],
    'cz_h': deque([1.7]*120),
    'sc_h': deque([0.0]*120),
    'ev_active': False,
    'ev_type': None,
    'ev_sev': 'normal',
    'threshold': 0.01,
    'sop_text': '',
    'logs': deque(maxlen=20),
    'last_data_t': 0.0,
    'data_ok': False,
}
```
