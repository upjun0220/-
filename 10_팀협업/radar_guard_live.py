"""
=================================================================
Radar-Guard | 시나리오 선택 → 유빈 UI 전달 파이프라인 (하드웨어 실구동 버젼)
=================================================================
[수정 이력]
  v2.0 (2026-05-19) — Jetson Nano + TI mmWave 호환성 패치
    1. TI mmWave TLV 바이너리 파서 추가 (TImmWaveParser)
       - ASCII readline 방식 → 바이너리 TLV 프레임 파싱으로 교체
       - IWR6843 / AWR1843 등 TI mmWave SDK 출력 포맷 지원
    2. 모델 저장/로드 추가 (load_trained_model)
       - radar_guard_pipeline.py 에서 저장한 .pt 파일 로드
       - 파일 없으면 경고 후 시뮬레이션 모드 강제 전환
    3. MinMaxScaler 상태 복원 로직 추가
=================================================================
"""

SCENARIO = "fall"   # "fall" | "electric_shock" | "pinching" | "vibration"

try:
    from IPython.display import display
except ImportError:
    def display(fig): pass

import struct
import os
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

# ================================================================
# 모델 저장 경로 (radar_guard_pipeline.py 와 동일하게 맞출 것)
# ================================================================
MODEL_SAVE_DIR = os.path.dirname(os.path.abspath(__file__))  # 이 파일과 같은 폴더

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
# [TI mmWave TLV 파서] — IWR6843 / AWR1843 SDK 출력 포맷
# ================================================================
# TI mmWave SDK UART 프레임 구조:
#   [매직워드 8B][헤더 32B][TLV 0~N개]
#   TLV 헤더: type(4B) + length(4B)
#   TLV Type 1 (감지 포인트): x(4B) + y(4B) + z(4B) + doppler(4B) per point
# ================================================================
_MAGIC_WORD          = b'\x02\x01\x04\x03\x06\x05\x08\x07'
_FRAME_HDR_FMT       = '<8I'   # 8 × uint32
_FRAME_HDR_SIZE      = 32      # 헤더 필드만 (매직 제외)
_FULL_HDR_SIZE       = 40      # 매직(8) + 헤더(32)
_TLV_HDR_FMT         = '<2I'   # type(uint32) + length(uint32)
_TLV_HDR_SIZE        = 8
_PT_FMT              = '<4f'   # x, y, z, doppler (float32 × 4)
_PT_SIZE             = 16
_TLV_DETECTED_POINTS = 1


