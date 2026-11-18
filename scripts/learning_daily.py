"""Learning versions of each isolated model, sealed beside the frozen originals.

Before issuing each day's learning forecast, every newly scored comparison of an
ORIGINAL forecast with its observed value (prediction, observation, location,
forecast day) updates that location's and forecast day's correction weights by
recursive least squares with slow forgetting:

    learned = p + s*w0 + w1*(p - ref)          (in the model's working units)

w0 corrects typical over/under-prediction; w1 corrects over- or under-reaction
relative to the location's reference level. Weights start at zero, so the learning
forecast equals the original until observations arrive. The originals are never
changed, so the scorecard compares learning vs original on the same target days.

No looking ahead: only comparisons already scored in the original ledger (whose
observations were captured before now) are used; each issue records the weights
snapshot and the last comparison row applied. Each learning model has its own
append-only ledger (data/learning/<model>, outputs/learning/<model>) built on
prospective_daily.py's sealing, hashing and scoring rules.

    learning_daily.py --models precipitation groundwater root-zone      (night)
    learning_daily.py --models streamflow regional-streamflow           (morning)
"""
import argparse
import glob
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
import numpy as np
import prospective_daily as p
from statewide_common import ROOT, read, save, log

MODELS = {
    # Rain: one storm day can miss by 60+ mm and swamp every other lesson, so each lesson's error is capped at
    # +/-1 scale unit (5 mm) before it updates the weights (learning-v1.1, from 2026-11-11; relearned from all scored comparisons).
    'precipitation': dict(base='data/prospective', kind='precipitation', transform='identity', scale=5.0, low=0.0, high=None, error_cap=1.0),
    'noaa-rain': dict(base='data/noaa-rain-prospective', kind='precipitation', transform='identity', scale=5.0, low=0.0, high=None, error_cap=1.0),
    'groundwater': dict(base='data/prospective', kind='groundwater', transform='identity', scale=0.5, low=None, high=None),
    'streamflow': dict(base='data/prospective', kind='streamflow', transform='log1p', scale=0.3, low=0.0, high=None),
    'streamflow-v2': dict(base='data/streamflow-v2-prospective', kind='streamflow', transform='log1p', scale=0.3, low=0.0, high=None),
    'regional-streamflow-v2': dict(base='data/regional-streamflow-v2-prospective', kind='streamflow', transform='log1p', scale=0.3, low=0.0, high=None),
    'streamflow-v3': dict(base='data/streamflow-v3-prospective', kind='streamflow', transform='log1p', scale=0.3, low=0.0, high=None),
    'regional-streamflow-v3': dict(base='data/regional-streamflow-v3-prospective', kind='streamflow', transform='log1p', scale=0.3, low=0.0, high=None),
    'groundwater-v3': dict(base='data/groundwater-v3-prospective', kind='groundwater', transform='identity', scale=0.5, low=None, high=None),
    'groundwater-v2': dict(base='data/groundwater-v2-prospective', kind='groundwater', transform='identity', scale=0.5, low=None, high=None),
    'regional-streamflow': dict(base='data/regional-prospective', kind='streamflow', transform='log1p', scale=0.3, low=0.0, high=None),
    'root-zone': dict(base='data/root-zone-prospective', kind='root-zone', transform='identity', scale=0.01, low=0.0, high=1.0),
    'fire-danger': dict(base='data/fire-danger-prospective', kind='fire-danger', transform='identity', scale=0.5, low=0.0, high=4.0),
    'water-temp': dict(base='data/water-temp-prospective', kind='water-temp', transform='identity', scale=0.5, low=-3.0, high=35.0),
    'drought': dict(base='data/drought-prospective', kind='drought', transform='identity', scale=10.0, low=0.0, high=500.0),
    'drought-v2': dict(base='data/drought-v2-prospective', kind='drought', transform='identity', scale=10.0, low=0.0, high=500.0),
}
# learning-v3 (from 2026-11-15) for streams and wells: corrections are kept separately for DRY and WET weather
# (rain over the 3 days up to the last reading plus the days to the target, within NOAA's 10-day reach,
# below or at least the site's normal rain for those days and that month), learned under the weather that actually happened and applied under the weather
# NOAA forecasts; then a gut-check from each site's own history (outputs/reasoning/rules.json) caps a rise
# in a dry stretch or a fall in a wet one. Context comes from the sealed rain of the matching v2 forecast.
RAIN_CONTEXT = {'streamflow': ('site-rain', 'streamflow', 'data/streamflow-v3-prospective'),
                'streamflow-v2': ('site-rain', 'streamflow', 'data/streamflow-v3-prospective'),
                'regional-streamflow': ('site-rain-regional', 'regional-streamflow', 'data/regional-streamflow-v3-prospective'),
                'regional-streamflow-v2': ('site-rain-regional', 'regional-streamflow', 'data/regional-streamflow-v3-prospective'),
                'groundwater': ('site-rain', 'groundwater', 'data/groundwater-v3-prospective'),
                'groundwater-v2': ('site-rain', 'groundwater', 'data/groundwater-v3-prospective'),
                'streamflow-v3': ('site-rain', 'streamflow', 'data/streamflow-v3-prospective'),
                'regional-streamflow-v3': ('site-rain-regional', 'regional-streamflow', 'data/regional-streamflow-v3-prospective'),
                'groundwater-v3': ('site-rain', 'groundwater', 'data/groundwater-v3-prospective')}
