"""Gut-check rules that tie stream and well forecasts to the rain around them, learned from history.

A forecast that ignores the weather can say a river will rise during a dry week, or fall during a soaking.
For each stream gauge (Connecticut and neighboring-state) and each well, and each forecast lead within
NOAA's 10-day reach, this script measures from the site's own history what actually happens:

  context rain = rain over the 3 days up to the last reading + every day from then to the target day
  DRY  (context rain < 3 mm):   largest plausible rise   = 99th percentile of the change in dry stretches
  WET  (context rain >= 25 mm): largest plausible fall   = 1st percentile (streams) / 99th (well depth)
                                of the change in wet stretches
Streams use the flow ratio Q(target)/Q(last); wells use the change in depth (ft; a rise in water is a
negative change in depth). Sites with too few dry or wet stretches use the pooled value of their set.

Learned on years before each model's test period (streams: targets before 2024; wells: before 2023) and
then checked on the test years: the frozen v1 forecasts are run at every 14th day, the rules are applied
using the rain that actually fell (a perfect rain forecast), and the error with and without the rules
is compared. Output: outputs/reasoning/rules.json (limits and the check), used by learning-v3.
"""
import glob
import json
from datetime import date, timedelta, datetime, timezone
import numpy as np
from statewide_common import ROOT, read, save, log
from site_rain import history as rain_history, window_sum

OUT = ROOT / 'outputs/reasoning'
START = date(2000, 1, 1)
DRY_MM, WET_MM, HORIZON = 3.0, 25.0, 10
PCT = 99      # how extreme a dry-stretch rise the gut-check allows (percentile of the site's own dry stretches)
WET_PCT = 99  # same for falls in wet stretches (chosen separately)
LEADS = list(range(2, 16))                 # days after the last reading (forecast days 1-14)


def context_rain(r, i, L):
    """Rain over the 3 days up to the last reading plus days i+1..i+L (NaN if any day missing)."""
    return window_sum(r, i + L, L + 3)


def flow_series(gid, n):
    q = np.full(n, np.nan)
    path = ROOT / 'data/streamflow/history' / (gid + '.json')
    if not path.exists(): return q
    for f in read(path)['features']:
        p = f['properties']
        if p.get('qualifier'): continue
        i = (date.fromisoformat(p['time'][:10]) - START).days
        try: v = float(p['value'])
        except (TypeError, ValueError): continue
        if 0 <= i < n and np.isfinite(v) and v >= 0: q[i] = v
    return q


def depth_series(wid, n):
    run = sorted(glob.glob(str(ROOT / 'data/groundwater-history/*/manifest.json')))[-1].rsplit('manifest.json', 1)[0]
    d = np.full(n, np.nan)
    for f in read(run + wid + '.json')['features']:
        p = f['properties']
        if p.get('qualifier') or p.get('value') in (None, ''): continue
        i = (date.fromisoformat(p['time'][:10]) - START).days
        if 0 <= i < n: d[i] = float(p['value'])
    return d


def change(x, i, L, kind):
    a, b = x[i], x[i + L]
    if not (np.isfinite(a) and np.isfinite(b)): return np.nan
    return (b + 0.01) / (a + 0.01) if kind == 'streamflow' else b - a


def limits_for(x, r, kind, end_day):
    """Per lead: (dry_max, n_dry, wet_min_or_max, n_wet) from origins whose target is before end_day."""
    n_end = (end_day - START).days; out = {}
    for L in LEADS:
        if L > HORIZON: continue
        dry, wet = [], []
        for i in range(3, min(len(x), len(r)) - L):
            if i + L >= n_end: break
            c = change(x, i, L, kind)
            if not np.isfinite(c): continue
            rr = context_rain(r, i, L)
            if not np.isfinite(rr): continue
            if rr < DRY_MM: dry.append(c)
            elif rr >= WET_MM: wet.append(c)
        if kind == 'streamflow':
            out[L] = dict(dry_rise=float(np.percentile(dry, PCT)) if len(dry) >= 50 else None, n_dry=len(dry),
                          wet_floor=float(np.percentile(wet, 100 - WET_PCT)) if len(wet) >= 30 else None, n_wet=len(wet))
        else:   # depth: dry -> most negative plausible change (rise); wet -> most positive plausible change (fall)
            out[L] = dict(dry_rise=float(np.percentile(dry, 100 - PCT)) if len(dry) >= 50 else None, n_dry=len(dry),
                          wet_floor=float(np.percentile(wet, WET_PCT)) if len(wet) >= 30 else None, n_wet=len(wet))
    return out


