# -*- coding: utf-8 -*-
"""오늘 A~E 실측으로 안전 우선 낙상 모델을 만든다.

실행 환경: PC PowerShell
  python 01_현행코드\train_fall_safety.py --today <오늘.jsonl>
"""
import argparse
import hashlib
import json
import os

import joblib
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut

FEATURES = ['ds_max', 'ds_mean', 'ds_first', 'ds_last', 'impulse', 'ds_broad',
            'settle_ratio', 'dop_peaks', 'zvel_sign_changes', 'h_drop',
            'end_low_ratio', 'net_drop_ratio', 'max_drop_ratio', 'horiz_range',
            'horiz_disp', 'n_peak_ratio', 'n_cv', 'n_trend', 'mean_dop_abs']
FN_COST = 10


def extract(sample):
    fr = [f for f in sample['frames'] if f['n'] > 0]
    if len(fr) < 4:
        return None
    cx = np.array([f['cx'] for f in fr]); cy = np.array([f['cy'] for f in fr])
    cz = np.array([f['cz'] for f in fr]); ds = np.array([f['dop_std'] for f in fr])
    n = np.array([f['n'] for f in fr], dtype=float)
    dop = np.array([f.get('dop_mean', 0.0) for f in fr])
    half = max(1, len(ds) // 2); first = ds[:half].mean(); last = ds[half:].mean()
    zvel = np.zeros(len(fr)); zvel[1:] = cy[:-1] - cy[1:]
    valid = zvel[np.abs(zvel) > 0.05]
    zsc = int(np.sum(np.diff(np.sign(valid)) != 0)) if len(valid) > 2 else 0
    peaks = sum(ds[i] >= 0.6 and ds[i] >= ds[i-1] and ds[i] > ds[i+1]
                for i in range(1, len(ds) - 1))
    pk = int(np.argmax(ds)); span = float(cy.max() - cy.min()) + 1e-6
    start = float(cy[:3].mean()); end = float(cy[-3:].mean())
    nm = float(n.mean()) + 1e-6; nh = max(1, len(n) // 2)
    return [float(ds.max()), float(ds.mean()), float(first), float(last),
            float(ds.max() / max(0.15, first)), int((ds >= 0.8).sum()),
            float(last / (ds.max() + 1e-6)), peaks, zsc, float(cy.max()-cy.min()),
            (end-float(cy.min()))/span, (end-start)/span,
            (float(cy.max())-start)/span,
            float(np.hypot(cx.max()-cx.min(), cz.max()-cz.min())),
            float(np.hypot(cx[pk:].mean()-cx[:max(1, pk)].mean(),
                           cz[pk:].mean()-cz[:max(1, pk)].mean())),
            float(n.max())/nm, float(n.std())/nm,
            (float(n[nh:].mean())-float(n[:nh].mean()))/nm,
            float(np.abs(dop).mean())]


def load(path, day):
    out = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            row = json.loads(line)
            if day == '0812' and row.get('person') not in 'ABC':
                continue
            label = row['label']
            if day == '0813' and row['person'] == 'A' and label == 'fast_sit':
                label = 'crouch'  # 현장 메모: 의자 없이 crouch를 잘못 눌렀음
            if label not in {'fall', 'crouch', 'wave', 'walk', 'normal'}:
                continue
            frames = row.get('frames') or []
            if len(frames) < 4 or frames[-1]['t'] - frames[0]['t'] > 2.5:
                continue
            feat = extract(row)
            if feat is not None:
                out.append((feat, label == 'fall', row['person'], day))
    return out


def make_model():
    return ExtraTreesClassifier(n_estimators=500, min_samples_leaf=3,
                                max_features=0.7, class_weight={0: 1, 1: 2},
                                random_state=2, n_jobs=-1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--today', required=True)
    ap.add_argument('--output', default=os.path.join(os.path.dirname(__file__),
                                                     'fall_safety_classifier.joblib'))
    args = ap.parse_args()
    rows = load(args.today, '0813')
    x = np.asarray([r[0] for r in rows]); y = np.asarray([r[1] for r in rows])
    groups = np.asarray([r[2] for r in rows])  # 같은 사람은 날짜가 달라도 같은 fold
    prob = np.zeros(len(y)); logo = LeaveOneGroupOut()
    for train, test in logo.split(x, y, groups):
        model = make_model().fit(x[train], y[train])
        prob[test] = model.predict_proba(x[test])[:, 1]
    choices = []
    for threshold in np.arange(0.20, 0.61, 0.01):
        tn, fp, fn, tp = confusion_matrix(y, prob >= threshold, labels=[0, 1]).ravel()
        choices.append((FN_COST*fn + fp, fn, fp, -tp, threshold, tp, tn))
    cost, fn, fp, _, threshold, tp, tn = min(choices)
    model = make_model().fit(x, y)
    hashes = {}
    for path in (args.today,):
        with open(path, 'rb') as fh:
            hashes[os.path.basename(path)] = hashlib.sha256(fh.read()).hexdigest()
    joblib.dump({'model': model, 'features': FEATURES, 'threshold': float(threshold),
                 'fn_cost': FN_COST, 'metrics': {'tp': int(tp), 'fn': int(fn),
                 'fp': int(fp), 'tn': int(tn), 'cost': int(cost)},
                 'samples': {'fall': int(y.sum()), 'negative': int((~y).sum())},
                 'source_sha256': hashes}, args.output)
    print(f'threshold={threshold:.2f} TP={tp} FN={fn} FP={fp} TN={tn} cost={cost}')
    print(args.output)


if __name__ == '__main__':
    main()
