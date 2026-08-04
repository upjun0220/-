"""sim_jetson.py — 젯슨 없이 console_ui 를 전 구간 검증하는 모의 송신기

  실행 위치: [내 PC PowerShell]  — 창 2개
      창1:  python sim_jetson.py
      창2:  python console_ui.py --live 127.0.0.1

  의존성: numpy 만 (torch·레이더·젯슨 전부 불필요)

═══ 이게 왜 필요한가 ═══
  jetson_sender.py 는 torch + 레이더 JSON 이 있어야 돌아간다. 그래서 노트북에서
  UI 를 검증할 방법이 없었다. 이 파일은 **같은 UDP 프로토콜·같은 패킷 스키마**로
  가짜 상황을 만들어 보낸다. 프로토콜이 어긋나면 여기서 잡힌다.

  ⚠ 판정 로직은 없다. 시나리오를 재생할 뿐이다. 낙상 판정의 정확성은
    jetson_sender.py 의 classify() 가 하고, 그건 실측 데이터로 따로 검증한다.

═══ 시나리오 (--fast 면 각 구간 1/3 길이) ═══
  READY  ── 노트북에서 '시스템 준비 → 기준 수집 시작' 을 눌러야 진행
  WARMUP ── 빈방 스캔 12s → 베이스라인 수집
  WAIT_TRAIN ── 노트북에서 '학습 시작' 을 눌러야 진행
  TRAINING ── 8초
  LIVE   ── 보행 20s → 낙상(경보+차단) → 노트북에서 '상황 종료' 누르면 정상 복귀
            → 다시 보행 … 반복
"""
import argparse
import json
import math
import random
import socket
import sys
import threading
import time
from collections import deque

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')



from radar_common import (
    SCHEMA_VERSION, DATA_PORT, CTRL_PORT, SEND_HZ, MAX_UDP, MIN_PTS, CLIENT_TTL,
    CMD_HELLO, CMD_START, CMD_TRAIN, CMD_RESET, CMD_RESOLVE, CMD_RESTORE,
    CEILING_H, HISTORY_LEN, ZONE_IDS, CURR_LIMIT, VOLT_MIN, VIB_DS_THRESH,
    PH_READY, PH_WARMUP, PH_WAIT_TRAIN, PH_TRAINING, PH_LIVE,
    RADAR_ZONE,
)

# ⚠ [8/01] 이 파일은 이벤트·차단기·로그를 전부 'C' 로 하드코딩하고 있었다.
#   레이더 실물은 RADAR_ZONE('A' 변전실) 한 대뿐이고 B·C 는 '장비 미설치'다.
#   그래서 루프백 검증을 하면 화면이 이렇게 어긋났다:
#     · 경보 배너      → "낙상 · C 조립"
#     · 구역 현황      →  A 변전실 '전원 투입' (차단 안 됨), C 는 '장비 미설치'
#     · 상황 종료 안내 → "재투입은 [전기 설비]에서" 인데 정작 차단된 A 는 멀쩡
#   = 장비가 없는 구역에서 사람이 넘어졌고, 사람이 있는 구역은 아무 일 없다는 화면.
#   → 구역 문자열을 단일 소스(RADAR_ZONE)로 바꾼다. 프로토콜·타이밍·수치는 그대로.
SIM_ZONE = RADAR_ZONE

SCAN_SEC = 12.0
N_WARMUP = 150
TRAIN_SEC = 8.0
WALK_SEC = 20.0

_lock = threading.RLock()
_clients = {}
S = {
    'phase': PH_READY, 'warmup_count': 0, 'threshold': 0.0250,
    'scan_left': None, 'pre_alert': '', 'data_ok': True,
    'ev_active': False, 'ev_type': None, 'ev_sev': 'normal', 'ev_conf': 0.0,
    'ev_zone': SIM_ZONE, 'ev_id': 0, 'ev_ts': 0.0,
    'ev_evidence': None, 'ev_gates': None, 'ev_rejected': [],
    'breaker': {z: 'ON' for z in ZONE_IDS},
    'cz_h': deque([1.7] * HISTORY_LEN, maxlen=HISTORY_LEN),
    'ds_h': deque([0.0] * HISTORY_LEN, maxlen=HISTORY_LEN),
    'sc_h': deque([0.0] * HISTORY_LEN, maxlen=HISTORY_LEN),
    'logs': deque(maxlen=20), 'incidents': deque(maxlen=20),
    'req': set(),
}


def log(msg):
    ts = time.strftime('%H:%M:%S')
    with _lock:
        S['logs'].append(f'[{ts}] {msg}')
    print(f'[SIM {ts}] {msg}')


