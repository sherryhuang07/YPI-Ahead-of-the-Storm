"""Streamflow v2: the frozen v1 gauge model plus rain (observed recent rain and forecast rain ahead).

Same 55 gauges, history files, log-flow features and chronological splits as v1
(scripts/train_streamflow_history.py): fit 2000-2020, choose the ridge penalty on 2021-2022,
calibrate 90% bands on 2023, test Jan 2024-Nov 2026 with a model fit through 2023, one origin
every 14 days. Added inputs, from the drainage area's daily rain (scripts/build_site_rain.py):
  past:   rain on the last day, last 3, 7 and 30 days up to the last flow reading (log(1+mm))
  ahead:  rain from the day after the last reading to the target day, and in the 3 days before it
One ridge regression per gauge and lead (each lead has its own rain-ahead total).

Training uses the rain that actually fell. Live forecasts use NOAA's forecast for about 10 days
and normal rain after, so the test reports both bounds:
  perfect rain = observed rain ahead (what a perfect rain forecast would give)
  normal rain  = no rain forecast: the rain-ahead inputs take their 2000-2020 average for that month
Rain ahead counts only the first 10 days after the last reading (NOAA's forecast reach).
Revision note: the first run (2026-11-11) counted rain to day 14 and used the month's average rain
spread over every day for 'normal rain'; its test results were seen before this revision.
Bands are calibrated on normal-rain errors (the wider, conservative case). v1 is re-scored on
exactly the same test cases. Decided before testing: v2 replaces v1 in the app only if its
normal-rain test error is no worse than v1's at a majority of gauges AND its perfect-rain error is
lower overall; otherwise it runs beside v1 as a challenger.
"""
import hashlib
from datetime import date, timedelta, datetime, timezone
import numpy as np
from statewide_common import ROOT, read, save, log
from train_streamflow_history import START, DATES, LEADS, fit, predict, flow
from site_rain import history as rain_history, normal_by_month, window_sum

OUT = ROOT / 'outputs/streamflow-v2'
POLICY = dict(version='streamflow-v2', base='streamflow v1 (data/prospective/model-v1.json)', alphas=[1, 10, 100, 1000],
              past_rain_days=[1, 3, 7, 30], ahead='sum from day after last reading to target, and last 3 days before target',
              train='2000-2020', selection='2021-2022', bands='2023 (normal-rain errors)', test='2024-01 to 2026-11, fit through 2023',
              adopt_rule='v2 replaces v1 in the app only if its normal-rain test MAE is no worse than v1 at a majority of gauges and its perfect-rain MAE is lower overall.')


def base_rows(q):
    z = np.log1p(q); idx = np.arange(28, len(q) - 15)
    doy = np.array([d.timetuple().tm_yday for d in DATES])
    X = np.column_stack([z[idx - k] for k in [0, 1, 2, 6, 13, 27]] + [np.array([np.mean(z[i - k + 1:i + 1]) for i in idx]) for k in [7, 14, 28]] +
                        [np.sin(2 * np.pi * doy[idx] / 365.25), np.cos(2 * np.pi * doy[idx] / 365.25)])
    Y = np.column_stack([z[idx + L] for L in LEADS])
    return idx, X, Y


HORIZON = 10   # NOAA's forecast reaches about 10 rain days; rain beyond that is unknown live, so it is not an input


def rain_features(r, i, L):
    past = [np.log1p(window_sum(r, i, n)) for n in POLICY['past_rain_days']]
    h = min(L, HORIZON)
    ahead = [np.log1p(window_sum(r, i + h, h)), np.log1p(window_sum(r, i + h, min(3, h)))]
    return past + ahead


def normal_ahead(R, idx, mask):
    """Typical rain-ahead inputs (training mean per month of the last reading), for 'no rain forecast'."""
    months = np.array([d.month for d in DATES[idx]]); out = np.zeros(R[:, :, 4:].shape)
    for m in range(1, 13):
        sel = mask & (months == m)
        out[months == m] = R[sel][:, :, 4:].mean(0) if sel.any() else R[mask][:, :, 4:].mean(0)
    return out, {m: R[mask & (months == m)][:, :, 4:].mean(0).tolist() for m in range(1, 13) if (mask & (months == m)).any()}


