"""14-day Connecticut fire danger forecast and its historical test.

    fire_danger_forecast.py train      fit the statistical part on 1997-2014, choose on 2015-2018,
                                       seal 2019-2025 test predictions, then score them
    fire_danger_forecast.py forecast   today's 14-day forecast (needs current weather + NBM)

Forecast for each day starting tomorrow:
- Days with NOAA NBM weather (about 10): run DANGER forward at each airport from its current
  Build Up Index with NBM 1 PM temperature, dew point and 10 m wind, and NBM rain in the
  24 hours ending 1 PM; statewide = median of airports; class from the Build Up
  Index, the rule that best matched DEEP's published ratings (data/fire-danger/validation.json).
- Later days: conditional climatology from the rebuilt history: P(class on day t+h |
  class on the last weather-forecast day, calendar month), trained on 1997-2014 only.

The statistical part's 1-14 day skill is tested on 2019-2025 against persistence. The NBM
part cannot be tested historically here (archived NBM forecasts are not downloaded); it is
tested prospectively by the sealed daily ledger.
"""
import argparse
import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import numpy as np
from statewide_common import ROOT, save, log
from fire_danger_model import danger, wet_bulb_f, herb_stage, rating, LEVELS

FD = ROOT / 'data/fire-danger'; OUT = ROOT / 'outputs/fire-danger'; LOCAL = ZoneInfo('America/New_York')
POLICY = dict(version='fire-v1', rating_rule='buildup', spread_index='timber', wind_height_factor=0.87, statewide='median of airports', train_end='2014-12-31',
              calibration=['2015-01-01', '2018-12-31'], test=['2019-01-01', '2025-12-31'], horizons=list(range(1, 15)),
              smoothing=1.0, note='Rule and calendar choices fixed before scoring the test years.')
AIRPORTS = {'BDL': (41.94, -72.68), 'BDR': (41.16, -73.13), 'HVN': (41.26, -72.89), 'DXR': (41.37, -73.48), 'IJD': (41.74, -72.18)}


def load_history():
    rows = list(csv.DictReader((FD / 'history.csv').open(encoding='utf-8')))
    days = [r['date'] for r in rows]
    si = 'median_' + POLICY['spread_index']
    cls = np.array([np.nan if r[si] == '' else rating(float(r[si]), float(r['median_bui']), POLICY['rating_rule']) for r in rows])
    return rows, days, cls


def fit_transitions(days, cls, end, smoothing):
    """counts[h][month][from_class] -> class probabilities, from pairs whose TARGET is on/before `end`."""
    counts = np.full((15, 13, 5, 5), smoothing)
    for i, d in enumerate(days):
        if np.isnan(cls[i]): continue
        m = int(d[5:7])
        for h in range(1, 15):
            j = i + h
            if j >= len(days) or days[j] > end: break
            if not np.isnan(cls[j]): counts[h, m, int(cls[i]), int(cls[j])] += 1
    return counts / counts.sum(axis=3, keepdims=True)


