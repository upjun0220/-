import sys
import time
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QLabel, QTextEdit)
from PyQt5.QtCore import QTimer, Qt, QThread, pyqtSignal
import pyqtgraph as pg
import pyqtgraph.opengl as gl

# ==============================================================================
# [백그라운드 스레드] 하드웨어 통신 및 초고속 즉각 차단 로직
# ==============================================================================
class HardwareControlThread(QThread):
    # UI로 데이터를 넘겨주기 위한 시그널
    update_signal = pyqtSignal(dict)
    alarm_signal = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.running = True
        
        # 임계값 설정
        self.LIMIT_CURR = 1.5
        self.LIMIT_VOLT = 200.0
        self.LIMIT_VIB = 0.20
        
        self.scenario_tick = 0
        self.is_tripped = False

    def run(self):
        last_ui_update = time.time()
        
        # 초당 1,000번(1ms) 도는 초고속 감시 루프
        while self.running:
            self.scenario_tick += 1
            
            # --------------------------------------------------------
            # [TODO: 클로드에게 요청할 부분 1] 
            # 여기에 실제 스마트 차단기(Modbus/RS485) 및 레이더 파싱 데이터 연동
            # --------------------------------------------------------
            new_curr = np.random.normal(1.0, 0.05)
            new_volt = np.random.normal(220.0, 0.5)
            new_vib = np.random.normal(0.05, 0.01)
            
            # 사고 시나리오 모사 (약 15초 뒤 발생)
            if 15000 < self.scenario_tick % 30000 < 25000:
                new_curr = np.random.normal(2.2, 0.1)
                new_volt = np.random.normal(193.0, 1.5)
                new_vib = np.random.normal(0.48, 0.06)
            
            # --------------------------------------------------------
            # [핵심] 즉각 차단(Trip) 판단 로직 - UI와 무관하게 1ms 반응
            # --------------------------------------------------------
            anomalies = []
            if new_curr > self.LIMIT_CURR:
                anomalies.append(f"🔴 [전류 과부하] 현재: {new_curr:.2f} A (+{new_curr - self.LIMIT_CURR:.2f} A 초과)")
            if new_volt < self.LIMIT_VOLT:
                anomalies.append(f"🔴 [전압 강하]   현재: {new_volt:.1f} V (-{self.LIMIT_VOLT - new_volt:.1f} V 미달)")
            if new_vib > self.LIMIT_VIB:
                anomalies.append(f"🔴 [이상 진동]   현재: {new_vib:.3f} (+{new_vib - self.LIMIT_VIB:.3f} 초과)")

            if anomalies and not self.is_tripped:
                self.is_tripped = True
                # --------------------------------------------------------
                # [TODO: 클로드에게 요청할 부분 2]
                # 여기에 젯슨 Jetson.GPIO 릴레이 제어 코드 삽입 (즉시 전력 차단)
                # 예: GPIO.output(TRIP_PIN, GPIO.HIGH)
                # --------------------------------------------------------
                print("[SYSTEM] 물리적 TRIP 신호 전송 완료!") 
                self.alarm_signal.emit(anomalies) # UI에도 알림
            
            elif not anomalies and self.is_tripped:
                self.is_tripped = False
                self.alarm_signal.emit([]) # 정상 복귀

            # --------------------------------------------------------
            # UI 업데이트는 1초에 20번(50ms)만 보내서 화면 버벅임 방지
            # --------------------------------------------------------
            now = time.time()
            if now - last_ui_update >= 0.05:
                # 3D 클라우드 가상 포인트
                num_points = np.random.randint(20, 40)
                pts = np.column_stack((np.random.normal(0, 0.5, num_points),
                                       np.random.normal(0, 0.5, num_points),
                                       np.random.normal(1.5, 0.3, num_points)))
                if self.is_tripped:
                    pts += np.random.normal(0, 0.2, pts.shape)

                self.update_signal.emit({
                    'curr': new_curr, 'volt': new_volt, 'vib': new_vib,
                    'pts': pts, 'is_tripped': self.is_tripped
                })
                last_ui_update = now
                
            time.sleep(0.001) # 1ms 대기 (1000Hz 루프)

    def stop(self):
        self.running = False
        self.wait()