for _m, (_set, _rules, _ctx) in RAIN_CONTEXT.items(): MODELS[_m].update(rain_set=_set, rules=_rules, context=_ctx)
WET_SPLIT = 1.0     # wet = at least normal rain for the window (ratio to the site's 2000-2020 monthly mean)
RAIN_HORIZON = 10
LEADS = 14
POLICY = dict(version='learning-v2', forgetting=0.99, prior_variance=[0.25, 0.25], slope_limit=0.5, evidence_days=30,
              rule='Recursive least squares on (observed - original) per location and forecast day, in units of the '
                   "model's scale; weights start at zero; slope clipped to +/-0.5 when applied; originals never change. "
                   'learning-v2 (from 2026-11-15): the learned correction is applied at strength n/(n+30), n = scored days '
                   'for that location and forecast day, so one weather event cannot swing it (learning-v1 applied it in full '
                   'from the first lesson and, in the first week, learned that week\'s storm as if it were a lasting bias).')


def fwd(v, t): return np.log1p(np.maximum(v, 0)) if t == 'log1p' else np.asarray(v, float)
def inv(v, t): return np.expm1(v) if t == 'log1p' else v


class Weights:
    """Per-location, per-forecast-day RLS state, persisted as a compressed npz."""
    def __init__(self, path):
        self.path = path
        if path.exists():
            z = np.load(path, allow_pickle=False)
            self.ids = list(z['ids']); self.ref = z['ref']; self.w = z['w']; self.P = z['P']; self.n = z['n']; self.mark = int(z['mark'])
        else:
            self.ids = []; self.ref = np.zeros(0); self.w = np.zeros((0, LEADS, 2)); self.P = np.zeros((0, LEADS, 2, 2)); self.n = np.zeros((0, LEADS), int); self.mark = 0
        self.index = {k: i for i, k in enumerate(self.ids)}

    def ensure(self, refs):
        """Add new locations in one allocation; ref is the first original prediction seen (working units)."""
        new = [(k, v) for k, v in refs.items() if k not in self.index]
        if not new: return
        m = len(new)
        for k, _ in new: self.index[k] = len(self.ids); self.ids.append(k)
        self.ref = np.concatenate([self.ref, [v for _, v in new]])
        self.w = np.concatenate([self.w, np.zeros((m, LEADS, 2))])
        self.P = np.concatenate([self.P, np.tile(np.diag(POLICY['prior_variance']), (m, LEADS, 1, 1))])
        self.n = np.concatenate([self.n, np.zeros((m, LEADS), int)])

    def update(self, loc, lead, pred_t, obs_t, scale, cap=None):
        """One RLS step with the original prediction and its observation (working units).
        cap: largest error one lesson may teach, in scale units (None = no cap)."""
        i = self.index[loc]; L = lead - 1; lam = POLICY['forgetting']
        x = np.array([1.0, (pred_t - self.ref[i]) / scale]); e = (obs_t - pred_t) / scale
        if cap is not None: e = float(np.clip(e, -cap, cap))
        P = self.P[i, L]; Px = P @ x; k = Px / (lam + x @ Px)
        self.w[i, L] = self.w[i, L] + k * (e - x @ self.w[i, L])
        self.P[i, L] = (P - np.outer(k, Px)) / lam; self.n[i, L] += 1

    def apply(self, loc, lead, pred_t, scale):
        if loc not in self.index: return pred_t
        i = self.index[loc]; w0, w1 = self.w[i, lead - 1]
        w1 = float(np.clip(w1, -POLICY['slope_limit'], POLICY['slope_limit']))
        n = int(self.n[i, lead - 1]); strength = n / (n + POLICY['evidence_days']) if n else 0.0     # hold back until evidence builds up
        return pred_t + strength * (scale * w0 + w1 * (pred_t - self.ref[i]))

    def save(self, path):
        tmp = path.with_suffix('.tmp.npz')
        np.savez_compressed(tmp, ids=np.array(self.ids, dtype=str), ref=self.ref, w=self.w, P=self.P, n=self.n, mark=self.mark)
        tmp.replace(path)


