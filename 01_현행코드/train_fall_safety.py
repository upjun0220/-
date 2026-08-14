# -*- coding: utf-8 -*-
"""두 수집 세션을 합쳐 사람 단위 LOSO로 낙상 RandomForest를 학습한다.

실행 환경: 내 PC PowerShell 또는 젯슨 터미널
  python train_fall_safety.py --data <8/13.jsonl> <8/14.jsonl> --output fall_classifier.joblib

운영점은 LOSO 예측에서 wave 오탐이 0건인 가장 낮은 임계값이다.
fast_sit은 실제 표본이 없고 사용자 결정으로 다음 지시까지 제외한다.
"""
import argparse
import hashlib
import json
import os

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import LeaveOneGroupOut

FEATURES = ['ds_max', 'ds_mean', 'ds_first', 'ds_last', 'impulse', 'ds_broad',
            'settle_ratio', 'dop_peaks', 'zvel_sign_changes', 'h_drop',
            'end_low_ratio', 'net_drop_ratio', 'max_drop_ratio', 'horiz_range',
            'horiz_disp', 'n_peak_ratio', 'n_cv', 'n_trend', 'mean_dop_abs']
USED_LABELS = {'fall', 'crouch', 'wave', 'walk', 'normal'}


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


def load(paths):
    out = []
    for path in paths:
        source = os.path.basename(path)
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                row = json.loads(line)
                label = row['label']
                # 8/13 A의 fast_sit 6건은 현장 메모상 실제 crouch였다.
                if ('20260813' in source or '0813' in source) \
                        and row.get('person') == 'A' and label == 'fast_sit':
                    label = 'crouch'
                if label not in USED_LABELS:
                    continue
                frames = row.get('frames') or []
                if len(frames) < 4 or frames[-1]['t'] - frames[0]['t'] > 2.5:
                    continue
                feat = extract(row)
                if feat is not None:
                    out.append((feat, label == 'fall', row['person'], label, source))
    return out


def make_model():
    return RandomForestClassifier(n_estimators=300, min_samples_leaf=8,
                                  max_features='sqrt', class_weight='balanced',
                                  random_state=42, n_jobs=-1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', nargs='+', required=True)
    ap.add_argument('--output', default='fall_classifier.joblib')
    args = ap.parse_args()

    rows = load(args.data)
    x = np.asarray([r[0] for r in rows]); y = np.asarray([r[1] for r in rows])
    groups = np.asarray([r[2] for r in rows]); labels = np.asarray([r[3] for r in rows])
    scores = np.zeros(len(y))
    for train, test in LeaveOneGroupOut().split(x, y, groups):
        model = make_model().fit(x[train], y[train])
        fall_col = list(model.classes_).index(True)
        scores[test] = model.predict_proba(x[test])[:, fall_col]

    wave = (~y) & (labels == 'wave')
    if not wave.any():
        raise RuntimeError('wave 표본이 없어 오탐 0건 운영점을 선택할 수 없습니다.')
    threshold = float(np.nextafter(scores[wave].max(), 1.0))
    pred = scores >= threshold
    metrics = {
        'tp': int((pred & y).sum()), 'fn': int((~pred & y).sum()),
        'fp': int((pred & ~y).sum()), 'tn': int((~pred & ~y).sum()),
        'wave_fp': int((pred & wave).sum()),
        'per_label': {label: {'positive': int((pred & (labels == label)).sum()),
                              'total': int((labels == label).sum())}
                      for label in sorted(set(labels))},
        'per_person': {person: {'fall_hit': int((pred & y & (groups == person)).sum()),
                                'fall_total': int((y & (groups == person)).sum()),
                                'false_positive': int((pred & ~y & (groups == person)).sum())}
                       for person in sorted(set(groups))},
    }
    # 기존 sender의 RF veto 경로도 안전하게 읽을 수 있도록 최종 클래스명은 문자열로 저장한다.
    final_y = np.where(y, 'fall', 'normal')
    model = make_model().fit(x, final_y)
    hashes = {}
    for path in args.data:
        with open(path, 'rb') as fh:
            hashes[os.path.basename(path)] = hashlib.sha256(fh.read()).hexdigest()
    joblib.dump({'model': model, 'features': FEATURES, 'threshold': threshold,
                 'threshold_policy': 'LOSO max recall with wave FP=0',
                 'excluded_labels': ['fast_sit'], 'metrics': metrics,
                 'samples': {'fall': int(y.sum()), 'negative': int((~y).sum())},
                 'source_sha256': hashes}, args.output)
    print(f'threshold={threshold:.6f} TP={metrics["tp"]} FN={metrics["fn"]} '
          f'FP={metrics["fp"]} TN={metrics["tn"]} wave_FP={metrics["wave_fp"]}')
    print(json.dumps(metrics['per_person'], ensure_ascii=False))
    print(args.output)


if __name__ == '__main__':
    main()