# ══════════════════════════════════════════════════════════════════════
# 제어 수신 (HELLO + 버튼)
# ══════════════════════════════════════════════════════════════════════
def control_listener():
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sk.bind(('0.0.0.0', CTRL_PORT))
    print(f'[SIM] 제어 포트 {CTRL_PORT} 대기')
    known = set()
    while True:
        try:
            data, addr = sk.recvfrom(4096)
            msg = json.loads(data.decode('utf-8'))
        except Exception:
            continue
        with _lock:
            _clients[(addr[0], DATA_PORT)] = time.time()
        if addr[0] not in known:
            known.add(addr[0])
            log(f'뷰어 연결됨: {addr[0]}')
        cmd = msg.get('cmd')
        if cmd in (None, CMD_HELLO):
            continue
        with _lock:
            if cmd == CMD_RESTORE:
                zs = msg.get('zones') or [z for z, v in S['breaker'].items() if v != 'ON']
                for z in zs:
                    S['breaker'][z] = 'ON'
                log(f'BREAKER RESTORE {zs}')
            else:
                S['req'].add(cmd)
        print(f'[SIM] CMD {cmd} <- {addr[0]}')


def _targets():
    now = time.time()
    with _lock:
        for a in [a for a, t in _clients.items() if now - t > CLIENT_TTL]:
            _clients.pop(a, None)
        return list(_clients.keys())


# ══════════════════════════════════════════════════════════════════════
# 시나리오
# ══════════════════════════════════════════════════════════════════════
def _points(cx, cy, cz, n, spread):
    sx, sy, sz = spread
    return [{'x': round(cx + random.gauss(0, sx), 3),
             'y': round(cy + random.gauss(0, sy), 3),
             'z': round(cz + random.gauss(0, sz), 3),
             'i': round(random.uniform(8, 40), 1)} for _ in range(n)]


def _fall_event():
    """실측 분포에 맞춘 낙상 근거. 값은 events_collect.jsonl 실측 범위 안."""
    imp = round(random.uniform(3.2, 8.9), 2)
    hd = round(random.uniform(0.9, 1.5), 3)
    hz = round(random.uniform(0.75, 1.26), 3)
    dsl = round(random.uniform(0.30, 0.80), 3)
    dsb = random.randint(2, 5)
    ev = {
        'dopstd_max': round(random.uniform(1.4, 2.4), 3), 'dopstd_mean': 0.62,
        'ds_first': round(random.uniform(0.15, 0.4), 3), 'ds_last': dsl,
        'ds_broad': dsb, 'impulse_ratio': imp, 'h_drop': hd, 'h_desc': 0.41,
        'horiz_range': hz, 'zacc_amp': round(random.uniform(300, 700), 1),
        'n_mean': 7.4, 'n_p75': 9.0,
        'height_start': 1.62, 'height_end': 0.31,
        'ae_score': 0.0412, 'ae_thr': 0.0250,
    }
    gates = {
        'impulse':  {'value': imp, 'thr': 2.2, 'unit': '비율', 'cmp': '>=', 'pass': imp >= 2.2},
        'h_drop':   {'value': hd, 'thr': 0.43, 'unit': 'm', 'cmp': '>=', 'pass': hd >= 0.43},
        'horiz':    {'value': hz, 'thr': 0.6, 'unit': 'm', 'cmp': '>=', 'pass': hz >= 0.6},
        'ds_last':  {'value': dsl, 'thr': 1.0, 'unit': 'm/s', 'cmp': '<=', 'pass': dsl <= 1.0},
        'ds_broad': {'value': dsb, 'thr': 2, 'unit': '프레임', 'cmp': '>=', 'pass': dsb >= 2},
    }
    rej = [{'candidate': 'fast_sit',
            'reason': f'horiz_range {hz:.2f} >= 0.6 (제자리 앉기는 수평 고정, 실측 0.35~0.79)'},
           {'candidate': 'vibration',
            'reason': f'h_drop {hd:.2f} >= 0.5 (고정 진동원은 위치 고정이라 높이변화 작음)'}]
    return ev, gates, rej