class RainContext:
    """Rain around each site, for reasoning about the weather a forecast was made in.

    observed(): what fell (station history, then PRISM-free saved NOAA forecasts for days stations
    have not reached), used to file a lesson under the weather that actually happened.
    forecast(): the rain sealed with the matching v2 forecast of that issue day (stations + NOAA ahead),
    used when applying a correction. Days are 7 AM-7 AM rain days, as in site_rain.
    """
    def __init__(self, cfg):
        from site_rain import history as rain_history, saved_nbm
        self.hist, self.start = rain_history(cfg['rain_set'])
        self.saved = saved_nbm(cfg['rain_set'], date.today() + timedelta(days=1))
        self.sealed = {}
        for f in glob.glob(str(ROOT / cfg['context'] / 'snapshots' / '*' / 'inputs.json')):
            s = read(f)
            if 'rain' not in s: continue
            day = str(datetime.fromisoformat(s['captured_at']).astimezone(p.LOCAL).date())
            for sid, v in s['rain'].items(): self.sealed[(day, sid)] = dict(zip(v['days'], v['mm']))
        self.rules = read(ROOT / 'outputs/reasoning/rules.json')['sets'][cfg['rules']]['rules'] if (ROOT / 'outputs/reasoning/rules.json').exists() else {}
        from site_rain import normal_by_month
        self._normal = {}; self._nbm = normal_by_month

    def normal(self, sid, month):
        if sid not in self._normal: self._normal[sid] = self._nbm(self.hist[sid], self.start) if sid in self.hist else {}
        return self._normal[sid].get(month)

    def _day(self, sid, d, issue_day=None):
        if issue_day is not None:
            v = self.sealed.get((issue_day, sid), {}).get(str(d))
            if v is not None: return v
        h = self.hist.get(sid); k = (d - self.start).days
        if h is not None and 0 <= k < len(h) and np.isfinite(h[k]): return float(h[k])
        return self.saved.get(sid, {}).get(str(d))

    def total(self, sid, last_day, target_day, issue_day=None):
        """Rain over the 3 days up to the last reading + days to the target (NOAA reach); None if unknown."""
        last = date.fromisoformat(last_day); n = min((date.fromisoformat(target_day) - last).days, RAIN_HORIZON)
        vals = [self._day(sid, last + timedelta(days=k), issue_day) for k in range(-2, n + 1)]
        return None if any(v is None for v in vals) else float(sum(vals))

    def ratio(self, sid, last_day, target_day, issue_day=None):
        """(rain total, its ratio to normal for the same days and month), or (None, None)."""
        t = self.total(sid, last_day, target_day, issue_day)
        if t is None: return None, None
        last = date.fromisoformat(last_day); n = min((date.fromisoformat(target_day) - last).days, RAIN_HORIZON) + 3
        nm = self.normal(sid, last.month)
        return t, (t / (nm * n) if nm else None)

    @staticmethod
    def regime(ratio): return 'wet' if ratio is not None and ratio >= WET_SPLIT else 'dry'


