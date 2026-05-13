"""
=================================================================
Radar-Guard | 낙상 목데이터 입력 → 결과 확인 데모
=================================================================
실행하면 나오는 것:
    1. 콘솔: 탐지 결과값 (유형, 신뢰도, 사고 시기 등)
    2. 그래프: 4개 패널 (신호, 복원오차, 에너지, 결과요약)
    3. 파일: fall_result.json (유빈 파트로 넘어가는 데이터)
=================================================================
"""

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import torch
import torch.nn as nn
from torch import optim
from sklearn.preprocessing import MinMaxScaler
from datetime import datetime
import json

fs, seq_length, feature_size = 1000, 3, 64
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {device}")

# ================================================================
# [승원 파트] 낙상 목데이터 생성 + LMS 필터링 + 특징 추출
# ================================================================
class RadarSignalProcessor:
    def __init__(self, order=32, mu=0.01):
        self.weights = np.zeros(order)
        self.buffer  = np.zeros(order)
        self.order, self.mu = order, mu

    def lms_filter(self, input_sample, ref_sample):
        self.buffer    = np.roll(self.buffer, 1)
        self.buffer[0] = ref_sample
        output         = np.dot(self.weights, self.buffer)
        error          = input_sample - output
        self.weights  += 2 * self.mu * error * self.buffer
        return error

    def extract_features(self, sig):
        n   = len(sig)
        w   = np.hanning(n)
        fft = np.fft.fft(sig * w)
        frq = np.fft.fftfreq(n, d=1/fs)
        mag = np.abs(fft) / (n / 2)
        return mag[np.where(frq >= 0)][:feature_size]


print("\n[승원] 낙상 목데이터 200샘플 처리 중...")
raw_signals, event_labels, features = [], [], []

for i in range(200):
    t     = np.linspace(0, 0.1, 128)
    noise = np.random.normal(0, 0.1, 128)

    # 낙상 시나리오: 정상 → 충격 → 정지
    if 100 < i < 110:
        base  = np.sin(2 * np.pi * 50 * t) * 3.0   # 충격 (고주파)
        label = "fall_impact"
    elif i >= 110:
        base  = np.zeros(128)                         # 쓰러진 후 정지
        label = "fall_stillness"
    else:
        base  = np.sin(2 * np.pi * 5 * t)            # 정상 보행
        label = "normal"

    raw = base + noise
    raw_signals.append(raw)
    event_labels.append(label)

    proc    = RadarSignalProcessor()
    noise2  = np.random.normal(0, 0.1, 128)
    cleaned = np.array([proc.lms_filter(r, n * 0.8) for r, n in zip(raw, noise2)])
    features.append(proc.extract_features(cleaned))

print(f"[승원] 완료 — 정상:{event_labels.count('normal')}개  "
      f"충격:{event_labels.count('fall_impact')}개  "
      f"정지:{event_labels.count('fall_stillness')}개")


# ================================================================
# [성준 파트] LSTM-AE 학습 + 이상 탐지 + 유형 분류 + 시기 판별
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
        _, (h, _) = self.encoder1(x)
        _, (h, _) = self.encoder2(h.transpose(0, 1))
        x = h.transpose(0, 1).repeat(1, self.seq_len, 1)
        x, _ = self.decoder1(x)
        x, _ = self.decoder2(x)
        return self.output_layer(x)


def create_sequences(data, seq_len):
    return np.array([data[i:i + seq_len] for i in range(len(data) - seq_len)])


# 정상 데이터 600개로 학습
print("\n[성준] 정상 패턴 학습 중 (600샘플)...")
normal_features = []
for _ in range(600):
    proc  = RadarSignalProcessor()
    t     = np.linspace(0, 0.1, 128)
    raw   = np.sin(2 * np.pi * 5 * t) + np.random.normal(0, 0.2, 128)
    noise = np.random.normal(0, 0.2, 128)
    cleaned = np.array([proc.lms_filter(r, n * 0.8) for r, n in zip(raw, noise)])
    normal_features.append(proc.extract_features(cleaned))

