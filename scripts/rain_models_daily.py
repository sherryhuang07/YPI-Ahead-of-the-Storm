"""Daily sealed forecasts from the rain-aware v2 models (streams and wells), in their own ledgers.

  rain_models_daily.py --kind groundwater   (night part, after the v1 issue and the NOAA rain download)
  rain_models_daily.py --kind streamflow    (morning part, after v1 streams)

Inputs are the same readings v1 just used (the newest prospective snapshot; wells add the stored
2001-2026 history for their one-year average), plus rain from site_rain.live_series: station rain,
then PRISM, then NOAA NBM (cycle issued by 7 AM yesterday), then normal. Rain ahead counts the
first 10 days, as in training; when NOAA does not cover all of them the model uses its "no rain
forecast" inputs (the month's typical values), which is how its normal-rain test was run.

Ledgers: data/<kind>-v2-prospective, outputs/<kind>-v2-prospective; same sealing, no-backdating
and scoring rules as every other ledger. Observations are copied from the v1 ledger with their
original capture times. Baseline = the last reading ("no change"), as for v1.
"""
import argparse
import glob
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import prospective_daily as p
from statewide_common import ROOT, read, save, log
from site_rain import live_series, window_sum

CFG = {'streamflow': dict(trained='outputs/streamflow-v2', version='streamflow-v2', key='gauge_id', horizon=10),
       'groundwater': dict(trained='outputs/groundwater-v2', version='groundwater-v2', key='id', horizon=10)}
LEADS = list(range(2, 16))


def registry(kind):
    path = p.D / 'model-v2.json'
    if not path.exists():
        t = read(ROOT / CFG[kind]['trained'] / 'latest.json'); run = ROOT / CFG[kind]['trained'] / 'runs' / t['run']
        man = read(run / 'manifest.json')
        p.exclusive(path, dict(created_at=p.utc().isoformat(), version=CFG[kind]['version'], trained_run=t['run'],
                               results_path=str((run / 'results.json').relative_to(ROOT)), results_sha256=man['files']['results.json'],
                               adopt=t['adopt'], adopt_rule=t['policy']['adopt_rule']))
    reg = read(path)
    if p.digest(ROOT / reg['results_path']) != reg['results_sha256']: raise ValueError('Frozen %s v2 model changed' % kind)
    return path, reg


def lin(model, x):
    z = np.r_[1.0, (np.asarray(x) - np.array(model['mean'])) / np.array(model['scale'])]
    return float(z @ np.array(model['beta'])[:, 0])


def ahead(r, src, i, L, normal_row, horizon):
    h = min(L, horizon); window = range(i + 1, i + h + 1)
    if any(src[j] in ('normal',) for j in window) or i + h >= len(r):
        return list(normal_row), 'no rain forecast (typical values)'
    return [np.log1p(window_sum(r, i + h, h)), np.log1p(window_sum(r, i + h, min(3, h)))], 'rain: ' + '/'.join(sorted({src[j] for j in window}))