def guard(pred, last, rule, rain_ctx, kind):
    """Apply one site/lead rule to a forecast value. Returns (value, note or None)."""
    if rule is None or not np.isfinite(rain_ctx): return pred, None
    if rain_ctx < DRY_MM and rule.get('dry_rise') is not None:
        if kind == 'streamflow':
            cap = (last + 0.01) * rule['dry_rise'] - 0.01
            if pred > cap: return cap, 'dry: capped rise at x%.2f (%.1f mm rain)' % (rule['dry_rise'], rain_ctx)
        else:
            cap = last + rule['dry_rise']
            if pred < cap: return cap, 'dry: capped water-level rise at %.2f ft (%.1f mm rain)' % (-rule['dry_rise'], rain_ctx)
    if rain_ctx >= WET_MM and rule.get('wet_floor') is not None:
        if kind == 'streamflow':
            floor = (last + 0.01) * rule['wet_floor'] - 0.01
            if pred < floor: return floor, 'wet: limited fall to x%.2f (%.1f mm rain)' % (rule['wet_floor'], rain_ctx)
        else:
            floor = last + rule['wet_floor']
            if pred > floor: return floor, 'wet: limited water-level fall to %.2f ft (%.1f mm rain)' % (rule['wet_floor'], rain_ctx)
    return pred, None


def pooled(rules):
    """Set-wide fallback per lead: median of site limits (used where a site lacks enough stretches)."""
    out = {}
    for L in LEADS:
        if L > HORIZON: continue
        d = [r[L]['dry_rise'] for r in rules.values() if r.get(L) and r[L]['dry_rise'] is not None]
        w = [r[L]['wet_floor'] for r in rules.values() if r.get(L) and r[L]['wet_floor'] is not None]
        out[L] = dict(dry_rise=float(np.median(d)) if d else None, wet_floor=float(np.median(w)) if w else None)
    return out


def v1_stream_pred(model, q, i):
    """Frozen v1 gauge model (as in prospective_daily.make_water), forecast from reading i: leads 2..15."""
    if model.get('method') == 'persistence': return np.repeat(q[i], 14)
    w = q[i - 27:i + 1]
    if len(w) < 28 or not np.isfinite(w).all(): return None
    z = np.log1p(w); doy = (START + timedelta(days=i)).timetuple().tm_yday
    f = [z[-1 - k] for k in [0, 1, 2, 6, 13, 27]] + [np.mean(z[-k:]) for k in [7, 14, 28]] + [np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)]
    return np.expm1(np.clip(np.r_[1, (np.array(f) - model['mean']) / model['scale']] @ np.array(model['beta']), 0, 20))