def scenario(fast=False):
    k = 0.33 if fast else 1.0
    log('시뮬레이터 시작 — 노트북에서 "시스템 준비"를 열어 진행하세요')
    while True:
        # ── READY: start 대기 ──
        with _lock:
            S.update({'phase': PH_READY, 'warmup_count': 0, 'scan_left': None})
        while True:
            with _lock:
                if CMD_START in S['req'] or CMD_RESET in S['req']:
                    S['req'].discard(CMD_START); S['req'].discard(CMD_RESET)
                    break
            time.sleep(0.1)

        # ── WARMUP: 빈방 스캔 → 베이스라인 ──
        log('빈방 스캔 시작 — 감지 구역 밖으로')
        t_end = time.time() + SCAN_SEC * k
        while time.time() < t_end:
            with _lock:
                S.update({'phase': PH_WARMUP, 'scan_left': round(t_end - time.time(), 1)})
                S['cz_h'].append(0.02); S['ds_h'].append(0.01); S['sc_h'].append(0.0)
            time.sleep(1.0 / SEND_HZ)
        log('스캔 완료 — 구역 안으로 들어오세요')
        with _lock:
            S['scan_left'] = None
        for i in range(int(N_WARMUP * k)):
            with _lock:
                S['warmup_count'] = int(i / k)
                S['cz_h'].append(1.15 + random.gauss(0, 0.03))
                S['ds_h'].append(abs(random.gauss(0.12, 0.04)))
                S['sc_h'].append(abs(random.gauss(0.008, 0.002)))
            time.sleep(1.0 / SEND_HZ)

        # ── WAIT_TRAIN: train 대기 ──
        log('베이스라인 수집 완료 — 학습 시작을 눌러 주세요')
        with _lock:
            S['phase'] = PH_WAIT_TRAIN
        while True:
            with _lock:
                if CMD_TRAIN in S['req'] or CMD_START in S['req']:
                    S['req'].discard(CMD_TRAIN); S['req'].discard(CMD_START)
                    break
            time.sleep(0.1)

        # ── TRAINING ──
        log('LSTM-AE 학습 중 — 움직이지 마세요')
        with _lock:
            S['phase'] = PH_TRAINING
        t_end = time.time() + TRAIN_SEC * k
        while time.time() < t_end:
            with _lock:
                S['cz_h'].append(1.15); S['ds_h'].append(0.10); S['sc_h'].append(0.007)
            time.sleep(1.0 / SEND_HZ)

        # ── LIVE ──
        log('LIVE — 감시 시작')
        with _lock:
            S['phase'] = PH_LIVE
        while True:
            if not _live_cycle(k):
                break        # reset 요청 -> READY 로


def _live_cycle(k):
    """보행 → 낙상 → 상황종료 대기 → 다시 보행. reset 요청이면 False."""
    # 보행
    t0 = time.time()
    while time.time() - t0 < WALK_SEC * k:
        if _consume_reset():
            return False
        a = (time.time() - t0) * 0.7
        with _lock:
            S['cz_h'].append(1.15 + 0.05 * math.sin(a))
            S['ds_h'].append(abs(random.gauss(0.22, 0.06)))
            S['sc_h'].append(abs(random.gauss(0.009, 0.003)))
        time.sleep(1.0 / SEND_HZ)

    # 낙상
    ev, gates, rej = _fall_event()
    with _lock:
        S.update({'ev_active': True, 'ev_type': 'fall_detected', 'ev_sev': 'critical',
                  'ev_conf': 0.87, 'ev_zone': SIM_ZONE, 'ev_id': S['ev_id'] + 1,
                  'ev_ts': time.time(), 'ev_evidence': ev, 'ev_gates': gates,
                  'ev_rejected': rej})
        S['breaker'][SIM_ZONE] = 'TRIPPED'
        S['incidents'].append({'type': 'fall_detected', 'zone': SIM_ZONE,
                               'detected': time.strftime('%H:%M:%S'), 'resolved': None})
    log(f'ALERT Zone {SIM_ZONE}: FALL DETECTED (conf=87%) / '
        f'BREAKER TRIP Zone {SIM_ZONE}')

    # 상황 종료 대기 (누울 상태 유지)
    while True:
        if _consume_reset():
            return False
        with _lock:
            if CMD_RESOLVE in S['req']:
                S['req'].discard(CMD_RESOLVE)
                S.update({'ev_active': False, 'ev_type': None, 'ev_sev': 'normal',
                          'ev_conf': 0.0, 'ev_evidence': None, 'ev_gates': None,
                          'ev_rejected': []})
                for inc in reversed(S['incidents']):
                    if inc['resolved'] is None:
                        inc['resolved'] = time.strftime('%H:%M:%S'); break
                tz = [z for z, v in S['breaker'].items() if v != 'ON']
                log(f'RESOLVED Zone {SIM_ZONE} (manual ack) — '
                    f'차단 유지 {tz}, 재투입은 수동')
                return True
            S['cz_h'].append(0.30 + random.gauss(0, 0.02))
            S['ds_h'].append(abs(random.gauss(0.04, 0.02)))
            S['sc_h'].append(abs(random.gauss(0.041, 0.004)))
        time.sleep(1.0 / SEND_HZ)


def _consume_reset():
    with _lock:
        if CMD_RESET in S['req']:
            S['req'].discard(CMD_RESET)
            S.update({'ev_active': False, 'ev_type': None, 'ev_sev': 'normal',
                      'ev_evidence': None, 'ev_gates': None, 'ev_rejected': []})
            log('RESET — READY 로 복귀')
            return True
    return False


