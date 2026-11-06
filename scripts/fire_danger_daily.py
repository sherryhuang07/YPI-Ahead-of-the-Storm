"""Daily sealed 14-day Connecticut fire danger forecast, scored against DEEP's published ratings.

Run order (daily-forecasts.ps1, night part): archive DEEP's latest report, refresh the last
45 days of airport weather, rebuild the index history, then this script, which issues the
forecast from fire_danger_forecast.forecast() and seals it with prospective_daily.py's
append-only rules (data/fire-danger-prospective, outputs/fire-danger-prospective).

Each day is one statewide value: the forecast class as a number (0 LOW .. 4 EXTREME; an
expected value on climatology days). Baseline: yesterday's rebuilt class, unchanged.
Observations are DEEP's published ratings, with their capture times, so a forecast is scored
only by ratings captured after it was issued. DEEP publishes mainly during fire seasons
and high-danger periods, so many days have no DEEP rating and stay unscored.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import prospective_daily as p
from statewide_common import ROOT, read, save, log
from fire_danger_forecast import forecast, load_history, POLICY, OUT as FOUT
from fire_danger_model import LEVELS

KIND = 'fire-danger'; LOCATION = 'connecticut-statewide'


def registry():
    path = p.D / 'model-v1.json'
    if not path.exists():
        latest = read(FOUT / 'latest-test.json'); run = FOUT / 'runs' / latest['run']; sealed = read(run / 'manifest.json')
        p.exclusive(path, dict(created_at=p.utc().isoformat(), version=POLICY['version'], policy=POLICY, test_run=latest['run'],
                               transitions=str((run / 'transitions.npy').relative_to(ROOT)), transitions_sha256=sealed['files']['transitions.npy'],
                               validation=str((ROOT / 'data/fire-danger/validation.json').relative_to(ROOT))))
    reg = read(path)
    if p.digest(ROOT / reg['transitions']) != reg['transitions_sha256']: raise ValueError('Frozen fire-danger transitions changed')
    if reg['policy'] != POLICY: raise ValueError('Fire-danger policy in code differs from the frozen registry; register a new version')
    return path, reg


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--test-dir'); a = ap.parse_args()
    base = Path(a.test_dir) if a.test_dir else None
    p.D = base / 'data' if base else ROOT / 'data/fire-danger-prospective'
    p.O = base / 'outputs' if base else ROOT / 'outputs/fire-danger-prospective'
    p.D.mkdir(parents=True, exist_ok=True); p.O.mkdir(parents=True, exist_ok=True)
    c = p.db(); p.verify(c); reg_path, reg = registry()
    today = str(p.utc().astimezone(p.LOCAL).date())
    already = c.execute('SELECT 1 FROM forecasts WHERE substr(issue_day,1,10)=? AND variable=?', (today, KIND)).fetchone()
    folder = p.D / 'snapshots' / p.stamp(); folder.mkdir(parents=True); rows = []; missing = []; errors = []
    if not already:
        try:
            f = forecast(); rows_hist, days, cls = load_history()
            persistence = float(cls[-1]) if not np.isnan(cls[-1]) else None
            if persistence is None: raise ValueError('Yesterday has no rebuilt rating (incomplete airport weather)')
            snap = dict(captured_at=p.utc().isoformat(), values={}, grids={}, errors=[], forecast=f,
                        history_sha256=p.digest(ROOT / 'data/fire-danger/history.csv'))
            snapshot = folder / 'inputs.json'; p.exclusive(snapshot, snap)
            rows = [dict(id=LOCATION, dates=[x['date'] for x in f['forecasts']], prediction=[float(x['level_index']) for x in f['forecasts']],
                         baseline=[persistence] * len(f['forecasts']), levels=[x['level'] for x in f['forecasts']],
                         spread_index=[x.get('spread_index') for x in f['forecasts']], buildup_index=[x.get('buildup_index') for x in f['forecasts']],
                         methods=[x['method'] for x in f['forecasts']], units='class number: 0 LOW, 1 MODERATE, 2 HIGH, 3 VERY HIGH, 4 EXTREME')]
        except Exception as e:
            # Not sealed: a transient source failure must not lock in an empty issue for the day;
            # a later run the same day may still issue (targets still start tomorrow).
            errors.append('%s: %s' % (type(e).__name__, e))
        if not errors:
            code = folder / 'fire-runner.py'
            with code.open('xb') as fh: fh.write(Path(__file__).read_bytes())
            p.seal(c, KIND, rows, missing, snapshot, snap, reg_path, model_version=POLICY['version'],
                   extra_sources=[dict(path=str(code.relative_to(ROOT)), sha256=p.digest(code)), dict(path=reg['transitions'], sha256=reg['transitions_sha256'])])
    deep = read(ROOT / 'data/fire-danger/deep-ratings.json')['ratings']
    for d, v in deep.items():
        c.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)', (KIND, LOCATION, d, float(v['level_index']), v['captured_at'], v['raw']))
    c.commit(); new = p.score(c)
    issued = c.execute('SELECT path FROM forecasts WHERE substr(issue_day,1,10)=? AND variable=?', (today, KIND)).fetchone()
    save(p.O / 'last-run.json', dict(completed_at=p.utc().isoformat(), issue_day=today, sealed_today=issued[0] if issued else None,
                                     new_comparisons=new, source_errors=errors, model_version=POLICY['version']))
    log('Fire danger daily test: forecast %s for %s; %d new comparisons with DEEP ratings.' % ('sealed or present' if issued else 'withheld', today, new))
    if errors: raise SystemExit('Fire danger forecast withheld: ' + '; '.join(errors))


if __name__ == '__main__':
    main()
