"""
=================================================================
Radar-Guard | 성준 파트 v2 — 유빈 명세서(v1) 완전 호환
=================================================================
수정 사항 (v1 → v2):
    [Fix 1] 이벤트 타입명 유빈 명세서 기준으로 통일
            electric_shock      → electric_shock_risk
            entrapment_detected → pinching
            equipment_fault     → vibration_anomaly

    [Fix 2] details 구조 유빈 명세서 기준으로 완전 재작성
            fall_detected     : worker_pose {posture, velocity_m_s, height_m}
            electric_shock_risk: proximity_m, equipment_voltage_kv, approach_speed_m_s
            pinching          : equipment_id, body_part_proximity_m, rotation_rpm
            vibration_anomaly : equipment_id, rms_vibration_um_s, threshold_um_s,
                                frequency_anomaly_hz, bearing_fault_suspected

    [Fix 3] 시각화 Streamlit 호환
            plt.show() 대신 fig 반환 → Streamlit: st.pyplot(fig) / 일반: plt.show()

함수 시그니처 (유빈 명세서 §5):
    def detect_anomaly(filtered_signal: dict) -> dict | None
=================================================================
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")   # Streamlit 환경에서 백엔드 충돌 방지
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import torch
import torch.nn as nn
from torch import optim
from sklearn.preprocessing import MinMaxScaler
from datetime import datetime, timedelta
import json

# Streamlit 환경 자동 감지
try:
    import streamlit as st
    IS_STREAMLIT = True
except ImportError:
    IS_STREAMLIT = False

# ─── 공통 설정 ──────────────────────────────────────────────────
fs           = 1000
seq_length   = 3
feature_size = 64
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using Device: {device}")

# ─── 유빈 명세서 §2: 이벤트 타입 4가지 (확정) ───────────────────
EVENT_TYPES = {
    "fall_detected":      "낙상",
    "electric_shock_risk":"감전 위험",
    "pinching":           "협착",
    "vibration_anomaly":  "진동 이상",
}


# ================================================================
# [Part 1] 승원 파트 인터페이스
# ================================================================
class RadarSignalProcessor:
    """승원 파트 신호처리기 — 성준 파트에서 인터페이스로만 사용"""
    def __init__(self, order=32, mu=0.01):
        self.order   = order
        self.mu      = mu
        self.weights = np.zeros(order)
        self.buffer  = np.zeros(order)

    def lms_filter(self, input_sample, ref_sample):
        self.buffer    = np.roll(self.buffer, 1)
        self.buffer[0] = ref_sample
        output         = np.dot(self.weights, self.buffer)
        error          = input_sample - output
        self.weights  += 2 * self.mu * error * self.buffer
        return error

    def extract_features(self, filtered_signal, fs):
        n         = len(filtered_signal)
        window    = np.hanning(n)
        fft_res   = np.fft.fft(filtered_signal * window)
        freqs     = np.fft.fftfreq(n, d=1 / fs)
        magnitude = np.abs(fft_res) / (n / 2)
        pos_idx   = np.where(freqs >= 0)
        return magnitude[pos_idx][:feature_size]


# ================================================================
# [Part 2] LSTM-Autoencoder
# ================================================================
class LSTM_Autoencoder(nn.Module):
    def __init__(self, n_features, embedding_dim, seq_len):
        super().__init__()
        self.seq_len  = seq_len
        self.encoder1 = nn.LSTM(n_features, embedding_dim, batch_first=True)
        self.encoder2 = nn.LSTM(embedding_dim, embedding_dim // 2, batch_first=True)
        self.decoder1 = nn.LSTM(embedding_dim // 2, embedding_dim // 2, batch_first=True)
        self.decoder2 = nn.LSTM(embedding_dim // 2, embedding_dim, batch_first=True)
        self.output_layer = nn.Linear(embedding_dim, n_features)

    def forward(self, x):
        _, (hidden, _) = self.encoder1(x)
        _, (hidden, _) = self.encoder2(hidden.transpose(0, 1))
        x = hidden.transpose(0, 1).repeat(1, self.seq_len, 1)
        x, _ = self.decoder1(x)
        x, _ = self.decoder2(x)
        return self.output_layer(x)


# ================================================================
# [Part 3] 사고 유형 분류기
#          → [Fix 1] 이벤트 타입명 유빈 명세서 기준으로 수정
#          → [Fix 2] details 구조 유빈 명세서 기준으로 수정
# ================================================================
class AccidentClassifier:
    def __init__(self, fs=1000):
        self.fs = fs

    def _extract_features(self, signal: np.ndarray) -> dict:
        n, eps = len(signal), 1e-10
        energy_front    = float(np.mean(signal[:n // 2] ** 2)) + eps
        energy_back     = float(np.mean(signal[n // 2:] ** 2)) + eps
        tail_energy     = float(np.mean(signal[int(n * 0.7):] ** 2))
        peak_amp        = float(np.max(np.abs(signal))) + eps
        sustained_cnt   = np.sum(np.abs(signal) > peak_amp * 0.5)

        fft_mag  = np.abs(np.fft.fft(signal))[:n // 2]
        freqs    = np.fft.fftfreq(n, d=1 / self.fs)[:n // 2]
        dominant_freq   = float(freqs[np.argmax(fft_mag[1:]) + 1])
        high_freq_ratio = float(np.sum(fft_mag[freqs > 20]) / (np.sum(fft_mag) + eps))
        mask_pl = ((freqs >= 45) & (freqs <= 55)) | ((freqs >= 55) & (freqs <= 65))
        power_line_ratio = float(np.sum(fft_mag[mask_pl]) / (np.sum(fft_mag) + eps))
        zcr = float(len(np.where(np.diff(np.sign(signal)))[0]) / n)

        return {
            "energy_ratio":      float(energy_back / energy_front),
            "tail_silence":      tail_energy < 0.05 * energy_front,
            "sustained_high":    (sustained_cnt / n) > 0.40,
            "peak_amplitude":    peak_amp,
            "dominant_freq_hz":  dominant_freq,
            "high_freq_ratio":   high_freq_ratio,
            "power_line_ratio":  power_line_ratio,
            "zcr":               zcr,
            "signal_rms":        float(np.sqrt(np.mean(signal ** 2))),
            "signal_variance":   float(np.var(signal)),
        }

    # ------------------------------------------------------------------
    # [Fix 2] 이벤트 유형별 details 구조 — 유빈 명세서 §2 기준
    # ------------------------------------------------------------------
    def _build_details(self, event_type: str, feat: dict,
                       recon_error: float, threshold: float) -> dict:
        excess = recon_error / threshold

        if event_type == "fall_detected":
            # 속도: 신호 에너지 변화율로 근사 (에너지가 클수록 속도 빠름)
            velocity = round(float(feat["peak_amplitude"] * 0.03), 3)
            # 높이: 피크 직전 에너지 기반 근사 (넘어지면서 낮아짐)
            height   = round(max(0.1, 1.8 - feat["peak_amplitude"] * 0.4), 2)
            return {
                "description":    "작업자 낙상 확정 (자세 붕괴 + 속도 임계 초과)",
                "worker_pose":    {
                    "posture":      "collapsed",
                    "velocity_m_s": min(velocity, 2.0),
                    "height_m":     height,
                },
                "equipment_anomaly": None,
                "anomaly_score":       round(excess, 3),
                "reconstruction_error":round(recon_error, 6),
            }

        elif event_type == "electric_shock_risk":
            # 근접 거리: 전력 주파수 성분 강도로 역산 (성분 강할수록 가까움)
            proximity = round(max(0.05, 1.0 - feat["power_line_ratio"] * 3.0), 2)
            # 접근 속도: ZCR 기반 (경련/불규칙할수록 빠른 접근)
            approach_speed = round(float(feat["zcr"] * 4.0), 2)
            return {
                "description":       "감전 위험 감지 (전력 주파수 성분 + 경련 패턴)",
                "proximity_m":       min(proximity, 0.5),
                "equipment_voltage_kv": 22.9,          # 현장 기본값
                "approach_speed_m_s":  min(approach_speed, 3.0),
                "anomaly_score":        round(excess, 3),
                "reconstruction_error": round(recon_error, 6),
            }

        elif event_type == "pinching":
            # 신체-장비 근접: 지속 에너지 강도 기반
            body_prox = round(max(0.02, 0.3 - feat["peak_amplitude"] * 0.05), 3)
            # 회전 RPM: 신호 지배 주파수 기반 (Hz → RPM 변환)
            rpm = round(abs(feat["dominant_freq_hz"]) * 60, 0)
            return {
                "description":          "협착 감지 (회전체 근접 + 압박 신호 지속)",
                "equipment_id":         "rotor_detected",
                "body_part_proximity_m":min(body_prox, 0.2),
                "rotation_rpm":         min(int(rpm), 3600),
                "anomaly_score":        round(excess, 3),
                "reconstruction_error": round(recon_error, 6),
            }

        elif event_type == "vibration_anomaly":
            # RMS 진동 (μm/s 단위로 변환: 신호 RMS × 스케일 팩터)
            rms_vib     = round(feat["signal_rms"] * 1000, 2)
            freq_anomaly = round(feat["dominant_freq_hz"], 1)
            # 베어링 불량: 지배 주파수가 비정상 범위(15~50Hz)이면 의심
            bearing_fault = (15.0 < freq_anomaly < 50.0)
            return {
                "description":          "진동 이상 감지 (저주파 드리프트/마모 패턴)",
                "equipment_id":         "motor_detected",
                "rms_vibration_um_s":   rms_vib,
                "threshold_um_s":       1.0,              # 현장 임계치 기본값
                "frequency_anomaly_hz": freq_anomaly,
                "bearing_fault_suspected": bearing_fault,
                "anomaly_score":        round(excess, 3),
                "reconstruction_error": round(recon_error, 6),
            }

        return {}

    # ------------------------------------------------------------------
    # 공개 메서드: 분류 실행
    # ------------------------------------------------------------------
    def classify(self, filtered_signal: np.ndarray,
                 reconstruction_error: float, threshold: float) -> dict:
        if reconstruction_error <= threshold:
            return {"event_type": None, "severity": "normal", "confidence": 1.0}

        feat         = self._extract_features(filtered_signal)
        excess_ratio = reconstruction_error / threshold

        # ── 분류 규칙 (우선순위: 감전 > 낙상 > 협착 > 진동이상) ──

        # [Fix 1] electric_shock → electric_shock_risk
        if feat["power_line_ratio"] > 0.15 and feat["zcr"] > 0.20:
            event_type = "electric_shock_risk"
            severity   = "critical"
            confidence = round(min(0.99,
                0.50 + 0.25 * min(1.0, feat["power_line_ratio"] / 0.3)
                     + 0.15 * min(1.0, feat["zcr"] / 0.4)
                     + 0.10 * min(1.0, excess_ratio - 1)), 2)

        elif feat["tail_silence"] and feat["high_freq_ratio"] > 0.25:
            event_type = "fall_detected"
            severity   = "critical" if excess_ratio > 2.0 else "warning"
            confidence = round(min(0.99,
                0.55 + 0.20 * min(1.0, excess_ratio - 1)
                     + 0.15 * feat["high_freq_ratio"]
                     + 0.10 * (1.0 - feat["energy_ratio"])), 2)

        # [Fix 1] entrapment_detected → pinching
        elif feat["sustained_high"] and feat["energy_ratio"] > 0.50:
            event_type = "pinching"
            severity   = "critical" if excess_ratio > 2.5 else "warning"
            confidence = round(min(0.99,
                0.50 + 0.25 * min(1.0, feat["energy_ratio"])
                     + 0.15 * min(1.0, excess_ratio - 1)
                     + 0.10 * int(feat["sustained_high"])), 2)

        # [Fix 1] equipment_fault → vibration_anomaly
        elif feat["dominant_freq_hz"] < 15.0 and not feat["tail_silence"]:
            event_type = "vibration_anomaly"
            severity   = "warning"
            confidence = round(min(0.99,
                0.45 + 0.30 * min(1.0, excess_ratio - 1)
                     + 0.10 * (1.0 - min(1.0, feat["dominant_freq_hz"] / 15.0))), 2)

        else:
            event_type = "fall_detected"
            severity   = "warning"
            confidence = round(min(0.75, 0.40 + 0.10 * excess_ratio), 2)

        details = self._build_details(event_type, feat, reconstruction_error, threshold)

        return {
            "event_type": event_type,
            "severity":   severity,
            "confidence": confidence,
            "details":    details,
            "_feat":      feat,          # 내부 디버깅용 (유빈 파트로 전달 불필요)
        }


# ================================================================
# [Part 4] generate_report — 유빈 명세서 §2 JSON 스키마 완전 준수
#          이 함수의 출력이 유빈 파트 generate_rag_guide(event) 의 입력
# ================================================================
def generate_report(classify_result: dict, zone: str = "C") -> dict | None:
    """
    성준 파트 최종 출력 함수 (유빈 명세서 §5 함수 시그니처)
    detect_anomaly()에서 호출됨.

    Returns: Stage 2→3 JSON 구조 / 정상이면 None
    """
    if classify_result.get("event_type") is None:
        return None

    now      = datetime.now()
    event_id = f"evt_{now.strftime('%Y%m%d_%H%M%S')}_{zone}001"
    etype    = classify_result["event_type"]
    details  = classify_result["details"]

    # event_log (유빈 §2: UI Event Log에 표시)
    event_log = [
        {"time": now.strftime('%H:%M:%S'),
         "msg":  f"Zone {zone} - LSTM-AE 이상 탐지"},
        {"time": (now + timedelta(milliseconds=120)).strftime('%H:%M:%S'),
         "msg":  f"Zone {zone} - 유형 분류 완료: {etype}"},
        {"time": (now + timedelta(milliseconds=240)).strftime('%H:%M:%S'),
         "msg":  f"Zone {zone} - 알림 발송 (severity={classify_result['severity']})"},
    ]

    return {
        "schema_version": "1.0",
        "timestamp":      now.isoformat(),
        "event_id":       event_id,
        "event_type":     etype,             # fall_detected | electric_shock_risk |
                                             # pinching | vibration_anomaly
        "zone_id":        zone,
        "severity":       classify_result["severity"],
        "confidence":     classify_result["confidence"],
        "details":        details,           # 유형별 구조 (§2 명세 준수)
        "event_log":      event_log,
        "raw_signal_ref": f"filtered_{now.strftime('%Y%m%d_%H%M%S')}.json",
    }


# ================================================================
# [Part 5] detect_anomaly — 유빈 명세서 §5 공식 함수 시그니처
# ================================================================
_model: LSTM_Autoencoder | None = None
_scaler: MinMaxScaler | None    = None
_threshold: float | None        = None
_classifier = AccidentClassifier(fs=fs)


def detect_anomaly(filtered_signal: dict) -> dict | None:
    """
    유빈 명세서 §5 함수 시그니처:
        Args:    filtered_signal: Stage 1-2 JSON 구조 (승원 파트 출력)
        Returns: event: Stage 2-3 JSON 구조 / 이상 없으면 None
    """
    global _model, _scaler, _threshold

    if _model is None or _scaler is None or _threshold is None:
        raise RuntimeError("모델이 학습되지 않았습니다. train_model()을 먼저 실행하세요.")

    # 승원 파트 출력에서 진동 스펙트럼 추출
    spec = filtered_signal.get("filtered_signal", {}).get("vibration_spectrum", {})
    amplitude = np.array(spec.get("amplitude", [0.0] * feature_size), dtype=np.float32)

    # feature_size 맞추기
    if len(amplitude) < feature_size:
        amplitude = np.pad(amplitude, (0, feature_size - len(amplitude)))
    else:
        amplitude = amplitude[:feature_size]

    scaled  = _scaler.transform([amplitude])
    seq     = np.array([scaled] * seq_length, dtype=np.float32)
    x_input = torch.from_numpy(seq).unsqueeze(0).to(device)

    _model.eval()
    with torch.no_grad():
        recon = _model(x_input)
        error = float(torch.mean((recon - x_input) ** 2).cpu().numpy())

    zone   = filtered_signal.get("zone_id", "?")
    result = _classifier.classify(amplitude, error, _threshold)
    return generate_report(result, zone=zone)


# ================================================================
# [Part 6] 학습 함수
# ================================================================
def create_sequences(data, seq_len):
    return np.array([data[i:i + seq_len] for i in range(len(data) - seq_len)])


def train_model():
    global _model, _scaler, _threshold
    print("\n[1/2] 정상 데이터 학습 중...")

    normal_features = []
    for _ in range(600):
        proc  = RadarSignalProcessor()
        t     = np.linspace(0, 0.1, 128)
        raw   = np.sin(2 * np.pi * 5 * t) + np.random.normal(0, 0.2, 128)
        noise = np.random.normal(0, 0.2, 128)
        cleaned = [proc.lms_filter(r, n * 0.8) for r, n in zip(raw, noise)]
        normal_features.append(proc.extract_features(np.array(cleaned), fs))

    _scaler       = MinMaxScaler()
    scaled_normal = _scaler.fit_transform(normal_features)
    X_train       = torch.from_numpy(create_sequences(scaled_normal, seq_length)).float().to(device)

    _model = LSTM_Autoencoder(n_features=feature_size, embedding_dim=32, seq_len=seq_length).to(device)
    optimizer = optim.AdamW(_model.parameters(), lr=0.001)
    criterion = nn.MSELoss()

    _model.train()
    for epoch in range(101):
        optimizer.zero_grad()
        loss = criterion(_model(X_train), X_train)
        loss.backward()
        optimizer.step()
        if epoch % 20 == 0:
            print(f"  Epoch {epoch:3d} | Loss: {loss.item():.6f}")

    _model.eval()
    with torch.no_grad():
        train_recon = _model(X_train)
        train_loss  = torch.mean((train_recon - X_train) ** 2, dim=(1, 2)).cpu().numpy()
        _threshold  = float(np.mean(train_loss) + 3 * np.std(train_loss))

    print(f"[2/2] 학습 완료 | 임계치(μ+3σ): {_threshold:.6f}")


# ================================================================
# [Part 7] 시각화 — [Fix 3] fig 반환 → Streamlit/Jupyter 양쪽 대응
# ================================================================
COLOR = {
    "fall_detected":      "#E74C3C",
    "electric_shock_risk":"#F39C12",
    "pinching":           "#8E44AD",
    "vibration_anomaly":  "#795548",
    "normal":             "#27AE60",
}
LABEL = {
    "fall_detected":      "🚨 낙상",
    "electric_shock_risk":"⚡ 감전 위험",
    "pinching":           "🔒 협착",
    "vibration_anomaly":  "⚙️  진동 이상",
}


def plot_results(test_loss: np.ndarray, is_anomaly: np.ndarray,
                 results: list, scaled_test: np.ndarray,
                 threshold: float) -> plt.Figure:
    """
    [Fix 3] plt.show() 제거 → fig 반환
    - Streamlit: st.pyplot(fig)
    - Jupyter  : plt.show() 또는 display(fig)
    """
    fig = plt.figure(figsize=(16, 10), facecolor="#F5F6FA")
    fig.suptitle("Radar-Guard | 성준 파트: 사고 유형 탐지 결과",
                 fontsize=14, fontweight="bold", color="#2C3E50")
    gs = plt.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35)

    # ── 복원 오차 ────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(test_loss, color="royalblue", lw=1.5, label="복원 오차 (MSE)")
    ax1.axhline(threshold, color="red", linestyle="--",
                label=f"임계치 μ+3σ = {threshold:.4f}")
    for res in results:
        if res.get("event_type"):
            i = res["_step"]
            c = COLOR.get(res["event_type"], "gray")
            ax1.axvline(i, color=c, lw=1.2, alpha=0.5)
            ax1.text(i, threshold * 1.05, LABEL.get(res["event_type"], ""),
                     fontsize=6.5, color=c, rotation=45, ha="left")
    ax1.set_title("전체 복원 오차 및 사고 탐지 포인트")
    ax1.set_xlabel("Time Step"); ax1.set_ylabel("MSE Loss")
    ax1.legend(fontsize=8); ax1.grid(alpha=0.25)

    # ── 탐지 포인트 산점도 ───────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    ax2.plot(scaled_test[:, 0], color="gray", alpha=0.4, lw=1)
    for res in results:
        if res.get("event_type"):
            i = res["_step"]
            c = COLOR.get(res["event_type"], "gray")
            ax2.scatter(i, scaled_test[i, 0], color=c, s=50, zorder=5)
    handles = [mpatches.Patch(color=COLOR[k], label=LABEL[k]) for k in COLOR if k != "normal"]
    ax2.legend(handles=handles, fontsize=7)
    ax2.set_title("탐지 포인트 분류 결과")
    ax2.set_xlabel("Time Step"); ax2.grid(alpha=0.25)

    # ── 신뢰도 바 ────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    detected = [r for r in results if r.get("event_type")]
    if detected:
        labels  = [LABEL.get(r["event_type"], r["event_type"]) for r in detected]
        confs   = [r["confidence"] for r in detected]
        colors  = [COLOR.get(r["event_type"], "gray") for r in detected]
        bars    = ax3.bar(range(len(confs)), confs, color=colors, alpha=0.8, edgecolor="white")
        ax3.axhline(0.7, color="black", linestyle=":", lw=1, label="신뢰도 기준 0.7")
        ax3.set_xticks(range(len(labels)))
        ax3.set_xticklabels(labels, fontsize=7, rotation=15)
        ax3.set_ylim(0, 1.05); ax3.set_ylabel("Confidence")
        ax3.set_title("탐지 건별 신뢰도"); ax3.legend(fontsize=8); ax3.grid(alpha=0.25, axis="y")

    return fig   # ← plt.show() 대신 fig 반환


def show_figure(fig: plt.Figure):
    """Streamlit / Jupyter 환경 자동 분기"""
    if IS_STREAMLIT:
        st.pyplot(fig)          # [Fix 3] Streamlit 환경
    else:
        plt.show()              # Jupyter / 일반 Python


# ================================================================
# [Part 8] 메인 실행 (직접 실행 시 데모)
# ================================================================
if __name__ == "__main__":
    # 학습
    train_model()

    # 테스트 시나리오 합성
    print("\n테스트 데이터 생성 중...")
    test_features, event_labels = [], []

    for i in range(240):
        proc  = RadarSignalProcessor()
        t     = np.linspace(0, 0.1, 128)
        noise = np.random.normal(0, 0.1, 128)

        if i < 60:
            sig, label = np.sin(2 * np.pi * 5 * t), "normal"
        elif i < 80:
            sig   = np.concatenate([np.sin(2 * np.pi * 50 * t[:64]) * 3, np.zeros(64)])
            label = "fall_detected"
        elif i < 120:
            sig   = (np.sin(2 * np.pi * 50 * t) * 2.0
                     + np.random.normal(0, 0.5, 128)
                     + np.sin(2 * np.pi * 63 * t) * 0.8)
            label = "electric_shock_risk"
        elif i < 180:
            sig   = np.sin(2 * np.pi * 5 * t) * 2.5 + np.random.normal(0, 0.3, 128)
            label = "pinching"
        else:
            sig   = (np.sin(2 * np.pi * 3 * t) * 1.5
                     + np.sin(2 * np.pi * 7 * t) * 0.5
                     + np.random.normal(0, 0.1, 128))
            label = "vibration_anomaly"

        raw     = sig + noise
        cleaned = [proc.lms_filter(r, n * 0.8) for r, n in zip(raw, noise)]
        test_features.append(proc.extract_features(np.array(cleaned), fs))
        event_labels.append(label)

    scaled_test = _scaler.transform(test_features)
    X_test = torch.from_numpy(
        create_sequences(scaled_test, seq_length)
    ).float().to(device)

    _model.eval()
    with torch.no_grad():
        test_recon = _model(X_test)
        test_loss  = torch.mean((test_recon - X_test) ** 2, dim=(1, 2)).cpu().numpy()
    is_anomaly = test_loss > _threshold

    # 분류 + 리포트 생성
    results_for_yubin = []
    print(f"\n{'─'*65}")
    print(f"{'Step':>5} │ {'이벤트 타입':<22} │ {'신뢰도':>6} │ 심각도")
    print(f"{'─'*65}")

    for i, (err, flag) in enumerate(zip(test_loss, is_anomaly)):
        if not flag:
            continue
        sig_win = scaled_test[i:i + seq_length].flatten()
        res     = _classifier.classify(sig_win, float(err), _threshold)
        report  = generate_report(res, zone="C")

        if report:
            report["_step"]         = i       # 시각화용 내부 키
            report["_confidence"]   = res["confidence"]
            report["confidence"]    = res["confidence"]
            report["event_type"]    = res["event_type"]
            report["_feat"]         = res.get("_feat", {})
            results_for_yubin.append(report)

            print(f"  {i:3d}  │ {res['event_type']:<22} │ "
                  f"{res['confidence']:>6.2f} │ {res['severity']}")

    print(f"{'─'*65}")
    print(f"\n✅ 유빈에게 전달: {len(results_for_yubin)}건")
    print(f"   임계치(μ+3σ): {_threshold:.6f}")

    # 유빈에게 전달할 JSON 저장
    export = []
    for r in results_for_yubin:
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        export.append(clean)

    with open("stage2_event.json", "w", encoding="utf-8") as f:
        json.dump(export, f, ensure_ascii=False, indent=2)
    print("\n[저장] stage2_event.json → 유빈 파트로 전달")

    # 샘플 리포트 출력
    if export:
        print("\n[샘플 리포트 — 첫 번째 탐지 이벤트]")
        print(json.dumps(export[0], indent=2, ensure_ascii=False))

    # 시각화
    # 내부 키가 있는 results_for_yubin 사용 (시각화에는 _step 필요)
    fig = plot_results(test_loss, is_anomaly, results_for_yubin, scaled_test, _threshold)
    show_figure(fig)   # [Fix 3] 자동 분기
