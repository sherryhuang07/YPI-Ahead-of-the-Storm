"""Groundwater v2: well water-level forecasts that use rain (recent observed and forecast ahead).

Same 8 USGS wells and daily depth-to-water history as v1. For each well and lead (2-15 days after the
last reading, i.e. forecast days 1-14), one ridge regression predicts the CHANGE in depth from the last
reading, from:
  level:  last depth, its change over 7 and 30 days, its departure from the last 365-day mean
  rain:   last 7, 30 and 90 days up to the last reading (log(1+mm)); rain from the next day to the
          target day, and in the 3 days before the target (log(1+mm))
  season: sin/cos of day of year
Splits (chronological, matching v1's blind replay test window): fit through 2018, choose the
penalty on 2019-2021, calibrate 90% bands on 2022 (normal-rain errors), test Jan 2023 - Nov 2026
with a model fit through 2022, one origin every 14 days. Test reports perfect rain (observed) and
normal rain bounds, beside v1's method for that well and "no change" on the same cases.
Rain ahead counts only the first 10 days (NOAA's reach); 'normal rain' = the rain-ahead inputs at their
average for that month in the training years. Revision note: the first run (2026-11-11) counted rain to
day 14 and spread the month's average rain over every day; its test results were seen before this revision.
Adopt rule fixed before testing: v2 replaces v1 in the app only if its normal-rain MAE is no worse
than v1 at a majority of wells and its perfect-rain MAE is lower overall.
"""
import glob
import hashlib
from datetime import date, timedelta, datetime, timezone
import numpy as np
from statewide_common import ROOT, read, save, log
from forecast_methods import predict as v1_predict
from site_rain import history as rain_history, normal_by_month, window_sum
from train_streamflow_history import fit, predict

OUT = ROOT / 'outputs/groundwater-v2'
START = date(2000, 1, 1)
LEADS = np.arange(2, 16)
POLICY = dict(version='groundwater-v2', alphas=[1, 10, 100, 1000], target='change in depth to water (ft) from the last reading',
              train='through 2018', selection='2019-2021', bands='2022 (normal-rain errors)', test='2023-01 to 2026-11, fit through 2022',
              adopt_rule='v2 replaces v1 in the app only if its normal-rain MAE is no worse than v1 at a majority of wells and its perfect-rain MAE is lower overall.')


def depth_series(well_id, n):
    run = sorted(glob.glob(str(ROOT / 'data/groundwater-history/*/manifest.json')))[-1].rsplit('manifest.json', 1)[0]
    d = np.full(n, np.nan)
    for f in read(run + well_id + '.json')['features']:
        p = f['properties']
        if p.get('qualifier') or p.get('value') in (None, ''): continue
        i = (date.fromisoformat(p['time'][:10]) - START).days
        if 0 <= i < n: d[i] = float(p['value'])
    return d


def level_features(d, i):
    if not np.isfinite(d[i]): return None
    def back(k):
        for j in range(3):
            if i - k - j >= 0 and np.isfinite(d[i - k - j]): return d[i - k - j]
        return np.nan
    year = d[max(0, i - 364):i + 1]
    if np.isfinite(year).sum() < 200: return None
    doy = (START + timedelta(days=int(i))).timetuple().tm_yday
    return [d[i], d[i] - back(7), d[i] - back(30), d[i] - np.nanmean(year), np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)]


HORIZON = 10   # NOAA's forecast reach in rain days; rain beyond it is not an input


def rain_features(r, i, L):
    h = min(L, HORIZON)
    return [np.log1p(window_sum(r, i, n)) for n in (7, 30, 90)] + [np.log1p(window_sum(r, i + h, h)), np.log1p(window_sum(r, i + h, min(3, h)))]


