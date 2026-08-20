r"""테스트_낙상선점_상태기계.py — 낙상이 정지형(하위 등급) 경보에 막히지 않는지
   jetson_sender.py 의 _can_latch/_latch_event/_log_dropped 를 직접 불러 확인한다.

  실행: [내 PC PowerShell]   python 01_현행코드\테스트_낙상선점_상태기계.py
  실기(레이더·젯슨) 없이 상태기계만 본다. torch 는 verify_jetson_safe.py 와
  같은 방식으로 가짜를 주입한다. 종료코드 0 = 전부 통과.
"""
import importlib
import os
import sys
import types
from collections import deque

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = os.path.dirname(os.path.abspath(__file__))


def make_fake_torch():
    torch = types.ModuleType('torch')
    nn = types.ModuleType('torch.nn')

    class Module:
        def __init__(self, *a, **k):
            pass

        def to(self, *a, **k):
            return self

        def parameters(self):
            return []

    class _Layer(Module):
        pass

    nn.Module = Module
    nn.LSTM = _Layer
    nn.Linear = _Layer
    nn.Sequential = _Layer

    class _Dev:
        def __init__(self, s):
            self.s = s

        def __repr__(self):
            return f'device({self.s})'

    torch.device = _Dev
    torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch.nn = nn
    torch.optim = types.SimpleNamespace(AdamW=lambda *a, **k: None)
    torch.no_grad = lambda: types.SimpleNamespace(
        __enter__=lambda s: None, __exit__=lambda s, *a: False)
    torch.save = lambda *a, **k: None
    torch.load = lambda *a, **k: {}
    torch.from_numpy = lambda x: x
    torch.mean = lambda *a, **k: 0.0

    sk = types.ModuleType('sklearn')
    skp = types.ModuleType('sklearn.preprocessing')
    skp.MinMaxScaler = lambda *a, **k: None
    sk.preprocessing = skp
    return {'torch': torch, 'torch.nn': nn, 'sklearn': sk,
            'sklearn.preprocessing': skp}


def load_sender():
    sys.argv = ['jetson_sender.py']
    injected = make_fake_torch()
    for k, v in injected.items():
        sys.modules[k] = v
    sys.modules['torch'].optim = injected['torch'].optim
    sys.modules.pop('jetson_sender', None)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    return importlib.import_module('jetson_sender')


m = load_sender()


class FakeBreaker:
    def __init__(self):
        self.trip_calls = []

    def trip(self, zone, reason=''):
        self.trip_calls.append((zone, reason))
        return True


m.BREAKER = FakeBreaker()

results = []


def ck(ok, name, detail=''):
    results.append(ok)
    print(f'  {"OK" if ok else "NG"}   {name}' + (f'  -> {detail}' if detail else ''))


def reset_state():
    m.state['ev_active'] = False
    m.state['ev_type'] = None
    m.state['ev_sev'] = 'normal'
    m.state['ev_id'] = 0
    m.state['logs'] = deque(maxlen=20)
    m.state['incidents'] = deque(maxlen=20)
    m.BREAKER.trip_calls.clear()


def make_clf(sev, conf=0.8):
    return {'severity': sev, 'confidence': conf, 'evidence': {}, 'gates': {}, 'rejected': []}


print('=' * 70)
print('  낙상 선점 상태기계 검증 (실기 없음)')
print('=' * 70)

print('\n[시나리오 1] 정지형 warning 떠 있는 중 낙상 critical 발생 -> 선점해야 한다')
reset_state()
ck(m._can_latch('stationary_anomaly', 'warning'), '1-a idle 상태 첫 latch 허용')
m._latch_event('stationary_anomaly', make_clf('warning'), 'A', '10:00:00', 1.0)
ck(m.state['ev_type'] == 'stationary_anomaly' and m.state['ev_id'] == 1,
   '1-b 정지형 latch 확인', f"ev_type={m.state['ev_type']} ev_id={m.state['ev_id']}")

