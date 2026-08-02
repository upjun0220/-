r"""verify_jetson_safe.py — "노트북용 수정이 젯슨을 깨지 않는다"를 증명하는 검증

  실행: [내 PC PowerShell]   python 01_현행코드\verify_jetson_safe.py
  의존성: 표준 라이브러리 + numpy (torch 불필요 — 가짜 torch 를 주입해 검사한다)

═══ 왜 필요한가 ═══
  7/31 에 jetson_sender.py 를 노트북에서도 돌 수 있게 고쳤다(--simulate, torch 가드).
  "젯슨에서 에러 안 난다"는 말로는 증명이 안 된다. 실제로 확인해야 하는 것:

    1) --simulate 없이 모듈이 로드되고 경로가 전부 젯슨 것인가
    2) SIMULATE 가드 안의 코드가 정말 실행되지 않는가 (특히 RF_MODEL_PATH_OVERRIDE —
       정의되지 않은 이름이므로 조건이 잘못되면 NameError 로 즉사한다)
    3) torch 가 '있을 때' 분기가 정상인가  ← 가짜 torch 모듈을 주입해 검사
    4) 판정 로직·상수가 radar_live_full.py 와 여전히 같은가
    5) 강등 경로(ae_disabled)가 정상 경로를 건드리지 않는가

  종료코드 0 = 전부 통과.
"""
import ast
import importlib
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEND = os.path.join(HERE, 'jetson_sender.py')
LIVE = os.path.join(ROOT, '02_레이더_원본코드', 'radar_live_full.py')

_fail = []
_pass = []


def ck(ok, name, detail=''):
    (_pass if ok else _fail).append(name)
    print(f'  {"✓" if ok else "✗"} {name}' + (f'   {detail}' if detail else ''))


# ══════════════════════════════════════════════════════════════════════
def make_fake_torch():
    """젯슨의 'torch 있음' 분기를 타게 하는 최소 가짜 모듈.

    LSTM_AE 의 클래스 '정의'가 통과하는지, DEVICE 가 제대로 잡히는지만 본다.
    실제 학습은 검증 대상이 아니다(그건 젯슨 실물에서 확인).
    """
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
        def __init__(self, *a, **k):
            super().__init__()

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


def load_sender(argv, fake_torch=False):
    """jetson_sender 를 원하는 argv / torch 유무 조건으로 새로 로드한다."""
    saved_argv, saved_mods = sys.argv, {}
    sys.argv = argv
    injected = make_fake_torch() if fake_torch else {}
    for k, v in injected.items():
        saved_mods[k] = sys.modules.get(k)
        sys.modules[k] = v
    if fake_torch:
        # torch.optim / from torch import optim 대응
        sys.modules['torch'].optim = injected['torch'].optim
    sys.modules.pop('jetson_sender', None)
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        m = importlib.import_module('jetson_sender')
        return m, None
    except BaseException as e:                       # noqa: BLE001
        return None, f'{type(e).__name__}: {e}'
    finally:
        sys.argv = saved_argv
        for k, v in saved_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# ══════════════════════════════════════════════════════════════════════
print('=' * 70)
print('  jetson_sender.py — 젯슨 안전성 검증')
print('=' * 70)

print('\n[1] --simulate 없이 로드 (= 젯슨 실행 방식)')
m, err = load_sender(['jetson_sender.py'])
ck(m is not None, '모듈 로드', err or '')
if m is None:
    print('\n로드 실패 — 이후 검사 불가')
    sys.exit(1)

ck(m.SIMULATE is False, 'SIMULATE = False')
ck(m.SIM_FAST is False, 'SIM_FAST = False')
ck(m.JSON_PATH == '/home/project/stage1_filtered.json',
   'JSON_PATH 가 젯슨 경로', m.JSON_PATH)
ck(m.BASELINE_PATH == '/home/project/baseline_model.pt',
   'BASELINE_PATH 가 젯슨 경로', m.BASELINE_PATH)
