"""Daily sealed test of the NOAA NBM rain forecast the farmer app shows.

The NBM issue (scripts/fetch_noaa_precip.py, run by prospective_daily.py) stores rain totals on
PRISM's day, 12:00 UTC to 12:00 UTC (7 AM to 7 AM in Connecticut winter) labelled by its end date,
built only from direct NBM rain amounts (no probability fallback, no PRISM blending). This script
seals those totals once per Connecticut day in its own append-only ledger (data/noaa-rain-prospective,
outputs/noaa-rain-prospective), with the same rules as every other ledger: only PRISM days that
start after the seal, no edits, scored only with PRISM values first captured after issue.

Comparison ("baseline"): the location's average rain over the last 14 PRISM days, the same rival
the original history-only rain forecast is scored against. Run after prospective_daily.py.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import prospective_daily as p
from statewide_common import ROOT, read, save, log

KIND = 'precipitation'
NBM = ROOT / 'outputs/forecasts/precipitation/noaa-live/latest.json'


def registry():
    path = p.D / 'model-v1.json'
    if not path.exists():
        p.exclusive(path, dict(created_at=p.utc().isoformat(), version='noaa-rain-v1', source='NOAA National Blend of Models CONUS QPF (scripts/fetch_noaa_precip.py)',
                               target='PRISM daily precipitation (mm), 12:00-12:00 UTC day labelled by its end date, first captured value',
                               prediction='Sum of non-overlapping direct NBM QPF intervals falling in that PRISM day; days without 24 h of direct QPF are not forecast',
                               baseline='Mean of the last 14 PRISM days at the location'))
    return path


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--test-dir'); a = ap.parse_args()
    base = Path(a.test_dir) if a.test_dir else None
    p.D = base / 'data' if base else ROOT / 'data/noaa-rain-prospective'
    p.O = base / 'outputs' if base else ROOT / 'outputs/noaa-rain-prospective'
    p.D.mkdir(parents=True, exist_ok=True); p.O.mkdir(parents=True, exist_ok=True)
    c = p.db(); p.verify(c); reg = registry()
    pointer = read(NBM); issue_path = ROOT / pointer['path']
    if p.digest(issue_path) != pointer['sha256']: raise ValueError('NOAA rain issue changed after it was written: ' + pointer['path'])
    nbm = read(issue_path); now = p.utc()
    prospective = read(ROOT / 'outputs/prospective/last-run.json'); snap_in = read(ROOT / prospective['snapshot'])
    hist = p.grid_values(snap_in)
    rows = []; missing = []
    for f in nbm['forecasts']:
        days = {d: v for d, v in (f.get('prism_day_precipitation_mm') or {}).items() if p.target_start(KIND, d) > now}
        if not days: missing.append(dict(id=f['id'], reason='No complete PRISM day of direct NBM rain after this issue')); continue
        h = hist.get(f['id'], {}); last = max(h) if h else None
        recent = [h.get(str(date.fromisoformat(last) - timedelta(days=i))) for i in range(14)] if last else []
        if len(recent) != 14 or any(v is None for v in recent): missing.append(dict(id=f['id'], reason='14-day PRISM comparison window incomplete')); continue
        ds = sorted(days)
        rows.append(dict(id=f['id'], dates=ds, prediction=[float(days[d]) for d in ds], baseline=[float(np.mean(recent))] * len(ds),
                         nbm_cycle=nbm['cycle'], units='mm per PRISM day (12:00-12:00 UTC)', method='NOAA NBM direct QPF'))
    folder = p.D / 'snapshots' / p.stamp(); folder.mkdir(parents=True)
    snap = dict(captured_at=nbm['retrieved_at'], values={}, grids={}, errors=[], nbm_issue=dict(path=pointer['path'], sha256=pointer['sha256'], cycle=nbm['cycle']),
                prism_snapshot=prospective['snapshot'])
    snapshot = folder / 'inputs.json'; p.exclusive(snapshot, snap)
    code = folder / 'noaa-rain-runner.py'
    with code.open('xb') as fh: fh.write(Path(__file__).read_bytes())
    p.seal(c, KIND, rows, missing, snapshot, snap, reg, model_version='noaa-rain-v1',
           extra_sources=[dict(path=pointer['path'], sha256=pointer['sha256']), dict(path=str(code.relative_to(ROOT)), sha256=p.digest(code))])
    # Observations: PRISM values from the main ledger with their original capture times.
    base_db = __import__('sqlite3').connect('file:%s?mode=ro' % (ROOT / 'data/prospective/ledger.sqlite').as_posix(), uri=True)
    wanted = {}
    for fpath, in c.execute('SELECT path FROM forecasts'):
        for r in read(ROOT / fpath)['forecasts']: wanted.setdefault(r['id'], set()).update(r['dates'])
    days = sorted(set().union(*wanted.values())) if wanted else []
    if days:
        for row in base_db.execute("SELECT variable,location,day,value,captured_at,snapshot FROM observations WHERE variable='precipitation' AND day>=?", (days[0],)):
            if row[2] in wanted.get(row[1], ()): c.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)', row)
    c.commit(); new = p.score(c)
    today = str(now.astimezone(p.LOCAL).date())
    issued = c.execute('SELECT path FROM forecasts WHERE substr(issue_day,1,10)=? AND variable=?', (today, KIND)).fetchone()
    save(p.O / 'last-run.json', dict(completed_at=p.utc().isoformat(), issue_day=today, sealed_today=issued[0] if issued else None, locations=len(rows),
                                     withheld=len(missing), nbm_cycle=nbm['cycle'], new_comparisons=new))
    log('NOAA rain test: %d locations sealed for PRISM days %s; %d new comparisons scored.' % (len(rows), ', '.join(rows[0]['dates'][:1] + rows[0]['dates'][-1:]) if rows else '-', new))


if __name__ == '__main__':
    main()