# ==============================================================================
# [UI 프론트엔드] 상태 렌더링 전용
# ==============================================================================
class RadarFusionDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Radar-Guard: 고속 예지보전 통합 시스템")
        self.resize(1400, 900)
        
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.layout = QVBoxLayout(self.main_widget)
        self.main_widget.setStyleSheet("background-color: #080818;")

        # 상태 배너
        self.status_banner = QLabel("SYSTEM NORMAL - LIVE Monitoring")
        self.status_banner.setStyleSheet("color: #44ff88; font-size: 26px; font-weight: bold; background-color: #101028; padding: 12px; border: 2px solid #223344;")
        self.status_banner.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.status_banner)

        self.breaker_status = QLabel("스마트 차단기: 🟢 정상 투입 (ON)")
        self.breaker_status.setStyleSheet("color: #00ff00; font-size: 22px; font-weight: bold; background-color: #0a0a1e; padding: 8px; border: 1px solid #00ff00; margin-bottom: 10px;")
        self.breaker_status.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.breaker_status)

        # 가운데 레이아웃
        self.middle_layout = QHBoxLayout()
        self.layout.addLayout(self.middle_layout, stretch=3)

        # 3D 뷰어
        self.gl_widget = gl.GLViewWidget()
        self.gl_widget.opts['distance'] = 5; self.gl_widget.opts['elevation'] = 20; self.gl_widget.opts['azimuth'] = 45
        self.gl_widget.setBackgroundColor('#0a0a1e')
        self.gl_widget.addItem(gl.GLGridItem())
        self.scatter3d = gl.GLScatterPlotItem(pos=np.zeros((1, 3)), size=5, color=(0, 1, 1, 0.8), pxMode=True)
        self.gl_widget.addItem(self.scatter3d)
        self.middle_layout.addWidget(self.gl_widget, stretch=1)

        # 오실로스코프
        self.graph_layout = pg.GraphicsLayoutWidget()
        self.middle_layout.addWidget(self.graph_layout, stretch=1)

        self.history_len = 150
        self.x_data = np.arange(self.history_len)

        self.p_curr, self.curve_curr, self.curr_data = self.create_plot("출력 전류 (A)", 0, 3, '#00ccff', 1.5)
        self.p_volt, self.curve_volt, self.volt_data = self.create_plot("출력 전압 (V)", 180, 240, '#ffaa00', 200.0)
        self.p_vib, self.curve_vib, self.vib_data = self.create_plot("축 진동 (dop_std)", 0, 1.0, '#cc66ff', 0.2)

        # 하단 보고 패널
        self.summary_panel = QTextEdit()
        self.summary_panel.setReadOnly(True)
        self.summary_panel.setStyleSheet("background-color: #04040e; color: #aabbcc; font-size: 16px; font-family: monospace; border: 1px solid #334455; padding: 10px;")
        self.layout.addWidget(self.summary_panel, stretch=1)
        self.summary_panel.setText("▶ 정상 동작 중 (특이사항 없음)")

        # 백그라운드 스레드 시작
        self.hw_thread = HardwareControlThread()
        self.hw_thread.update_signal.connect(self.update_graphs)
        self.hw_thread.alarm_signal.connect(self.update_alarms)
        self.hw_thread.start()

    def create_plot(self, title, y_min, y_max, color, limit_val):
        plot = self.graph_layout.addPlot(title=title)
        plot.setYRange(y_min, y_max)
        plot.showGrid(x=True, y=True, alpha=0.3)
        curve = plot.plot(pen=pg.mkPen(color, width=2))
        data = np.full(self.history_len, (y_min + y_max) / 2)
        plot.addItem(pg.InfiniteLine(pos=limit_val, angle=0, pen=pg.mkPen('#ff3333', style=Qt.DashLine, width=2)))
        self.graph_layout.nextRow()
        return plot, curve, data

    def update_graphs(self, data):
        self.curr_data = np.roll(self.curr_data, -1); self.curr_data[-1] = data['curr']
        self.volt_data = np.roll(self.volt_data, -1); self.volt_data[-1] = data['volt']
        self.vib_data = np.roll(self.vib_data, -1); self.vib_data[-1] = data['vib']

        self.curve_curr.setData(self.x_data, self.curr_data)
        self.curve_volt.setData(self.x_data, self.volt_data)
        self.curve_vib.setData(self.x_data, self.vib_data)
        
        pts = data['pts']
        colors = np.zeros((len(pts), 4))
        if data['is_tripped']:
            colors[:, 0] = 1.0; colors[:, 1] = 0.2; colors[:, 2] = 0.2; colors[:, 3] = 0.8
        else:
            colors[:, 0] = 0.0; colors[:, 1] = 1.0; colors[:, 2] = 1.0; colors[:, 3] = 0.8
        self.scatter3d.setData(pos=pts, color=colors)

    def update_alarms(self, anomalies):
        if anomalies:
            self.status_banner.setText("CRITICAL: 설비 복합 이상 감지! (차단기 TRIP 진행)")
            self.status_banner.setStyleSheet("color: white; font-size: 26px; font-weight: bold; background-color: #aa0000; padding: 12px; border: 2px solid #ff3333;")
            
            self.breaker_status.setText("스마트 차단기: 🔴 회로 차단 완료 (TRIP)")
            self.breaker_status.setStyleSheet("color: #ff3333; font-size: 22px; font-weight: bold; background-color: #3a0000; padding: 8px; border: 2px solid #ff3333; margin-bottom: 10px;")

            summary_txt = "⚠️ [ 위험 상황 상세 보고 ] ⚠️\n========================================================\n"
            summary_txt += "\n".join(anomalies)
            summary_txt += "\n========================================================\n▶ 시스템 조치: LOTO 절차에 따른 스마트 차단기 회로 트립(Trip) 제어 신호 송출."
            self.summary_panel.setText(summary_txt)
            self.summary_panel.setStyleSheet("background-color: #2a0000; color: #ffcccc; font-size: 18px; font-weight: bold; font-family: monospace; border: 2px solid #ff3333; padding: 10px;")
        else:
            self.status_banner.setText("SYSTEM NORMAL - LIVE Monitoring")
            self.status_banner.setStyleSheet("color: #44ff88; font-size: 26px; font-weight: bold; background-color: #101028; padding: 12px; border: 2px solid #223344;")
            
            self.breaker_status.setText("스마트 차단기: 🟢 정상 투입 (ON)")
            self.breaker_status.setStyleSheet("color: #00ff00; font-size: 22px; font-weight: bold; background-color: #0a0a1e; padding: 8px; border: 1px solid #00ff00; margin-bottom: 10px;")

            self.summary_panel.setText("▶ 정상 동작 중 (특이사항 없음)\n▶ 레이더 3D 클라우드 및 전력계통 데이터 수집 중...")
            self.summary_panel.setStyleSheet("background-color: #04040e; color: #aabbcc; font-size: 16px; font-family: monospace; border: 1px solid #334455; padding: 10px;")

    def closeEvent(self, event):
        self.hw_thread.stop()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = RadarFusionDashboard()
    window.show()
    sys.exit(app.exec_())