def train():
    rows, days, cls = load_history()
    probs = fit_transitions(days, cls, POLICY['train_end'], POLICY['smoothing'])
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'); run = OUT / 'runs' / stamp; run.mkdir(parents=True)
    a, b = POLICY['test']; preds = []
    for i, d in enumerate(days):
        if not (a <= d <= b) or np.isnan(cls[i]): continue
        m = int(d[5:7])
        for h in range(1, 15):
            p = probs[h, m, int(cls[i])]
            preds.append(dict(issue_last_day=d, target=str(date.fromisoformat(d) + timedelta(days=h)), horizon=h, persistence=int(cls[i]),
                              most_likely=int(np.argmax(p)), expected=float(p @ np.arange(5)), p_high_or_above=float(p[2:].sum())))
    with (run / 'sealed-test-predictions.json').open('x', encoding='utf-8') as f: json.dump(preds, f)
    np.save(run / 'transitions.npy', probs)
    sealed = {n: hashlib.sha256((run / n).read_bytes()).hexdigest() for n in ('sealed-test-predictions.json', 'transitions.npy')}
    save(run / 'manifest.json', dict(created_at=datetime.now(timezone.utc).isoformat(), policy=POLICY, files=sealed,
                                     history_sha256=hashlib.sha256((FD / 'history.csv').read_bytes()).hexdigest()))
    # Score in a separate step, only after sealing.
    for n, s in sealed.items():
        if hashlib.sha256((run / n).read_bytes()).hexdigest() != s: raise ValueError('Sealed file changed: ' + n)
    index = {d: i for i, d in enumerate(days)}; by_h = defaultdict(list)
    for p in preds:
        j = index.get(p['target'])
        if j is None or np.isnan(cls[j]): continue
        y = int(cls[j]); by_h[p['horizon']].append((p['most_likely'] == y, p['persistence'] == y, abs(p['expected'] - y), abs(p['persistence'] - y),
                                                    (p['p_high_or_above'] >= 0.5, y >= 2), (p['persistence'] >= 2, y >= 2)))
    score = {}
    for h, v in sorted(by_h.items()):
        acc, pacc, mae, pmae, hi, phi = zip(*v)
        def hits(pairs):
            tp = sum(f and o for f, o in pairs); fn = sum((not f) and o for f, o in pairs); fp = sum(f and not o for f, o in pairs)
            return dict(detected=tp / (tp + fn) if tp + fn else None, false_alarm_share=fp / (tp + fp) if tp + fp else None)
        score[str(h)] = dict(cases=len(v), accuracy=float(np.mean(acc)), persistence_accuracy=float(np.mean(pacc)),
                             mae_classes=float(np.mean(mae)), persistence_mae_classes=float(np.mean(pmae)),
                             high_or_above=hits(hi), persistence_high_or_above=hits(phi))
    report = dict(status='Statistical fire-danger part tested on held-out 2019-2025 rebuilt ratings.', policy=POLICY, by_horizon=score,
                  note='Targets are ratings rebuilt from airport weather with the 1964 NFDRS, not DEEP-published ratings. Overlapping windows are correlated.')
    with (run / 'scoreboard.json').open('x', encoding='utf-8') as f: json.dump(report, f, indent=1)
    save(OUT / 'latest-test.json', dict(run=stamp, **report))
    log('Fire danger: statistical part tested on 2019-2025 (run %s).' % stamp)
    for h in ('1', '7', '14'):
        s = score.get(h)
        if s: print('day %s: accuracy %.2f vs persistence %.2f; MAE %.2f vs %.2f classes' % (h, s['accuracy'], s['persistence_accuracy'], s['mae_classes'], s['persistence_mae_classes']))


# ---------------- live forecast ----------------

def nbm_weather(points, not_after=None):
    """1 PM (18 UTC) temperature/dew point/wind and 24 h rain ending then, per airport, from the latest NBM cycle."""
    import requests, rasterio
    from rasterio.warp import transform
    from fetch_noaa_precip import locate, BASE, USER
    day, cycle, files, _ = locate(not_after=not_after); c0 = datetime.strptime(day + cycle, '%Y%m%d%H').replace(tzinfo=timezone.utc)
    hours = sorted({int(re.search(r'f(\d{3})', f).group(1)) for f in files if 1 <= int(re.search(r'f(\d{3})', f).group(1)) <= 264})
    folder = FD / 'nbm' / (day + cycle + 'z'); folder.mkdir(parents=True, exist_ok=True); grids = {}
    for h in hours:
        path = folder / ('f%03d.grib2' % h)
        if not path.exists():
            r = requests.get(BASE + '/cgi-bin/filter_blend.pl', headers=USER, timeout=90, params=dict(
                file='blend.t%sz.core.f%03d.co.grib2' % (cycle, h), dir='/blend.%s/%s/core' % (day, cycle), var_TMP='on', var_DPT='on', var_WIND='on',
                var_APCP='on', lev_2_m_above_ground='on', lev_10_m_above_ground='on', lev_surface='on', subregion='', leftlon=-74, rightlon=-71, toplat=42.2, bottomlat=40.9))
            if not r.content.startswith(b'GRIB'): raise RuntimeError('NBM filter did not return GRIB for hour %d' % h)
            path.write_bytes(r.content)
        grids[h] = path
    wx = defaultdict(dict); qpf = defaultdict(dict)
    for h, path in grids.items():
        with rasterio.open(path) as s:
            xs, ys = transform('EPSG:4326', s.crs, [p[1] for p in points.values()], [p[0] for p in points.values()])
            for i in range(1, s.count + 1):
                t = s.tags(i); el = str(t.get('GRIB_ELEMENT', '')); end = datetime.fromtimestamp(int(t['GRIB_VALID_TIME']), timezone.utc)
                if 'stddev' in str(t.get('GRIB_COMMENT', '')) or 'stddev' in str(t.get('GRIB_SHORT_NAME', '')): continue
                vals = [float(v[0]) for v in s.sample(list(zip(xs, ys)), indexes=i)]
                for name, v in zip(points, vals):
                    if el in ('T', 'Td', 'WindSpd'): wx[(name, end)][el] = v
                    m = re.fullmatch(r'QPF(\d+)', el)
                    if m: qpf[(name, end)][int(m.group(1))] = v
    return c0, wx, qpf