def train(w, rain, normal_series, n):
    d = depth_series(w['id'], n)
    rows = []
    for i in range(400, n - 16):
        lf = level_features(d, i)
        if lf is None or not np.isfinite(lf).all(): continue
        rows.append(i)
    idx = np.array(rows)
    if not len(idx): return dict(id=w['id'], status='withheld: no complete windows')
    LF = np.array([level_features(d, i) for i in idx])
    RF = np.array([[rain_features(rain, i, L) for L in LEADS] for i in idx])
    Yd = np.array([[d[i + L] - d[i] for L in LEADS] for i in idx])
    ok = np.isfinite(RF).all((1, 2))
    idx, LF, RF, Yd = idx[ok], LF[ok], RF[ok], Yd[ok]
    day = np.array([START + timedelta(days=int(i)) for i in idx]); end = np.array([START + timedelta(days=int(i) + 15) for i in idx])
    tr = end < date(2019, 1, 1)
    months = np.array([x.month for x in day]); RN = np.zeros(RF[:, :, 3:].shape); normal_table = {}
    for m_ in range(1, 13):
        sel = tr & (months == m_); src = RF[sel] if sel.any() else RF[tr]
        RN[months == m_] = src[:, :, 3:].mean(0); normal_table[m_] = src[:, :, 3:].mean(0).tolist()
    se = (day >= date(2019, 1, 1)) & (end < date(2022, 1, 1)) & (idx % 14 == 0)
    ca = (day >= date(2022, 1, 1)) & (end < date(2023, 1, 1)) & (idx % 14 == 0)
    te = (day >= date(2023, 1, 1)) & (idx % 14 == 0)
    if tr.sum() < 365 or min(se.sum(), ca.sum(), te.sum()) < 8:
        return dict(id=w['id'], status='withheld: too few windows', counts=[int(tr.sum()), int(se.sum()), int(ca.sum()), int(te.sum())])
    def X(k, normal=False):
        rr = RF[:, k, :].copy()
        if normal: rr[:, 3:] = RN[:, k, :]
        return np.column_stack([LF, rr])
    def fit_all(mask, a):
        out = []
        for k in range(len(LEADS)):
            m = mask & np.isfinite(Yd[:, k]); out.append(fit(X(k)[m], Yd[m, k:k + 1], a))
        return out
    def pred(models, mask, normal=False): return np.column_stack([predict(m, X(k, normal)[mask])[:, 0] for k, m in enumerate(models)])
    def mae(p, mask):
        y = Yd[mask]; ok = np.isfinite(y); return float(np.mean(abs(p - y)[ok]))
    scores = {a: mae(pred(fit_all(tr, a), se), se) for a in POLICY['alphas']}
    alpha = min(scores, key=scores.get)
    cal = pred(fit_all(end < date(2022, 1, 1), alpha), ca, True); err = abs(cal - Yd[ca])
    width = np.array([np.sort(e[np.isfinite(e)])[min(np.isfinite(e).sum(), int(np.ceil((np.isfinite(e).sum() + 1) * .9))) - 1] for e in err.T])
    m22 = fit_all(end < date(2023, 1, 1), alpha)
    perfect = pred(m22, te); normal = pred(m22, te, True)
    v1 = []
    for i in idx[te]:
        h = d[i - 89:i + 1]
        try:
            if np.isfinite(h).sum() < 70: raise ValueError
            v1.append(v1_predict(h, w['method'], 'groundwater', horizon=15)[1:15] - d[i])
        except ValueError: v1.append(np.full(14, 0.0))   # v1 withholds; scored as "no change"
    v1 = np.array(v1); y = Yd[te]; ok = np.isfinite(y)
    m = lambda p: float(np.mean(abs(p - y)[ok]))
    metrics = dict(test_cases=int(te.sum()), mae_perfect_rain=m(perfect), mae_normal_rain=m(normal), mae_v1=m(v1), mae_persistence=m(np.zeros_like(y)),
                   per_lead_perfect=[float(np.mean(abs(perfect[:, k] - y[:, k])[ok[:, k]])) for k in range(14)],
                   per_lead_normal=[float(np.mean(abs(normal[:, k] - y[:, k])[ok[:, k]])) for k in range(14)],
                   per_lead_v1=[float(np.mean(abs(v1[:, k] - y[:, k])[ok[:, k]])) for k in range(14)],
                   per_lead_persistence=[float(np.mean(abs(y[:, k])[ok[:, k]])) for k in range(14)],
                   band_coverage_normal=float(((abs(normal - y) <= width)[ok]).mean()), band_coverage_perfect=float(((abs(perfect - y) <= width)[ok]).mean()))
    final = fit_all(np.ones(len(idx), bool), alpha)
    return dict(id=w['id'], name=w['name'], status='trained', alpha=alpha, selection_mae=scores, metrics=metrics, band_width_ft=width.tolist(), normal_ahead=normal_table,
                models=[{k: (v.tolist() if hasattr(v, 'tolist') else v) for k, v in mm.items()} for mm in final])