# ══════════════════════════════════════════════════════════════════════
# 송신
# ══════════════════════════════════════════════════════════════════════
def _pack(base, pts):
    while True:
        base['points'] = pts
        p = json.dumps(base, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        if len(p) <= MAX_UDP or len(pts) <= MIN_PTS:
            return p
        pts = pts[::2]


def sender_loop():
    sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sk.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
    period = 1.0 / SEND_HZ
    seq = 0
    peak = 0
    while True:
        time.sleep(period)
        tg = _targets()
        if not tg:
            continue
        seq += 1
        full = (seq % max(1, int(SEND_HZ)) == 0)   # 히스토리는 1초에 한 번만
        with _lock:
            ph = S['phase']
            fallen = S['ev_active']
            present = ph in (PH_WAIT_TRAIN, PH_TRAINING, PH_LIVE)
            cz = S['cz_h'][-1] if S['cz_h'] else 1.15
            ds = S['ds_h'][-1] if S['ds_h'] else 0.0
            cy = CEILING_H - cz
            a = seq * 0.05
            cx, czz = 0.45 * math.sin(a), 0.30 * math.cos(a * 0.7)
            spread = (0.42, 0.08, 0.24) if fallen else (0.10, 0.30, 0.10)
            pts = _points(cx, cy, czz, 8 if present else 1, spread) if present else []
            tripped = [z for z, v in S['breaker'].items() if v != 'ON']
            zs = {z: 'NORMAL' for z in ZONE_IDS}
            if fallen:
                zs[S['ev_zone']] = 'ALERT'
            for z in tripped:
                zs[z] = 'ALERT' if zs.get(z) == 'ALERT' else 'TRIPPED'
            pkt = {
                'schema_version': SCHEMA_VERSION, 'seq': seq, 'ts': time.time(),
                'phase': ph, 'warmup_count': S['warmup_count'],
                'threshold': S['threshold'], 'data_ok': True, 'data_age': 0.05,
                'scan_left': S['scan_left'], 'pre_alert': S['pre_alert'],
                'ev': {'active': S['ev_active'], 'type': S['ev_type'],
                       'sev': S['ev_sev'], 'conf': S['ev_conf'], 'zone': S['ev_zone'],
                       'id': S['ev_id'], 'ts': S['ev_ts'],
                       'evidence': S['ev_evidence'], 'gates': S['ev_gates'],
                       'rejected': S['ev_rejected']},
                'power': {'curr': round(random.gauss(0.6 if tripped else 1.0, 0.04), 3),
                          'volt': round(random.gauss(220.0, 0.4), 1), 'src': 'sim'},
                'breaker': {'state': dict(S['breaker']),
                            'reason': {z: ('fall_detected' if v != 'ON' else None)
                                       for z, v in S['breaker'].items()}},
                'full': full,
                'n_pts': len(pts),
                'centroid': {'cx': round(cx, 3), 'cy': round(cy, 3), 'cz': round(czz, 3)},
                'height': round(cz, 3), 'dop_std': round(ds, 3), 'zone_state': zs,
                'cfg': {'N_WARMUP': N_WARMUP, 'SCAN_SEC': SCAN_SEC,
                        'CEILING_H': CEILING_H, 'JSON_PATH': '(simulated)',
                        'CURR_LIMIT': CURR_LIMIT, 'VOLT_MIN': VOLT_MIN,
                        'VIB_DS_THRESH': VIB_DS_THRESH},
            }
            if full:
                pkt.update({'cz': [round(v, 3) for v in S['cz_h']],
                            'ds': [round(v, 3) for v in S['ds_h']],
                            'sc': [round(v, 7) for v in S['sc_h']],
                            'logs': list(S['logs']),
                            'incidents': list(S['incidents'])})
        payload = _pack(pkt, pts)
        if len(payload) > peak:
            peak = len(payload)
            if peak > 1400:
                print(f'[SIM] ⚠ 패킷 {peak}B — MTU 1500 초과, IP 단편화 발생 구간')
        for addr in tg:
            try:
                sk.sendto(payload, addr)
            except OSError as e:
                print('[SIM] 송신 실패', e, len(payload))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--fast', action='store_true', help='각 구간 1/3 길이로 빠르게')
    a = ap.parse_args()
    print('=' * 62)
    print('  Radar-Guard | 모의 젯슨 (레이더·torch 불필요)')
    print('=' * 62)
    print(f'  UDP OUT : *:{DATA_PORT}   UDP IN : 0.0.0.0:{CTRL_PORT}   {SEND_HZ}Hz')
    print(f'  구역    : {SIM_ZONE} (레이더 설치 구역 — radar_common.RADAR_ZONE)')
    print('  노트북  : python console_ui.py --live 127.0.0.1')
    print('=' * 62)
    threading.Thread(target=control_listener, daemon=True).start()
    threading.Thread(target=sender_loop, daemon=True).start()
    try:
        scenario(a.fast)
    except KeyboardInterrupt:
        print('\n[SIM] 종료')
