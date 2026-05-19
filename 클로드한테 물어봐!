"""
=================================================================
Radar-Guard | 시나리오 선택 → 유빈 UI 전달 파이프라인 (하드웨어 실구동 버젼)
=================================================================
"""

SCENARIO = "fall"   # "fall" | "electric_shock" | "pinching" | "vibration"

try:
    from IPython.display import display
except ImportError:
    def display(fig): pass

import numpy as np
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
from torch import optim
from sklearn.preprocessing import MinMaxScaler
from datetime import datetime, timedelta
import json
import time
import serial  # Jetson Nano와 레이더 시리얼 통신을 위한 모듈

fs           = 1000
seq_length   = 3
feature_size = 64
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

SCENARIO_KR = {
    "fall":           "낙상",
    "electric_shock": "감전",
    "pinching":       "협착",
    "vibration":      "진동이상",
}
ZONE_MAP = {
    "fall": "C", "electric_shock": "A", "pinching": "B", "vibration": "C"
}


# ================================================================
# 승원 파트 (실시간 신호처리 클래스)
# ================================================================
class RadarSignalProcessor:
    def __init__(self, order=32, mu=0.01, window_size=128):
        self.weights = np.zeros(order)
        self.buffer  = np.zeros(order)
        self.order, self.mu = order, mu
        self.window_size = window_size
        self.signal_history = np.zeros(window_size)

    def lms_filter(self, input_sample, ref_sample):
        self.buffer    = np.roll(self.buffer, 1)
        self.buffer[0] = ref_sample
        output         = np.dot(self.weights, self.buffer)
        error          = input_sample - output
        self.weights  += 2 * self.mu * error * self.buffer
        
        self.signal_history = np.roll(self.signal_history, -1)
        self.signal_history[-1] = error
        return error

    def extract_features_realtime(self):
        n   = self.window_size
        w   = np.hanning(n)
        fft = np.fft.fft(self.signal_history * w)
        frq = np.fft.fftfreq(n, d=1/fs)
        mag = np.abs(fft) / (n / 2)
        
        # 가드 코드 추가: 크기 불일치 방지
        feats = mag[np.where(frq >= 0)][:feature_size]
        if len(feats) < feature_size:
            feats = np.pad(feats, (0, feature_size - len(feats)), 'constant')
        return feats