def main():
    reg = read(ROOT / 'data/prospective/model-v1.json')
    rain, rstart = rain_history(); assert rstart == START
    n = (date.today() - START).days + 1; results = []
    for w in reg['groundwater']:
        r = rain[w['id']]; r = np.concatenate([r, np.full(max(0, n + 20 - len(r)), np.nan)])[:n + 20]
        nm = normal_by_month(r, START); ns = np.array([nm[(START + timedelta(days=i)).month] for i in range(len(r))])
        res = train(w, r, ns, n); results.append(res)
        if res['status'] == 'trained':
            mm = res['metrics']; log('Groundwater v2 %s: test MAE perfect rain %.3f, normal rain %.3f, v1 %.3f, no change %.3f ft' % (w['id'], mm['mae_perfect_rain'], mm['mae_normal_rain'], mm['mae_v1'], mm['mae_persistence']))
    good = [r for r in results if r['status'] == 'trained']
    mean = lambda k: float(np.mean([r['metrics'][k] for r in good]))
    summary = dict(created_at=datetime.now(timezone.utc).isoformat(), policy=POLICY, wells=len(results), trained=len(good),
                   mean_mae=dict(perfect_rain=mean('mae_perfect_rain'), normal_rain=mean('mae_normal_rain'), v1=mean('mae_v1'), persistence=mean('mae_persistence')),
                   wells_better_than_v1=dict(perfect_rain=sum(r['metrics']['mae_perfect_rain'] < r['metrics']['mae_v1'] for r in good),
                                             normal_rain_no_worse=sum(r['metrics']['mae_normal_rain'] <= r['metrics']['mae_v1'] for r in good)),
                   per_lead_mean={k: np.mean([r['metrics']['per_lead_' + k] for r in good], 0).tolist() for k in ('perfect', 'normal', 'v1', 'persistence')},
                   band_coverage_mean=dict(normal_rain=mean('band_coverage_normal'), perfect_rain=mean('band_coverage_perfect')))
    summary['adopt'] = bool(summary['wells_better_than_v1']['normal_rain_no_worse'] > len(good) / 2 and summary['mean_mae']['perfect_rain'] < summary['mean_mae']['v1'])
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'); run = OUT / 'runs' / stamp; run.mkdir(parents=True)
    for name, obj in (('results.json', results), ('summary.json', summary), ('policy.json', POLICY)): save(run / name, obj)
    save(run / 'manifest.json', dict(files={nm_: hashlib.sha256((run / nm_).read_bytes()).hexdigest() for nm_ in ('results.json', 'summary.json', 'policy.json')}))
    save(OUT / 'latest.json', dict(run=stamp, **summary))
    import json
    print(json.dumps({k: summary[k] for k in ('trained', 'mean_mae', 'wells_better_than_v1', 'band_coverage_mean', 'adopt')}, indent=1))


if __name__ == '__main__':
    main()