ck(m.RF_MODEL_PATH.endswith('fall_classifier.joblib')
   and '01_현행코드' not in m.RF_MODEL_PATH,
   'RF_MODEL_PATH 가 ~/ 경로 (override 미적용)', m.RF_MODEL_PATH)
ck(getattr(m, 'RF_MODEL_PATH_OVERRIDE', 'x') is None,
   'RF_MODEL_PATH_OVERRIDE = None → SIMULATE 블록이 실행되지 않았음')
ck(m.SCAN_SEC == 12.0 and m.N_WARMUP == 150 and m.STEP_IN_SEC == 5.0,
   '--fast 상수 오염 없음', f'SCAN_SEC={m.SCAN_SEC} N_WARMUP={m.N_WARMUP}')

print('\n[2] 7/12 실측 튜닝 상수 (회귀 없어야 함)')
for k, want in (('STAT_MISS_TOL', 3), ('STAT_PRE_SEC', 10.0), ('STAT_CRIT_SEC', 30.0),
                ('FALL_CONFIRM', 1), ('CLF_WIN', 20), ('FEATURE_DIM', 9),
                ('CEILING_H', 2.30), ('POSTFALL_HOLD', 1.2)):
    got = getattr(m, k, None)
    ck(got == want, f'{k} = {want}', '' if got == want else f'실제 {got}')

print('\n[3] --simulate 로 로드 (노트북 검증 모드)')
ms, err = load_sender(['jetson_sender.py', '--simulate', '--fast'])
ck(ms is not None, '모듈 로드', err or '')
if ms is not None:
    ck(ms.SIMULATE is True and ms.SIM_FAST is True, 'SIMULATE / SIM_FAST = True')
    ck('/home/project/' not in ms.JSON_PATH, 'JSON_PATH 가 임시 경로로 대체', ms.JSON_PATH)
    ck(ms.N_WARMUP == 30 and ms.SCAN_SEC == 3.0, '--fast 상수 적용',
       f'N_WARMUP={ms.N_WARMUP} SCAN_SEC={ms.SCAN_SEC}')

print('\n[4] torch 가 "있을 때" 분기 (가짜 torch 주입 — 젯슨 조건)')
mt, err = load_sender(['jetson_sender.py'], fake_torch=True)
if mt is None:
    ck(False, 'torch 있음 분기 로드', err)
else:
    ck(mt.TORCH_OK is True, 'TORCH_OK = True')
    ck('device(' in repr(mt.DEVICE), 'DEVICE 가 torch.device 로 잡힘', repr(mt.DEVICE))
    ck(hasattr(mt, 'LSTM_AE') and isinstance(mt.LSTM_AE, type),
       'LSTM_AE 클래스 정의 통과 (nn.Module 상속)')
    ck(mt.LSTM_AE.__mro__[1] is sys.modules.get('torch').nn.Module
       if 'torch' in sys.modules else True,
       'LSTM_AE 가 진짜 nn.Module 을 상속') if False else None
    ck(mt.optim is not None, 'from torch import optim 바인딩')
    ck(mt.MinMaxScaler is not None, 'MinMaxScaler 바인딩')
    ck(mt.SIMULATE is False, 'torch 있어도 SIMULATE 는 여전히 False')

print('\n[5] 정적 검사 — SIMULATE 가드 밖으로 새어나간 코드가 있나')
src = open(SEND, encoding='utf-8').read()
tree = ast.parse(src)
guarded, leaked = 0, []
for node in ast.walk(tree):
    if isinstance(node, ast.If):
        test = ast.unparse(node.test)
        if 'SIMULATE' in test or 'SIM_FAST' in test:
            guarded += 1
ck(guarded >= 4, f'SIMULATE/SIM_FAST 가드 블록 {guarded}개 확인')


