"""Replay the live record to compare learning policies on exactly the same forecasts.

For every scored comparison in an original ledger (streams, neighboring-state streams, wells), in time
order: a learning policy may use only lessons scored before that forecast was issued (no look-ahead in
the weights). Policies:
  v1  correction applied in full from the first lesson (one correction per site and forecast day)
  v2  the same, held back to n/(n+30)
  v3  separate DRY and WET corrections (context rain < 5 mm or >= 5 mm: the 3 days up to the last
      reading plus the days to the target, within NOAA's 10-day reach), held back to n/(n+30)
  v3+ v3 plus the gut-check rules (outputs/reasoning/rules.json)
Lessons are filed under the weather that actually happened. When applying, the forecast's weather is
needed: forecasts issued from Nov 12 have their sealed NOAA rain (v2 snapshots); for earlier ones the
rain that fell stands in (a perfect rain forecast), so those days flatter v3 a little; both are reported.
"""
import json, sqlite3, glob
from collections import defaultdict
from datetime import date, datetime, timedelta
import numpy as np
from statewide_common import ROOT, read
import learning_daily as L
from site_rain import history as rain_history
from reasoning_rules import guard, HORIZON

NORMALS = {}
WET_SPLIT = 1.0   # ratio to the site's normal rain for the window


def sealed_rain(v2_dir):
    """(issue day, site) -> {day: mm} from the rain stored with each sealed v2 forecast (forecast rain)."""
    out = {}
    for f in glob.glob(str(ROOT / v2_dir / 'snapshots' / '*' / 'inputs.json')):
        s = read(f)
        if 'rain' not in s: continue
        day = datetime.fromisoformat(s['captured_at']).astimezone(__import__('prospective_daily').LOCAL).date()
        for sid, v in s['rain'].items(): out[(str(day), sid)] = dict(zip(v['days'], v['mm']))
    return out


def ctx(rain_obs, start, sealed, issue_day, sid, i, Lr):
    """Context rain for last-reading index i and Lr days ahead; forecast rain if sealed, else what fell."""
    days = [start + timedelta(days=k) for k in range(i - 2, i + min(Lr, HORIZON) + 1)]
    s = sealed.get((issue_day, sid))
    vals = []
    for d in days:
        v = s.get(str(d)) if s else None
        if v is None:
            k = (d - start).days; v = rain_obs[k] if 0 <= k < len(rain_obs) and np.isfinite(rain_obs[k]) else None
        if v is None: return np.nan, bool(s)
        vals.append(v)
    return float(sum(vals)), bool(s)


def replay(ledger, variable, rain_set, v2_dir, rules_set, cfg_name):
    cfg = L.MODELS[cfg_name]; c = sqlite3.connect('file:%s?mode=ro' % (ROOT / ledger / 'ledger.sqlite').as_posix(), uri=True)
    issued = {sha: (t, path) for sha, t, path in c.execute('SELECT sha256, issued_at, path FROM forecasts')}
    rows = c.execute('SELECT forecast_sha, location, day, lead, predicted, observed, scored_at FROM scores WHERE variable=?', (variable,)).fetchall()
    rain, start = rain_history(rain_set); sealed = sealed_rain(v2_dir)
    from site_rain import normal_by_month
    NORMALS.clear(); NORMALS.update({k: normal_by_month(v, start) for k, v in rain.items()})
    rules = read(ROOT / 'outputs/reasoning/rules.json')['sets'][rules_set]['rules']
    last_reading = {}
    for sha, (t, path) in issued.items():
        for f in read(ROOT / path)['forecasts']: last_reading[(sha, f['id'])] = (f['baseline'][0], f['source_last_day'])
    events = []
    for sha, loc, day, lead, pred, obs, scored in rows:
        events.append((issued[sha][0], 0, (sha, loc, day, lead, pred, obs)))       # forecast made
        events.append((scored, 1, (sha, loc, day, lead, pred, obs)))               # lesson available
    events.sort(key=lambda e: (e[0], e[1]))
    pols = {k: L.Weights(ROOT / 'tmp/none.npz') for k in ('v1', 'v2', 'v3')}
    tf = lambda v: float(L.fwd(v, cfg['transform'])); sc = cfg['scale']
    res = defaultdict(list); sealed_used = []
    def regime(sha, loc, day, lead):
        base, last_day = last_reading.get((sha, loc), (None, None))
        if last_day is None: return None, np.nan, False
        i = (date.fromisoformat(last_day) - start).days; Lr = (date.fromisoformat(day) - date.fromisoformat(last_day)).days
        r = rain.get(loc)
        if r is None: return None, np.nan, False
        issue_day = issued[sha][0][:10]
        cr, was_sealed = ctx(r, start, sealed, str((datetime.fromisoformat(issued[sha][0]).astimezone(__import__('prospective_daily').LOCAL)).date()), loc, i, Lr)
        nm = NORMALS[loc][date.fromisoformat(last_day).month] * (min(Lr, HORIZON) + 3)
        return ('wet' if cr >= WET_SPLIT * nm else 'dry') if np.isfinite(cr) else None, cr, was_sealed
    for _, kind, (sha, loc, day, lead, pred, obs) in events:
        reg, cr, was_sealed = regime(sha, loc, day, lead)
        keys = {'v1': loc, 'v2': loc, 'v3': loc + '|' + (reg or 'dry')}
        if kind == 1:          # learn: lesson filed under the weather that happened (observed rain)
            obs_reg, _, _ = regime_observed(rain, start, last_reading, sha, loc, day)
            keys['v3'] = loc + '|' + (obs_reg or 'dry')
            for k, w in pols.items():
                w.ensure({keys[k]: tf(pred)}); w.update(keys[k], int(lead), tf(pred), tf(obs), sc, cfg.get('error_cap'))
            continue
        out = {}
        for k, w in pols.items():
            ev = 0 if k == 'v1' else 30
            L.POLICY['evidence_days'] = ev
            y = L.inv(w.apply(keys[k], int(lead), tf(pred), sc), cfg['transform'])
            out[k] = max(cfg['low'], y) if cfg['low'] is not None else y
        L.POLICY['evidence_days'] = 30
        base, last_day = last_reading.get((sha, loc), (None, None))
        Lr = (date.fromisoformat(day) - date.fromisoformat(last_day)).days if last_day else 99
        g, note = guard(out['v3'], base, rules.get(loc, {}).get(str(Lr)), cr, variable) if (base is not None and Lr <= HORIZON) else (out['v3'], None)
        out['v3+'] = g
        for k, v in out.items(): res[k].append(abs(v - obs))
        res['original'].append(abs(pred - obs)); res['day'].append(day); res['sealed'].append(was_sealed); res['guarded'].append(note is not None)
    return res