can2 = m._can_latch('fall_detected', 'critical')
ck(can2, '1-c warning 떠 있을 때 critical _can_latch -> True')
if can2:
    m._latch_event('fall_detected', make_clf('critical'), 'A', '10:00:05', 0.9)
ck(m.state['ev_type'] == 'fall_detected' and m.state['ev_id'] == 2,
   '1-d 화면이 낙상으로 전환·ev_id 증가', f"ev_type={m.state['ev_type']} ev_id={m.state['ev_id']}")
ck(len(m.BREAKER.trip_calls) == 1, '1-e BREAKER.trip() 호출됨', f'{m.BREAKER.trip_calls}')
old = m.state['incidents'][0]
ck(old['resolved'] is not None, '1-f 선점된 정지형 incident가 미해결로 안 남음', f"resolved={old['resolved']}")

print('\n[시나리오 2] 낙상 critical 떠 있는 중 정지형 warning 발생 -> 화면 유지, 로그만')
reset_state()
m._latch_event('fall_detected', make_clf('critical'), 'A', '10:01:00', 0.9)
n_logs = len(m.state['logs'])
can3 = m._can_latch('stationary_anomaly', 'warning')
ck(not can3, '2-a critical 떠 있을 때 warning _can_latch -> False(배타)')
if not can3:
    m._log_dropped('stationary_anomaly', '10:01:05', '배타 latch')
ck(m.state['ev_type'] == 'fall_detected' and m.state['ev_id'] == 1,
   '2-b 화면은 낙상 그대로', f"ev_type={m.state['ev_type']} ev_id={m.state['ev_id']}")
ck(len(m.state['logs']) == n_logs + 1, '2-c 로그에만 한 줄 추가')
ck(len(m.BREAKER.trip_calls) == 1, '2-d BREAKER.trip() 추가 호출 없음')

print('\n[시나리오 3] 낙상 critical 떠 있는 중 낙상이 또 발생 -> 화면 유지, 로그만')
reset_state()
m._latch_event('fall_detected', make_clf('critical'), 'A', '10:02:00', 0.9)
n_logs = len(m.state['logs'])
can4 = m._can_latch('fall_detected', 'critical')
ck(not can4, '3-a 같은 critical 재발생 _can_latch -> False(배타)')
if not can4:
    m._log_dropped('fall_detected', '10:02:05', '배타 latch')
ck(m.state['ev_id'] == 1, '3-b ev_id 그대로(화면 유지)')
ck(len(m.state['logs']) == n_logs + 1, '3-c 로그에만 한 줄 추가')
ck(len(m.BREAKER.trip_calls) == 1, '3-d BREAKER.trip() 추가 호출 없음')

print('\n[시나리오 4] 낙상 critical 떠 있는 중 감전 확정 -> 예외로 선점(2차 감전 방지)')
reset_state()
m._latch_event('fall_detected', make_clf('critical'), 'A', '10:03:00', 0.9)
can5 = m._can_latch('electric_shock_risk_confirmed', 'critical')
ck(can5, '4-a critical(낙상) 떠 있어도 감전확정은 _can_latch -> True(예외)')
if can5:
    m._latch_event('electric_shock_risk_confirmed', make_clf('critical'), 'A', '10:03:02', 0.99)
ck(m.state['ev_type'] == 'electric_shock_risk_confirmed' and m.state['ev_id'] == 2,
   '4-b 화면이 감전확정으로 전환', f"ev_type={m.state['ev_type']} ev_id={m.state['ev_id']}")

print('\n[시나리오 5] 감전 확정 떠 있는 중 감전 확정이 또 발생 -> 자기 자신은 예외 아님(배타)')
can6 = m._can_latch('electric_shock_risk_confirmed', 'critical')
ck(not can6, '5-a 같은 감전확정 재발생은 예외 조건(ev_type != new_et) 불충족 -> False')

ok_n = sum(1 for r in results if r)
ng_n = sum(1 for r in results if not r)
print(f'\n통과 {ok_n} / 실패 {ng_n}')
sys.exit(0 if ng_n == 0 else 1)