class TImmWaveParser:
    """
    TI mmWave SDK (IWR6843/AWR1843) UART 바이너리 스트림 파서.

    실행 환경: Jetson Nano SSH 터미널 또는 VS Code Remote SSH 터미널
        ser    = serial.Serial('/dev/ttyTHS1', 115200, timeout=1)
        parser = TImmWaveParser(ser)
        while True:
            points = parser.read_frame()   # list[dict] 또는 None
            if points:
                scalar = TImmWaveParser.aggregate_to_scalar(points)
    """

    def __init__(self, ser, max_buf: int = 8192):
        self.ser     = ser
        self.max_buf = max_buf
        self._buf    = bytearray()

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------
    def read_frame(self):
        """
        직렬 포트에서 바이트를 읽어 TLV 프레임 1개를 파싱합니다.
        감지된 포인트 리스트(dict)를 반환하며, 프레임 미완성 시 None 반환.

        Returns:
            list[dict] | None
            dict 키: 'x', 'y', 'z', 'doppler' (단위: m, m/s)
        """
        # 1. 새 바이트 읽기
        waiting = self.ser.in_waiting
        if waiting > 0:
            self._buf.extend(self.ser.read(waiting))

        # 버퍼 오버플로 방지
        if len(self._buf) > self.max_buf:
            self._buf = self._buf[-_FULL_HDR_SIZE:]

        # 2. 매직 워드 탐색
        idx = self._buf.find(_MAGIC_WORD)
        if idx == -1:
            return None
        if idx > 0:
            del self._buf[:idx]   # 매직 워드 이전 쓰레기 데이터 제거

        # 3. 전체 헤더 도착 대기
        if len(self._buf) < _FULL_HDR_SIZE:
            return None

        # 4. 헤더 파싱
        # 필드 순서: version, totalPacketLen, platform,
        #            frameNumber, timeCpuCycles,
        #            numDetectedObj, numTLVs, subFrameNumber
        hdr       = struct.unpack(_FRAME_HDR_FMT,
                                  self._buf[8: 8 + _FRAME_HDR_SIZE])
        total_len = hdr[1]   # 바이트 단위 전체 패킷 길이
        num_tlvs  = hdr[6]

        # 5. 전체 프레임 도착 대기
        if len(self._buf) < total_len:
            return None

        frame = bytes(self._buf[:total_len])
        del self._buf[:total_len]   # 소비한 프레임 제거

        # 6. TLV 파싱
        return self._parse_tlvs(frame, num_tlvs)

    @staticmethod
    def aggregate_to_scalar(points: list) -> float:
        """
        포인트 클라우드 → 스칼라 신호 (LMS 필터 입력용).

        거리 역수를 가중치로 사용해 도플러 속도를 가중 평균합니다.
        가까울수록 높은 가중치 → 근접 물체의 움직임에 더 민감하게 반응.

        Args:
            points: read_frame() 반환값
        Returns:
            float: 가중 도플러 스칼라 (m/s)
        """
        if not points:
            return 0.0
        dopplers = np.array([p['doppler'] for p in points], dtype=np.float32)
        ranges   = np.array(
            [np.sqrt(p['x']**2 + p['y']**2 + p['z']**2) for p in points],
            dtype=np.float32
        )
        weights  = 1.0 / (ranges + 0.5)
        weights /= (weights.sum() + 1e-10)
        return float(np.dot(dopplers, weights))

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------
    def _parse_tlvs(self, frame: bytes, num_tlvs: int) -> list:
        points = []
        offset = _FULL_HDR_SIZE

        for _ in range(num_tlvs):
            if offset + _TLV_HDR_SIZE > len(frame):
                break
            tlv_type, tlv_len = struct.unpack(
                _TLV_HDR_FMT, frame[offset: offset + _TLV_HDR_SIZE]
            )
            offset += _TLV_HDR_SIZE

            if tlv_type == _TLV_DETECTED_POINTS:
                n_pts = tlv_len // _PT_SIZE
                for i in range(n_pts):
                    pt_start = offset + i * _PT_SIZE
                    pt_end   = pt_start + _PT_SIZE
                    if pt_end > len(frame):
                        break
                    x, y, z, d = struct.unpack(_PT_FMT, frame[pt_start:pt_end])
                    points.append({'x': x, 'y': y, 'z': z, 'doppler': d})

            offset += tlv_len

        return points   # 빈 리스트도 반환 (프레임 유효, 감지 없음)


# ================================================================
# [모델 저장/로드] — Jetson 이식용
# ================================================================
def save_model(model, scaler, threshold, scenario, save_dir=MODEL_SAVE_DIR):
    """
    훈련된 모델·스케일러·임계치를 .pt 파일로 저장.
    radar_guard_pipeline.py 의 _train_model_impl() 에서 자동 호출됩니다.

    저장 위치:
        {save_dir}/radar_guard_model_{scenario}.pt
    """
    os.makedirs(save_dir, exist_ok=True)
    path = os.path.join(save_dir, f"radar_guard_model_{scenario}.pt")
    torch.save({
        "model_state":           model.state_dict(),
        "scaler_scale_":         scaler.scale_,
        "scaler_min_":           scaler.min_,
        "scaler_data_min_":      scaler.data_min_,
        "scaler_data_max_":      scaler.data_max_,
        "scaler_data_range_":    scaler.data_range_,
        "scaler_feature_range":  scaler.feature_range,
        "scaler_n_features_in_": scaler.n_features_in_,
        "threshold":             threshold,
        "feature_size":          feature_size,
        "embedding_dim":         32,
        "seq_length":            seq_length,
    }, path)
    print(f"💾 모델 저장 완료: {path}")
    return path