def train(g, rain, normal_series):
    path = ROOT / 'data/streamflow/history' / (g['gauge_id'] + '.json')
    q = np.full(len(DATES), np.nan)
    for f in read(path)['features']:
        p = f['properties']
        if p.get('qualifier'): continue
        i = (date.fromisoformat(p['time'][:10]) - START).days
        try: v = float(p['value'])
        except (ValueError, TypeError): continue
        if 0 <= i < len(q) and np.isfinite(v) and v >= 0: q[i] = v
    idx, Xb, Y = base_rows(q)
    R = np.array([[rain_features(rain, i, L) for L in LEADS] for i in idx])              # origins x leads x 6
    ok = np.isfinite(Xb).all(1) & np.isfinite(Y).all(1) & np.isfinite(R).all((1, 2))
    idx, Xb, Y, R = idx[ok], Xb[ok], Y[ok], R[ok]
    end = DATES[idx + 15]
    Rn, normal_table = normal_ahead(R, idx, end < date(2021, 1, 1))
    tr = end < date(2021, 1, 1); se = (DATES[idx] >= date(2021, 1, 1)) & (end < date(2023, 1, 1)) & (idx % 14 == 0)
    ca = (DATES[idx] >= date(2023, 1, 1)) & (end < date(2024, 1, 1)) & (idx % 14 == 0); te = (DATES[idx] >= date(2024, 1, 1)) & (idx % 14 == 0)
    if tr.sum() < 730 or min(se.sum(), ca.sum(), te.sum()) < 12:
        return dict(gauge_id=g['gauge_id'], status='withheld: too few complete rain+flow windows', counts=[int(tr.sum()), int(se.sum()), int(ca.sum()), int(te.sum())])
    def X_for(L_i, normal=False):
        rr = R[:, L_i, :].copy()
        if normal: rr[:, 4:] = Rn[:, L_i, :]
        return np.column_stack([Xb, rr])
    def fit_all(mask, alpha): return [fit(X_for(k)[mask], Y[mask, k:k + 1], alpha) for k in range(len(LEADS))]
    def pred_all(models, mask, normal=False): return np.column_stack([predict(m, X_for(k, normal)[mask])[:, 0] for k, m in enumerate(models)])
    scores = {}
    for alpha in POLICY['alphas']:
        scores[alpha] = float(np.mean(abs(flow(pred_all(fit_all(tr, alpha), se)) - flow(Y[se]))))
    alpha = min(scores, key=scores.get)
    cal = pred_all(fit_all(end < date(2023, 1, 1), alpha), ca, normal=True)
    err = np.sort(abs(Y[ca] - cal), axis=0); n = len(err); width = err[min(n, int(np.ceil((n + 1) * .9))) - 1]
    m23 = fit_all(end < date(2024, 1, 1), alpha)
    perfect = pred_all(m23, te); normal = pred_all(m23, te, normal=True)
    # v1 on the same cases: same features without rain, v1's chosen penalty (or persistence)
    v1 = g['selected_method']
    if v1 == 'persistence': v1p = np.repeat(np.log1p(q[idx[te], None]), len(LEADS), 1)
    else: v1p = predict(fit(Xb[end < date(2024, 1, 1)], Y[end < date(2024, 1, 1)], float(v1)), Xb[te])
    actual = flow(Y[te]); base = np.repeat(q[idx[te], None], len(LEADS), 1)
    mae = lambda p: float(np.mean(abs(flow(p) - actual)))
    metrics = dict(test_fortnights=int(te.sum()), mae_perfect_rain=mae(perfect), mae_normal_rain=mae(normal), mae_v1=mae(v1p),
                   mae_persistence=float(np.mean(abs(base - actual))),
                   per_lead_perfect=abs(flow(perfect) - actual).mean(0).tolist(), per_lead_normal=abs(flow(normal) - actual).mean(0).tolist(),
                   per_lead_v1=abs(flow(v1p) - actual).mean(0).tolist(), per_lead_persistence=abs(base - actual).mean(0).tolist(),
                   band_coverage_normal=float(((Y[te] >= normal - width) & (Y[te] <= normal + width)).mean()),
                   band_coverage_perfect=float(((Y[te] >= perfect - width) & (Y[te] <= perfect + width)).mean()))
    final = fit_all(np.ones(len(idx), bool), alpha)
    return dict(gauge_id=g['gauge_id'], name=g['name'], status='trained', alpha=alpha, selection_mae=scores, metrics=metrics, band_log_width=width.tolist(), normal_ahead=normal_table,
                models=[{k: (v.tolist() if hasattr(v, 'tolist') else v) for k, v in m.items()} for m in final])


