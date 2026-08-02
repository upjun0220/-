# -*- coding: utf-8 -*-
"""
================================================================
Radar-Guard | Smart Breaker + Facility Map Simulator (standalone)
================================================================
실행 (내 PC PowerShell):
    cd "C:\\Users\\82102\\OneDrive\\문서\\Claude\\Projects\\공모전"
    python breaker_facility_sim.py
실행 (젯슨 터미널):
    python3 ~/breaker_facility_sim.py

목적:
    - 하드(스마트 차단기) 미도착 → 목데이터로 전류/전압/진동 이상을 주입
    - 전기(전류·전압) + 기계(도플러 dop_std) "융합 판정" → 해당 Zone 자동 차단
    - Facility Map(A/B/C)에 즉시 동기화 + 차단기 TRIP 연출
    - LOTO 원칙: 자동 재투입 없음. [Event Resolved] → [Restore Power] 사람이 직접.
    - UI 라벨은 전부 영어 (젯슨 한글 폰트 이슈 회피)

┌───────────────────────────────────────────────────────────┐
│  ★★ radar_live_full.py 이식 가이드 (이 파일에서 제일 중요) ★★     │
│                                                             │
│  아래 "이식 경계(PORTABLE)" 블록만 그대로 복사하면 됨:            │
│    1) 임계 상수 (CURR_LIMIT / VOLT_MIN / VIB_DS_THRESH)        │
│    2) classify_equipment(curr, volt, dop_std)  ← 순수함수      │
│    3) BreakerLogic                             ← 순수 상태머신   │
│  이 셋은 PyQt/pyqtgraph/numpy-random 의존이 전혀 없음.          │
│                                                             │
│  이식 시 데이터 계약(반드시 이 형태로 넘길 것):                    │
│    - dop_std : full live가 이미 창별로 계산하는 값 그대로 사용     │
│    - curr, volt : BreakerModbusSource(실제 차단기)에서 읽어옴     │
│    → classify_equipment(curr, volt, dop_std) 호출만 하면 동일 동작 │
│                                                             │
│  변수명은 full live와 일치시켜 둠: dop_std, zone, severity.       │
└───────────────────────────────────────────────────────────┘

의존성: PyQt5, pyqtgraph, numpy
"""

import sys
from collections import deque

import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QTextEdit,
    QVBoxLayout, QHBoxLayout, QFrame,
)
from PyQt5.QtCore import QTimer, Qt
import pyqtgraph as pg


# ============================================================
# ██████████  이식 경계 시작 (PORTABLE — Qt 의존 없음)  ██████████
#   radar_live_full.py 로 이 구획만 복사하면 됨
# ============================================================

# --- 임계값 (full live 변수명 규칙과 일치) ---
CURR_LIMIT    = 1.5     # [A]  과전류 임계
VOLT_MIN      = 200.0   # [V]  저전압(전압강하) 임계
VIB_DS_THRESH = 0.20    # dop_std 설비 이상진동 임계
#   ⚠ VIB_DS_THRESH 는 임시값. 내일 선풍기(기계 진동) 수집분으로 최종 확정 예정.

# --- Zone 매핑 (radar_guard_pipeline.py 의 ZONE_MAP 규칙 재사용) ---
ELEC_ZONE = "A"   # Substation — 전기(전류/전압) 이상
VIB_ZONE  = "C"   # Assembly/equipment — 기계 진동 이상
ZONE_IDS   = ["A", "B", "C"]
ZONE_NAMES = {"A": "Zone A (Substation)", "B": "Zone B (Machining)", "C": "Zone C (Assembly)"}

# --- severity 색/라벨 (합본 SEVERITY 스킴 재사용) ---
SEV_COLOR = {"normal": "#1f8b4c", "warning": "#e0a800", "critical": "#c0392b"}
SEV_LABEL = {"normal": "NORMAL", "warning": "LOCKOUT", "critical": "TRIPPED"}