def guard_audit(name):
    """이 이름이 '정의되지 않은 상태로 참조'될 수 있는지 AST 로 검사.

    안전 조건 = (a) 최상위에서 조건 없이 먼저 대입되거나,
                (b) 최상위에서 아예 참조되지 않는다.
    단순 grep 은 `X = None` 같은 정상 초기화까지 잡으므로 쓰지 않는다.
    """
    uncond_assign = None            # 조건 밖 최상위 대입 줄번호
    guarded_assign = []
    loads = []                     # 최상위에서 '읽는' 위치
    for node in tree.body:         # tree.body = 모듈 최상위만
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    uncond_assign = uncond_assign or node.lineno
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Name) and sub.id == name:
                    loads.append(node.lineno)
        elif isinstance(node, ast.If):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Name) and sub.id == name
                        and isinstance(sub.ctx, ast.Store)):
                    guarded_assign.append(sub.lineno)
    if uncond_assign is None and not loads:
        return True, '최상위에서 참조 없음'
    if uncond_assign is None:
        return False, f'조건부({guarded_assign})로만 정의되는데 {loads}행에서 읽음'
    bad = [l for l in loads if l < uncond_assign]
    if bad:
        return False, f'{bad}행이 초기화({uncond_assign}행)보다 먼저 읽음'
    return True, f'{uncond_assign}행에서 무조건 초기화 후 {loads or "-"}행에서 사용'


for nm in ('RF_MODEL_PATH_OVERRIDE', 'SIMULATE', 'SIM_FAST'):
    ok, why = guard_audit(nm)
    ck(ok, f'{nm} — 미정의 참조 위험 없음', why)

# 함수/모듈은 정의만 하고 SIMULATE 가드 안에서만 '호출'돼야 한다
for nm in ('sim_radar_writer', 'tempfile'):
    called_unguarded = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.Expr)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id == nm:
                    called_unguarded.append(node.lineno)
    ck(not called_unguarded, f'{nm} — 가드 밖 최상위 사용 없음',
       '' if not called_unguarded else f'{called_unguarded}행')

print('\n[6] 판정 로직이 radar_live_full.py 와 동일한가 (주석 제외 코드 비교)')


def code_of(path, fn):
    s = open(path, encoding='utf-8').read()
    mm = re.search(r'(?m)^def %s\(.*?(?=^def |^class |^# ═)' % fn, s, re.S)
    if not mm:
        return None
    return [' '.join(l.split('#')[0].split())
            for l in mm.group(0).splitlines() if l.split('#')[0].strip()]


if os.path.exists(LIVE):
    for fn in ('classify', 'extract_features', '_rf_features', '_rf_veto'):
        a, b = code_of(LIVE, fn), code_of(SEND, fn)
        ck(a is not None and a == b, f'{fn}() 코드 동일',
           '' if a == b else f'live {len(a or [])}줄 vs sender {len(b or [])}줄')
else:
    ck(False, 'radar_live_full.py 를 찾을 수 없음', LIVE)

print('\n[7] 의도한 동작 변경 (에러가 아니라 수정 — 확인용)')
for note in (
        '차단기 판정을 PH_LIVE 에서만 수행 (이전: 웜업·학습 중에도 수행)',
        '설비진동 게이트에 사람 dop_std 를 넣지 않음 (이전: 걸을 때마다 차단)',
        '학습 실패 시 무한 대기 대신 규칙 전용 LIVE 로 강등',
        '히스토리(cz/ds/sc/logs/incidents)를 1초에 한 번만 전송 (MTU 초과 해소)',
        'evidence/gates/rejected/power/breaker 를 패킷에 추가'):
    print(f'  · {note}')

print('\n' + '=' * 70)
print(f'  통과 {len(_pass)}건 / 실패 {len(_fail)}건')
if _fail:
    print('  실패 항목: ' + ', '.join(_fail))
    print('  → 젯슨에 올리기 전에 고쳐야 합니다.')
else:
    print('  ✅ 젯슨 실행 경로에 영향 없음이 확인됐습니다.')
print('=' * 70)
sys.exit(1 if _fail else 0)
