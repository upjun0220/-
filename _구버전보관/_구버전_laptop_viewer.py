"""
laptop_viewer.py -- Radar-Guard [노트북 측]  (radar_live_full.py 분할본 2/2)
===========================================================================
역할: 젯슨(jetson_sender.py)에서 UDP로 받은 판정 결과 + 포인트클라우드를
      5패널 대시보드로 렌더링하고, 버튼 명령을 젯슨으로 되돌려 보낸다.
      + RAG 검색(pgvector)과 Gemma 상세 SOP 생성을 '노트북 로컬'에서 수행.

실행 (노트북 터미널 1개):
  python laptop_viewer.py 192.168.0.50        <- 젯슨 IP
  (또는 아래 JETSON_IP를 직접 채우거나 RADAR_JETSON_IP 환경변수)

노트북 사전 준비 (RAG/LLM을 쓸 때만. 없어도 탐지·표시는 정상 동작):
  ollama serve  &&  ollama pull gemma2:2b  &&  ollama pull nomic-embed-text
  docker start radar-guard-db     (pgvector에 safety_manual 컬렉션 적재된 상태)

포트:  5005 = 젯슨 -> 노트북 (데이터)      5006 = 노트북 -> 젯슨 (제어/HELLO)
"""

import json, os, sys, time, socket, threading, textwrap, warnings
from datetime import datetime
from collections import deque

import numpy as np
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from matplotlib.widgets import Button
from mpl_toolkits.mplot3d import Axes3D  # noqa
matplotlib.rcParams['font.family'] = 'DejaVu Sans'

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════
# 0. NETWORK CONFIG
# ═══════════════════════════════════════════════════════════
JETSON_IP = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('-')
             else os.environ.get('RADAR_JETSON_IP', '192.168.0.50'))
DATA_PORT = 5005          # 젯슨 -> 노트북 (여기서 수신)
CTRL_PORT = 5006          # 노트북 -> 젯슨 (버튼 명령 + HELLO)
HELLO_SEC = 2.0           # HELLO 주기(젯슨이 이 주소로 데이터를 보내게 함)

# ═══════════════════════════════════════════════════════════
# 1. DISPLAY / LLM CONFIG
# ═══════════════════════════════════════════════════════════
CEILING_H   = 2.30       # 젯슨과 동일하게 유지할 것
N_WARMUP    = 150        # 젯슨 패킷의 cfg로 자동 갱신됨
SCAN_SEC    = 12.0       # 〃
HISTORY_LEN = 120
UPDATE_MS   = 1000
DEBUG_TIMING = False     # True = 매 프레임 루프 소요시간 출력(진단용)
WRAP_WIDTH  = 52
JSON_PATH   = '/home/project/stage1_filtered.json'   # 안내문구용(젯슨 cfg로 갱신)

# ── 노트북 로컬 RAG / LLM ──
CONN_STR   = 'postgresql://postgres:password@localhost:5432/radar_guard'
OLLAMA_URL = 'http://localhost:11434/api/generate'
LLM_MODEL  = 'gemma2:2b'
DETAILED_SOP_POPUP = True    # 경보 시 Gemma 상세 SOP 팝업창
USE_LLM_SUMMARY    = False   # 검색 원문 아래 LLM 요약 덧붙이기
SOP_LANG   = 'en'            # 'ko'(한글, 폰트 필요) / 'en'(폰트 무관)


# ── 한글 SOP 표시용 폰트 ────────────────────────────────────
def _set_korean_font():
    try:
        import matplotlib.font_manager as fm
        avail = {f.name for f in fm.fontManager.ttflist}
        for _name in ('Malgun Gothic', 'NanumGothic', 'NanumBarunGothic', 'AppleGothic',
                      'Noto Sans CJK KR', 'Noto Sans KR', 'UnDotum', 'Baekmuk Gulim'):
            if _name in avail:
                matplotlib.rcParams['font.family'] = _name
                matplotlib.rcParams['axes.unicode_minus'] = False
                return _name
    except Exception:
        pass
    return None
KOREAN_FONT = _set_korean_font()
if KOREAN_FONT is None:
    print('[FONT] ⚠ 한글 폰트 없음 -> SOP 한글이 깨질 수 있음 (SOP_LANG="en" 권장)')

# ── RAG imports (없으면 검색 없이 즉시조치만 표시) ──
try:
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    from langchain_community.vectorstores import PGVector
    RAG_OK = True
except ImportError:
    RAG_OK = False

# ═══════════════════════════════════════════════════════════
# 2. LABELS / SOP TEXT
# ═══════════════════════════════════════════════════════════
PH_READY      = 'READY'
PH_WARMUP     = 'WARMUP'
PH_WAIT_TRAIN = 'WAIT_TRAIN'
PH_TRAINING   = 'TRAINING'
PH_LIVE       = 'LIVE'

STEP_LABELS = ['  Radar ON  ', '  Baseline  ', '  Training  ', '  LIVE  ']
STEP_COLORS_ACTIVE   = ['#00ccff', '#ffcc00', '#ff8800', '#44ff88']
STEP_COLORS_INACTIVE = ['#223344', '#332200', '#331800', '#112211']
STEP_TEXT_INACTIVE   = '#445566'

EVENT_LABELS = {
    'fall_detected':       'FALL DETECTED',
    'stationary_anomaly':  'STATIONARY ANOMALY (VERIFY: SHOCK/ENTRAPMENT)',
    'electric_shock_risk': 'ELECTRIC SHOCK RISK',
    'pinching':            'PINCHING / ENTRAPMENT',
    'vibration_anomaly':   'VIBRATION ANOMALY',
}
EVENT_CATEGORY = {
    'fall_detected':       '03_naksan_eunggeupcheo',
    'electric_shock_risk': '01_gamjeon_LOTO',
    'pinching':            '02_hyeopcak_kkim',
    'vibration_anomaly':   '04_yeji_boen',
}
SEV_COLOR = {'normal': '#44ff88', 'warning': '#ffaa00', 'critical': '#ff3333'}
EVENT_SHORT = {
    'fall_detected':      'FALL',
    'stationary_anomaly': 'STATIONARY (verify)',
    'electric_shock_risk':'SHOCK',
    'pinching':           'PINCH',
    'vibration_anomaly':  'VIBRATION',
}

