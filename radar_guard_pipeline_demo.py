"""
=================================================================
Radar-Guard | UI 확인용 데모 코드
=================================================================
목적:
    성준 파트 결과(results_for_yubin)가 유빈 파트 generate_report()를
    거쳐 UI에 정상적으로 표시되는지 확인하기 위한 독립 테스트 코드

데이터:
    - [옵션 A] NAB(Numenta Anomaly Benchmark) 공개 데이터셋 자동 사용
    - [옵션 B] 네트워크 없으면 완전 합성 데이터로 자동 전환

출력:
    1. 유빈에게 전달되는 JSON 리포트 콘솔 출력
    2. matplotlib 기반 UI 시뮬레이션 대시보드
    3. reports_output.json 파일 저장
=================================================================
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from datetime import datetime, timedelta
import json, warnings
warnings.filterwarnings("ignore")

# ─── NAB 데이터셋 시도 (없으면 합성 데이터로 fallback) ───────────
try:
    import pandas as pd
    import urllib.request
    NAB_URL = (
        "https://raw.githubusercontent.com/numenta/NAB/master/"
        "data/realKnownCause/machine_temperature_system_failure.csv"
    )
    urllib.request.urlretrieve(NAB_URL, "_nab_temp.csv")
    df_nab = pd.read_csv("_nab_temp.csv", parse_dates=["timestamp"])
    df_nab = df_nab.set_index("timestamp").resample("1h").mean().dropna()
    NAB_AVAILABLE = True
    print("[데이터] NAB Machine Temperature 데이터셋 로드 성공")
except Exception:
    NAB_AVAILABLE = False
    print("[데이터] NAB 다운로드 실패 → 합성 데이터로 자동 전환")


# ================================================================
# [1] 성준 파트 출력 형식 재현
#     실제로는 성준파트_anomaly_classifier.py 의 results_for_yubin
#     이 여기로 넘어오지만, 데모에서는 직접 생성
# ================================================================

fs = 1000

def make_signal(scenario: str, n: int = 128) -> np.ndarray:
    """각 사고 시나리오에 맞는 신호 합성"""
    t = np.linspace(0, 0.1, n)
    if scenario == "fall":
        # 충격(고주파) 후 소멸
        sig = np.concatenate([
            np.sin(2 * np.pi * 50 * t[:n//2]) * 3.0,
            np.zeros(n - n//2)
        ])
    elif scenario == "electric_shock":
        # 50Hz 전력 주파수 + 경련성 불규칙
        sig = (np.sin(2 * np.pi * 50 * t) * 2.0
               + np.random.normal(0, 0.6, n)
               + np.sin(2 * np.pi * 63 * t) * 0.8)
    elif scenario == "entrapment":
        # 지속적 고에너지
        sig = np.sin(2 * np.pi * 5 * t) * 2.5 + np.random.normal(0, 0.2, n)
    elif scenario == "equipment_fault":
        # 저주파 드리프트
        sig = (np.sin(2 * np.pi * 3 * t) * 1.5
               + np.sin(2 * np.pi * 7 * t) * 0.5
               + np.random.normal(0, 0.1, n))
    else:
        sig = np.sin(2 * np.pi * 5 * t) + np.random.normal(0, 0.1, n)
    return sig


def extract_signal_features(signal: np.ndarray, fs: int = 1000) -> dict:
    """신호에서 분류 특성 추출 (성준 파트 AccidentClassifier._extract_features 복사)"""
    n, eps = len(signal), 1e-10
    energy_front = float(np.mean(signal[:n//2] ** 2)) + eps
    energy_back  = float(np.mean(signal[n//2:] ** 2)) + eps
    tail_energy  = float(np.mean(signal[int(n*0.7):] ** 2))
    peak_amp     = float(np.max(np.abs(signal))) + eps
    sustained_cnt = np.sum(np.abs(signal) > peak_amp * 0.5)

    fft_mag  = np.abs(np.fft.fft(signal))[:n//2]
    freqs    = np.fft.fftfreq(n, d=1/fs)[:n//2]
    dominant_freq   = float(freqs[np.argmax(fft_mag[1:]) + 1])
    high_freq_ratio = float(np.sum(fft_mag[freqs > 20]) / (np.sum(fft_mag) + eps))
    mask_50 = (freqs >= 45) & (freqs <= 55)
    mask_60 = (freqs >= 55) & (freqs <= 65)
    power_line_ratio = float(
        (np.sum(fft_mag[mask_50]) + np.sum(fft_mag[mask_60])) / (np.sum(fft_mag) + eps)
    )
    zcr = float(len(np.where(np.diff(np.sign(signal)))[0]) / n)

    return {
        "energy_ratio":      round(energy_back / energy_front, 4),
        "tail_silence":      tail_energy < 0.05 * energy_front,
        "sustained_high":    (sustained_cnt / n) > 0.40,
        "peak_amplitude":    round(peak_amp, 4),
        "dominant_freq_hz":  round(dominant_freq, 2),
        "high_freq_ratio":   round(high_freq_ratio, 4),
        "power_line_ratio":  round(power_line_ratio, 4),
        "zcr":               round(zcr, 4),
        "signal_variance":   round(float(np.var(signal)), 6),
    }


# ── 4가지 사고 유형 + 정상 시나리오 데이터 ──────────────────────
SCENARIOS = [
    {"scenario": "fall",           "event_type": "fall_detected",       "zone": "A", "recon_error": 0.082, "threshold": 0.021},
    {"scenario": "electric_shock", "event_type": "electric_shock",      "zone": "B", "recon_error": 0.104, "threshold": 0.021},
    {"scenario": "entrapment",     "event_type": "entrapment_detected", "zone": "C", "recon_error": 0.071, "threshold": 0.021},
    {"scenario": "equipment_fault","event_type": "equipment_fault",     "zone": "D", "recon_error": 0.035, "threshold": 0.021},
]

# NAB 데이터가 있으면 실제 이상 구간에서 equipment_fault 신호로 활용
if NAB_AVAILABLE:
    nab_vals = df_nab["value"].values
    nab_norm = (nab_vals - nab_vals.min()) / (nab_vals.max() - nab_vals.min() + 1e-10)
    # 이상 구간(후반부)을 equipment_fault 신호로 사용
    anomaly_region = nab_norm[int(len(nab_norm)*0.75):]
    SCENARIOS[3]["nab_signal"] = anomaly_region[:128] if len(anomaly_region) >= 128 else None
    print(f"  NAB 데이터 크기: {len(nab_vals)}개 샘플")

# ── 성준 파트 결과 목록 생성 (results_for_yubin 재현) ───────────
severity_map = {
    "fall_detected":      "critical",
    "electric_shock":     "critical",
    "entrapment_detected":"critical",
    "equipment_fault":    "warning",
}
confidence_map = {
    "fall_detected":      0.88,
    "electric_shock":     0.91,
    "entrapment_detected":0.84,
    "equipment_fault":    0.73,
}
reason_map = {
    "fall_detected":      "고주파 충격 후 신호 소멸 (high_freq=0.412, tail_silence=True)",
    "electric_shock":     "전력 주파수 성분 감지 (power_line_ratio=0.321) + 경련성 떨림 (ZCR=0.318)",
    "entrapment_detected":"지속적 고에너지 유지 (energy_ratio=0.921, sustained=True)",
    "equipment_fault":    "저주파 지배 성분 (dominant=3.1Hz) — 기계 진동/마모 의심",
}

results_for_yubin = []
base_time = datetime.now()

for i, sc in enumerate(SCENARIOS):
    sig = make_signal(sc["scenario"])
    if sc["scenario"] == "equipment_fault" and NAB_AVAILABLE and sc.get("nab_signal") is not None:
        sig = sc["nab_signal"]  # NAB 실제 데이터 사용

    feat = extract_signal_features(sig, fs)
    etype = sc["event_type"]

    results_for_yubin.append({
        "step":                i * 30 + 65,
        "event_type":          etype,
        "severity":            severity_map[etype],
        "confidence":          confidence_map[etype],
        "reason":              reason_map[etype],
        "signal_features":     feat,
        "anomaly_score":       round(sc["recon_error"] / sc["threshold"], 3),
        "reconstruction_error":sc["recon_error"],
        "zone":                sc["zone"],
        "_signal":             sig,          # 시각화용 (유빈 파트에는 불필요)
        "_timestamp":          base_time + timedelta(minutes=i*7),
    })

print(f"\n성준 → 유빈: {len(results_for_yubin)}건의 이벤트 전달 준비 완료")


# ================================================================
# [2] 유빈 파트: generate_report() 재현
# ================================================================
DESCRIPTION_MAP = {
    "fall_detected":      "작업자 낙상 감지 — 자세 붕괴 및 신호 소멸 확인",
    "electric_shock":     "작업자 감전 감지 — 전력 주파수 성분 및 경련 패턴 확인",
    "entrapment_detected":"작업자 협착 감지 — 지속적 압박 신호 유지 확인",
    "equipment_fault":    "장비 이상 감지 — 저주파 진동/드리프트 패턴 확인",
}
ICON_MAP = {
    "fall_detected":      "🚨 낙상",
    "electric_shock":     "⚡ 감전",
    "entrapment_detected":"🔒 협착",
    "equipment_fault":    "⚙️  기기이상",
}

def generate_report(result: dict) -> dict:
    """
    성준 파트의 classify() 결과를 받아 유빈의 공식 JSON 스키마로 변환
    (유빈 파트 코드 — 성준 파트에서 호출만 함)
    """
    now      = result.get("_timestamp", datetime.now())
    etype    = result["event_type"]
    zone     = result.get("zone", "?")
    event_id = f"evt_{now.strftime('%Y%m%d_%H%M%S')}_{zone}001"
    feat     = result.get("signal_features", {})

    return {
        "schema_version": "1.1",
        "timestamp":      now.isoformat(),
        "event_id":       event_id,
        "event_type":     etype,
        "zone_id":        zone,
        "severity":       result["severity"],
        "confidence":     result["confidence"],
        "details": {
            "description":     DESCRIPTION_MAP.get(etype, "알 수 없는 이벤트"),
            "classify_reason": result["reason"],
            "signal_features": feat,
            "worker_status": {
                "posture":      "collapsed" if etype == "fall_detected"       else
                                "shocked"   if etype == "electric_shock"      else
                                "pinned"    if etype == "entrapment_detected"  else
                                "unknown",
                "tail_silence": feat.get("tail_silence"),
                "sustained":    feat.get("sustained_high"),
                "zcr":          feat.get("zcr"),
            },
            "equipment_status": {
                "dominant_freq_hz":  feat.get("dominant_freq_hz"),
                "power_line_ratio":  feat.get("power_line_ratio"),
                "fault_suspected":   etype == "equipment_fault",
            },
        },
        "anomaly_score":       result["anomaly_score"],
        "reconstruction_error":result["reconstruction_error"],
        "event_log": [
            {"time": now.strftime('%H:%M:%S.%f')[:-3],
             "msg":  f"Zone {zone} - LSTM-AE 이상 탐지 (score={result['anomaly_score']})"},
            {"time": (now + timedelta(milliseconds=120)).strftime('%H:%M:%S.%f')[:-3],
             "msg":  f"Zone {zone} - 유형 분류 완료: {etype}"},
            {"time": (now + timedelta(milliseconds=240)).strftime('%H:%M:%S.%f')[:-3],
             "msg":  f"Zone {zone} - 알림 발송 (severity={result['severity']}, confidence={result['confidence']})"},
        ],
    }

# ── JSON 리포트 생성 ──────────────────────────────────────────────
all_reports = [generate_report(r) for r in results_for_yubin]

# JSON 파일 저장
out_path = "reports_output.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(all_reports, f, ensure_ascii=False, indent=2)
print(f"\n[저장] {out_path} — {len(all_reports)}건 리포트")


# ── 콘솔 출력 (유빈 파트에서 확인할 내용) ───────────────────────
print("\n" + "="*65)
print("  유빈 파트 수신 결과 — 리포트 요약")
print("="*65)
for r in all_reports:
    icon = ICON_MAP.get(r["event_type"], "❓")
    print(
        f"  [{r['zone_id']}존] {icon:<12}  "
        f"신뢰도 {r['confidence']:.0%}  |  "
        f"심각도 {r['severity']:<8}  |  "
        f"{r['details']['description']}"
    )
print("="*65)


# ================================================================
# [3] UI 시뮬레이션 대시보드 (matplotlib)
# ================================================================
COLOR = {
    "fall_detected":       "#E74C3C",
    "electric_shock":      "#F39C12",
    "entrapment_detected": "#8E44AD",
    "equipment_fault":     "#795548",
    "normal":              "#27AE60",
}
SEVERITY_BG = {"critical": "#FFEBEE", "warning": "#FFF8E1", "none": "#E8F5E9"}

fig = plt.figure(figsize=(18, 12), facecolor="#F5F6FA")
fig.suptitle(
    "Radar-Guard | 유빈 파트 UI 시뮬레이션 대시보드",
    fontsize=16, fontweight="bold", y=0.98, color="#2C3E50"
)

gs = gridspec.GridSpec(3, 4, figure=fig, hspace=0.55, wspace=0.40)

# ── [Row 0] 사고 카드 4개 ─────────────────────────────────────────
for col, (res, rep) in enumerate(zip(results_for_yubin, all_reports)):
    ax = fig.add_subplot(gs[0, col])
    etype = rep["event_type"]
    c     = COLOR[etype]
    bg    = SEVERITY_BG[rep["severity"]]

    ax.set_facecolor(bg)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis("off")

    # 색상 바
    ax.add_patch(mpatches.FancyBboxPatch(
        (0, 0.88), 1, 0.12, boxstyle="square,pad=0", color=c, transform=ax.transAxes, clip_on=False
    ))
    ax.text(0.5, 0.94, ICON_MAP[etype], ha="center", va="center",
            fontsize=11, color="white", fontweight="bold", transform=ax.transAxes)

    # 본문
    ax.text(0.5, 0.72, f"Zone {rep['zone_id']}",
            ha="center", fontsize=10, color="#7F8C8D", transform=ax.transAxes)
    ax.text(0.5, 0.54, f"신뢰도  {rep['confidence']:.0%}",
            ha="center", fontsize=12, fontweight="bold", color=c, transform=ax.transAxes)
    ax.text(0.5, 0.38, f"심각도  {rep['severity'].upper()}",
            ha="center", fontsize=9,
            color="#C0392B" if rep["severity"] == "critical" else "#E67E22",
            transform=ax.transAxes)
    ax.text(0.5, 0.20, rep["details"]["description"][:22] + "…",
            ha="center", fontsize=7.5, color="#555", transform=ax.transAxes)
    ax.text(0.5, 0.07, rep["timestamp"][11:19],
            ha="center", fontsize=7, color="#AAA", transform=ax.transAxes)

    # 테두리
    for spine in ax.spines.values():
        spine.set_edgecolor(c); spine.set_linewidth(2)

# ── [Row 1 Left×2] 신호 파형 (4가지) ────────────────────────────
ax_sig = fig.add_subplot(gs[1, :2])
ax_sig.set_facecolor("#FAFAFA")
t_plot = np.linspace(0, 0.1, 128)
for res in results_for_yubin:
    sig = res["_signal"]
    c   = COLOR[res["event_type"]]
    lbl = ICON_MAP[res["event_type"]]
    ax_sig.plot(t_plot * 1000, sig, color=c, lw=1.6, alpha=0.85, label=lbl)
ax_sig.axhline(0, color="#CCC", lw=0.8, linestyle="--")
ax_sig.set_title("사고 유형별 레이더 신호 파형", fontsize=10, fontweight="bold", color="#2C3E50")
ax_sig.set_xlabel("Time (ms)"); ax_sig.set_ylabel("Amplitude")
ax_sig.legend(fontsize=8, loc="upper right"); ax_sig.grid(alpha=0.2)

# ── [Row 1 Right×2] FFT 스펙트럼 ────────────────────────────────
ax_fft = fig.add_subplot(gs[1, 2:])
ax_fft.set_facecolor("#FAFAFA")
for res in results_for_yubin:
    sig     = res["_signal"]
    n       = len(sig)
    fft_mag = np.abs(np.fft.fft(sig))[:n//2]
    freqs   = np.fft.fftfreq(n, d=1/fs)[:n//2]
    c       = COLOR[res["event_type"]]
    lbl     = ICON_MAP[res["event_type"]]
    ax_fft.plot(freqs[:200], fft_mag[:200], color=c, lw=1.4, alpha=0.8, label=lbl)

ax_fft.axvline(50, color="gray", lw=1, linestyle=":", alpha=0.6, label="50Hz (전력)")
ax_fft.set_title("주파수 스펙트럼 (FFT)", fontsize=10, fontweight="bold", color="#2C3E50")
ax_fft.set_xlabel("Frequency (Hz)"); ax_fft.set_ylabel("Magnitude")
ax_fft.legend(fontsize=8); ax_fft.grid(alpha=0.2)
ax_fft.set_xlim(0, 200)

# ── [Row 2 Left] 신호 특성 레이더 차트 ──────────────────────────
ax_radar = fig.add_subplot(gs[2, :2], polar=True)
categories = ["에너지비율", "고주파비율", "전력주파수", "ZCR(경련)", "피크강도"]
N = len(categories)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
angles += angles[:1]

for res in results_for_yubin:
    feat = res["signal_features"]
    vals = [
        min(1.0, feat.get("energy_ratio", 0)),
        feat.get("high_freq_ratio", 0) * 3,
        feat.get("power_line_ratio", 0) * 5,
        feat.get("zcr", 0) * 3,
        min(1.0, feat.get("peak_amplitude", 0) / 4),
    ]
    vals += vals[:1]
    c = COLOR[res["event_type"]]
    ax_radar.plot(angles, vals, color=c, lw=2, alpha=0.8)
    ax_radar.fill(angles, vals, color=c, alpha=0.08)

ax_radar.set_xticks(angles[:-1])
ax_radar.set_xticklabels(categories, fontsize=8)
ax_radar.set_ylim(0, 1)
ax_radar.set_title("사고 유형별 신호 특성 레이더", fontsize=10, fontweight="bold",
                   color="#2C3E50", pad=20)
ax_radar.grid(alpha=0.3)

# 범례
handles = [mpatches.Patch(color=COLOR[r["event_type"]], label=ICON_MAP[r["event_type"]])
           for r in results_for_yubin]
ax_radar.legend(handles=handles, loc="lower left", bbox_to_anchor=(-0.25, -0.1), fontsize=8)

# ── [Row 2 Right×2] 유빈 JSON 리포트 미리보기 ───────────────────
ax_json = fig.add_subplot(gs[2, 2:])
ax_json.axis("off")
ax_json.set_facecolor("#1E1E2E")

sample_rep = all_reports[1]   # 감전 케이스 (가장 특색 있음)
json_lines = json.dumps({
    "event_id":   sample_rep["event_id"],
    "event_type": sample_rep["event_type"],
    "zone_id":    sample_rep["zone_id"],
    "severity":   sample_rep["severity"],
    "confidence": sample_rep["confidence"],
    "description":sample_rep["details"]["description"],
    "reason":     sample_rep["details"]["classify_reason"][:45] + "…",
    "log_0":      sample_rep["event_log"][0]["msg"],
}, indent=2, ensure_ascii=False).split("\n")

ax_json.set_facecolor("#1E1E2E")
ax_json.text(0.02, 0.97, "[ 유빈 파트 수신 JSON 샘플 — 감전 케이스 ]",
             transform=ax_json.transAxes, fontsize=8, color="#F39C12",
             fontweight="bold", va="top", family="monospace")
for li, line in enumerate(json_lines[:18]):
    col = "#ABB2BF"
    if "event_type" in line or "severity" in line:
        col = "#E06C75"
    elif "confidence" in line or "zone" in line:
        col = "#61AFEF"
    elif "description" in line or "reason" in line:
        col = "#98C379"
    ax_json.text(0.02, 0.88 - li * 0.052, line,
                 transform=ax_json.transAxes, fontsize=7.2,
                 color=col, va="top", family="monospace")

plt.savefig("ui_dashboard.png", dpi=150, bbox_inches="tight", facecolor="#F5F6FA")
plt.show()
print("\n[저장] ui_dashboard.png — UI 시뮬레이션 대시보드")


# ================================================================
# [4] 전달 인터페이스 요약 출력
# ================================================================
print("\n" + "="*65)
print("  성준 → 유빈  전달 데이터 구조 최종 확인")
print("="*65)
sample = results_for_yubin[0].copy()
sample.pop("_signal", None); sample.pop("_timestamp", None)
print(json.dumps(sample, indent=2, ensure_ascii=False, default=str))
print("="*65)
print("""
▶ 유빈 파트에서 사용하는 키:
    event_type          → 리포트 제목 및 알림 분류
    severity            → 알림 레벨 (critical / warning)
    confidence          → UI 신뢰도 게이지
    reason              → 로그 메시지 본문
    signal_features     → 상세 신호 데이터 (필요 시 표시)
    anomaly_score       → 이상 지수 (정상=1.0 기준 배율)
    reconstruction_error→ 원시 오차값
""")