def rain_24h(qpf, name, end, c0):
    """Rain (mm) in the 24 h ending `end` from non-overlapping NBM accumulations, or None if not covered."""
    cand = {e: v for (n, e), v in qpf.items() if n == name}
    reach = {c0}
    for e in sorted(cand):
        if any(e - timedelta(hours=k) in reach for k in cand[e]): reach.add(e)
    if end not in reach: return None
    # Today's window can begin before the NBM cycle; then only rain after the cycle start is counted.
    total = 0.0; node = end; start = max(end - timedelta(hours=24), c0)
    while node > start:
        k = min(k for k in cand[node] if node - timedelta(hours=k) in reach)
        if node - timedelta(hours=k) < start: return None    # interval straddles the window start
        total += max(0.0, cand[node][k]); node -= timedelta(hours=k)
    return total


def forecast():
    from fetch_fire_weather import STATIONS
    rows, days, cls = load_history(); last = rows[-1]
    today = datetime.now(LOCAL).date()
    if date.fromisoformat(last['date']) < today - timedelta(days=2): raise ValueError('Fire weather history is stale; update it first.')
    probs = np.load(sorted((OUT / 'runs').glob('*/transitions.npy'))[-1])
    bui = {s: float(last[s + '_bui']) for s in STATIONS if last.get(s + '_bui') not in ('', None)}
    # Today's Build Up Index step needs NBM weather at 1 PM today: a catch-up run started after about 1 PM uses the
    # newest cycle issued at least an hour before then, instead of one that starts after it.
    one_pm = datetime.combine(today, datetime.min.time(), LOCAL).replace(hour=13).astimezone(timezone.utc)
    c0, wx, qpf = nbm_weather({s: AIRPORTS[s] for s in bui}, not_after=one_pm - timedelta(hours=1))
    out = []; last_class = None
    if date.fromisoformat(last['date']) != today - timedelta(days=1):
        raise ValueError('Rebuilt history must end yesterday so today can be stepped with NBM weather.')
    for h in range(0, 15):          # h = 0 (today) only advances the Build Up Index; output starts tomorrow
        d = today + timedelta(days=h)
        # 1 PM local -> 18 UTC in standard time, 17 UTC in daylight time.
        end = datetime.combine(d, datetime.min.time(), LOCAL).replace(hour=13).astimezone(timezone.utc)
        per = {}
        for s in list(bui):
            w = wx.get((s, end)); r = rain_24h(qpf, s, end, c0)
            if not w or r is None or not all(k in w for k in ('T', 'Td', 'WindSpd')): continue
            tf = w['T'] * 1.8 + 32; tdf = min(w['Td'] * 1.8 + 32, tf)
            res = danger(tf, wet_bulb_f(tf, tdf), False, r / 25.4, w['WindSpd'] * 2.23694 * POLICY['wind_height_factor'], bui[s], herb_stage(d))
            bui[s] = res['bui']; per[s] = res
        if h == 0:
            if len(per) < 3: raise ValueError('No NBM weather for today; cannot advance the Build Up Index')
            continue
        if len(per) >= 3:
            si = float(np.median([v[POLICY['spread_index']] for v in per.values()])); bi = float(np.median([v['bui'] for v in per.values()]))
            k = rating(si, bi, POLICY['rating_rule']); last_class = k; anchor = h
            out.append(dict(date=str(d), level=LEVELS[k], level_index=k, spread_index=round(si, 1), buildup_index=round(bi, 1),
                            method='NOAA NBM weather -> 1964 NFDRS indexes (median of %d airports)' % len(per)))
        elif last_class is not None:
            p = probs[h - anchor, d.month, last_class]
            out.append(dict(date=str(d), level=LEVELS[int(np.argmax(p))], level_index=float(p @ np.arange(5)), probabilities=[round(x, 3) for x in p],
                            method='Rebuilt-history conditional climatology from the last NBM day (%d days on)' % (h - anchor)))
        else:
            raise ValueError('No NBM weather for the first forecast day')
    return dict(issued_for=str(today), nbm_cycle=c0.isoformat(), start_buildup=last, forecasts=out)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('mode', choices=['train', 'forecast']); a = ap.parse_args()
    if a.mode == 'train': train()
    else:
        f = forecast(); save(OUT / 'latest-forecast.json', f)
        for x in f['forecasts']: print(x['date'], x['level'], x.get('spread_index', ''), x.get('buildup_index', ''), x['method'][:40])


if __name__ == '__main__':
    main()