INSTANT_ACTION_KO = {
    'fall_detected': (
        "[즉시 조치]  낙상 감지\n"
        "  1. 의식·호흡 확인\n"
        "  2. 환자를 함부로 움직이지 말 것 (척추 손상 위험)\n"
        "  3. 주변 위험요소 차단·현장 확보\n"
        "  4. 119 신고 후 구조 도착까지 관찰\n"
    ),
    'stationary_anomaly': (
        "[즉시 조치]  정지형 이상 (감전/협착 여부 확인)\n"
        "  1. 접근 전 전원 차단 확인 (LOTO)\n"
        "     -- 감전 의심 시: 맨손 접촉 금지\n"
        "  2. 협착 시: 무리하게 잡아당기지 말 것\n"
        "  3. 119 신고\n"
        "  4. 현장에서 유형 확인 후 SOP 따를 것\n"
    ),
    'vibration_anomaly': (
        "[점검]  진동 / 경미한 이상\n"
        "  - 해당 구역 육안 점검\n"
    ),
}
INSTANT_ACTION_EN = {
    'fall_detected': (
        "[IMMEDIATE]  FALL DETECTED\n"
        "  1. Check consciousness / breathing\n"
        "  2. DO NOT move victim (spinal risk)\n"
        "  3. Cut nearby hazards; secure area\n"
        "  4. Call emergency; monitor until help\n"
    ),
    'stationary_anomaly': (
        "[IMMEDIATE]  STATIONARY ANOMALY (verify: shock/entrapment)\n"
        "  1. Before approach: confirm power OFF (LOTO)\n"
        "     -- if shock: NO bare-hand contact\n"
        "  2. If entrapment: NO forced pulling\n"
        "  3. Call emergency\n"
        "  4. Verify type on-site, then follow SOP\n"
    ),
    'vibration_anomaly': (
        "[CHECK]  Vibration / minor anomaly\n"
        "  - Visual check the zone\n"
    ),
}
def instant_action(ev_type):
    d = INSTANT_ACTION_KO if SOP_LANG == 'ko' else INSTANT_ACTION_EN
    fb = f"[경보] {EVENT_LABELS.get(ev_type, ev_type)}\n" if SOP_LANG == 'ko' \
         else f"[ALERT] {EVENT_LABELS.get(ev_type, ev_type)}\n"
    return d.get(ev_type, fb)

# ═══════════════════════════════════════════════════════════
# 3. SHARED STATE (젯슨 패킷 미러 + 노트북 로컬 SOP)
# ═══════════════════════════════════════════════════════════
_lock = threading.RLock()
state = {
    'connected':   False,
    'seq':         0,
    'last_pkt_t':  0.0,
    'phase':       PH_READY,
    'warmup_count': 0,
    'threshold':   0.01,
    'data_ok':     False,
    'data_age':    1e9,
    'scan_left':   None,
    'pre_alert':   '',
    'latest_pts':  [],
    'n_pts':       0,
    'cz_h':  [1.7] * HISTORY_LEN,
    'ds_h':  [0.0] * HISTORY_LEN,
    'sc_h':  [0.0] * HISTORY_LEN,
    'incidents':   [],
    'ev_active':   False,
    'ev_type':     None,
    'ev_sev':      'normal',
    'ev_conf':     0.0,
    'ev_zone':     'C',
    'ev_id':       0,
    # ── 노트북 로컬 ──
    'rag_running':  False,
    'sop_text':     '',
    'instant_sop':  '',
    'detailed_sop':     '',
    'detailed_sop_ver': 0,
    '_manual_ctx':      '',
    'sop_cache_status': 'SOP cache: waiting for LIVE...',
}
_last_rag_id = 0        # RAG를 이미 돌린 ev_id


def add_log(msg):
    print(f'[LOG {datetime.now().strftime("%H:%M:%S")}] {msg}')

# ═══════════════════════════════════════════════════════════
# 4. RAG / LLM  (노트북 로컬 실행)
# ═══════════════════════════════════════════════════════════
def generate_detailed_sop(ev_type, zone, manual_ctx=''):
    """Ollama REST(/api/generate) 직접 호출로 상세 SOP 생성 (urllib, langchain 불필요)."""
    import urllib.request
    label = EVENT_LABELS.get(ev_type, ev_type)
    if SOP_LANG == 'ko':
        ctx_block = (f'\n참고 안전매뉴얼 발췌:\n{manual_ctx[:1200]}\n' if manual_ctx else '')
        prompt = (
            f'너는 산업 현장 안전관리자다. 방금 "{label}"이(가) Zone {zone}에서 감지됐다.'
            f'{ctx_block}\n'
            f'현장 작업자가 지금 즉시 따라야 할 초동 조치를 한국어로 작성하라. '
            f'번호를 매긴 4~5단계, 각 단계는 짧은 한 문장. 서론·부연 없이 조치만.'
        )
    else:
        ctx_block = (f'\nSafety manual excerpt:\n{manual_ctx[:1200]}\n' if manual_ctx else '')
        prompt = (
            f'You are an industrial safety officer. "{label}" was just detected in Zone {zone}.'
            f'{ctx_block}\n'
            f'Write the immediate response actions the on-site worker must take now, '
            f'as a numbered 4-5 step list, one short sentence each. No preamble, actions only.'
        )
    body = json.dumps({
        'model': LLM_MODEL, 'prompt': prompt, 'stream': False,
        'keep_alive': '10m',
        'options': {'num_ctx': 1024, 'num_predict': 200, 'temperature': 0.2},
    }).encode('utf-8')
    req = urllib.request.Request(OLLAMA_URL, data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode('utf-8')).get('response', '').strip()


_sop_cache = {}   # 이벤트 유형별 상세 SOP 사전생성 캐시 -> 경보 시 즉시 표시

def _prewarm_gemma():
    """LIVE 진입 후 이벤트 유형별 상세 SOP를 미리 생성해 캐시 (백그라운드)."""
    for _ in range(600):
        with _lock:
            if state['phase'] == PH_LIVE:
                break
        time.sleep(0.5)
    add_log('상세 SOP 사전생성 시작 (백그라운드, 유형별 1회)...')
    _types = ('fall_detected', 'stationary_anomaly', 'vibration_anomaly')
    with _lock:
        state['sop_cache_status'] = 'SOP cache: generating 0/3...'
    for i, et in enumerate(_types, 1):
        try:
            txt = generate_detailed_sop(et, 'C', '')
            if txt:
                _sop_cache[et] = txt
                add_log(f'상세 SOP 캐시 완료: {et} ({i}/3)')
                with _lock:
                    done = len(_sop_cache)
                    state['sop_cache_status'] = (f'SOP cache READY {done}/3 (instant popup)'
                                                 if done >= 3 else f'SOP cache: generating {done}/3...')
        except Exception as e:
            add_log(f'상세 SOP 사전생성 중단 ({et}): {e} -- ollama/gemma2:2b 확인')
            with _lock:
                state['sop_cache_status'] = f'SOP cache FAILED ({e})'
            break


