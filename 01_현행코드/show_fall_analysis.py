# -*- coding: utf-8 -*-
"""오늘 수집한 사람별 낙상 점수와 핵심 피처를 터미널에 표시한다.

실행 환경: 젯슨 터미널
  python3 ~/show_fall_analysis.py ~/events_fall_5people_20260813_1.jsonl
"""
import json
import os
import sys

import joblib
import numpy as np
from sklearn.model_selection import LeaveOneGroupOut

from train_fall_safety import extract, load, make_model


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser('~/events_fall_5people_20260813_1.jsonl')
    ck = joblib.load(os.path.expanduser('~/fall_safety_classifier.joblib'))
    threshold = float(ck['threshold'])
    samples = load(path, '0813')
    x = np.asarray([r[0] for r in samples]); y = np.asarray([r[1] for r in samples])
    groups = np.asarray([r[2] for r in samples]); scores = np.zeros(len(y))
    for train, test in LeaveOneGroupOut().split(x, y, groups):
        model = make_model().fit(x[train], y[train])
        scores[test] = model.predict_proba(x[test])[:, 1]
    rows = [json.loads(line) for line in open(path, encoding='utf-8')]
    print('=' * 112)
    print(f'오늘 5명 낙상 분석 | 운영점 {threshold:.2f} | 점수는 확률이 아닌 안전 우선 판정 점수')
    print('=' * 112)
    print('사람  시각      판정  점수   ds_max ds_mean broad h_drop horiz')
    print('-' * 112)
    summary = {}
    today_fall_scores = {}
    for sample, score in zip(samples, scores):
        if sample[3] == '0813' and sample[1]:
            today_fall_scores.setdefault(sample[2], []).append(float(score))
    used = {person: 0 for person in today_fall_scores}
    for row in rows:
        if row.get('label') != 'fall':
            continue
        feat = extract(row)
        score = today_fall_scores[row['person']][used[row['person']]]
        used[row['person']] += 1
        hit = score >= threshold
        summary.setdefault(row['person'], [0, 0])
        summary[row['person']][0] += int(hit); summary[row['person']][1] += 1
        print(f"{row['person']:^4}  {row['ts'][11:19]}  "
              f"{'FALL' if hit else 'MISS':^5} {score:5.3f}  {feat[0]:6.3f} "
              f"{feat[1]:7.3f} {int(feat[5]):5d} {feat[9]:6.3f} {feat[13]:5.3f}")
    print('-' * 112)
    total_hit = total = 0
    for person in sorted(summary):
        hit, count = summary[person]; total_hit += hit; total += count
        print(f'{person}: {hit}/{count} ({100*hit/count:.1f}%)')
    print(f'오늘 합계: {total_hit}/{total} ({100*total_hit/total:.1f}%)')
    print('\n창을 닫으려면 Ctrl+C 또는 창 닫기')


if __name__ == '__main__':
    main()