def main():
    import argparse
    global OUT, POLICY
    ap = argparse.ArgumentParser(); ap.add_argument('--set', choices=['ct', 'regional'], default='ct'); a = ap.parse_args()
    if a.set == 'regional':
        # Neighboring-state gauges: same method, splits and adopt rule; their frozen regional-v1 models are the comparison.
        OUT = ROOT / 'outputs/regional-streamflow-v2'
        POLICY = dict(POLICY, version='regional-streamflow-v2', base='neighboring-state streamflow v1 (data/regional-prospective/model-v1.json)')
    reg = read(ROOT / ('data/regional-prospective/model-v1.json' if a.set == 'regional' else 'data/prospective/model-v1.json'))
    rain_name = 'site-rain-regional' if a.set == 'regional' else 'site-rain'
    rain, rstart = rain_history(rain_name); assert rstart == START
    meta = {s['id']: s for s in read(ROOT / 'data/rain-stations' / (rain_name + '.json'))['sites']}
    results = []
    for g in reg['streamflow']:
        r = rain.get(g['gauge_id'])
        if r is None: results.append(dict(gauge_id=g['gauge_id'], status='withheld: no rain series')); continue
        r = np.concatenate([r, np.full(max(0, len(DATES) + 20 - len(r)), np.nan)])[:len(DATES) + 20]
        nm = normal_by_month(r, START); ns = np.array([nm[(START + timedelta(days=i)).month] for i in range(len(r))])
        res = train(g, r, ns); res['rain_method'] = meta[g['gauge_id']]['method']; results.append(res)
        if res['status'] == 'trained':
            m = res['metrics']; log('Streamflow v2 %s: test MAE perfect rain %.1f, normal rain %.1f, v1 %.1f, no change %.1f cfs' % (g['gauge_id'], m['mae_perfect_rain'], m['mae_normal_rain'], m['mae_v1'], m['mae_persistence']))
    good = [r for r in results if r['status'] == 'trained']
    def med(k): return float(np.median([r['metrics'][k] for r in good]))
    summary = dict(created_at=datetime.now(timezone.utc).isoformat(), policy=POLICY, gauges=len(results), trained=len(good),
                   median_mae=dict(perfect_rain=med('mae_perfect_rain'), normal_rain=med('mae_normal_rain'), v1=med('mae_v1'), persistence=med('mae_persistence')),
                   gauges_better_than_v1=dict(perfect_rain=sum(r['metrics']['mae_perfect_rain'] < r['metrics']['mae_v1'] for r in good),
                                              normal_rain_no_worse=sum(r['metrics']['mae_normal_rain'] <= r['metrics']['mae_v1'] for r in good)),
                   mean_mae=dict(perfect_rain=float(np.mean([r['metrics']['mae_perfect_rain'] for r in good])), normal_rain=float(np.mean([r['metrics']['mae_normal_rain'] for r in good])),
                                 v1=float(np.mean([r['metrics']['mae_v1'] for r in good])), persistence=float(np.mean([r['metrics']['mae_persistence'] for r in good]))),
                   per_lead_mean=dict(perfect_rain=np.mean([r['metrics']['per_lead_perfect'] for r in good], 0).tolist(), normal_rain=np.mean([r['metrics']['per_lead_normal'] for r in good], 0).tolist(),
                                      v1=np.mean([r['metrics']['per_lead_v1'] for r in good], 0).tolist(), persistence=np.mean([r['metrics']['per_lead_persistence'] for r in good], 0).tolist()),
                   band_coverage_median=dict(normal_rain=med('band_coverage_normal'), perfect_rain=med('band_coverage_perfect')))
    s = summary
    summary['adopt'] = bool(s['gauges_better_than_v1']['normal_rain_no_worse'] > len(good) / 2 and s['mean_mae']['perfect_rain'] < s['mean_mae']['v1'])
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'); run = OUT / 'runs' / stamp; run.mkdir(parents=True)
    for name, obj in (('results.json', results), ('summary.json', summary), ('policy.json', POLICY)):
        save(run / name, obj)
    files = {n: hashlib.sha256((run / n).read_bytes()).hexdigest() for n in ('results.json', 'summary.json', 'policy.json')}
    save(run / 'manifest.json', dict(files=files)); save(OUT / 'latest.json', dict(run=stamp, **summary))
    print(json_summary(summary))


def json_summary(s):
    import json
    return json.dumps({k: s[k] for k in ('trained', 'median_mae', 'mean_mae', 'gauges_better_than_v1', 'band_coverage_median', 'adopt')}, indent=1)


if __name__ == '__main__':
    main()