def _sop_status(msg):
    with _lock:
        base = state.get('sop_text', '').split('\n>> [Detailed SOP]')[0].rstrip()
        state['sop_text'] = base + f'\n\n>> [Detailed SOP] {msg}'


def _make_detailed_sop(ev_type, zone):
    """캐시가 있으면 즉시 표시, 없으면 Gemma로 생성 후 캐시."""
    cached = _sop_cache.get(ev_type)
    if cached:
        with _lock:
            state['detailed_sop']     = cached
            state['detailed_sop_ver'] = state.get('detailed_sop_ver', 0) + 1
        _sop_status('shown instantly (pre-generated)')
        add_log('detailed SOP: cache hit -> instant popup')
        return
    try:
        with _lock:
            ctx = state.get('_manual_ctx', '')
        _sop_status('generating via Gemma (first time)...')
        add_log('detailed SOP: generating (no cache yet)...')
        txt = generate_detailed_sop(ev_type, zone, ctx)
        if txt:
            _sop_cache[ev_type] = txt
            with _lock:
                state['detailed_sop']     = txt
                state['detailed_sop_ver'] = state.get('detailed_sop_ver', 0) + 1
            _sop_status('ready -> popup (cached for next time)')
            add_log('detailed SOP ready -> popup (cached)')
        else:
            _sop_status('Gemma returned empty response')
    except Exception as e:
        _sop_status(f'FAILED: {e}  (check: ollama serve / gemma2:2b)')
        add_log(f'detailed SOP failed: {e}')


def run_rag(ev_type, zone):
    """검색(메인 패널) + Gemma 상세 SOP(팝업)를 한 스레드에서 순차 수행."""
    _rag_retrieve(ev_type, zone)
    if DETAILED_SOP_POPUP:
        _make_detailed_sop(ev_type, zone)


def _rag_retrieve(ev_type, zone):
    situation = f'{EVENT_LABELS.get(ev_type, ev_type)} detected in Zone {zone}'
    category  = EVENT_CATEGORY.get(ev_type)
    add_log(f'RAG started: {situation}')
    with _lock:
        instant = state.get('instant_sop', '')
        state['sop_text'] = instant + '\n>> Searching safety manual...'

    if not RAG_OK:
        with _lock:
            state['sop_text']    = instant + '\n[Detailed SOP unavailable: LangChain not installed]'
            state['rag_running'] = False
        return

    try:
        emb  = OllamaEmbeddings(model='nomic-embed-text')
        vs   = PGVector(connection_string=CONN_STR, embedding_function=emb,
                        collection_name='safety_manual')
        docs = vs.similarity_search(situation, k=2,
               filter={'category': category}) if category \
               else vs.similarity_search(situation, k=2)
        if not docs:
            with _lock:
                state['sop_text']    = instant + f'\n[Manual: no match for category {category}]'
                state['rag_running'] = False
            return
        excerpts = []
        for i, d in enumerate(docs, 1):
            src  = d.metadata.get('source_file', '?')
            body = ' '.join(d.page_content.split())[:360]
            excerpts.append(f'[{i}] ({src})\n{textwrap.fill(body, width=WRAP_WIDTH)}')
        manual = '\n\n'.join(excerpts)
        with _lock:
            state['sop_text']    = (instant +
                f'\n=== Manual (retrieved, top {len(docs)}) ===\n\n{manual}')
            state['_manual_ctx'] = ' '.join(d.page_content for d in docs)[:1500]
            state['rag_running'] = False
        add_log(f'Manual retrieved ({len(docs)} chunk) - retrieval-only, no LLM')

        if USE_LLM_SUMMARY:
            try:
                llm = ChatOllama(model=LLM_MODEL, temperature=0.2,
                                 num_ctx=1024, num_predict=180, keep_alive=0)
                ctx = ' '.join(d.page_content for d in docs)[:1500]
                out = llm.invoke(
                    f'상황: {situation}\n아래 안전 매뉴얼 발췌를 근거로, 현장 작업자가 '
                    f'지금 즉시 따라야 할 조치를 한국어 3~4줄로 요약하라:\n{ctx}'
                ).content.strip()
                with _lock:
                    state['sop_text'] += (f'\n\n=== AI summary ({LLM_MODEL}) ===\n'
                                          + textwrap.fill(out, width=WRAP_WIDTH))
                add_log(f'LLM summary appended ({LLM_MODEL})')
            except Exception as e:
                add_log(f'LLM summary skipped: {e}')

    except Exception as e:
        with _lock:
            state['sop_text']    = instant + (f'\n[Manual search error: {e}]\n'
                                              f'  check (노트북): docker start radar-guard-db / ollama serve')
            state['rag_running'] = False
        add_log(f'RAG error: {e}')

# ═══════════════════════════════════════════════════════════
# 5. NETWORK  (젯슨 데이터 수신 + 제어 송신)
# ═══════════════════════════════════════════════════════════
_ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send_cmd(cmd):
    try:
        _ctrl_sock.sendto(json.dumps({'cmd': cmd}).encode('utf-8'),
                          (JETSON_IP, CTRL_PORT))
    except OSError as e:
        print(f'[NET] 명령 전송 실패({cmd}): {e}')


def hello_loop():
    """젯슨이 이 노트북 주소를 알도록 주기적으로 HELLO 송신."""
    while True:
        send_cmd('hello')
        time.sleep(HELLO_SEC)


