"""Daily sealed drought forecast: the next two U.S. Drought Monitor maps, statewide and 9 regions.

Run after the other night jobs (rain, streamflow, wells, soil, fire danger and water temperature
inputs are refreshed by them) and `fetch_drought_data.py --recent`. Each Connecticut day:
- latest released map M0 per area; targets = the next two Tuesday maps strictly after today
  (1-3 weeks after M0 depending on the weekday; the frozen model has one fit per lead);
- rain between today and each target: NOAA NBM at the five fire-weather airports (24 h ending
  1 PM, as already downloaded by the fire danger job), normal rain for days NBM does not cover;
- sealed in its own append-only ledger (data/drought-prospective, outputs/drought-prospective).
The ledger's scored value is the Drought Severity and Coverage Index (DSCI, 0-500); the full
D0+..D4+ percentages, the chance the class worsens or improves, and the class (current class,
stepped one class only when a change is more likely than not) are stored with it. Baseline: the current map,
unchanged. Observations are Drought Monitor values first downloaded after the issue.

--version v2 runs drought-v2 (adds USGS VegDRI) in its own ledger (data/drought-v2-prospective,
outputs/drought-v2-prospective), from the frozen model in outputs/drought-v2. Run
`vegdri-update.ps1 -Recent` first so the newest VegDRI week is included.
"""
import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import prospective_daily as p
from statewide_common import ROOT, read, save, log
from drought_features import load_all, drivers, normal_rain_per_day
from train_drought import predict, finish, dsci, category, prob, LEVELS

KIND = 'drought'
VERSIONS = {'v1': dict(version='drought-v1', data='data/drought-prospective', out='outputs/drought-prospective', trained='outputs/drought', vegdri=False),
            'v2': dict(version='drought-v2', data='data/drought-v2-prospective', out='outputs/drought-v2-prospective', trained='outputs/drought-v2', vegdri=True)}
V = VERSIONS['v1']


def registry():
    path = p.D / ('model-%s.json' % V['version'].split('-')[-1])
    if not path.exists():
        latest = read(ROOT / V['trained'] / 'latest.json'); run = ROOT / V['trained'] / 'runs' / latest['run']; sealed = read(run / 'manifest.json')
        p.exclusive(path, dict(created_at=p.utc().isoformat(), version=V['version'], trained_run=latest['run'],
                               model_path=str((run / 'model.json').relative_to(ROOT)), model_sha256=sealed['files']['model.json'],
                               policy_path=str((run / 'policy.json').relative_to(ROOT)), policy_sha256=sealed['files']['policy.json']))
    reg = read(path)
    for k in ('model', 'policy'):
        if p.digest(ROOT / reg[k + '_path']) != reg[k + '_sha256']: raise ValueError('Frozen drought %s changed' % k)
    return path, reg


def merge_live_soil():
    """Append the latest NASA daily soil inputs to the drought soil series (keeps it continuous)."""
    path = ROOT / 'data/drought/soil-moisture-daily.csv'; rows = {r['date']: r for r in csv.DictReader(path.open(encoding='utf-8'))}
    live = {}
    for r in csv.DictReader((ROOT / 'data/root-zone/daily-inputs/latest.csv').open(encoding='utf-8')):
        if r['moisture_m3m3']: live.setdefault(r['date'], []).append(float(r['moisture_m3m3']))
    for d, v in live.items():
        if len(v) >= 35 and d not in rows: rows[d] = dict(date=d, soil_moisture_m3m3=round(float(np.mean(v)), 5), watersheds=len(v), source='NLDAS v2.0 24-hour mean (live inputs)')
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['date', 'soil_moisture_m3m3', 'watersheds', 'source']); w.writeheader(); w.writerows([rows[d] for d in sorted(rows)])


def forecast_rain(today, last_target, normal):
    """Daily statewide rain (inches) from NOAA NBM at the airports; None where NBM does not cover the day."""
    from fire_danger_forecast import nbm_weather, rain_24h, AIRPORTS
    c0, wx, qpf = nbm_weather(AIRPORTS); out = {}
    d = today
    while d <= last_target:
        end = datetime.combine(d, datetime.min.time(), p.LOCAL).replace(hour=13).astimezone(timezone.utc)
        v = [rain_24h(qpf, s, end, c0) for s in AIRPORTS]; v = [x for x in v if x is not None]
        out[str(d)] = float(np.mean(v)) / 25.4 if len(v) >= 3 else None
        d += timedelta(days=1)
    return out, c0.isoformat()


