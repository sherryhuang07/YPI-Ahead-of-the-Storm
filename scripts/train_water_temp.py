"""Train the water temperature model, seal 2022-2025 test predictions, then score them.

Fit (normal cycle and ridge weights) uses target days through 2018; method choice and bands
use 2019-2021 targets issued after 2018; test predictions are for 2022-2025 targets issued
after 2021. Predictions are written and hashed before any test observation is read for scoring.
"""
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import numpy as np
from statewide_common import ROOT, save, log
from water_temp_model import POLICY, fit_normal, normal, features, design, fit, predict

WT = ROOT / 'data/water-temp'; OUT = ROOT / 'outputs/water-temp'


def load():
    by = defaultdict(dict)
    for r in csv.DictReader((WT / 'daily.csv').open(encoding='utf-8')): by[r['station']][r['date']] = float(r['water_temp_c'])
    out = {}
    for s, v in by.items():
        first, last = date.fromisoformat(min(v)), date.fromisoformat(max(v))
        days = [str(first + timedelta(days=k)) for k in range((last - first).days + 1)]
        out[s] = (days, np.array([v.get(d, np.nan) for d in days]))
    return out


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    data = load(); p = POLICY
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'); run = OUT / 'runs' / stamp; run.mkdir(parents=True)
    models = {}; preds = []; excluded = []
    for s, (days, t) in data.items():
        tr = [i for i, d in enumerate(days) if d <= p['train_end'] and np.isfinite(t[i])]
        if len(tr) < p['min_train']: excluded.append(dict(station=s, reason='Under %d training days' % p['min_train'])); continue
        coef = fit_normal([days[i] for i in tr], t[tr]); nv = normal(coef, days); models[s] = dict(normal=coef.tolist(), leads={})
        feats = {i: features(t, i, nv, days) for i in range(len(days))}
        for L in p['leads']:
            groups = defaultdict(list)
            for i, f in feats.items():
                j = i + L
                if f is None or j >= len(days): continue
                issue = days[i + p['issue_offset_days']]; target = days[j]
                g = ('train' if target <= p['train_end'] else
                     'cal' if p['calibration'][0] <= target <= p['calibration'][1] and issue > p['train_end'] else
                     'test' if p['test'][0] <= target <= p['test'][1] and issue > p['calibration'][1] else None)
                if g is None or (g != 'test' and not np.isfinite(t[j])): continue
                groups[g].append((i, j, design(f, target)))
            if len(groups['train']) < p['min_train'] or len(groups['cal']) < p['min_calibration']:
                excluded.append(dict(station=s, lead=L, reason='Too few complete examples')); continue
            m = fit(np.array([g[2] for g in groups['train']]), np.array([t[g[1]] - nv[g[1]] for g in groups['train']]), p['ridge_penalty'])
            cx = np.array([g[2] for g in groups['cal']]); cy = np.array([t[g[1]] for g in groups['cal']])
            cp = predict(m, cx) + nv[[g[1] for g in groups['cal']]]; base = np.array([t[g[0]] for g in groups['cal']])
            method = 'ridge' if np.mean(abs(cp - cy)) < np.mean(abs(base - cy)) else 'persistence'
            chosen = cp if method == 'ridge' else base; radius = float(np.quantile(abs(chosen - cy), 0.9))
            models[s]['leads'][str(L)] = dict(model=m, method=method, radius=radius, calibration_mae=float(np.mean(abs(chosen - cy))),
                                              train=len(groups['train']), calibration=len(groups['cal']))
            if groups['test']:
                tx = np.array([g[2] for g in groups['test']]); idx = [g[1] for g in groups['test']]
                tp = predict(m, tx) + nv[idx] if method == 'ridge' else np.array([t[g[0]] for g in groups['test']])
                for (i, j, _), v in zip(groups['test'], tp):
                    preds.append(dict(station=s, last_input=days[i], target=days[j], lead=L, forecast_day=L - 1, prediction=float(v),
                                      persistence=float(t[i]), normal=float(nv[j]), lower=float(v - radius), upper=float(v + radius), method=method))
    with (run / 'sealed-test-predictions.json').open('x', encoding='utf-8') as f: json.dump(preds, f)
    with (run / 'model.json').open('x', encoding='utf-8') as f: json.dump(models, f)
    with (run / 'policy.json').open('x', encoding='utf-8') as f: json.dump(POLICY, f)
    files = {n: sha(run / n) for n in ('sealed-test-predictions.json', 'model.json', 'policy.json')}
    save(run / 'manifest.json', dict(created_at=datetime.now(timezone.utc).isoformat(), files=files, daily_sha256=sha(WT / 'daily.csv'), excluded=excluded))
    # ---- scoring: only after the sealed files exist and are re-verified ----
    for n, h in files.items():
        if sha(run / n) != h: raise ValueError('Sealed file changed: ' + n)
    by = defaultdict(list); by_station = defaultdict(list)
    for q in preds:
        days, t = data[q['station']]; j = days.index(q['target']) if q['target'] in days else None
        y = t[j] if j is not None else np.nan
        if not np.isfinite(y): continue
        e = q['prediction'] - y
        by[q['forecast_day']].append((abs(e), abs(q['persistence'] - y), abs(q['normal'] - y), e, q['lower'] <= y <= q['upper']))
        by_station[(q['station'], q['forecast_day'])].append((abs(e), abs(q['persistence'] - y)))
    score = {}
    for h, v in sorted(by.items()):
        a = np.array(v, dtype=float)
        score[str(h)] = dict(cases=len(v), mae_c=float(a[:, 0].mean()), persistence_mae_c=float(a[:, 1].mean()), normal_mae_c=float(a[:, 2].mean()),
                             bias_c=float(a[:, 3].mean()), band_coverage=float(a[:, 4].mean()))
    stations = [dict(station=s, forecast_day=h, mae_c=float(np.mean([x[0] for x in v])), persistence_mae_c=float(np.mean([x[1] for x in v])), cases=len(v))
                for (s, h), v in sorted(by_station.items())]
    report = dict(status='Held-out 2022-2025 test of the water temperature model.', policy=POLICY, by_forecast_day=score, by_station=stations, excluded=excluded,
                  note='Targets are NDBC daily means. Overlapping windows and nearby stations are correlated, not independent tests.')
    with (run / 'scoreboard.json').open('x', encoding='utf-8') as f: json.dump(report, f, indent=1)
    save(OUT / 'latest.json', dict(run=stamp, **{k: v for k, v in report.items() if k != 'by_station'}))
    log('Water temperature: trained and tested (run %s).' % stamp)
    for h in ('1', '7', '14'):
        x = score.get(h)
        if x: print('day %s: error %.2f C vs unchanged %.2f vs seasonal normal %.2f; band covers %.0f%% (%d cases)' % (
            h, x['mae_c'], x['persistence_mae_c'], x['normal_mae_c'], 100 * x['band_coverage'], x['cases']))


if __name__ == '__main__':
    main()