def udp_receiver():
    global _last_rag_id, N_WARMUP, SCAN_SEC, CEILING_H, JSON_PATH
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0', DATA_PORT))
    print(f'[NET] {DATA_PORT} 포트에서 젯슨({JETSON_IP}) 데이터 수신 대기 중...')

    while True:
        try:
            data, addr = sock.recvfrom(65535)
        except OSError as e:
            print('[NET] 수신 에러:', e); time.sleep(0.3); continue
        try:
            pkt = json.loads(data.decode('utf-8'))
        except Exception as e:
            print(f'[NET] 파싱 실패: {e} (len={len(data)} from {addr[0]})')
            continue

        cfg = pkt.get('cfg') or {}
        if cfg:
            N_WARMUP  = cfg.get('N_WARMUP', N_WARMUP)
            SCAN_SEC  = cfg.get('SCAN_SEC', SCAN_SEC)
            CEILING_H = cfg.get('CEILING_H', CEILING_H)
            JSON_PATH = cfg.get('JSON_PATH', JSON_PATH)

        ev = pkt.get('ev') or {}
        trigger = None
        with _lock:
            if not state['connected']:
                print(f'[NET] 젯슨 연결됨: {addr[0]}')
            state['connected']    = True
            state['seq']          = pkt.get('seq', 0)
            state['last_pkt_t']   = time.time()
            state['phase']        = pkt.get('phase', PH_READY)
            state['warmup_count'] = pkt.get('warmup_count', 0)
            state['threshold']    = pkt.get('threshold', 0.01)
            state['data_ok']      = pkt.get('data_ok', False)
            state['data_age']     = pkt.get('data_age', 1e9)
            state['scan_left']    = pkt.get('scan_left')
            state['pre_alert']    = pkt.get('pre_alert', '')
            state['latest_pts']   = pkt.get('points', [])
            state['n_pts']        = pkt.get('n_pts', len(state['latest_pts']))
            state['cz_h']         = pkt.get('cz') or state['cz_h']
            state['ds_h']         = pkt.get('ds') or state['ds_h']
            state['sc_h']         = pkt.get('sc') or state['sc_h']
            state['incidents']    = pkt.get('incidents', [])
            was_active            = state['ev_active']
            state['ev_active']    = ev.get('active', False)
            state['ev_type']      = ev.get('type')
            state['ev_sev']       = ev.get('sev', 'normal')
            state['ev_conf']      = ev.get('conf', 0.0)
            state['ev_zone']      = ev.get('zone', 'C')
            state['ev_id']        = ev.get('id', 0)

            if state['ev_active'] and state['ev_id'] != _last_rag_id:
                # 새 경보 latch -> 즉시조치 표시 + 로컬 RAG/LLM 시작
                _last_rag_id = state['ev_id']
                et, zn = state['ev_type'], state['ev_zone']
                inst = instant_action(et)
                state['instant_sop'] = inst
                state['sop_text']    = inst + '\n>> Searching safety manual (pgvector)...'
                state['rag_running'] = True
                trigger = (et, zn)
            elif was_active and not state['ev_active']:
                # 젯슨에서 해제됨 -> SOP 패널 정리
                state.update({'sop_text': '', 'instant_sop': '', 'rag_running': False})

        if trigger:
            add_log(f'ALERT 수신: {trigger[0]} Zone {trigger[1]} -> RAG 시작(노트북)')
            threading.Thread(target=run_rag, args=trigger, daemon=True).start()

# ═══════════════════════════════════════════════════════════
# 6. MATPLOTLIB FIGURE
# ═══════════════════════════════════════════════════════════
fig = plt.figure(figsize=(17, 9), facecolor='#080818')
fig.suptitle('Radar-Guard  |  IWR6843ISK-ODS  |  Real-time Safety Monitor (LAPTOP)',
             color='white', fontsize=12, fontweight='bold', y=0.99)

# ── Step Guide (4 steps) ─────────────────────────────────
step_texts = []
step_xs = [0.13, 0.36, 0.59, 0.82]
step_y   = 0.967
step_arrows_x = [0.255, 0.485, 0.715]
for sx, label, col_off in zip(step_xs, STEP_LABELS, STEP_COLORS_INACTIVE):
    t = fig.text(sx, step_y, label,
                 color=STEP_TEXT_INACTIVE, fontsize=9, ha='center', va='center',
                 fontfamily='monospace', fontweight='bold',
                 bbox=dict(boxstyle='round,pad=0.4', facecolor='#0a0a1e',
                           edgecolor='#223344', alpha=0.95))
    step_texts.append(t)

for ax_pos in step_arrows_x:
    fig.text(ax_pos, step_y, '  -->  ', color='#334455',
             fontsize=9, ha='center', va='center', fontfamily='monospace')

# ── Status Bar ───────────────────────────────────────────
status_box = fig.text(0.5, 0.948, 'Initializing...',
                      color='white', fontsize=9.5, va='center', ha='center',
                      fontfamily='monospace',
                      bbox=dict(boxstyle='round,pad=0.38', facecolor='#101028',
                                edgecolor='#445566', alpha=0.95))

# ── Active Alarm Banner ──────────────────────────────────
alarm_banner = fig.text(0.5, 0.086, '', color='white', fontsize=10,
                        va='center', ha='center', fontfamily='monospace',
                        fontweight='bold', visible=False,
                        bbox=dict(boxstyle='round,pad=0.45', facecolor='#3a0000',
                                  edgecolor='#ff3333', linewidth=1.6, alpha=0.97))

# ── Progress Bar ─────────────────────────────────────────
ax_prog = fig.add_axes([0.04, 0.925, 0.92, 0.012])
ax_prog.set_xlim(0, 1); ax_prog.set_ylim(0, 1)
ax_prog.axis('off')
ax_prog.set_facecolor('#0a0a1e')
prog_bg   = mpatches.FancyBboxPatch((0, 0.1), 1.0, 0.8, boxstyle='round,pad=0.01',
                                    facecolor='#151530', edgecolor='#223344', linewidth=0.8)
prog_fill = mpatches.FancyBboxPatch((0, 0.1), 0.0, 0.8, boxstyle='round,pad=0.01',
                                    facecolor='#00aaff', edgecolor='none', alpha=0.85)
ax_prog.add_patch(prog_bg)
ax_prog.add_patch(prog_fill)
prog_label = ax_prog.text(0.5, 0.5, '', ha='center', va='center',
                          color='white', fontsize=8, fontfamily='monospace')

# ── GridSpec (5 data panels) ─────────────────────────────
gs = gridspec.GridSpec(
    2, 3, figure=fig,
    left=0.04, right=0.98, top=0.91, bottom=0.10,
    hspace=0.38, wspace=0.28,
    height_ratios=[1.15, 1],
)

# -- Panel 1: 3D Point Cloud --
ax3d = fig.add_subplot(gs[0, 0], projection='3d')
ax3d.set_facecolor('#08081a')
ax3d.set_title('3D Point Cloud  (latest frame)', color='white', fontsize=8, pad=3)
ax3d.set_xlabel('X (m)', color='#8899bb', fontsize=7, labelpad=1)
ax3d.set_ylabel('Z floor (m)', color='#8899bb', fontsize=7, labelpad=1)
ax3d.set_zlabel('Height (m)', color='#8899bb', fontsize=7, labelpad=1)
ax3d.tick_params(colors='#556677', labelsize=6)
ax3d.set_xlim(-2, 2); ax3d.set_ylim(-2, 2); ax3d.set_zlim(0, 2.5)
for pn in (ax3d.xaxis.pane, ax3d.yaxis.pane, ax3d.zaxis.pane):
    pn.fill = False; pn.set_edgecolor('#1a1a33')
# 빈 배열 대신 더미 1점으로 초기화 (컬러매핑 초기화 안전)
scatter3d = ax3d.scatter([0.0], [0.0], [0.0], c=[0.0], cmap='plasma',
                         vmin=200, vmax=600, s=16, alpha=0.85)