def main():
    global V
    ap = argparse.ArgumentParser(); ap.add_argument('--test-dir'); ap.add_argument('--version', choices=sorted(VERSIONS), default='v1'); a = ap.parse_args()
    V = VERSIONS[a.version]
    base = Path(a.test_dir) if a.test_dir else None
    p.D = base / 'data' if base else ROOT / V['data']
    p.O = base / 'outputs' if base else ROOT / V['out']
    p.D.mkdir(parents=True, exist_ok=True); p.O.mkdir(parents=True, exist_ok=True)
    c = p.db(); p.verify(c); reg_path, reg = registry(); models = read(ROOT / reg['model_path'])
    if not a.test_dir: merge_live_soil()
    today = p.utc().astimezone(p.LOCAL).date(); issue = str(today)
    A = load_all(); normal = normal_rain_per_day(A['rain'])
    k = (1 - today.weekday()) % 7 or 7                  # days to the next Tuesday after today
    targets = [today + timedelta(days=k), today + timedelta(days=k + 7)]
    rain, cycle = forecast_rain(today, targets[-1], normal)
    rows = []; missing = []; sources_note = {}
    for unit, maps in A['usdm'].items():
        m0 = max(maps); preds = []; cums = []; cats = []; ahead_src = []; pw = []; pi = []
        for t in targets:
            lead = (t - date.fromisoformat(m0)).days // 7
            if str(lead) not in models: missing.append(dict(id=unit, reason='Target %s is %d weeks after the latest map; no model for that lead' % (t, lead))); break
            days = [str(today + timedelta(days=j)) for j in range((t - today).days + 1)]
            ahead = sum(rain[d] if rain.get(d) is not None else normal for d in days)
            ahead_src.append('%d of %d days NOAA NBM, rest normal' % (sum(rain.get(d) is not None for d in days), len(days)))
            x = drivers(A, unit, m0, issue, str(t), ahead, vegdri=V['vegdri'])
            if x is None: missing.append(dict(id=unit, reason='No current Drought Monitor map')); break
            mm = models[str(lead)]['model']; y = finish(maps[m0] / 100, predict(mm, x[None, :])[0], mm.get('deadband', 0.0))
            w_ = float(prob(models[str(lead)]['worsen'], x[None, :])[0]); i_ = float(prob(models[str(lead)]['improve'], x[None, :])[0])
            step = category(maps[m0] / 100) + (1 if w_ > 0.5 else -1 if i_ > 0.5 else 0)
            preds.append(dsci(y)); cums.append([round(float(v) * 100, 2) for v in y]); cats.append(LEVELS[max(0, min(5, step))])
            pw.append(round(w_, 3)); pi.append(round(i_, 3))
        else:
            rows.append(dict(id=unit, dates=[str(t) for t in targets], prediction=preds, baseline=[dsci(maps[m0] / 100)] * 2,
                             cumulative_percent_d0_to_d4=cums, dominant_class=cats, chance_worse=pw, chance_better=pi, current_map=m0, current_class=LEVELS[category(maps[m0] / 100)],
                             rain_ahead_source=ahead_src, units='DSCI 0-500 (sum of percent of area at D0+..D4+)'))
    folder = p.D / 'snapshots' / p.stamp(); folder.mkdir(parents=True)
    snap = dict(captured_at=p.utc().isoformat(), values={}, grids={}, errors=[], nbm_cycle=cycle, rain_forecast_in=rain,
                inputs={n: p.digest(ROOT / 'data' / n) for n in ('drought/usdm-weekly.csv', 'drought/palmer-divisions.csv', 'drought/soil-moisture-daily.csv',
                                                                  'fire-danger/history.csv', 'water-temp/daily.csv') + (('drought/vegdri-weekly.csv',) if V['vegdri'] else ())})
    snapshot = folder / 'inputs.json'; p.exclusive(snapshot, snap)
    code = folder / 'drought-runner.py'
    with code.open('xb') as f: f.write(Path(__file__).read_bytes())
    p.seal(c, KIND, rows, missing, snapshot, snap, reg_path, model_version=V['version'],
           extra_sources=[dict(path=str(code.relative_to(ROOT)), sha256=p.digest(code)), dict(path=reg['model_path'], sha256=reg['model_sha256'])])
    seen = read(ROOT / 'data/drought/usdm-first-seen.json')
    for unit, maps in A['usdm'].items():
        for d, v in maps.items():
            when = seen.get(unit + '|' + d)
            if when: c.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)', (KIND, unit, d, float(np.sum(v)), when, 'data/drought/usdm-weekly.csv'))
    c.commit(); new = p.score(c)
    issued = c.execute('SELECT path FROM forecasts WHERE substr(issue_day,1,10)=? AND variable=?', (issue, KIND)).fetchone()
    save(p.O / 'last-run.json', dict(completed_at=p.utc().isoformat(), issue_day=issue, targets=[str(t) for t in targets], sealed_today=issued[0] if issued else None,
                                     available_forecasts=len(rows), withheld=missing, new_comparisons=new, nbm_cycle=cycle, model_version=V['version']))
    log('Drought forecast (%s): %d areas for maps %s; %d new comparisons.' % (V['version'], len(rows), ', '.join(str(t) for t in targets), new))
    for r in rows:
        if r['id'] == 'CT' or len(rows) <= 3: print(r['id'], r['current_class'], '->', r['dominant_class'], 'chance worse', r['chance_worse'], 'better', r['chance_better'], r['rain_ahead_source'])


if __name__ == '__main__':
    main()
