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
import json
import sqlite3
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
    'groundwater-v2': dict(base='data/groundwater-v2-prospective', kind='groundwater', transform='identity', scale=0.5, low=None, high=None),
    'regional-streamflow': dict(base='data/regional-prospective', kind='streamflow', transform='log1p', scale=0.3, low=0.0, high=None),
    'root-zone': dict(base='data/root-zone-prospective', kind='root-zone', transform='identity', scale=0.01, low=0.0, high=1.0),
    'fire-danger': dict(base='data/fire-danger-prospective', kind='fire-danger', transform='identity', scale=0.5, low=0.0, high=4.0),
    'water-temp': dict(base='data/water-temp-prospective', kind='water-temp', transform='identity', scale=0.5, low=-3.0, high=35.0),
    'drought': dict(base='data/drought-prospective', kind='drought', transform='identity', scale=10.0, low=0.0, high=500.0),
    'drought-v2': dict(base='data/drought-v2-prospective', kind='drought', transform='identity', scale=10.0, low=0.0, high=500.0),
}
LEADS = 14
POLICY = dict(version='learning-v1', forgetting=0.99, prior_variance=[0.25, 0.25], slope_limit=0.5,
              rule='Recursive least squares on (observed - original) per location and forecast day, in units of the '
                   "model's scale; weights start at zero; slope clipped to +/-0.5 when applied; originals never change.")


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
        return pred_t + scale * w0 + w1 * (pred_t - self.ref[i])

    def save(self, path):
        tmp = path.with_suffix('.tmp.npz')
        np.savez_compressed(tmp, ids=np.array(self.ids, dtype=str), ref=self.ref, w=self.w, P=self.P, n=self.n, mark=self.mark)
        tmp.replace(path)


def train(weights, base, kind, cfg):
    """Apply every comparison scored in the original ledger since the last run, oldest first."""
    rows = base.execute('SELECT rowid,location,lead,predicted,observed FROM scores WHERE variable=? AND rowid>? '
                        'ORDER BY day,lead,rowid', (kind, weights.mark)).fetchall()
    refs = {}
    for _, loc, _, pred, _ in rows: refs.setdefault(loc, float(fwd(pred, cfg['transform'])))
    weights.ensure(refs)
    for rowid, loc, lead, pred, obs in rows:
        weights.update(loc, int(lead), float(fwd(pred, cfg['transform'])), float(fwd(obs, cfg['transform'])), cfg['scale'], cfg.get('error_cap'))
        weights.mark = max(weights.mark, rowid)
    return len(rows)


def learned_rows(record, weights, cfg):
    rows = []
    for r in record['forecasts']:
        frozen = np.array(r['prediction'], float); out = []
        for lead, v in enumerate(frozen, 1):
            y = inv(weights.apply(r['id'], lead, float(fwd(v, cfg['transform'])), cfg['scale']), cfg['transform'])
            if cfg['low'] is not None: y = max(cfg['low'], y)
            if cfg['high'] is not None: y = min(cfg['high'], y)
            out.append(float(y))
        rows.append(dict(id=r['id'], dates=r['dates'], prediction=out, baseline=frozen.tolist(),
                         source_last_day=r.get('source_last_day'), units=r.get('units'),
                         method='Original forecast corrected by weights learned from earlier scored comparisons (%s)' % version(cfg)))
    return rows


def version(cfg):
    return 'learning-v1.1' if cfg.get('error_cap') is not None else 'learning-v1'


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
        if ver != 'learning-v1' and weights_path.exists():
            # New policy: keep the old weights for the record and relearn from every comparison scored so far
            # (all were observed before now, so nothing looks ahead).
            weights_path.replace(p.D / 'weights-learning-v1.npz')
        p.exclusive(registry, dict(created_at=p.utc().isoformat(), model=name, base_ledger=cfg['base'], kind=kind,
                                   transform=cfg['transform'], scale=cfg['scale'], **dict(POLICY, version=ver),
                                   error_cap=cfg.get('error_cap'),
                                   **({'replaces': 'learning-v1 (uncapped: one storm taught every location to add ~2-3 mm/day)'} if ver != 'learning-v1' else {})))
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
        rows = learned_rows(record, weights, cfg)
        p.seal(c, kind, rows, record.get('unavailable', []), snapshot, snap, registry, model_version=ver,
               extra_sources=[dict(path=path, sha256=sha), dict(path=str(frozen_weights.relative_to(ROOT)), sha256=p.digest(frozen_weights)),
                              dict(path=str(code.relative_to(ROOT)), sha256=p.digest(code))])
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