# -- Panel 2: Centroid Height --
ax_z = fig.add_subplot(gs[0, 1], facecolor='#08081a')
ax_z.set_title('Centroid Height  (CEILING_H - y;  fall = doppler)', color='white', fontsize=8, pad=3)
ax_z.set_ylim(0, 2.5); ax_z.set_xlim(0, HISTORY_LEN)
ax_z.axhline(1.70, color='#44cc66', lw=0.8, ls=':', alpha=0.55)
ax_z.axhline(0.0,  color='#8899bb', lw=0.8, ls=':', alpha=0.4)
ax_z.text(2, 1.76, 'Standing ~1.7m', color='#44cc66', fontsize=7)
ax_z.text(2, 0.08, 'Floor 0m', color='#8899bb', fontsize=7)
for sp in ax_z.spines.values(): sp.set_color('#1a1a33')
ax_z.tick_params(colors='#556677', labelsize=7)
ax_z.set_xlabel('Frames', color='#8899bb', fontsize=7)
ax_z.set_ylabel('Height (m)',  color='#8899bb', fontsize=7)
line_z, = ax_z.plot([], [], color='#00ccff', lw=1.8)

# -- Panel 3: Motion / Vibration --
ax_sc = fig.add_subplot(gs[0, 2], facecolor='#08081a')
ax_sc.set_title('Motion / Vibration  (dop_std)', color='white', fontsize=8, pad=3)
ax_sc.set_xlim(0, HISTORY_LEN); ax_sc.set_ylim(0, 2.0)
for sp in ax_sc.spines.values(): sp.set_color('#1a1a33')
ax_sc.tick_params(colors='#556677', labelsize=7)
ax_sc.set_xlabel('Frames', color='#8899bb', fontsize=7)
ax_sc.set_ylabel('dop_std', color='#8899bb', fontsize=7)
line_sc, = ax_sc.plot([], [], color='#ffaa00', lw=1.8)
thr_line  = ax_sc.axhline(1.2, color='#ff4444', ls='--', lw=1.1, alpha=0.85, label='fall thr 1.2')
ax_sc.text(2, 0.62, 'stationary/vib', color='#88aacc', fontsize=6)
ax_sc.legend(loc='upper right', fontsize=7,
             facecolor='#08081a', edgecolor='#334455', labelcolor='white')

# -- Panel 4: Incident History --
ax_log = fig.add_subplot(gs[1, 0], facecolor='#060614')
ax_log.set_title('Incident History', color='white', fontsize=8, pad=3)
ax_log.axis('off')
log_text = ax_log.text(0.02, 0.97, '', transform=ax_log.transAxes,
                        color='#aabbcc', fontsize=7, va='top',
                        fontfamily='monospace')

# -- Panel 5: SOP / Guide --
ax_sop = fig.add_subplot(gs[1, 1:])
ax_sop.set_facecolor('#04040e')
ax_sop.set_title('Action Guide  /  SOP (instant + pgvector retrieval)',
                  color='white', fontsize=8, pad=3)
ax_sop.axis('off')
sop_text = ax_sop.text(0.015, 0.97, '',
                        transform=ax_sop.transAxes,
                        color='#ccddee', fontsize=7.5, va='top',
                        fontfamily='monospace')

# ═══════════════════════════════════════════════════════════
# 7. STEP GUIDE HELPERS
# ═══════════════════════════════════════════════════════════
def _step_idx(phase, data_ok):
    if not data_ok:
        return -1
    if phase == PH_READY:
        return 0
    if phase == PH_WARMUP:
        return 1
    if phase in (PH_WAIT_TRAIN, PH_TRAINING):
        return 2
    return 3   # LIVE


def update_step_guide(phase, data_ok):
    idx = _step_idx(phase, data_ok)
    for i, t in enumerate(step_texts):
        if i <= idx:
            t.set_color(STEP_COLORS_ACTIVE[i])
            t.get_bbox_patch().set_facecolor('#0a1020')
            t.get_bbox_patch().set_edgecolor(STEP_COLORS_ACTIVE[i])
        else:
            t.set_color(STEP_TEXT_INACTIVE)
            t.get_bbox_patch().set_facecolor('#0a0a1e')
            t.get_bbox_patch().set_edgecolor('#223344')


def update_progress_bar(phase, warmup_count):
    if phase == PH_WARMUP:
        pct = warmup_count / max(1, N_WARMUP)
        prog_fill.set_width(pct)
        prog_fill.set_facecolor('#00aaff')
        prog_label.set_text(f'Baseline collection: {warmup_count} / {N_WARMUP} frames  ({int(pct*100)}%)'
                            f'  -- Stand still in front of radar')
        prog_label.set_color('white')
        ax_prog.set_visible(True)
    elif phase == PH_WAIT_TRAIN:
        prog_fill.set_width(1.0)
        prog_fill.set_facecolor('#ffcc00')
        prog_label.set_text(f'Baseline COMPLETE  ({N_WARMUP} / {N_WARMUP} frames)  '
                            f'-- Click  "Start Training"  to proceed')
        prog_label.set_color('#ffdd44')
        ax_prog.set_visible(True)
    elif phase == PH_TRAINING:
        prog_fill.set_width(1.0)
        prog_fill.set_facecolor('#ffaa00')
        prog_label.set_text('Training LSTM-AE model...  Please wait (~20-30 sec)  --  Do not move')
        prog_label.set_color('#ffcc44')
        ax_prog.set_visible(True)
    elif phase == PH_LIVE:
        prog_fill.set_width(1.0)
        prog_fill.set_facecolor('#44ff88')
        prog_label.set_text('LIVE detection active  --  Monitoring for anomalies')
        prog_label.set_color('#44ff88')
        ax_prog.set_visible(True)
    else:
        prog_fill.set_width(0.0)
        prog_label.set_text('')
        ax_prog.set_visible(True)