scaler        = MinMaxScaler()
scaled_normal = scaler.fit_transform(normal_features)
X_train       = torch.from_numpy(create_sequences(scaled_normal, seq_length)).float().to(device)

model     = LSTM_Autoencoder(feature_size, 32, seq_length).to(device)
optimizer = optim.AdamW(model.parameters(), lr=0.001)
criterion = nn.MSELoss()

model.train()
for epoch in range(101):
    optimizer.zero_grad()
    loss = criterion(model(X_train), X_train)
    loss.backward()
    optimizer.step()
    if epoch % 25 == 0:
        print(f"  Epoch {epoch:3d} | Loss: {loss.item():.6f}")

# 임계치 설정
model.eval()
with torch.no_grad():
    recon      = model(X_train)
    train_loss = torch.mean((recon - X_train) ** 2, dim=(1, 2)).cpu().numpy()
    threshold  = float(np.mean(train_loss) + 3 * np.std(train_loss))
print(f"[성준] 학습 완료 | 임계치(μ+3σ): {threshold:.6f}")

# 낙상 데이터 탐지
scaled_test = scaler.transform(features)
X_test = torch.from_numpy(create_sequences(scaled_test, seq_length)).float().to(device)
with torch.no_grad():
    test_recon = model(X_test)
    test_loss  = torch.mean((test_recon - X_test) ** 2, dim=(1, 2)).cpu().numpy()
is_anomaly = test_loss > threshold

# 사고 시기 판별
anomaly_steps = np.where(is_anomaly)[0]
start_step    = int(anomaly_steps[0]) if len(anomaly_steps) > 0 else None
peak_step     = int(np.argmax(test_loss))
duration      = int(len(anomaly_steps))
ms_per_step   = (128 / fs) * 1000
elapsed_ms    = round(start_step * ms_per_step, 1) if start_step else 0