def load_trained_model(scenario, save_dir=MODEL_SAVE_DIR):
    """
    저장된 .pt 파일에서 모델·스케일러·임계치 복원.

    실행 환경: Jetson Nano SSH 터미널
        python3 "클로드한테 물어봐!.py"

    모델 파일이 없으면 (None, None, None) 반환 → 호출부에서 경고 처리.

    Args:
        scenario: "fall" | "electric_shock" | "pinching" | "vibration"
        save_dir: .pt 파일이 저장된 디렉터리 경로
    Returns:
        (model, scaler, threshold) 또는 (None, None, None)
    """
    path = os.path.join(save_dir, f"radar_guard_model_{scenario}.pt")
    if not os.path.exists(path):
        print(f"⚠️  모델 파일 없음: {path}")
        print("   → radar_guard_pipeline.py 를 먼저 실행해 모델을 저장하세요.")
        return None, None, None

    ckpt = torch.load(path, map_location=device)

    # 모델 복원
    mdl = LSTM_Autoencoder(
        ckpt["feature_size"],
        ckpt["embedding_dim"],
        ckpt["seq_length"]
    ).to(device)
    mdl.load_state_dict(ckpt["model_state"])
    mdl.eval()

    # MinMaxScaler 복원 (transform() 호출에 필요한 속성 수동 주입)
    scaler = MinMaxScaler()
    scaler.scale_          = ckpt["scaler_scale_"]
    scaler.min_            = ckpt["scaler_min_"]
    scaler.data_min_       = ckpt["scaler_data_min_"]
    scaler.data_max_       = ckpt["scaler_data_max_"]
    scaler.data_range_     = ckpt["scaler_data_range_"]
    scaler.feature_range   = ckpt["scaler_feature_range"]
    scaler.n_features_in_  = ckpt["scaler_n_features_in_"]
    scaler.n_samples_seen_ = 1  # sklearn 내부 검증용 더미 값

    threshold = float(ckpt["threshold"])
    print(f"✅ 모델 로드 완료: {path}  (threshold={threshold:.5f})")
    return mdl, scaler, threshold


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


def classify_event(time_signal, freq_signal, recon_error, threshold):
    freqs    = np.fft.fftfreq(128, d=1/fs)[:feature_size]
    dom_idx  = int(np.argmax(freq_signal[1:])) + 1
    dom_freq = float(freqs[dom_idx])

    if dom_freq > 40.0:
        return {"event_type": "fall_detected",    "severity": "critical", "confidence": 0.92}
    elif 25.0 < dom_freq <= 40.0:
        return {"event_type": "pinching",         "severity": "critical", "confidence": 0.88}
    elif dom_freq < 20.0:
        return {"event_type": "vibration_anomaly","severity": "warning",  "confidence": 0.85}
    else:
        return {"event_type": "fall_detected",    "severity": "warning",  "confidence": 0.70}


def build_details(event_type, time_signal, freq_signal, recon_error, threshold, timing):
    return {
        "anomaly_score":        round(recon_error / threshold, 3),
        "reconstruction_error": round(recon_error, 6),
        "timing":               timing,
        "description":          f"{event_type} 감지",
    }