def make_guide_text(phase, data_ok, ev_active, ev_type, ev_zone, ev_conf,
                    rag_run, sop, warmup_count, connected):
    if not connected:
        return (
            "======= CONNECTION =======\n\n"
            f"  젯슨({JETSON_IP})에서 패킷이 아직 없습니다.\n\n"
            "  젯슨 터미널에서 확인:\n"
            "    python3 ~/radar_parser.py\n"
            "    python3 ~/jetson_sender.py\n\n"
            "  IP가 다르면 이 창을 닫고:\n"
            "    python laptop_viewer.py <젯슨IP>\n\n"
            "  방화벽에서 UDP 5005/5006 허용 필요."
        )
    if not data_ok:
        return (
            "======= SETUP GUIDE =======\n\n"
            "  Step 1 (NOT DONE):  Start radar data collection\n\n"
            "  [Jetson Terminal 1]\n"
            "    python3 ~/radar_parser.py\n\n"
            "  Waiting for data file:\n"
            f"    {JSON_PATH}\n\n"
            "  Once radar_parser.py is running,\n"
            "  radar points will appear in the 3D panel\n"
            "  and Step 1 will turn blue."
        )
    if phase == PH_READY:
        return (
            "======= SETUP GUIDE =======\n\n"
            "  Step 1  (DONE):    Radar data is flowing  OK\n\n"
            "  Step 2  (TODO):    Collect normal baseline\n\n"
            "  >> Click  [ Start Baseline Collection ]  button\n"
            "     at the bottom-left of this window.\n\n"
            "  Then stand still in front of the radar\n"
            "  for ~30 seconds.\n\n"
            "  The system will learn what 'normal' looks like\n"
            "  and then start automatic anomaly detection."
        )
    if phase == PH_WARMUP:
        pct = int(warmup_count / max(1, N_WARMUP) * 100)
        bars_done  = int(pct / 5)
        bar_str    = '[' + '#' * bars_done + '-' * (20 - bars_done) + ']'
        return (
            "======= BASELINE COLLECTION =======\n\n"
            f"  Progress: {bar_str} {pct}%\n"
            f"  Frames:   {warmup_count} / {N_WARMUP}\n\n"
            "  >> STAND STILL in front of the radar.\n"
            "     Do not move until 100% is reached.\n\n"
            "  The system is recording your normal\n"
            "  radar signature to use as a reference.\n\n"
            "  After collection, click Start Training."
        )
    if phase == PH_WAIT_TRAIN:
        return (
            "======= BASELINE COMPLETE =======\n\n"
            f"  Collected {N_WARMUP} frames of normal data.  OK\n\n"
            "  Step 3  (TODO):    Train LSTM-AE model\n\n"
            "  >> Click  [ Start Training (Step 3) ]  button\n"
            "     at the bottom-left of this window.\n\n"
            "  Training takes ~20-30 seconds (on Jetson).\n"
            "  Stand still during training as well.\n\n"
            "  After training, LIVE detection starts automatically."
        )
    if phase == PH_TRAINING:
        return (
            "======= TRAINING IN PROGRESS =======\n\n"
            "  LSTM Autoencoder is learning (on Jetson)...\n\n"
            "  >> DO NOT MOVE  (~20-30 sec remaining)\n\n"
            "  The model is fitting to the collected\n"
            "  baseline data to detect anomalies.\n\n"
            "  Detection will start automatically\n"
            "  when training is complete."
        )
    # LIVE
    if sop:
        return '\n'.join(sop.split('\n')[:22])
    if rag_run:
        return (
            "======= RETRIEVING SOP =======\n\n"
            "  Searching safety manual (pgvector, 노트북)...\n"
            "  (retrieval-only, a few seconds)\n\n"
            "  Do not close this window."
        )
    if ev_active and ev_type:
        return (
            f"  ANOMALY DETECTED\n\n"
            f"  Type:  {EVENT_LABELS.get(ev_type, ev_type)}\n"
            f"  Zone:  {ev_zone}\n"
            f"  Conf:  {ev_conf:.0%}\n\n"
            "  Querying safety manual...\n"
            "  SOP guide will appear shortly."
        )
    return (
        "======= LIVE MONITORING =======\n\n"
        "  No anomaly detected.\n\n"
        "  System is monitoring in real-time.\n"
        "  SOP guide will appear automatically\n"
        "  when an anomaly is detected.\n\n"
        "  Use [ Reset Baseline ] button\n"
        "  to recollect normal baseline data."
    )

# ═══════════════════════════════════════════════════════════
# 8. RENDER UPDATE  (+ 상세 SOP 팝업)
# ═══════════════════════════════════════════════════════════
_sop_popup = {'fig': None, 'txt': None, 'ver': -1}

def _refresh_sop_popup():
    """detailed_sop_ver가 바뀌면 별도 팝업 창을 열거나 내용 갱신 (메인 스레드 전용)."""
    with _lock:
        ver  = state.get('detailed_sop_ver', 0)
        body = state.get('detailed_sop', '')
        ev_t = state.get('ev_type')
        ev_z = state.get('ev_zone', '')
    if ver == _sop_popup['ver'] or not body:
        return
    _sop_popup['ver'] = ver
    title   = f"Detailed SOP (Gemma) - {EVENT_LABELS.get(ev_t, ev_t)} / Zone {ev_z}"
    wrapped = '\n'.join(textwrap.fill(ln, width=52) for ln in body.split('\n'))
    content = f"[ {title} ]\n\n{wrapped}\n\n(이 창을 닫아도 감시는 계속됩니다)"
    try:
        f = _sop_popup['fig']
        if f is None or not plt.fignum_exists(f.number):
            f = plt.figure('Detailed SOP', figsize=(6.4, 8.2), facecolor='#0a0a1e')
            ax = f.add_axes([0, 0, 1, 1]); ax.axis('off')
            ax.add_patch(mpatches.Rectangle((0.02, 0.02), 0.96, 0.96,
                         transform=ax.transAxes, facecolor='#0d1530',
                         edgecolor='#ff6644', linewidth=2, zorder=0))
            _sop_popup['txt'] = ax.text(0.06, 0.95, '', transform=ax.transAxes,
                         va='top', ha='left', color='#e6f0ff', fontsize=10.5,
                         family=(KOREAN_FONT or 'DejaVu Sans'), zorder=1)
            _sop_popup['fig'] = f
        _sop_popup['txt'].set_text(content)
        _sop_popup['txt'].set_color('#ffdddd' if ev_t == 'fall_detected' else '#e6f0ff')
        f.canvas.draw_idle()
        try:
            f.show()
        except Exception:
            pass
    except Exception as e:
        print(f'[SOP-POPUP] error: {e}')


