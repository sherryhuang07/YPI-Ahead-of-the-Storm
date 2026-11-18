"""Choose how rain amounts enter the rain-aware stream and well models, using the SELECTION years only.

v2 measures rain as log(1 + mm), which gives the first few millimetres an outsized effect (5.6 mm
counts about half as much as 40 mm), so a light shower forecast for a dry week doubled some river
forecasts in November 2026. Candidates: log1p (v2), sqrt, linear (mm/10), excess5 (rain beyond the
first 5 mm, /10). Each is trained exactly as v2 (same sites, splits and penalty choice) and scored on the
selection period (streams 2021-2022, wells 2019-2021): the measure with the lowest median selection
error is chosen. Test-period numbers are printed for information only and do not influence the choice.
Output: outputs/reasoning/rain-measures.json
"""
import json
from datetime import date, timedelta, datetime, timezone
import numpy as np
from statewide_common import ROOT, read
from site_rain import history as rain_history, normal_by_month
import train_streamflow_rain as S
import train_groundwater_rain as G

MEASURES = ['log1p', 'sqrt', 'linear', 'excess5']


def run_streams(set_name, registry, rain_name):
    reg = read(ROOT / registry); rain, start = rain_history(rain_name); out = {}
    for meas in MEASURES:
        S.RAIN_MEASURE = meas; sel, test, v1 = [], [], []
        for g in reg['streamflow']:
            r = rain.get(g['gauge_id'])
            if r is None: continue
            r = np.concatenate([r, np.full(max(0, len(S.DATES) + 20 - len(r)), np.nan)])[:len(S.DATES) + 20]
            nm = normal_by_month(r, start); ns = np.array([nm[(start + timedelta(days=i)).month] for i in range(len(r))])
            res = S.train(g, r, ns)
            if res['status'] != 'trained': continue
            sel.append(min(res['selection_mae'].values())); test.append(res['metrics']['mae_perfect_rain']); v1.append(res['metrics']['mae_v1'])
            res['metrics'].setdefault('mae_normal_rain', None)
        out[meas] = dict(sites=len(sel), selection_median=float(np.median(sel)), selection_mean=float(np.mean(sel)),
                         test_perfect_median=float(np.median(test)), test_v1_median=float(np.median(v1)))
        print(set_name, meas, json.dumps(out[meas]), flush=True)
    return out


def run_wells():
    reg = read(ROOT / 'data/prospective/model-v1.json'); rain, start = rain_history('site-rain'); n = (date.today() - start).days + 1; out = {}
    for meas in MEASURES:
        G.RAIN_MEASURE = meas; sel, test = [], []
        for w in reg['groundwater']:
            r = rain[w['id']]; r = np.concatenate([r, np.full(max(0, n + 20 - len(r)), np.nan)])[:n + 20]
            nm = normal_by_month(r, start); ns = np.array([nm[(start + timedelta(days=i)).month] for i in range(len(r))])
            res = G.train(w, r, ns, n)
            if res['status'] != 'trained': continue
            sel.append(min(res['selection_mae'].values())); test.append(res['metrics']['mae_perfect_rain'])
        out[meas] = dict(sites=len(sel), selection_median=float(np.median(sel)), selection_mean=float(np.mean(sel)), test_perfect_median=float(np.median(test)))
        print('wells', meas, json.dumps(out[meas]), flush=True)
    return out


def main():
    res = dict(created_at=datetime.now(timezone.utc).isoformat(), rule='choose the measure with the lowest median selection-period error; test numbers are information only',
               streams=run_streams('streams', 'data/prospective/model-v1.json', 'site-rain'),
               regional=run_streams('regional', 'data/regional-prospective/model-v1.json', 'site-rain-regional'),
               wells=run_wells())
    for k in ('streams', 'regional', 'wells'):
        res[k + '_chosen'] = min(res[k], key=lambda m: res[k][m]['selection_median'])
        print('chosen for %s: %s' % (k, res[k + '_chosen']))
    (ROOT / 'outputs/reasoning').mkdir(parents=True, exist_ok=True)
    (ROOT / 'outputs/reasoning/rain-measures.json').write_text(json.dumps(res, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