def classify_equipment(curr, volt, dop_std):
    """
    [이식 핵심] 전기(전류/전압) + 기계(도플러 진동) 융합 판정 — 순수 함수.
    Args:
        curr    : 전류 [A]   (차단기 실측 or 목)
        volt    : 전압 [V]   (차단기 실측 or 목)
        dop_std : 도플러 표준편차 (레이더 실측 or 목) — full live와 동일 피처
    Returns:
        list[dict]: 감지된 이상들. 없으면 []. 각 원소는
            {event_type, zone_id, severity, value, limit, msg}
            (데이터_인터페이스_명세서 필드명 유지)
    """
    anomalies = []
    if curr > CURR_LIMIT:
        anomalies.append({
            "event_type": "overcurrent", "zone_id": ELEC_ZONE, "severity": "critical",
            "value": curr, "limit": CURR_LIMIT,
            "msg": f"Overcurrent {curr:.2f} A (> {CURR_LIMIT} A)",
        })
    if volt < VOLT_MIN:
        anomalies.append({
            "event_type": "voltage_drop", "zone_id": ELEC_ZONE, "severity": "critical",
            "value": volt, "limit": VOLT_MIN,
            "msg": f"Voltage drop {volt:.1f} V (< {VOLT_MIN} V)",
        })
    if dop_std > VIB_DS_THRESH:
        anomalies.append({
            "event_type": "vibration_anomaly", "zone_id": VIB_ZONE, "severity": "critical",
            "value": dop_std, "limit": VIB_DS_THRESH,
            "msg": f"Abnormal vibration dop_std {dop_std:.3f} (> {VIB_DS_THRESH})",
        })
    return anomalies


class BreakerLogic:
    """
    [이식 가능] Zone별 스마트 차단기 상태머신. Qt 의존 없음.
    상태:  'ON'(투입) | 'TRIPPED'(개방)
    LOTO:  이상 → 자동 TRIP. resolve()는 상태 유지(복구 안 함).
           restore()로 사람이 직접 재투입해야만 ON 복귀. (restart prevention)
    """
    def __init__(self):
        self.state = {z: "ON" for z in ZONE_IDS}

    def on_anomalies(self, anomalies):
        """이상 발생 Zone 자동 차단. 이번 tick에 새로 TRIP된 Zone 리스트 반환."""
        tripped_now = []
        for a in anomalies:
            z = a["zone_id"]
            if self.state.get(z) == "ON":
                self.state[z] = "TRIPPED"
                tripped_now.append(z)
        return tripped_now

    def resolve(self):
        """이상은 해소되나 차단은 유지 (자동 복구 금지)."""
        return  # 의도적으로 아무 것도 안 함

    def restore(self):
        """사람이 직접 전력 복구 — 모든 TRIP Zone 재투입. 복구된 Zone 반환."""
        restored = [z for z, s in self.state.items() if s == "TRIPPED"]
        for z in restored:
            self.state[z] = "ON"
        return restored

    def tripped_zones(self):
        return [z for z, s in self.state.items() if s == "TRIPPED"]

    def any_tripped(self):
        return any(s == "TRIPPED" for s in self.state.values())

# ============================================================
# ██████████  이식 경계 끝 (PORTABLE)  ██████████
# ============================================================


# ------------------------------------------------------------
# 데이터 소스 (교체 지점) — 지금은 목. 나중에 아래 두 개로 교체:
#   RadarSource(dop_std)  +  BreakerModbusSource(curr, volt)
# read() 가 (curr, volt, dop_std) 튜플을 반환하는 "계약"만 지키면 됨.
# ------------------------------------------------------------
class MockSource:
    NORMAL = dict(curr=1.0, volt=220.0, dop=0.05)

    def __init__(self):
        self.inject = set()      # {"overcurrent","voltage_drop","vibration"}

    def set_inject(self, key):
        self.inject.add(key)

    def clear(self):
        self.inject.clear()

    def read(self):
        curr = np.random.normal(1.00, 0.03)
        volt = np.random.normal(220.0, 0.4)
        dop  = abs(np.random.normal(0.05, 0.01))
        if "overcurrent" in self.inject:
            curr = np.random.normal(2.20, 0.08)
        if "voltage_drop" in self.inject:
            volt = np.random.normal(193.0, 1.2)
        if "vibration" in self.inject:
            dop = abs(np.random.normal(0.42, 0.04))
        return curr, volt, dop


# ------------------------------------------------------------
# UI (pyqtgraph)
# ------------------------------------------------------------
BUF = 160  # 그래프 히스토리 길이


class Dashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Radar-Guard | Smart Breaker + Facility Map Simulator")
        self.resize(1500, 860)

        self.source = MockSource()
        self.breaker = BreakerLogic()

        self.curr_buf = deque([MockSource.NORMAL["curr"]] * BUF, maxlen=BUF)
        self.volt_buf = deque([MockSource.NORMAL["volt"]] * BUF, maxlen=BUF)
        self.dop_buf  = deque([MockSource.NORMAL["dop"]]  * BUF, maxlen=BUF)
        self.x = np.arange(BUF)

        root = QWidget(); self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 10)

        # ---- 상태 배너 ----
        self.banner = QLabel("SYSTEM NORMAL - Live Monitoring")
        self.banner.setAlignment(Qt.AlignCenter)
        self.banner.setFixedHeight(52)
        outer.addWidget(self.banner)

        # ---- 중앙 3영역 ----
        mid = QHBoxLayout(); outer.addLayout(mid, stretch=1)

        pg.setConfigOptions(antialias=True)

        # (1) Equipment vibration (Doppler) — 좌
        left = QVBoxLayout()
        left.addWidget(self._title("(1) Equipment Vibration (Radar Doppler dop_std)"))
        self.p_dop = pg.PlotWidget()
        self.p_dop.setYRange(0, 0.6); self.p_dop.showGrid(x=True, y=True, alpha=0.3)
        self.p_dop.addLine(y=VIB_DS_THRESH, pen=pg.mkPen('#c0392b', width=2, style=Qt.DashLine))
        self.c_dop = self.p_dop.plot(pen=pg.mkPen('#8e44ad', width=2))
        left.addWidget(self.p_dop)
        mid.addLayout(left, stretch=3)

        # (2) Smart breaker — 중앙
        center = QVBoxLayout()
        center.addWidget(self._title("(2) Smart Breaker (Current / Voltage)"))
        self.breaker_box = QLabel(); self.breaker_box.setAlignment(Qt.AlignCenter)
        self.breaker_box.setFixedHeight(84)
        center.addWidget(self.breaker_box)
        self.p_curr = pg.PlotWidget()
        self.p_curr.setYRange(0, 3); self.p_curr.showGrid(x=True, y=True, alpha=0.3)
        self.p_curr.setTitle("Output Current (A)")
        self.p_curr.addLine(y=CURR_LIMIT, pen=pg.mkPen('#c0392b', width=2, style=Qt.DashLine))
        self.c_curr = self.p_curr.plot(pen=pg.mkPen('#0090d0', width=2))
        center.addWidget(self.p_curr)
        self.p_volt = pg.PlotWidget()
        self.p_volt.setYRange(180, 240); self.p_volt.showGrid(x=True, y=True, alpha=0.3)
        self.p_volt.setTitle("Output Voltage (V)")
        self.p_volt.addLine(y=VOLT_MIN, pen=pg.mkPen('#c0392b', width=2, style=Qt.DashLine))
        self.c_volt = self.p_volt.plot(pen=pg.mkPen('#e08e00', width=2))
        center.addWidget(self.p_volt)
        mid.addLayout(center, stretch=4)

        # (3) Facility Map — 우
        right = QVBoxLayout()
        right.addWidget(self._title("(3) Facility Map"))
        self.zone_boxes = {}
        for z in ZONE_IDS:
            box = QLabel(); box.setAlignment(Qt.AlignCenter)
            box.setWordWrap(True)
            box.setFrameShape(QFrame.StyledPanel)
            self.zone_boxes[z] = box
            right.addWidget(box, stretch=1)
        mid.addLayout(right, stretch=2)

        # ---- 버튼 ----
        btns = QHBoxLayout(); outer.addLayout(btns)
        self._btn(btns, "Inject Overcurrent",   lambda: self._inject("overcurrent", "Overcurrent"))
        self._btn(btns, "Inject Voltage Drop",  lambda: self._inject("voltage_drop", "Voltage drop"))
        self._btn(btns, "Inject Vibration Fault", lambda: self._inject("vibration", "Equipment vibration"))
        btns.addSpacing(24)
        self._btn(btns, "Event Resolved (clear fault - keep OFF)", self._resolve, "#8e44ad")
        self._btn(btns, "Restore Power (manual re-close)",         self._restore, "#1f8b4c")

        # ---- 로그 ----
        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.setFixedHeight(120)
        self.log.setStyleSheet("background:#0d1117;color:#c9d1d9;"
                               "font-family:Consolas,monospace;font-size:13px;")
        outer.addWidget(self.log)

        self._log("System started - monitoring. Use buttons to inject faults.")
        self._refresh(*self._latest(), [])

        # ---- 타이머 (목 데이터 폴링 20Hz) ----
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)

    # -------- 헬퍼 --------
    def _title(self, t):
        lab = QLabel(t); lab.setStyleSheet("font-weight:bold;font-size:15px;padding:4px;")
        return lab

    def _btn(self, layout, text, slot, color="#30363d"):
        b = QPushButton(text); b.clicked.connect(slot); b.setFixedHeight(40)
        b.setStyleSheet(f"background:{color};color:white;font-weight:bold;"
                        f"font-size:13px;border-radius:6px;padding:4px 10px;")
        layout.addWidget(b)
        return b

    def _log(self, msg):
        from datetime import datetime
        self.log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _latest(self):
        return self.curr_buf[-1], self.volt_buf[-1], self.dop_buf[-1]

    # -------- 버튼 핸들러 --------
    def _inject(self, key, label):
        self.source.set_inject(key)
        self._log(f">> Fault injected: {label}")

    def _resolve(self):
        if not self.breaker.any_tripped() and not self.source.inject:
            self._log("... No active fault to resolve.")
            return
        self.source.clear()
        self.breaker.resolve()
        self._log("[OK] Event Resolved - signals normalized. (Breaker stays OFF - LOTO)")

    def _restore(self):
        restored = self.breaker.restore()
        if restored:
            self._log(f"[PWR] Power restored - Zone {', '.join(restored)} breaker re-closed (ON).")
        else:
            self._log("... No tripped breaker to restore.")

    # -------- 메인 루프 --------
    def tick(self):
        curr, volt, dop = self.source.read()
        self.curr_buf.append(curr); self.volt_buf.append(volt); self.dop_buf.append(dop)

        anomalies = classify_equipment(curr, volt, dop)          # ← 이식 대상 함수
        tripped_now = self.breaker.on_anomalies(anomalies)       # ← 이식 대상 로직
        for z in tripped_now:
            reason = ", ".join(a["msg"] for a in anomalies if a["zone_id"] == z)
            self._log(f"[TRIP] Auto-trip - Zone {z} | {reason}")

        self._refresh(curr, volt, dop, anomalies)

    def _refresh(self, curr, volt, dop, anomalies):
        self.c_curr.setData(self.x, np.array(self.curr_buf))
        self.c_volt.setData(self.x, np.array(self.volt_buf))
        self.c_dop.setData(self.x, np.array(self.dop_buf))

        active_zones = {a["zone_id"] for a in anomalies}

        # Facility Map
        for z in ZONE_IDS:
            if self.breaker.state[z] == "ON":
                sev = "normal"; extra = "Breaker ON - Power OK"
            elif z in active_zones:
                sev = "critical"; extra = "TRIPPED - fault active"
            else:
                sev = "warning"; extra = "Locked out - awaiting restore"
            self.zone_boxes[z].setStyleSheet(
                f"background:{SEV_COLOR[sev]};color:white;border-radius:8px;"
                f"padding:10px;font-size:14px;")
            self.zone_boxes[z].setText(
                f"<b>{ZONE_NAMES[z]}</b><br>[{SEV_LABEL[sev]}]<br>{extra}")

        # 차단기 큰 표시
        if self.breaker.any_tripped():
            tz = ", ".join(self.breaker.tripped_zones())
            self.breaker_box.setText(f"BREAKER OPEN (TRIP)  v\nZone {tz} isolated")
            self.breaker_box.setStyleSheet("background:#3a0000;color:#ff6b6b;"
                "font-size:20px;font-weight:bold;border:2px solid #c0392b;border-radius:8px;")
        else:
            self.breaker_box.setText("BREAKER CLOSED (ON)  ^\nAll circuits normal")
            self.breaker_box.setStyleSheet("background:#06220f;color:#4ade80;"
                "font-size:20px;font-weight:bold;border:2px solid #1f8b4c;border-radius:8px;")

        # 배너
        if active_zones:
            self._set_banner("CRITICAL - Equipment fault detected - Breaker TRIP", "#c0392b")
        elif self.breaker.any_tripped():
            self._set_banner("LOCKOUT - Breaker OFF - Manual [Restore Power] required", "#e0a800")
        else:
            self._set_banner("SYSTEM NORMAL - Live Monitoring", "#1f8b4c")

    def _set_banner(self, text, color):
        self.banner.setText(text)
        self.banner.setStyleSheet(f"background:{color};color:white;font-size:20px;"
                                  f"font-weight:bold;border-radius:6px;")


def main():
    app = QApplication(sys.argv)
    win = Dashboard()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