def main():
    import argparse
    global PCT, WET_PCT
    ap = argparse.ArgumentParser(); ap.add_argument('--pct', type=float, default=PCT); ap.add_argument('--wet-pct', type=float, default=WET_PCT); ap.add_argument('--out', default='rules.json')
    ap.add_argument('--select', action='store_true', help='learn on earlier years, score the 3-4 years before the test period (for choosing --pct)')
    a_ = ap.parse_args(); PCT = a_.pct; WET_PCT = a_.wet_pct
    n = (date.today() - START).days + 1; result = dict(created_at=datetime.now(timezone.utc).isoformat(), dry_mm=DRY_MM, wet_mm=WET_MM,
                                                       horizon_days=HORIZON, sets={})
    from forecast_methods import predict as v1_well
    for set_name, rain_name, registry, kind, test_start in (
            ('streamflow', 'site-rain', 'data/prospective/model-v1.json', 'streamflow', date(2024, 1, 1)),
            ('regional-streamflow', 'site-rain-regional', 'data/regional-prospective/model-v1.json', 'streamflow', date(2024, 1, 1)),
            ('groundwater', 'site-rain', 'data/prospective/model-v1.json', 'groundwater', date(2023, 1, 1))):
        rain, _ = rain_history(rain_name); reg = read(ROOT / registry)
        sites = reg['streamflow'] if kind == 'streamflow' else reg['groundwater']
        rules = {}; series = {}
        for s in sites:
            sid = s['gauge_id'] if kind == 'streamflow' else s['id']
            x = flow_series(sid, n) if kind == 'streamflow' else depth_series(sid, n)
            r = rain.get(sid)
            if r is None: continue
            learn_end = date(test_start.year - (3 if kind == 'streamflow' else 4), 1, 1) if a_.select else test_start
            series[sid] = (x, r, s); rules[sid] = limits_for(x, r, kind, learn_end)
        pool = pooled(rules)
        for sid, rr in rules.items():
            for L in rr:
                for k in ('dry_rise', 'wet_floor'):
                    if rr[L][k] is None: rr[L][k] = pool[L][k]; rr[L][k + '_source'] = 'pooled'
        # ---- check on the test years with the rain that actually fell
        before, after, changed, cases, by_rule = [], [], 0, 0, {'dry': [0, 0.0, 0.0], 'wet': [0, 0.0, 0.0]}
        t0 = ((date(test_start.year - (3 if kind == 'streamflow' else 4), 1, 1) if a_.select else test_start) - START).days
        t_end = (test_start - START).days if a_.select else n - 16
        for sid, (x, r, s) in series.items():
            for i in range(t0, min(n - 16, t_end - 15), 14):
                if not np.isfinite(x[i]): continue
                if kind == 'streamflow':
                    p = v1_stream_pred(s['model'] if 'model' in s else {'method': 'persistence'}, x, i)
                else:
                    h = x[i - 89:i + 1]
                    if np.isfinite(h).sum() < 70: continue
                    try: p = v1_well(h, s['method'], 'groundwater', horizon=15)[1:15]
                    except ValueError: continue
                if p is None: continue
                for k, L in enumerate(LEADS):
                    if L > HORIZON or not np.isfinite(x[i + L]): continue
                    ctx = context_rain(r, i, L); g, note = guard(float(p[k]), float(x[i]), rules[sid].get(L), ctx, kind)
                    e0 = abs(p[k] - x[i + L]); e1 = abs(g - x[i + L]); before.append(e0); after.append(e1); cases += 1
                    if note:
                        changed += 1; key = note.split(':')[0]; by_rule[key][0] += 1; by_rule[key][1] += e0; by_rule[key][2] += e1
        check = dict(test_from=str(test_start), cases=cases, changed=changed, mae_v1=float(np.mean(before)), mae_with_rules=float(np.mean(after)),
                     by_rule={k: dict(cases=v[0], mae_before=v[1] / v[0] if v[0] else None, mae_after=v[2] / v[0] if v[0] else None) for k, v in by_rule.items()},
                     units='cfs' if kind == 'streamflow' else 'ft')
        result['sets'][set_name] = dict(kind=kind, learned_before=str(test_start), rules={sid: {str(L): v for L, v in rr.items()} for sid, rr in rules.items()},
                                        pooled={str(L): v for L, v in pool.items()}, check=check)
        log('Reasoning rules (%s): %d sites; on %s+ test years %d of %d forecasts changed; v1 error %.3f -> %.3f %s' % (
            set_name, len(rules), test_start, changed, cases, check['mae_v1'], check['mae_with_rules'], check['units']))
        print(set_name, json.dumps(check))
    result['percentile'] = PCT; result['wet_percentile'] = WET_PCT
    OUT.mkdir(parents=True, exist_ok=True); save(OUT / a_.out, result)


if __name__ == '__main__':
    main()
