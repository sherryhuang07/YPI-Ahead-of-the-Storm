"""Daily sealed 14-day coastal water temperature forecast (separate append-only ledger).

Run after `fetch_water_temp.py --recent`. Uses prospective_daily.py's sealing rules
(data/water-temp-prospective, outputs/water-temp-prospective). Each Connecticut day:
yesterday is the last input day; forecasts cover tomorrow through 14 days ahead (leads 2-15
from the last input), per station, with the frozen model from train_water_temp.py. A
station whose yesterday reading is missing is withheld for the day, never filled. Later
runs record each target day's first captured daily mean and score sealed forecasts against
it, beside "unchanged since yesterday".
"""
import argparse
import csv
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import prospective_daily as p
from statewide_common import ROOT, read, save, log
from water_temp_model import normal, features, design, predict

KIND = 'water-temp'; WT = ROOT / 'data/water-temp'


def registry():
    path = p.D / 'model-v1.json'
    if not path.exists():
        latest = read(ROOT / 'outputs/water-temp/latest.json'); run = ROOT / 'outputs/water-temp/runs' / latest['run']; sealed = read(run / 'manifest.json')
        p.exclusive(path, dict(created_at=p.utc().isoformat(), version='water-temp-v1', trained_run=latest['run'],
                               model_path=str((run / 'model.json').relative_to(ROOT)), model_sha256=sealed['files']['model.json'],
                               policy_path=str((run / 'policy.json').relative_to(ROOT)), policy_sha256=sealed['files']['policy.json'],
                               policy='Frozen normals, weights, method choices and bands; never refit from prospective scores.'))
    reg = read(path)
    for k in ('model', 'policy'):
        if p.digest(ROOT / reg[k + '_path']) != reg[k + '_sha256']: raise ValueError('Frozen water temperature %s changed' % k)
    return path, reg


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--test-dir'); a = ap.parse_args()
    base = Path(a.test_dir) if a.test_dir else None
    p.D = base / 'data' if base else ROOT / 'data/water-temp-prospective'
    p.O = base / 'outputs' if base else ROOT / 'outputs/water-temp-prospective'
    p.D.mkdir(parents=True, exist_ok=True); p.O.mkdir(parents=True, exist_ok=True)
    c = p.db(); p.verify(c); reg_path, reg = registry()
    models = read(ROOT / reg['model_path']); policy = read(ROOT / reg['policy_path'])
    today = p.utc().astimezone(p.LOCAL).date(); last = today - timedelta(days=1)
    start = last - timedelta(days=59); days = [str(start + timedelta(days=k)) for k in range(60)]
    values = {}
    for r in csv.DictReader((WT / 'daily.csv').open(encoding='utf-8')):
        if start <= date.fromisoformat(r['date']) <= last: values.setdefault(r['station'], {})[r['date']] = float(r['water_temp_c'])
    folder = p.D / 'snapshots' / p.stamp(); folder.mkdir(parents=True)
    snap = dict(captured_at=p.utc().isoformat(), values={KIND: values}, grids={}, errors=[], daily_sha256=p.digest(WT / 'daily.csv'))
    snapshot = folder / 'inputs.json'; p.exclusive(snapshot, snap)
    code = folder / 'water-temp-runner.py'
    with code.open('xb') as f: f.write(Path(__file__).read_bytes())
    rows = []; missing = []; dates = [str(today + timedelta(days=h)) for h in range(1, 15)]
    for s, m in models.items():
        t = np.array([values.get(s, {}).get(d, np.nan) for d in days]); nv = normal(np.array(m['normal']), days)
        f = features(t, len(days) - 1, nv, days)
        if f is None: missing.append(dict(id=s, reason='Missing yesterday or under 5 of the last 7 daily readings')); continue
        if any(str(h + 1) not in m['leads'] for h in range(1, 15)): missing.append(dict(id=s, reason='No trained model for every forecast day')); continue
        pred = []; lo = []; hi = []; meth = []
        for h, d in enumerate(dates, 1):
            lm = m['leads'][str(h + 1)]
            v = float(predict(lm['model'], design(f, d)[None, :])[0] + normal(np.array(m['normal']), [d])[0]) if lm['method'] == 'ridge' else float(t[-1])
            pred.append(v); lo.append(v - lm['radius']); hi.append(v + lm['radius']); meth.append(lm['method'])
        rows.append(dict(id=s, dates=dates, prediction=pred, baseline=[float(t[-1])] * 14, lower=lo, upper=hi, method=meth,
                         source_last_day=str(last), units='degrees C, daily mean water temperature'))
    p.seal(c, KIND, rows, missing, snapshot, snap, reg_path, model_version='water-temp-v1',
           extra_sources=[dict(path=str(code.relative_to(ROOT)), sha256=p.digest(code)), dict(path=reg['model_path'], sha256=reg['model_sha256'])])
    p.record_observations(c, snap, snapshot, {}); new = p.score(c)
    issued = c.execute('SELECT path FROM forecasts WHERE substr(issue_day,1,10)=? AND variable=?', (str(today), KIND)).fetchone()
    save(p.O / 'last-run.json', dict(completed_at=p.utc().isoformat(), issue_day=str(today), sealed_today=issued[0] if issued else None,
                                     available_forecasts=len(rows), unavailable_forecasts=len(missing), withheld=missing, new_comparisons=new, model_version='water-temp-v1'))
    log('Water temperature daily test: %d stations forecast, %d withheld for %s; %d new comparisons.' % (len(rows), len(missing), today, new))


if __name__ == '__main__':
    main()