def regime_observed(rain, start, last_reading, sha, loc, day):
    base, last_day = last_reading.get((sha, loc), (None, None)); r = rain.get(loc)
    if last_day is None or r is None: return None, np.nan, False
    i = (date.fromisoformat(last_day) - start).days; Lr = (date.fromisoformat(day) - date.fromisoformat(last_day)).days
    days = range(i - 2, i + min(Lr, HORIZON) + 1)
    v = [r[k] for k in days if 0 <= k < len(r)]
    if len(v) != len(days) or not np.isfinite(v).all(): return None, np.nan, False
    s = float(sum(v)); nm = NORMALS[loc][date.fromisoformat(last_day).month] * (min(Lr, HORIZON) + 3)
    return ('wet' if s >= WET_SPLIT * nm else 'dry'), s, False


def main():
    report = {}
    for name, ledger, var, rset, v2dir, rules_set, cfgn in (
            ('Connecticut streams', 'data/prospective', 'streamflow', 'site-rain', 'data/streamflow-v2-prospective', 'streamflow', 'streamflow'),
            ('Neighboring-state streams', 'data/regional-prospective', 'streamflow', 'site-rain-regional', 'data/regional-streamflow-v2-prospective', 'regional-streamflow', 'regional-streamflow'),
            ('Wells', 'data/prospective', 'groundwater', 'site-rain', 'data/groundwater-v2-prospective', 'groundwater', 'groundwater')):
        r = replay(ledger, var, rset, v2dir, rules_set, cfgn)
        m = {k: float(np.mean(r[k])) for k in ('original', 'v1', 'v2', 'v3', 'v3+')}
        by_day = {}
        for d in sorted(set(r['day'])):
            ix = [i for i, x in enumerate(r['day']) if x == d]
            by_day[d] = {k: round(float(np.mean([r[k][i] for i in ix])), 3) for k in ('original', 'v1', 'v2', 'v3', 'v3+')}
        report[name] = dict(cases=len(r['original']), mean_error=m, guarded=int(sum(r['guarded'])), with_sealed_noaa_rain=int(sum(r['sealed'])), by_target_day=by_day)
        print('%s: %d cases (%d with sealed NOAA rain, %d gut-checked)' % (name, len(r['original']), sum(r['sealed']), sum(r['guarded'])))
        print('   average miss: ' + ', '.join('%s %.3f' % (k, v) for k, v in m.items()))
        for d, v in by_day.items(): print('   ', d, ' '.join('%s %.2f' % (k, x) for k, x in v.items()))
    (ROOT / 'outputs/reasoning').mkdir(parents=True, exist_ok=True)
    (ROOT / 'outputs/reasoning/policy-replay.json').write_text(json.dumps(report, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
