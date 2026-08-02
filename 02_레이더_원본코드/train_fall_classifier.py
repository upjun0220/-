# -*- coding: utf-8 -*-
"""
Radar-Guard 낙상/동작 분류기 오프라인 학습 (PC, scikit-learn)
================================================================
목적: 규칙(magic number) 대신 데이터로 fall vs wave(팔흔들기) 등을 분류.
      임계값으론 안 갈리던 fall vs wave를 다피처 트리모델이 가르는지 검증.

입력 : events_collect_new.jsonl  (radar_collect.py 산출, 라벨별 샘플)
출력 : - 콘솔: 교차검증 정확도, 혼동행렬, 피처 중요도, fall-vs-wave 집중분석
       - fall_classifier.joblib  (학습된 모델 + 피처 순서)

실행 : [PC]  python train_fall_classifier.py
사전 : pip install scikit-learn joblib numpy

주의: 피처는 '라이브 9차원 창에서 그대로 재현 가능한 것'만 사용
      (spread_xz / zacc 제외 -> 오프라인 학습 = 라이브 추론 완전 일치).
"""
import json, os
import numpy as np
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
# [7/31 폴더 정리] 데이터가 03_데이터/이벤트_학습용/ 으로 이동함.
#   환경변수 RADAR_DATA 로 다른 파일을 지정할 수 있다.
ROOT = os.path.dirname(HERE)
DATA = os.environ.get(
    'RADAR_DATA', os.path.join(ROOT, '03_데이터', '이벤트_학습용',
                               'events_collect_new.jsonl'))
CEIL = 2.30

FEATURE_NAMES = [
    'ds_max', 'ds_mean', 'ds_first', 'ds_last', 'impulse', 'ds_broad',
    'settle_ratio', 'dop_peaks', 'zvel_sign_changes',
    # [7/8 환경불변] 절대높이 min_h/final_h/start_h -> cy 상대비율(천장높이 무관)
    'h_drop', 'end_low_ratio', 'net_drop_ratio', 'max_drop_ratio',
    'horiz_range', 'horiz_disp',
    # [7/8 환경불변] 절대 포인트수 n_mean/p75/max -> 비율(거리/게인 무관)
    'n_peak_ratio', 'n_cv', 'n_trend', 'mean_dop_abs',
]

def _peaks(ds, thr=0.6):
    p = 0
    for i in range(1, len(ds) - 1):
        if ds[i] >= thr and ds[i] >= ds[i-1] and ds[i] > ds[i+1]:
            p += 1
    return p