# 유형 분류
peak_sig = scaled_test[peak_step:peak_step + seq_length].flatten()
n, eps   = len(peak_sig), 1e-10
energy_front = float(np.mean(peak_sig[:n // 2] ** 2)) + eps
tail_energy  = float(np.mean(peak_sig[int(n * 0.7):] ** 2))
peak_amp     = float(np.max(np.abs(peak_sig))) + eps
fft_mag      = np.abs(np.fft.fft(peak_sig))[:n // 2]
freqs        = np.fft.fftfreq(n, d=1 / fs)[:n // 2]
hf_ratio     = float(np.sum(fft_mag[freqs > 20]) / (np.sum(fft_mag) + eps))
pl_mask      = ((freqs >= 45) & (freqs <= 55)) | ((freqs >= 55) & (freqs <= 65))
pl_ratio     = float(np.sum(fft_mag[pl_mask]) / (np.sum(fft_mag) + eps))
zcr          = float(len(np.where(np.diff(np.sign(peak_sig)))[0]) / n)
tail_silence = tail_energy < 0.05 * energy_front
excess       = float(test_loss[peak_step]) / threshold

if pl_ratio > 0.15 and zcr > 0.20:
    event_type, confidence = "electric_shock_risk", round(min(0.99, 0.50 + 0.25 * min(1, pl_ratio / 0.3)), 2)
elif tail_silence and hf_ratio > 0.25:
    event_type, confidence = "fall_detected", round(min(0.99, 0.55 + 0.20 * min(1, excess - 1) + 0.15 * hf_ratio), 2)
else:
    event_type, confidence = "fall_detected", round(min(0.75, 0.40 + 0.10 * excess), 2)

# ── 콘솔 결과 출력 ──────────────────────────────────────────────
print("\n" + "=" * 55)
print("  성준 파트 탐지 결과 (낙상 목데이터 입력)")
print("=" * 55)
print(f"  이벤트 유형    : {event_type}")
print(f"  심각도         : critical")
print(f"  신뢰도         : {confidence:.0%}")
print(f"  임계치(μ+3σ)   : {threshold:.6f}")
print(f"  피크 오차      : {test_loss[peak_step]:.6f}")
print(f"  이상 배율      : {excess:.2f}× (임계치 대비)")
print(f"  이상 탐지 건수 : {duration}건 / {len(test_loss)}건")
print(f"  사고 시작 step : {start_step}")
print(f"  사고 피크 step : {peak_step}")
print(f"  지속 구간      : {duration} steps")
print(f"  경과 시간      : {elapsed_ms} ms")
print(f"  tail_silence   : {tail_silence}  (신호 소멸 여부)")
print(f"  high_freq_ratio: {hf_ratio:.3f}  (고주파 충격 성분)")
print("=" * 55)

# ── JSON 저장 (유빈에게 전달) ────────────────────────────────────
result = {
    "schema_version": "1.0",
    "timestamp":      datetime.now().isoformat(),
    "event_id":       f"evt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_C001",
    "event_type":     event_type,
    "zone_id":        "C",
    "severity":       "critical",
    "confidence":     confidence,
    "details": {
        "description":          "작업자 낙상 확정 (자세 붕괴 + 속도 임계 초과)",
        "anomaly_score":        round(excess, 3),
        "reconstruction_error": round(float(test_loss[peak_step]), 6),
        "worker_pose": {
            "posture":      "collapsed",
            "velocity_m_s": round(min(peak_amp * 0.03, 2.0), 3),
            "height_m":     round(max(0.1, 1.8 - peak_amp * 0.4), 2),
        },
        "equipment_anomaly": None,
        "timing": {
            "anomaly_start_step": start_step,
            "anomaly_peak_step":  peak_step,
            "anomaly_duration":   duration,
            "elapsed_ms":         elapsed_ms,
        },
    },
    "event_log": [
        {"time": datetime.now().strftime('%H:%M:%S'), "msg": "Zone C - LSTM-AE 이상 탐지"},
        {"time": datetime.now().strftime('%H:%M:%S'), "msg": f"Zone C - 유형 분류: {event_type}"},
        {"time": datetime.now().strftime('%H:%M:%S'), "msg": "Zone C - 낙상 확정, 알림 발송"},
    ],
}

with open("fall_result.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print("\n[저장] fall_result.json → 유빈 파트로 전달")


# ================================================================
# 그래프 출력 (4개 패널)
# ================================================================
fig, axes = plt.subplots(2, 2, figsize=(14, 9))
fig.patch.set_facecolor("#F5F6FA")
fig.suptitle("Radar-Guard | 낙상(Fall) 목데이터 입력 결과",
             fontsize=14, fontweight="bold", color="#2C3E50")

# ── [패널 1] 원본 vs 필터링 신호 (낙상 충격 구간) ────────────────
ax = axes[0, 0]
t_ms      = np.linspace(0, 0.1, 128) * 1000
raw_105   = raw_signals[105]           # 낙상 충격 구간 샘플
proc_tmp  = RadarSignalProcessor()
noise_tmp = np.random.normal(0, 0.1, 128)
clean_105 = np.array([proc_tmp.lms_filter(r, n * 0.8) for r, n in zip(raw_105, noise_tmp)])

ax.plot(t_ms, raw_105,   color="#E74C3C", lw=1.2, alpha=0.7, label="원본 신호 (노이즈 포함)")
ax.plot(t_ms, clean_105, color="#2980B9", lw=2.0, label="LMS 필터링 후 (승원 파트)")
ax.set_title("① 낙상 충격 순간 신호 (step 105)", fontsize=10, fontweight="bold")
ax.set_xlabel("Time (ms)"); ax.set_ylabel("Amplitude")
ax.legend(fontsize=8); ax.grid(alpha=0.3)
ax.set_facecolor("#FAFAFA")

# ── [패널 2] 복원 오차 + 임계치 ──────────────────────────────────
ax = axes[0, 1]
ax.plot(test_loss, color="#2980B9", lw=1.5, label="복원 오차 (MSE)")
ax.axhline(threshold, color="#E74C3C", linestyle="--", lw=1.8,
           label=f"임계치 μ+3σ = {threshold:.4f}")
ax.fill_between(range(len(test_loss)), test_loss, threshold,
                where=(test_loss > threshold),
                color="#E74C3C", alpha=0.25, label="이상 탐지 구간")
if start_step:
    ax.axvline(start_step, color="#F39C12", lw=2, linestyle=":",
               label=f"사고 시작 step {start_step}")
ax.axvline(peak_step, color="#8E44AD", lw=2, linestyle="-.",
           label=f"사고 피크 step {peak_step}")
ax.set_title("② LSTM-AE 복원 오차 (성준 파트)", fontsize=10, fontweight="bold")
ax.set_xlabel("Time Step"); ax.set_ylabel("MSE Loss")
ax.legend(fontsize=7); ax.grid(alpha=0.3)
ax.set_facecolor("#FAFAFA")

# ── [패널 3] 구간별 신호 에너지 ──────────────────────────────────
ax = axes[1, 0]
energies = [float(np.mean(np.array(f) ** 2)) for f in features]
bar_colors = []
for lbl in event_labels:
    if lbl == "normal":       bar_colors.append("#3498DB")
    elif lbl == "fall_impact":bar_colors.append("#E74C3C")
    else:                     bar_colors.append("#95A5A6")

ax.bar(range(len(energies)), energies, color=bar_colors, alpha=0.8, width=1.0)
ax.axvline(100, color="#F39C12", lw=2.5, linestyle="--", label="낙상 충격 시작")
ax.axvline(110, color="#95A5A6", lw=2.5, linestyle="--", label="정지 구간 시작")
legend_patches = [
    mpatches.Patch(color="#3498DB", label="정상 보행"),
    mpatches.Patch(color="#E74C3C", label="낙상 충격"),
    mpatches.Patch(color="#95A5A6", label="낙상 후 정지"),
]
ax.legend(handles=legend_patches, fontsize=8)
ax.set_title("③ 시간별 신호 에너지", fontsize=10, fontweight="bold")
ax.set_xlabel("Time Step"); ax.set_ylabel("Signal Energy")
ax.grid(alpha=0.3, axis="y"); ax.set_facecolor("#FAFAFA")

# ── [패널 4] 유빈에게 전달되는 결과 요약 ────────────────────────
ax = axes[1, 1]
ax.set_facecolor("#1E1E2E")
ax.axis("off")

lines = [
    ("▶  유빈에게 전달되는 결과값",      "#F39C12", 11, True),
    ("",                                  "#FFF",    8,  False),
    (f'event_type   : "{event_type}"',   "#E06C75", 9,  False),
    (f'severity     : "critical"',        "#E06C75", 9,  False),
    (f'confidence   : {confidence:.0%}',  "#61AFEF", 9,  False),
    ("",                                  "#FFF",    8,  False),
    (f'start_step   : {start_step}',      "#98C379", 9,  False),
    (f'peak_step    : {peak_step}',       "#98C379", 9,  False),
    (f'duration     : {duration} steps',  "#98C379", 9,  False),
    (f'elapsed_ms   : {elapsed_ms} ms',   "#98C379", 9,  False),
    ("",                                  "#FFF",    8,  False),
    (f'posture      : "collapsed"',       "#ABB2BF", 9,  False),
    (f'tail_silence : {tail_silence}',    "#ABB2BF", 9,  False),
    (f'hf_ratio     : {hf_ratio:.3f}',    "#ABB2BF", 9,  False),
    (f'anomaly_score: {excess:.2f}×',     "#ABB2BF", 9,  False),
]
y = 0.97
for text, color, size, bold in lines:
    ax.text(0.05, y, text, transform=ax.transAxes,
            fontsize=size, color=color, va="top",
            fontweight="bold" if bold else "normal",
            family="monospace")
    y -= 0.063

plt.tight_layout()
plt.savefig("fall_result.png", dpi=150, bbox_inches="tight", facecolor="#F5F6FA")
plt.show()
print("[저장] fall_result.png")