def lesson_keys(base, kind, cfg, rows):
    """For rain-aware models: file each lesson under loc|dry or loc|wet by the rain that actually fell."""
    ctx = RainContext(cfg); paths = {s: pth for s, pth in base.execute('SELECT sha256, path FROM forecasts')}; last = {}
    out = {}
    for rowid, sha, loc, day, lead in rows:
        if (sha, loc) not in last:
            for f in read(ROOT / paths[sha])['forecasts']: last[(sha, f['id'])] = f.get('source_last_day')
        ld = last.get((sha, loc))
        out[rowid] = '%s|%s' % (loc, RainContext.regime(ctx.ratio(loc, ld, day)[1] if ld else None))
    return out


def train(weights, base, kind, cfg):
    """Apply every comparison scored in the original ledger since the last run, oldest first."""
    rows = base.execute('SELECT rowid,location,lead,predicted,observed,forecast_sha,day FROM scores WHERE variable=? AND rowid>? '
                        'ORDER BY day,lead,rowid', (kind, weights.mark)).fetchall()
    keys = lesson_keys(base, kind, cfg, [(r[0], r[5], r[1], r[6], r[2]) for r in rows]) if cfg.get('rain_set') and rows else {}
    refs = {}
    for rowid, loc, _, pred, _, _, _ in rows: refs.setdefault(keys.get(rowid, loc), float(fwd(pred, cfg['transform'])))
    weights.ensure(refs)
    for rowid, loc, lead, pred, obs, _, _ in rows:
        weights.update(keys.get(rowid, loc), int(lead), float(fwd(pred, cfg['transform'])), float(fwd(obs, cfg['transform'])), cfg['scale'], cfg.get('error_cap'))
        weights.mark = max(weights.mark, rowid)
    return len(rows)


def learned_rows(record, weights, cfg, issue_day=None):
    from reasoning_rules import guard
    ctx = RainContext(cfg) if cfg.get('rain_set') else None
    rows = []
    for r in record['forecasts']:
        frozen = np.array(r['prediction'], float); out = []; notes = []
        for lead, v in enumerate(frozen, 1):
            key = r['id']; note = None
            if ctx is not None and r.get('source_last_day'):
                # Reason with the weather: use the correction learned in the same kind of weather NOAA expects.
                total, ratio = ctx.ratio(r['id'], r['source_last_day'], r['dates'][lead - 1], issue_day)
                key = '%s|%s' % (r['id'], RainContext.regime(ratio))
            y = inv(weights.apply(key, lead, float(fwd(v, cfg['transform'])), cfg['scale']), cfg['transform'])
            if cfg['low'] is not None: y = max(cfg['low'], y)
            if cfg['high'] is not None: y = min(cfg['high'], y)
            if ctx is not None and r.get('source_last_day'):
                L_ = (date.fromisoformat(r['dates'][lead - 1]) - date.fromisoformat(r['source_last_day'])).days
                if L_ <= RAIN_HORIZON and total is not None:
                    y, note = guard(float(y), float(r['baseline'][0]), ctx.rules.get(r['id'], {}).get(str(L_)), total, cfg['kind'])
                notes.append('%s weather (%s mm expected, %s of normal)%s' % (key.split('|')[1], '?' if total is None else '%.1f' % total,
                             '?' if ratio is None else '%d%%' % round(100 * ratio), '; gut-check ' + note if note else ''))
            out.append(float(y))
        row = dict(id=r['id'], dates=r['dates'], prediction=out, baseline=frozen.tolist(),
                   source_last_day=r.get('source_last_day'), units=r.get('units'),
                   method='Original forecast corrected by weights learned from earlier scored comparisons (%s)' % version(cfg))
        if notes: row['reasoning'] = notes
        rows.append(row)
    return rows