def extract(sample):
    """샘플(라벨 윈도우) -> 19차원 피처. 라이브 classify에서 동일하게 재현할 것."""
    fr = [f for f in sample['frames'] if f['n'] > 0]
    if len(fr) < 4:
        return None
    cx = np.array([f['cx'] for f in fr]); cy = np.array([f['cy'] for f in fr])
    cz = np.array([f['cz'] for f in fr]); ds = np.array([f['dop_std'] for f in fr])
    n  = np.array([f['n'] for f in fr], dtype=float)
    dop = np.array([f.get('dop_mean', 0.0) for f in fr])
    half = max(1, len(ds) // 2)
    ds_first = ds[:half].mean(); ds_last = ds[half:].mean()
    zvel = np.zeros(len(fr))
    for i in range(1, len(fr)):
        zvel[i] = cy[i-1] - cy[i]            # prev_cy - cy = 수직속도(상승 +)
    zv_valid = zvel[np.abs(zvel) > 0.05]
    zvel_sc = int(np.sum(np.diff(np.sign(zv_valid)) != 0)) if len(zv_valid) > 2 else 0
    pk = int(np.argmax(ds))
    # [7/8 환경불변] cy(천장~사람 거리)만으로 상대화 -> 천장높이/설치 오차 무관.
    #   cy: 설 때 작고 쓰러지면 큼. span(수직범위)으로 정규화해 절대위치 의존 제거.
    span = float(cy.max() - cy.min()) + 1e-6
    cy_s = float(cy[:3].mean()); cy_e = float(cy[-3:].mean())
    end_low_ratio  = (cy_e - float(cy.min())) / span    # 종료 자세 (0=선상태, 1=바닥)
    net_drop_ratio = (cy_e - cy_s) / span               # 순 하강 (낙상 +, 팔흔들기 ~0)
    max_drop_ratio = (float(cy.max()) - cy_s) / span    # 최대 하강 깊이
    # [7/8 환경불변] 절대 포인트수 대신 비율 -> 거리/센서게인 무관.
    nm = float(n.mean()) + 1e-6
    nh = max(1, len(n) // 2)
    n_peak_ratio = float(n.max()) / nm                              # 버스트 정도
    n_cv         = float(n.std()) / nm                              # 변동계수
    n_trend      = (float(n[nh:].mean()) - float(n[:nh].mean())) / nm  # 증감 추세
    return [
        float(ds.max()), float(ds.mean()), float(ds_first), float(ds_last),
        float(ds.max() / max(0.15, ds_first)), int((ds >= 0.8).sum()),
        float(ds_last / (ds.max() + 1e-6)), _peaks(ds), zvel_sc,
        float(cy.max() - cy.min()),
        end_low_ratio, net_drop_ratio, max_drop_ratio,
        float(np.hypot(cx.max()-cx.min(), cz.max()-cz.min())),
        float(np.hypot(cx[pk:].mean()-cx[:max(1,pk)].mean(), cz[pk:].mean()-cz[:max(1,pk)].mean())),
        n_peak_ratio, n_cv, n_trend,
        float(np.abs(dop).mean()),
    ]

# 데이터 로드
X, y = [], []
for line in open(DATA, encoding='utf-8'):
    line = line.strip()
    if not line:
        continue
    d = json.loads(line)
    v = extract(d)
    if v is None:
        continue
    X.append(v); y.append(d['label'])
X = np.array(X); y = np.array(y)
print("로드: %d개 샘플, 클래스분포 = %s" % (len(y), dict(Counter(y))))
print("피처 %d개: %s\n" % (len(FEATURE_NAMES), FEATURE_NAMES))

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_predict, LeaveOneOut
from sklearn.metrics import confusion_matrix, classification_report

rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=2,
                            class_weight='balanced', random_state=42)

# [A] 전체 다중클래스 5-fold CV
print("=" * 60)
print("[A] 전체 다중클래스 - 5-fold 교차검증 (RandomForest)")
print("=" * 60)
yp = cross_val_predict(rf, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=42))
labels = sorted(set(y))
cm = confusion_matrix(y, yp, labels=labels)
print("혼동행렬 (행=실제, 열=예측):")
print("      " + " ".join("%7s" % l[:6] for l in labels))
for i, l in enumerate(labels):
    print("%6s " % l[:6] + " ".join("%7d" % cm[i][j] for j in range(len(labels))))
print("\n" + classification_report(y, yp, labels=labels, zero_division=0))

# [B] fall vs wave 이진 LOO (데모 핵심)
print("=" * 60)
print("[B] fall vs wave 이진 - Leave-One-Out (핵심: 갈리는가?)")
print("=" * 60)
mask = np.isin(y, ['fall', 'wave'])
Xb, yb = X[mask], y[mask]
if len(set(yb)) == 2:
    ypb = cross_val_predict(rf, Xb, yb, cv=LeaveOneOut())
    cmb = confusion_matrix(yb, ypb, labels=['fall', 'wave'])
    print("LOO 정확도: %.1f%%  (fall=%d, wave=%d)" %
          ((ypb == yb).mean()*100, int((yb=='fall').sum()), int((yb=='wave').sum())))
    print("혼동행렬 [fall,wave]:\n%s" % cmb)
    print("  fall 재현율: %d/%d 맞춤 (놓친 낙상 = %d)" % (cmb[0,0], cmb[0].sum(), cmb[0,1]))
    print("  wave 배제:   %d/%d 정상처리 (오탐 = %d)" % (cmb[1,1], cmb[1].sum(), cmb[1,0]))

# [C] 피처 중요도
print("\n" + "=" * 60)
print("[C] 피처 중요도 (fall vs wave)")
print("=" * 60)
rf.fit(Xb, yb)
for name, v in sorted(zip(FEATURE_NAMES, rf.feature_importances_), key=lambda z: -z[1])[:12]:
    print("  %-18s %.3f %s" % (name, v, '#' * int(v * 100)))

# [D] 저장
import joblib
rf_full = RandomForestClassifier(n_estimators=300, min_samples_leaf=2,
                                 class_weight='balanced', random_state=42).fit(X, y)
joblib.dump({'model': rf_full, 'features': FEATURE_NAMES, 'ceiling_h': CEIL},
            os.path.join(HERE, 'fall_classifier.joblib'))
print("\n저장: fall_classifier.joblib  (라이브 적용 시 동일 19피처로 predict)")