def well_history(wid, snap_vals):
    run = sorted(glob.glob(str(ROOT / 'data/groundwater-history/*/manifest.json')))[-1].rsplit('manifest.json', 1)[0]
    h = {}
    for f in read(run + wid + '.json')['features']:
        pr = f['properties']
        if not pr.get('qualifier') and pr.get('value') not in (None, ''): h[pr['time'][:10]] = float(pr['value'])
    h.update({k: float(v) for k, v in snap_vals.items()})
    return h


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--kind', choices=sorted(CFG), required=True); ap.add_argument('--test-dir'); a = ap.parse_args()
    kind = a.kind; cfg = CFG[kind]; base = Path(a.test_dir) if a.test_dir else None
    p.D = base / 'data' if base else ROOT / ('data/%s-v2-prospective' % kind)
    p.O = base / 'outputs' if base else ROOT / ('outputs/%s-v2-prospective' % kind)
    p.D.mkdir(parents=True, exist_ok=True); p.O.mkdir(parents=True, exist_ok=True)
    c = p.db(); p.verify(c); reg_path, reg = registry(kind)
    models = {r[cfg['key']]: r for r in read(ROOT / reg['results_path']) if r.get('status') == 'trained'}
    last_run = read(ROOT / 'outputs/prospective/last-run.json'); snapshot_in = read(ROOT / last_run['snapshot'])
    now = p.utc(); today = now.astimezone(p.LOCAL).date()
    rain, cycle = live_series(today)
    rows = []; missing = []
    for sid, m in models.items():
        try:
            vals = snapshot_in['values'][kind].get(sid)
            if not vals: raise ValueError('No current readings in the snapshot')
            hist = well_history(sid, vals) if kind == 'groundwater' else {k: float(v) for k, v in vals.items()}
            last = date.fromisoformat(max(hist)); age = (today - last).days
            if age != 1: raise ValueError('Needs yesterday\'s reading (latest is %s)' % last)
            R = rain[sid]; days = R['days']; i = days.index(str(last)); r = R['rain']; src = R['source']
            month = str(last.month)
            if kind == 'streamflow':
                q = np.array([hist.get(str(last - timedelta(days=27 - k)), np.nan) for k in range(28)])
                if not np.isfinite(q).all(): raise ValueError('Recent 28-day flow window is incomplete')
                z = np.log1p(q); doy = last.timetuple().tm_yday
                xb = [z[-1 - k] for k in [0, 1, 2, 6, 13, 27]] + [np.mean(z[-k:]) for k in [7, 14, 28]] + [np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)]
                past = [np.log1p(window_sum(r, i, n)) for n in (1, 3, 7, 30)]; base_value = float(q[-1])
            else:
                dd = np.array([hist.get(str(last - timedelta(days=364 - k)), np.nan) for k in range(365)])
                if np.isfinite(dd).sum() < 200: raise ValueError('Fewer than 200 readings in the last year')
                def back(k):
                    for j in range(3):
                        v = hist.get(str(last - timedelta(days=k + j)))
                        if v is not None: return v
                    return np.nan
                doy = last.timetuple().tm_yday; d0 = dd[-1]
                xb = [d0, d0 - back(7), d0 - back(30), d0 - np.nanmean(dd), np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)]
                past = [np.log1p(window_sum(r, i, n)) for n in (7, 30, 90)]; base_value = float(d0)
            if not np.isfinite(xb + past).all(): raise ValueError('Level or past-rain inputs incomplete')
            pred = []; lo = []; hi = []; how = []
            for k, L in enumerate(LEADS):
                normal_row = np.array(m['normal_ahead'][month])[k] if month in m['normal_ahead'] else np.mean([np.array(v)[k] for v in m['normal_ahead'].values()], 0)
                ah, note = ahead(r, src, i, L, normal_row, cfg['horizon']); how.append(note)
                y = lin(m['models'][k], xb + past + ah)
                if kind == 'streamflow':
                    w = m['band_log_width'][k]; pred.append(float(np.expm1(np.clip(y, 0, 20)))); lo.append(float(np.expm1(np.clip(y - w, 0, 20)))); hi.append(float(np.expm1(np.clip(y + w, 0, 20))))
                else:
                    w = m['band_width_ft'][k]; pred.append(base_value + y); lo.append(base_value + y - w); hi.append(base_value + y + w)
            dates = [str(today + timedelta(days=j)) for j in range(1, 15)]
            rows.append(dict(id=sid, name=m.get('name', sid), dates=dates, prediction=pred, lower_90=lo, upper_90=hi, baseline=[base_value] * 14,
                             source_last_day=str(last), rain_inputs=how, units='cfs' if kind == 'streamflow' else 'feet below land surface at monitored well'))
        except (ValueError, KeyError) as e:
            missing.append(dict(id=sid, reason=str(e)))
    folder = p.D / 'snapshots' / p.stamp(); folder.mkdir(parents=True)
    snap = dict(captured_at=snapshot_in['captured_at'], values={}, grids={}, errors=[], readings_snapshot=last_run['snapshot'], nbm_cycle=cycle,
                rain={sid: dict(days=v['days'][-30:], mm=[round(float(x), 2) for x in v['rain'][-30:]], source=v['source'][-30:]) for sid, v in rain.items() if sid in models})
    snapshot = folder / 'inputs.json'; p.exclusive(snapshot, snap)
    code = folder / 'rain-models-runner.py'
    with code.open('xb') as fh: fh.write(Path(__file__).read_bytes())
    p.seal(c, kind, rows, missing, snapshot, snap, reg_path, model_version=reg['version'],
           extra_sources=[dict(path=reg['results_path'], sha256=reg['results_sha256']), dict(path=str(code.relative_to(ROOT)), sha256=p.digest(code))])
    base_db = __import__('sqlite3').connect('file:%s?mode=ro' % (ROOT / 'data/prospective/ledger.sqlite').as_posix(), uri=True)
    wanted = {}
    for fpath, in c.execute('SELECT path FROM forecasts'):
        for rr in read(ROOT / fpath)['forecasts']: wanted.setdefault(rr['id'], set()).update(rr['dates'])
    for row in base_db.execute('SELECT variable,location,day,value,captured_at,snapshot FROM observations WHERE variable=?', (kind,)):
        if row[2] in wanted.get(row[1], ()): c.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)', row)
    c.commit(); new = p.score(c)
    issued = c.execute('SELECT path FROM forecasts WHERE substr(issue_day,1,10)=? AND variable=?', (str(today), kind)).fetchone()
    save(p.O / 'last-run.json', dict(completed_at=p.utc().isoformat(), issue_day=str(today), sealed_today=issued[0] if issued else None, model_version=reg['version'],
                                     adopted_for_app=reg['adopt'], locations=len(rows), withheld=missing, nbm_cycle=cycle, new_comparisons=new))
    log('%s v2 (with rain): %d sealed, %d withheld; NOAA cycle %s; %d new comparisons.' % (kind, len(rows), len(missing), cycle, new))


if __name__ == '__main__':
    main()