def version(cfg):
    # learning-v3 for streams and wells (dry/wet corrections + gut-check); learning-v2 for the others
    # (rain models also cap each lesson; see error_cap)
    # learning-v3.1 (2026-11-17): same weights; gut-check caps a dry-stretch rise at the site's 80th percentile
    # (was 99th: too loose to stop a light-shower forecast doubling a river) and keeps the wet floor at the 99th.
    return 'learning-v3.1' if cfg.get('rain_set') else POLICY['version']


def run_model(name, root_out=None):
    cfg = MODELS[name]; kind = cfg['kind']
    base_dir = ROOT / cfg['base']
    p.D = (root_out / 'data' / name) if root_out else ROOT / 'data/learning' / name
    p.O = (root_out / 'outputs' / name) if root_out else ROOT / 'outputs/learning' / name
    p.D.mkdir(parents=True, exist_ok=True); p.O.mkdir(parents=True, exist_ok=True)
    today = str(p.utc().astimezone(p.LOCAL).date())
    base = sqlite3.connect('file:%s?mode=ro' % (base_dir / 'ledger.sqlite').as_posix(), uri=True)
    issued = base.execute('SELECT path,sha256 FROM forecasts WHERE substr(issue_day,1,10)=? AND variable=? AND sha256 NOT IN '
                          '(SELECT forecast_sha FROM exclusions) ORDER BY issued_at DESC', (today, kind)).fetchone()
    c = p.db(); p.verify(c)
    ver = version(cfg); registry = p.D / ('model-%s.json' % ver.split('-')[-1])
    weights_path = p.D / 'weights.npz'
    if not registry.exists():
        if ver == 'learning-v3' and weights_path.exists():
            # Dry/wet corrections are stored per weather, so relearn from every comparison scored so far
            # (all observed before now); the learning-v2 weights are kept for the record.
            weights_path.replace(p.D / 'weights-learning-v2.npz')
        # learning-v2 keeps the learned weights (no relearning); only how strongly they are applied changes.
        # (The 2026-11-11 rain cap, learning-v1.1, did relearn: its old weights are in weights-learning-v1.npz.)
        p.exclusive(registry, dict(created_at=p.utc().isoformat(), model=name, base_ledger=cfg['base'], kind=kind,
                                   transform=cfg['transform'], scale=cfg['scale'], **dict(POLICY, version=ver),
                                   error_cap=cfg.get('error_cap'),
                                   replaces='learning-v1/v1.1: corrections applied in full from the first lesson; in the first week they '
                                            'made Connecticut streams 41% and rain 22% worse than the originals',
                                   **(dict(weather=dict(wet_if_at_least_normal_rain_ratio=WET_SPLIT, horizon_days=RAIN_HORIZON, rain_set=cfg['rain_set'], context=cfg['context'],
                                                        gut_check='outputs/reasoning/rules.json', rules_sha256=p.digest(ROOT / 'outputs/reasoning/rules.json')),
                                           replay='outputs/reasoning/policy-replay.json',
                                           gut_check_percentiles=dict(dry=read(ROOT / 'outputs/reasoning/rules.json').get('percentile'),
                                                                      wet=read(ROOT / 'outputs/reasoning/rules.json').get('wet_percentile'))) if ver.startswith('learning-v3') else {})))
    weights = Weights(weights_path)
    trained = train(weights, base, kind, cfg); weights.save(weights_path)
    status = dict(model=name, trained_on_new_comparisons=trained, total_comparisons_learned=int(weights.n.sum()), last_comparison_row=weights.mark)
    if issued is None:
        status['issued'] = 'skipped: no original forecast sealed today'
    else:
        path, sha = issued
        if p.digest(ROOT / path) != sha: raise ValueError('Original forecast hash mismatch: ' + path)
        record = read(ROOT / path)
        folder = p.D / 'snapshots' / p.stamp(); folder.mkdir(parents=True)
        frozen_weights = folder / 'weights.npz'; weights.save(frozen_weights)
        code = folder / 'learning-runner.py'
        with code.open('xb') as f: f.write(Path(__file__).read_bytes())
        snap = dict(captured_at=p.utc().isoformat(), values={}, grids={}, errors=[], original_forecast=dict(path=path, sha256=sha),
                    last_comparison_row_applied=weights.mark, comparisons_learned=int(weights.n.sum()))
        snapshot = folder / 'inputs.json'; p.exclusive(snapshot, snap)
        rows = learned_rows(record, weights, cfg, issue_day=today)
        extra = [dict(path=path, sha256=sha), dict(path=str(frozen_weights.relative_to(ROOT)), sha256=p.digest(frozen_weights)),
                 dict(path=str(code.relative_to(ROOT)), sha256=p.digest(code))]
        if cfg.get('rain_set'):        # keep the exact gut-check rules this forecast used
            rules_copy = folder / 'reasoning-rules.json'; rules_copy.write_bytes((ROOT / 'outputs/reasoning/rules.json').read_bytes())
            extra.append(dict(path=str(rules_copy.relative_to(ROOT)), sha256=p.digest(rules_copy)))
        p.seal(c, kind, rows, record.get('unavailable', []), snapshot, snap, registry, model_version=ver, extra_sources=extra)
        status['issued'] = '%d locations sealed or already present for %s' % (len(rows), today)
    # Observations come from the original ledger with their original capture times, so a learning
    # forecast is scored only by values captured after it was issued (checked by score()).
    wanted = {}
    for fpath, in c.execute('SELECT path FROM forecasts'):
        for r in read(ROOT / fpath)['forecasts']: wanted.setdefault(r['id'], set()).update(r['dates'])
    for row in base.execute('SELECT variable,location,day,value,captured_at,snapshot FROM observations WHERE variable=?', (kind,)):
        if row[2] in wanted.get(row[1], ()): c.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)', row)
    c.commit(); status['new_comparisons'] = p.score(c)
    board = read(p.O / 'scoreboard.json')
    board['note'] = ('mae = learning version; baseline_mae = the frozen original on the same cases. '
                     'Overlapping windows and correlated locations are not independent tests.')
    save(p.O / 'scoreboard.json', board)
    save(p.O / 'last-run.json', dict(completed_at=p.utc().isoformat(), issue_day=today, **status))
    log('Learning version %s: learned from %d new comparisons; %s; %d new comparisons scored.' % (name, trained, status['issued'], status['new_comparisons']))
    return status


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--models', nargs='+', choices=list(MODELS), default=list(MODELS))
    ap.add_argument('--test-dir', help='Write learning ledgers to this throwaway folder (inside the project).')
    a = ap.parse_args(); failures = []
    for name in a.models:
        try: print(json.dumps(run_model(name, Path(a.test_dir) if a.test_dir else None)))
        except Exception as e: failures.append(name); print('%s: failed (%s: %s)' % (name, type(e).__name__, e))
    if failures: raise SystemExit('Learning versions failed: ' + ', '.join(failures))


if __name__ == '__main__':
    main()