# ================================================================
# 재국 파트 (자동 제어 및 JSON 트리거 출력)
# ================================================================
RESPONSE_MAP = {
    "electric_shock_risk": {"action": "POWER_CUT",       "description": "전원 차단 실행", "breaker_status": "OPEN", "response_ms": 50,  "notify_level": "CRITICAL"},
    "fall_detected":       {"action": "EMERGENCY_ALERT", "description": "비상 알림 발송", "breaker_status": "HOLD", "response_ms": 200, "notify_level": "CRITICAL"},
    "pinching":            {"action": "MACHINE_STOP",    "description": "긴급 정지 명령", "breaker_status": "OPEN", "response_ms": 100, "notify_level": "CRITICAL"},
    "vibration_anomaly":   {"action": "WARNING_ALERT",   "description": "점검 경고 발송", "breaker_status": "HOLD", "response_ms": 500, "notify_level": "WARNING"},
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
# [통합 코어] Jetson Nano 실시간 mmWave 가동 엔진 (v2.0)
# ================================================================
def run_radar_guard_live():
    print(f"\n{'='*55}\n  Radar-Guard 실시간 하드웨어 가동 시작 (v2.0)\n{'='*55}")
    print(f"  디바이스: {device}")

    # ----------------------------------------------------------------
    # 1. 훈련된 모델 로드 (radar_guard_pipeline.py 에서 저장한 파일)
    # ----------------------------------------------------------------
    model, scaler, threshold = load_trained_model(SCENARIO)

    if model is None:
        print("\n⚠️  저장된 모델이 없어 랜덤 가중치로 실행합니다.")
        print("   이상 탐지 결과가 정확하지 않을 수 있습니다.")
        print("   → 먼저 radar_guard_pipeline.py 에서 시나리오를 한 번 실행해 주세요.\n")
        model     = LSTM_Autoencoder(feature_size, 32, seq_length).to(device)
        model.eval()
        scaler    = MinMaxScaler()
        scaler.fit(np.random.normal(0, 1, (100, feature_size)))
        threshold = 0.05

    # ----------------------------------------------------------------
    # 2. Jetson Nano 하드웨어 시리얼 포트 오프너
    #    실행 환경: Jetson Nano SSH 터미널
    #    - 실제 연결: /dev/ttyTHS1 (Jetson UART2, 115200 baud)
    #    - 노트북 테스트: hardware_mode = False 로 자동 전환
    # ----------------------------------------------------------------
    hardware_mode = False
    ser           = None
    parser        = None

    try:
        ser    = serial.Serial('/dev/ttyTHS1', 115200, timeout=1)
        parser = TImmWaveParser(ser)
        hardware_mode = True
        print("🔌 실제 mmWave 레이더 하드웨어 연결 성공 (/dev/ttyTHS1, 115200 baud)")
        print("   TI mmWave TLV 바이너리 파서 활성화")
    except Exception:
        print("⚠️  하드웨어가 감지되지 않아 가상 시뮬레이터 스트림으로 대체 가동합니다.")

    proc          = RadarSignalProcessor(order=32, mu=0.01, window_size=128)
    live_features = []

    print("🔋 실시간 데이터 수집 및 감시 중... (Ctrl+C 종료)\n")

    try:
        while True:
            # ----------------------------------------------------------
            # 3. 데이터 수신
            # ----------------------------------------------------------
            if hardware_mode:
                # ── TI mmWave TLV 바이너리 파싱 ──────────────────────
                # TI IWR6843/AWR1843은 ASCII가 아닌 바이너리 TLV 프레임을 출력합니다.
                # TImmWaveParser.read_frame() 이 프레임 1개를 파싱하여
                # 감지된 포인트 리스트(x, y, z, doppler)를 반환합니다.
                points = parser.read_frame()
                if points is None:
                    # 프레임 미완성 → 다음 루프에서 재시도
                    time.sleep(0.001)
                    continue
                # 포인트 클라우드 → 스칼라 (거리 가중 도플러)
                raw_val = TImmWaveParser.aggregate_to_scalar(points)
            else:
                # ── 시뮬레이션 모드 데이터 ────────────────────────────
                raw_val = np.sin(2 * np.pi * 5 * time.time()) + np.random.normal(0, 0.18)

            # ----------------------------------------------------------
            # 4. 승원 파트 — LMS 필터링
            # ----------------------------------------------------------
            noise_ref      = np.random.normal(0, 0.1)
            cleaned_sample = proc.lms_filter(raw_val, noise_ref)

            # ----------------------------------------------------------
            # 5. 성준 파트 — 이상 탐지
            # ----------------------------------------------------------
            current_feature = proc.extract_features_realtime()
            live_features.append(current_feature.tolist())

            if len(live_features) > seq_length:
                live_features.pop(0)   # 슬라이딩 윈도우 유지

            if len(live_features) == seq_length:
                input_feat  = np.array(live_features)
                scaled_feat = scaler.transform(input_feat)
                X_live      = torch.from_numpy(
                    np.array([scaled_feat])
                ).float().to(device)

                with torch.no_grad():
                    recon = model(X_live)
                    loss  = torch.mean((recon - X_live) ** 2).item()

                if loss > threshold:
                    print(f"🚨 [이상 발생] Loss: {loss:.4f} > Threshold: {threshold:.4f}")

                    time_signal = scaled_feat.flatten()
                    freq_signal = current_feature
                    clf         = classify_event(time_signal, freq_signal, loss, threshold)
                    timing      = {
                        "event_timestamp": datetime.now().isoformat(),
                        "elapsed_ms":      0,
                    }
                    details   = build_details(
                        clf["event_type"], time_signal, freq_signal,
                        loss, threshold, timing
                    )
                    event_obj = {
                        "event_id":   f"evt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_Live",
                        "event_type": clf["event_type"],
                        "zone_id":    ZONE_MAP.get(SCENARIO, "A"),
                        "severity":   clf["severity"],
                        "confidence": clf["confidence"],
                        "details":    details,
                    }

                    # 재국 파트 + 유빈 UI 연쇄 호출
                    jaeguk_breaker(event_obj)
                    print_yubin_preview(event_obj)

                    live_features = []
                    time.sleep(1.5)

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("[정지] 실시간 감시 시스템을 안전하게 종료합니다.")
    finally:
        if ser and ser.is_open:
            ser.close()
            print("시리얼 포트 정상 종료")


if __name__ == "__main__":
    run_radar_guard_live()