# ================================================================
# 성준 파트 (AI 모델 구조 및 탐지/분류 레이어)
# ================================================================
class LSTM_Autoencoder(nn.Module):
    def __init__(self, n_features, embedding_dim, seq_len):
        super().__init__()
        self.seq_len  = seq_len
        self.encoder1 = nn.LSTM(n_features, embedding_dim, batch_first=True)
        self.encoder2 = nn.LSTM(embedding_dim, embedding_dim // 2, batch_first=True)
        self.decoder1 = nn.LSTM(embedding_dim // 2, embedding_dim // 2, batch_first=True)
        self.decoder2 = nn.LSTM(embedding_dim // 2, embedding_dim, batch_first=True)
        self.fc       = nn.Linear(embedding_dim, n_features)

    def forward(self, x):
        x, (h1, _) = self.encoder1(x)
        x, (h2, _) = self.encoder2(x)
        decoder_input = h2.transpose(0, 1).repeat(1, self.seq_len, 1)
        x, _ = self.decoder1(decoder_input)
        x, _ = self.decoder2(x)
        return self.fc(x)

# (중략 - classify_event 및 build_details 함수는 원본 구조 유지)
def classify_event(time_signal, freq_signal, recon_error, threshold):
    # 상단 원본 classify_event 로직이 그대로 매핑됩니다.
    freqs = np.fft.fftfreq(128, d=1/fs)[:feature_size]
    dom_idx = int(np.argmax(freq_signal[1:])) + 1
    dom_freq = float(freqs[dom_idx])
    
    if dom_freq > 40.0:
        return {"event_type": "fall_detected", "severity": "critical", "confidence": 0.92}
    elif 25.0 < dom_freq <= 40.0:
        return {"event_type": "pinching", "severity": "critical", "confidence": 0.88}
    elif dom_freq < 20.0:
        return {"event_type": "vibration_anomaly", "severity": "warning", "confidence": 0.85}
    else:
        return {"event_type": "fall_detected", "severity": "warning", "confidence": 0.70}

def build_details(event_type, time_signal, freq_signal, recon_error, threshold, timing):
    return {"anomaly_score": round(recon_error / threshold, 3), "reconstruction_error": round(recon_error, 6), "timing": timing, "description": f"{event_type} 감지"}


# ================================================================
# 재국 파트 (자동 제어 및 JSON 트리거 출력)
# ================================================================
RESPONSE_MAP = {
    "electric_shock_risk": {"action": "POWER_CUT", "description": "전원 차단 실행", "breaker_status": "OPEN", "response_ms": 50, "notify_level": "CRITICAL"},
    "fall_detected": {"action": "EMERGENCY_ALERT", "description": "비상 알림 발송", "breaker_status": "HOLD", "response_ms": 200, "notify_level": "CRITICAL"},
    "pinching": {"action": "MACHINE_STOP", "description": "긴급 정지 명령", "breaker_status": "OPEN", "response_ms": 100, "notify_level": "CRITICAL"},
    "vibration_anomaly": {"action": "WARNING_ALERT", "description": "점검 경고 발송", "breaker_status": "HOLD", "response_ms": 500, "notify_level": "WARNING"},
}

def jaeguk_breaker(event):
    event_type = event.get("event_type", "unknown")
    resp = RESPONSE_MAP.get(event_type, RESPONSE_MAP["vibration_anomaly"])
    print(f"\n⚡ [재국 자동 제어] 명령: {resp['action']} | 차단기: {resp['breaker_status']} ({resp['response_ms']}ms)")
    
    with open("ui_trigger.json", "w", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False, indent=2)


# ================================================================
# 유빈 파트 (UI 미리보기)
# ================================================================
def print_yubin_preview(event):
    print("\n🖥️  [유빈 UI 미리보기]")
    print(f"  ● 상태 알림 : {event['event_type']} | 구역: Zone {event['zone_id']}")
    print(f"  ● 신뢰 수준 : {event['confidence']:.0%} | 시간: {event['details']['timing']['event_timestamp']}")


# ================================================================
# [통합 코어] Jetson Nano 실시간 mmWave 가동 엔진
# ================================================================
def run_radar_guard_live():
    print(f"\n{'='*55}\n  Radar-Guard 실시간 하드웨어 가동 시작\n{'='*55}")
    
    # 1. Jetson Nano 하드웨어 시리얼 포트 오프너 (포트 및 속도 지정)
    # 일반 노트북 테스트 시 True 환경 모사 가동, Jetson 연결 시 주석 해제하세요.
    try:
        ser = serial.Serial('/dev/ttyTHS1', 115200, timeout=1) 
        hardware_mode = True
        print("🔌 실제 mmWave 레이더 하드웨어 연결 성공 (/dev/ttyTHS1)")
    except Exception as e:
        hardware_mode = False
        print("⚠️ 하드웨어가 감지되지 않아 가상 시뮬레이터 스트림으로 대체 가동합니다.")

    proc = RadarSignalProcessor(order=32, mu=0.01, window_size=128)
    
    # 성준 파트 가중치 모델 초기화 및 가상 더미 스케일러 빌드
    model = LSTM_Autoencoder(feature_size, 32, seq_length).to(device)
    model.eval()
    scaler = MinMaxScaler()
    scaler.fit(np.random.normal(0, 1, (100, feature_size))) # 가동용 임시 스케일러 바인딩
    threshold = 0.05
    
    live_features = []
    print("🔋 실시간 데이터 수집 및 감시 중... (Ctrl+C 종료)")
    
    try:
        while True:
            # 2. 하드웨어 데이터 파싱 인터페이스
            if hardware_mode:
                if ser.in_waiting > 0:
                    data_line = ser.readline().decode('utf-8', errors='ignore').strip()
                    try:
                        # 레이더 데이터 패킷에서 유효 값 추출 (센서 프로토콜 가이드에 맞춤 수정 필요)
                        raw_val = float(data_line.split(',')[0]) 
                    except ValueError:
                        continue
                else:
                    time.sleep(0.001)
                    continue
            else:
                # [시뮬레이션 모드 데이터]
                raw_val = np.sin(2*np.pi*5*(time.time())) + np.random.normal(0, 0.18)
            
            noise_ref = np.random.normal(0, 0.1)

            # 1. 승원 파트 신호처리 (들여쓰기 전면 교정)
            cleaned_sample = proc.lms_filter(raw_val, noise_ref)

            # 2. 성준 파트 이상탐지 파이프라인
            current_feature = proc.extract_features_realtime()
            live_features.append(current_feature.tolist())
            
            if len(live_features) > seq_length:
                live_features.pop(0) # 슬라이딩 윈도우 유지

            if len(live_features) == seq_length:
                input_feat = np.array(live_features)
                scaled_feat = scaler.transform(input_feat)
                X_live = torch.from_numpy(np.array([scaled_feat])).float().to(device)
                
                with torch.no_grad():
                    recon = model(X_live)
                    loss = torch.mean((recon - X_live)**2).item()
                
                if loss > threshold:
                    print(f"🚨 [이상 발생] Loss: {loss:.4f} > Threshold: {threshold:.4f}")
                    
                    time_signal = scaled_feat.flatten()
                    freq_signal = current_feature
                    
                    clf = classify_event(time_signal, freq_signal, loss, threshold)
                    timing = {"event_timestamp": datetime.now().isoformat(), "elapsed_ms": 0}
                    details = build_details(clf["event_type"], time_signal, freq_signal, loss, threshold, timing)
                    
                    event_obj = {
                        "event_id": f"evt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_Live",
                        "event_type": clf["event_type"],
                        "zone_id": ZONE_MAP.get(SCENARIO, "A"),
                        "severity": clf["severity"],
                        "confidence": clf["confidence"],
                        "details": details
                    }
                    
                    # 3. 재국 및 4. 유빈 레이어 연쇄 호출
                    jaeguk_breaker(event_obj)
                    print_yubin_preview(event_obj)
                    
                    live_features = [] # 알람 후 버퍼 리셋
                    time.sleep(1.5) 
            
            time.sleep(0.001) # 1ms 루프 타임 스케줄링 완화
            
    except KeyboardInterrupt:
        print("\n[정지] 실시간 감시 시스템을 안전하게 종료합니다.")
        if hardware_mode:
            ser.close()

if __name__ == "__main__":
    run_radar_guard_live()