def update(_i):
    with _lock:
        connected  = state['connected'] and (time.time() - state['last_pkt_t'] < 5.0)
        phase      = state['phase']
        wc         = state['warmup_count']
        pts        = list(state['latest_pts'])
        n_real     = state['n_pts']
        cz_h       = list(state['cz_h'])
        sc_h       = list(state['sc_h'])
        ds_h       = list(state['ds_h'])
        ev_active  = state['ev_active']
        ev_type    = state['ev_type']
        ev_sev     = state['ev_sev']
        ev_conf    = state['ev_conf']
        ev_zone    = state['ev_zone']
        thr        = state['threshold']
        sop        = state['sop_text']
        rag_run    = state['rag_running']
        pre_alert  = state['pre_alert']
        scan_left  = state['scan_left']
        incidents  = list(state['incidents'])
        data_age   = state['data_age']
        data_ok    = state['data_ok']
        cache_st   = state.get('sop_cache_status', '')

    if not connected:
        data_ok = False
    xs_t  = list(range(len(cz_h)))
    stale = data_age > 5.0

    # ---- 3D scatter ----
    if pts:
        n  = n_real or len(pts)
        cz = cz_h[-1] if cz_h else 1.7
        _CAP = 28                                   # 표시 전용 상한 (탐지는 젯슨이 전체로 수행)
        draw_pts = pts[::max(1, len(pts) // _CAP)][:_CAP]
        xs = [p['x'] for p in draw_pts]
        zf = [p['z'] for p in draw_pts]                    # 바닥평면 z축
        hs = [CEILING_H - p['y'] for p in draw_pts]        # 높이 = CEILING_H - y
        cs = [p.get('i', 0.0) for p in draw_pts]
        scatter3d._offsets3d = (xs, zf, hs)
        scatter3d.set_array(np.array(cs, dtype=float))
    else:
        cz = cz_h[-1] if cz_h else 1.7
        n  = 0
        empty = np.empty(0)
        scatter3d._offsets3d = (empty, empty, empty)
        scatter3d.set_array(empty)

    # ---- Step guide / Progress ----
    update_step_guide(phase, data_ok)
    update_progress_bar(phase, wc)
    if scan_left is not None:   # STEP A: 빈 방 클러터 스캔 중 (보라색)
        prog_fill.set_width(max(0.02, 1.0 - scan_left / max(1.0, SCAN_SEC)))
        prog_fill.set_facecolor('#cc66ff')
        prog_label.set_text(f'STEP A: EMPTY-ROOM SCAN  {scan_left:.0f}s left'
                            f'  --  keep everyone OUT of view!')
        prog_label.set_color('#dd99ff')

    # ---- Status bar ----
    sev_col = SEV_COLOR.get(ev_sev, '#44ff88')
    if not connected:
        status_box.set_text(
            f'[NO LINK]  젯슨({JETSON_IP}) 패킷 없음.  '
            f'젯슨에서 jetson_sender.py 실행 / UDP {DATA_PORT},{CTRL_PORT} 방화벽 확인')
        status_box.set_color('#ff4444')
        status_box.get_bbox_patch().set_edgecolor('#ff4444')
    elif not data_ok:
        status_box.set_text(
            f'[WAITING]  No radar data file on Jetson.  '
            f'Run: python3 ~/radar_parser.py  |  Target: {JSON_PATH}')
        status_box.set_color('#ff8800')
        status_box.get_bbox_patch().set_edgecolor('#ff8800')
    elif stale:
        status_box.set_text(
            f'[NO DATA]  Radar data stopped (>5 sec).  Check radar_parser.py  |  Phase: {phase}')
        status_box.set_color('#ff8800')
        status_box.get_bbox_patch().set_edgecolor('#ff8800')
    elif phase == PH_READY:
        status_box.set_text(
            f'[STEP 2]  Radar data OK (H={cz:.2f}m  pts={n})  '
            f'-- Click  "Start Baseline Collection"  to begin')
        status_box.set_color('#00ccff')
        status_box.get_bbox_patch().set_edgecolor('#00ccff')
    elif phase == PH_WARMUP:
        pct = int(wc / max(1, N_WARMUP) * 100)
        status_box.set_text(
            f'[STEP 2: COLLECTING]  {wc} / {N_WARMUP} frames  ({pct}%)  '
            f'-- Stand still  |  H={cz:.2f}m  pts={n}')
        status_box.set_color('#ffcc00')
        status_box.get_bbox_patch().set_edgecolor('#ffcc00')
    elif phase == PH_WAIT_TRAIN:
        status_box.set_text(
            f'[STEP 3 READY]  Baseline complete!  Click  "Start Training"  button  |  H={cz:.2f}m  pts={n}')
        status_box.set_color('#ffcc00')
        status_box.get_bbox_patch().set_edgecolor('#ffcc00')
    elif phase == PH_TRAINING:
        status_box.set_text(
            f'[STEP 3: TRAINING]  LSTM-AE fitting on Jetson...  Do not move  |  H={cz:.2f}m  pts={n}')
        status_box.set_color('#ff8800')
        status_box.get_bbox_patch().set_edgecolor('#ff8800')
    else:
        if ev_active and ev_type:
            lbl = EVENT_LABELS.get(ev_type, ev_type)
            status_box.set_text(
                f'[ALERT]  {lbl}  |  Zone {ev_zone}  conf={ev_conf:.0%}  '
                f'|  H={cz:.2f}m  pts={n}')
        else:
            status_box.set_text(
                f'[STEP 4: LIVE - NORMAL]  H={cz:.2f}m  pts={n}  '
                f'|  score={(sc_h[-1] if sc_h else 0):.5f}  thr={thr:.5f}  |  {cache_st}')
        status_box.set_color(sev_col)
        status_box.get_bbox_patch().set_edgecolor(sev_col)

    # ---- Height timeseries ----
    line_z.set_data(xs_t, cz_h)
    line_z.set_color('#ff4444' if (ev_active and ev_type == 'fall_detected') else '#00ccff')

    # ---- Motion / Vibration (dop_std) ----
    line_sc.set_data(list(range(len(ds_h))), ds_h)
    line_sc.set_color(sev_col)
    ax_sc.set_ylim(0, max(2.0, float(np.max(ds_h)) * 1.2 + 1e-7 if ds_h else 2.0))

    # ---- Incident history ----
    if incidents:
        inc_lines = []
        for inc in incidents[-8:]:
            slbl = EVENT_SHORT.get(inc['type'], inc['type'])
            if inc.get('resolved'):
                inc_lines.append(f"[{inc['detected']}] {slbl}  Zone {inc['zone']}")
                inc_lines.append(f"      resolved {inc['resolved']}")
            else:
                inc_lines.append(f"[{inc['detected']}] {slbl}  Zone {inc['zone']}  << ACTIVE")
        log_text.set_text('\n'.join(inc_lines))
    else:
        log_text.set_text('No incidents yet.\nAlarms will be recorded here.')

    # ---- SOP / Guide panel ----
    guide = make_guide_text(phase, data_ok, ev_active, ev_type,
                            ev_zone, ev_conf, rag_run, sop, wc, connected)
    sop_text.set_text(guide)
    if ev_active and ev_type:
        sop_text.set_color('#ffcccc')
    elif phase == PH_LIVE:
        sop_text.set_color('#ccddee')
    else:
        sop_text.set_color('#aabbcc')

    # ---- Alarm / PRE-ALERT banner ----
    if ev_active and ev_type:
        lbl = EVENT_LABELS.get(ev_type, ev_type)
        alarm_banner.set_text(f'[ ! ]  ACTIVE ALARM  Zone {ev_zone}: {lbl}   ->  press [Event Resolved]')
        alarm_banner.set_color('white')
        alarm_banner.get_bbox_patch().set_facecolor('#3a0000')
        alarm_banner.get_bbox_patch().set_edgecolor('#ff3333')
        alarm_banner.set_visible(True)
    elif pre_alert:
        alarm_banner.set_text(f'[ ~ ]  {pre_alert}')
        alarm_banner.set_color('#ffdd66')
        alarm_banner.get_bbox_patch().set_facecolor('#3a2a00')
        alarm_banner.get_bbox_patch().set_edgecolor('#ffcc00')
        alarm_banner.set_visible(True)
    else:
        alarm_banner.set_visible(False)

    _refresh_sop_popup()

    if '_refresh_btn_label' in globals():
        _refresh_btn_label()
    return scatter3d, line_z, line_sc, status_box, log_text, sop_text, prog_fill, prog_label

# ═══════════════════════════════════════════════════════════
# 9. MAIN
# ═══════════════════════════════════════════════════════════
if __name__ == '__main__':
    print('=' * 65)
    print('  Radar-Guard v3 | LAPTOP VIEWER (display + RAG/LLM)')
    print('=' * 65)
    print(f'  Jetson     : {JETSON_IP}   (제어/HELLO -> UDP {CTRL_PORT})')
    print(f'  Listening  : 0.0.0.0:{DATA_PORT}  (젯슨 데이터)')
    print(f'  DB (local) : {CONN_STR}')
    print(f'  RAG        : {"ENABLED (LangChain)" if RAG_OK else "DISABLED (pip install langchain-ollama langchain-community psycopg2-binary)"}')
    print(f'  LLM        : {LLM_MODEL} @ {OLLAMA_URL}')
    print()
    print('  노트북 사전 준비(RAG/LLM 사용 시):')
    print('    ollama serve  /  ollama pull gemma2:2b  /  ollama pull nomic-embed-text')
    print('    docker start radar-guard-db')
    print()
    print('  젯슨: python3 ~/radar_parser.py  +  python3 ~/jetson_sender.py')
    print('=' * 65)
    print()

    # ── Buttons ──────────────────────────────────────────
    ax_btn_start = fig.add_axes([0.37, 0.025, 0.26, 0.048])
    btn_start = Button(ax_btn_start,
                       'START Baseline Collection  (Step 2)',
                       color='#0a1a2a', hovercolor='#0d2a4a')
    btn_start.label.set_color('#00ccff')
    btn_start.label.set_fontsize(9)
    btn_start.label.set_fontweight('bold')

    def do_start(_event=None):
        with _lock:
            phase = state['phase']
        ts = datetime.now().strftime('%H:%M:%S')
        if phase == PH_READY:
            send_cmd('start')
            print(f'[{ts}] [BTN] Start Baseline -> Jetson (EMPTY ROOM first!)')
        elif phase == PH_WAIT_TRAIN:
            send_cmd('train')
            print(f'[{ts}] [BTN] Start Training -> Jetson (stand still)')
        elif phase == PH_WARMUP:
            print('Already collecting baseline...')
        elif phase == PH_TRAINING:
            print('Already training...')
        else:
            print('System is LIVE. Use Reset to recollect baseline.')

    def _refresh_btn_label(_i=None):
        with _lock:
            phase = state['phase']
            conn  = state['connected'] and (time.time() - state['last_pkt_t'] < 5.0)
        if not conn:
            btn_start.label.set_text('waiting for Jetson...')
            btn_start.label.set_color('#888888')
        elif phase == PH_READY:
            btn_start.label.set_text('START Baseline Collection  (Step 2)')
            btn_start.label.set_color('#00ccff')
        elif phase == PH_WARMUP:
            btn_start.label.set_text('Collecting baseline...  (stand still)')
            btn_start.label.set_color('#888888')
        elif phase == PH_WAIT_TRAIN:
            btn_start.label.set_text('START Training  (Step 3)  -- click here!')
            btn_start.label.set_color('#ffdd00')
        elif phase == PH_TRAINING:
            btn_start.label.set_text('Training in progress...  (stand still)')
            btn_start.label.set_color('#888888')
        else:
            btn_start.label.set_text('LIVE  -- Use Reset to recollect')
            btn_start.label.set_color('#44ff88')

    btn_start.on_clicked(do_start)

    ax_btn_reset = fig.add_axes([0.67, 0.025, 0.26, 0.048])
    btn_reset = Button(ax_btn_reset,
                       'RESET Baseline  (recollect normal data)',
                       color='#1a0a0a', hovercolor='#3a0a0a')
    btn_reset.label.set_color('#ff8866')
    btn_reset.label.set_fontsize(9)

    def do_reset(_event=None):
        send_cmd('reset')
        with _lock:
            state.update({'sop_text': '', 'instant_sop': '', 'rag_running': False})
        print(f'[{datetime.now().strftime("%H:%M:%S")}] [BTN] Reset -> Jetson')

    btn_reset.on_clicked(do_reset)

    ax_btn_resolve = fig.add_axes([0.06, 0.025, 0.26, 0.048])
    btn_resolve = Button(ax_btn_resolve,
                         'EVENT RESOLVED  (clear latched alarm)',
                         color='#0a1e0a', hovercolor='#0d3a1a')
    btn_resolve.label.set_color('#66ff99')
    btn_resolve.label.set_fontsize(9)
    btn_resolve.label.set_fontweight('bold')

    def do_resolve(_event=None):
        ts = datetime.now().strftime('%H:%M:%S')
        with _lock:
            active = state['ev_active']
        send_cmd('resolve')
        print(f'[{ts}] [BTN] Event Resolved -> Jetson'
              + ('' if active else ' (no active alarm)'))

    btn_resolve.on_clicked(do_resolve)

    # ── Threads ───────────────────────────────────────────
    threading.Thread(target=udp_receiver, daemon=True).start()
    threading.Thread(target=hello_loop,   daemon=True).start()
    if DETAILED_SOP_POPUP:
        threading.Thread(target=_prewarm_gemma, daemon=True).start()

    add_log(f'Viewer started -- waiting for Jetson {JETSON_IP}')

    # ── Manual render loop (FuncAnimation 대신: 느려도 얼지 않음) ──
    update_sec = UPDATE_MS / 1000.0
    plt.show(block=False)
    frame_i = 0
    t_prev  = time.time()
    while plt.fignum_exists(fig.number):
        try:
            update(frame_i)
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
        except Exception as e:
            print(f'[UPD-ERR] frame={frame_i}: {e}')
        if DEBUG_TIMING:
            now = time.time()
            print(f'[UPD] frame={frame_i}  loop_dt={now - t_prev:.2f}s')
            t_prev = now
        frame_i += 1
        time.sleep(update_sec)
    print('[EXIT] window closed -- bye')
