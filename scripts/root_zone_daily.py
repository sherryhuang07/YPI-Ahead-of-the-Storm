"""Daily prospective test for the standalone root-zone soil-moisture model.

Separate ledger (data/root-zone-prospective, outputs/root-zone-prospective) built
on the same append-only machinery as prospective_daily.py:

- Each Connecticut day, seal one 14-day forecast (targets start tomorrow) for
  every watershed with a complete 28-day input window ending six days earlier.
- Inputs are the NLDAS-2 daily watershed values assembled beforehand by
  assemble_root_zone_inputs.py live; they are copied into a dated snapshot.
- Later runs record the first captured NLDAS value for each target day and
  score sealed forecasts against it, alongside the unchanged-moisture baseline.
- The trained model is frozen in a registry on first use; any change to it
  stops the run instead of silently switching models. Prospective scores never
  retune it.

Run root-zone-update.ps1 -Step daily (or Run Daily Forecasts.cmd).
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import prospective_daily as p
from statewide_common import ROOT, read, save, log
from root_zone_model import features, predict

INPUTS = ROOT / 'data/root-zone/daily-inputs'
KIND = 'root-zone'


def registry_path():
    path = p.D / 'model-v1.json'
    if not path.exists():
        latest = read(ROOT / 'outputs/root-zone/latest.json')
        run = ROOT / 'outputs/root-zone' / latest['run']
        sealed = read(run / 'manifest.json')
        p.exclusive(path, dict(created_at=p.utc().isoformat(), version='root-zone-v1', trained_run=latest['run'],
                               model_path=str((run / 'model.json').relative_to(ROOT)), model_sha256=sealed['files']['model.json'],
                               policy_path=str((run / 'policy.json').relative_to(ROOT)), policy_sha256=sealed['files']['policy.json'],
                               policy='Frozen coefficients, method choices and bands from the 1980-2014 fit. No refitting or '
                                      'model selection from prospective scores. Inputs: NLDAS-2 v2.0 daily watershed means, UTC-5 day.'))
    reg = read(path)
    for key in ('model', 'policy'):
        if p.digest(ROOT / reg[key + '_path']) != reg[key + '_sha256']:
            raise ValueError('Frozen root-zone %s changed; register a separately tracked model version' % key)
    for issued, in p.db().execute('SELECT path FROM forecasts'):
        for s in read(ROOT / issued)['sources']:
            if s['path'] == str(path.relative_to(ROOT)) and s['sha256'] != p.digest(path):
                raise ValueError('Root-zone model registry changed since an earlier issue')
    return path, reg


def load_inputs(today):
    meta = read(INPUTS / 'latest.json')
    if meta['issue_date'] != str(today):
        raise ValueError('Daily inputs were assembled for %s, not today (%s). Run the input step first.' % (meta['issue_date'], today))
    values = {}
    with (INPUTS / 'latest.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['moisture_m3m3']:
                values.setdefault(r['watershed_id'], {})[r['date']] = float(r['moisture_m3m3'])
    return meta, values


def make_rows(models, policy, values, issue):
    lag = policy['input_lag_days']; cutoff = issue - timedelta(days=lag)
    window = [cutoff - timedelta(days=27 - k) for k in range(28)]
    dates = [str(issue + timedelta(days=h)) for h in policy['horizons_days']]
    rows = []; missing = []
    for sid, per_h in models.items():
        history = values.get(sid, {})
        series = np.array([history.get(str(d), np.nan) for d in window])
        if not np.all(np.isfinite(series)):
            missing.append(dict(id=sid, reason='Incomplete 28-day NLDAS input window ending %s' % cutoff)); continue
        if any(str(h) not in per_h for h in policy['horizons_days']):
            missing.append(dict(id=sid, reason='No trained model for every horizon')); continue
        s = np.concatenate([series, np.full(lag, np.nan)]); idx = len(s) - 1
        pred = []; lower = []; upper = []; methods = []
        for h, day in zip(policy['horizons_days'], dates):
            m = per_h[str(h)]; x = features(s, idx, day, lag)
            v = float(predict(m['model'], x[None, :])[0]) if m['method'] == 'ridge' else float(x[0])
            pred.append(v); lower.append(max(0.0, v - m['interval_radius'])); upper.append(min(1.0, v + m['interval_radius'])); methods.append(m['method'])
        rows.append(dict(id=sid, dates=dates, prediction=pred, baseline=[float(series[-1])] * len(dates), lower=lower, upper=upper,
                         method=methods, source_last_day=str(cutoff), units='m3/m3 (0-100 cm watershed mean, NLDAS-2 Noah)'))
    return rows, missing


def interval_coverage(c):
    """Share of scored cases whose observation fell inside the sealed nominal 90% band."""
    inside = total = 0
    bands = {}
    for path, sha in c.execute('SELECT path,sha256 FROM forecasts WHERE sha256 NOT IN (SELECT forecast_sha FROM exclusions)'):
        for r in read(ROOT / path)['forecasts']:
            for d, lo, hi in zip(r['dates'], r['lower'], r['upper']):
                bands[(sha, r['id'], d)] = (lo, hi)
    for sha, loc, day, obs in c.execute('SELECT forecast_sha,location,day,observed FROM scores'):
        lo, hi = bands[(sha, loc, day)]; total += 1; inside += lo <= obs <= hi
    return dict(scored=total, inside_nominal_90=inside, coverage=inside / total if total else None)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--test-dir', help='Write the ledger to this throwaway folder instead (dry runs and tests).')
    args = ap.parse_args()
    base = Path(args.test_dir) if args.test_dir else None
    p.D = base / 'data' if base else ROOT / 'data/root-zone-prospective'
    p.O = base / 'outputs' if base else ROOT / 'outputs/root-zone-prospective'
    p.O.mkdir(parents=True, exist_ok=True); p.D.mkdir(parents=True, exist_ok=True)
    c = p.db(); p.verify(c)
    reg_path, reg = registry_path()
    models = read(ROOT / reg['model_path']); policy = read(ROOT / reg['policy_path'])
    today = p.utc().astimezone(p.LOCAL).date()
    meta, values = load_inputs(today)
    folder = p.D / 'snapshots' / p.stamp(); folder.mkdir(parents=True)
    # Capture time is when the NLDAS inputs were assembled, which precedes issuance.
    snap = dict(captured_at=meta['created_at'], values={KIND: values}, grids={}, errors=[], input_metadata=meta,
                purpose='Root-zone soil moisture only; separate from precipitation, groundwater and streamflow ledgers')
    snapshot = folder / 'inputs.json'; p.exclusive(snapshot, snap)
    code = folder / 'root-zone-runner.py'
    with code.open('xb') as f: f.write(Path(__file__).read_bytes())
    extra = [dict(path=str(code.relative_to(ROOT)), sha256=p.digest(code)),
             dict(path=reg['model_path'], sha256=reg['model_sha256']),
             dict(path='data/root-zone/basins/weights.json', sha256=p.digest(ROOT / 'data/root-zone/basins/weights.json'))]
    check = ROOT / 'data/root-zone/daily-inputs/archive-check.json'
    if check.exists(): extra.append(dict(path=str(check.relative_to(ROOT)), sha256=p.digest(check)))
    rows, missing = make_rows(models, policy, values, today)
    p.seal(c, KIND, rows, missing, snapshot, snap, reg_path, model_version='root-zone-v1', extra_sources=extra)
    p.record_observations(c, snap, snapshot, {}); new = p.score(c)
    board = read(p.O / 'scoreboard.json'); board['interval'] = interval_coverage(c)
    board['note'] = ('Targets are the first captured NLDAS-2 watershed values (modeled moisture, not sensors). '
                     'Overlapping 14-day windows and correlated watersheds are not independent tests.')
    save(p.O / 'scoreboard.json', board)
    issued_today = c.execute('SELECT path FROM forecasts WHERE substr(issue_day,1,10)=? AND variable=?', (str(today), KIND)).fetchone()
    save(p.O / 'last-run.json', dict(completed_at=p.utc().isoformat(), issue_day=str(today), snapshot=str(snapshot.relative_to(ROOT)),
                                     sealed_today=issued_today[0] if issued_today else None, available_forecasts=len(rows),
                                     unavailable_forecasts=len(missing), new_comparisons=new, input_window=meta['required_window'],
                                     newest_input_day=meta['last_day'], model_version='root-zone-v1', source_errors=[]))
    log('Root-zone daily test: %d watershed forecasts sealed or already present for %s; %d new comparisons.' % (len(rows), today, new))


if __name__ == '__main__':
    main()
