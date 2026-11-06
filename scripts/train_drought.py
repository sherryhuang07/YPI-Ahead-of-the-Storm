"""Train and test the combined drought model (U.S. Drought Monitor, 1-3 weeks ahead).

Samples: every weekly map M0 (valid Tuesday) for Connecticut and its 9 planning regions;
issue = M0 + 2 days (Thursday release); targets = the next 1, 2 and 3 maps. Target values are
the cumulative percent of area in D0+, D1+, D2+, D3+, D4+. One ridge regression per lead predicts
the change from M0; results are clipped to 0-100% and made monotone (D1+ <= D0+ ...).

Split by target map date: fit <= 2014; penalty chosen on 2015-2018 (issued after 2014);
test 2019-2026 (issued after 2018). Test predictions are sealed and hashed before scoring.
Rain falling between issue and the target map is an input: training uses what actually fell.
The test reports both bounds: with observed future rain (a perfect rain forecast) and with
normal rain (no rain forecast). Live forecasts use NOAA rain where available, normal beyond.
"""
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import numpy as np
from statewide_common import ROOT, save, log
from drought_features import load_all, drivers, rain_between, normal_rain_per_day

OUT = ROOT / 'outputs/drought'
POLICY = dict(version='drought-v1', train_end='2014-12-31', calibration=['2015-01-01', '2018-12-31'], test=['2019-01-01', '2026-12-31'],
              leads_weeks=[1, 2, 3], penalties=[0.1, 1.0, 10.0, 100.0], deadbands=[0, 5, 10, 15, 20, 30, 40, 60], issue_offset_days=2,
              target='U.S. Drought Monitor cumulative percent of area D0+..D4+, statewide and 9 planning regions',
              note='Chosen before scoring the test years. Also: probability of the dominant class worsening or improving by the target map (logistic, penalty chosen on calibration log loss). A predicted change smaller than the deadband (DSCI points, chosen on calibration years) is snapped back to the current map. VegDRI not yet included (USGS access pending).')
LEVELS = ['None', 'D0', 'D1', 'D2', 'D3', 'D4']


def category(cum):
    """Dominant class: the most severe category covering at least half the area."""
    k = 0
    for i in range(5):
        if cum[i] >= 0.5: k = i + 1
    return k


def dsci(cum): return float(np.sum(cum) * 100)       # Drought Severity and Coverage Index, 0-500


def finish(cur, delta, deadband=0.0):
    y = np.minimum.accumulate(np.clip(cur + delta, 0, 1))
    return cur.copy() if abs(dsci(y) - dsci(cur)) < deadband else y


def fit(x, y, penalty):
    mean = x.mean(0); sd = x.std(0); sd[sd < 1e-9] = 1
    z = np.column_stack([np.ones(len(x)), (x - mean) / sd]); reg = np.eye(z.shape[1]) * penalty; reg[0, 0] = 0
    return dict(mean=mean.tolist(), sd=sd.tolist(), coef=np.linalg.solve(z.T @ z + reg, z.T @ y).tolist(), penalty=penalty)


def predict(m, x):
    z = np.column_stack([np.ones(len(x)), (x - np.array(m['mean'])) / np.array(m['sd'])])
    return z @ np.array(m['coef'])


def fit_logistic(x, y, penalty, iters=25):
    """L2-regularised logistic regression by Newton steps (intercept unpenalised)."""
    mean = x.mean(0); sd = x.std(0); sd[sd < 1e-9] = 1
    z = np.column_stack([np.ones(len(x)), (x - mean) / sd]); w = np.zeros(z.shape[1]); reg = np.eye(len(w)) * penalty; reg[0, 0] = 0
    for _ in range(iters):
        q = 1 / (1 + np.exp(-np.clip(z @ w, -30, 30)))
        g = z.T @ (q - y) + reg @ w; h = (z * (q * (1 - q))[:, None]).T @ z + reg + 1e-9 * np.eye(len(w))
        step = np.linalg.solve(h, g); w -= step
        if np.max(abs(step)) < 1e-6: break
    return dict(mean=mean.tolist(), sd=sd.tolist(), w=w.tolist(), penalty=penalty)


def prob(m, x):
    z = np.column_stack([np.ones(len(x)), (x - np.array(m['mean'])) / np.array(m['sd'])])
    return 1 / (1 + np.exp(-np.clip(z @ np.array(m['w']), -30, 30)))


def auc(p, y):
    """Probability that a random event week gets a higher forecast probability than a random non-event week."""
    p = np.asarray(p); y = np.asarray(y).astype(bool)
    if y.all() or not y.any(): return None
    order = np.argsort(p); ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p) + 1)
    return float((ranks[y].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (~y).sum()))


def events(s):
    c0, c1 = category(s['cur']), category(s['y'])
    return float(c1 > c0), float(c1 < c0)


def samples(a, rain_mode='observed'):
    out = []; normal = normal_rain_per_day(a['rain'])
    for unit, maps in a['usdm'].items():
        dates = sorted(maps)
        for i, m0 in enumerate(dates):
            issue = str(date.fromisoformat(m0) + timedelta(days=POLICY['issue_offset_days']))
            for k in POLICY['leads_weeks']:
                if i + k >= len(dates): continue
                target = dates[i + k]
                if (date.fromisoformat(target) - date.fromisoformat(m0)).days != 7 * k: continue
                ahead = rain_between(a['rain'], issue, target) if rain_mode == 'observed' else normal * ((date.fromisoformat(target) - date.fromisoformat(issue)).days + 1)
                x = drivers(a, unit, m0, issue, target, ahead)
                if x is None: continue
                out.append(dict(unit=unit, map=m0, issue=issue, target=target, lead=k, x=x, cur=maps[m0] / 100, y=maps[target] / 100))
    return out


def main():
    a = load_all(); S = samples(a); Sn = {(s['unit'], s['map'], s['lead']): s for s in samples(a, 'normal')}
    p = POLICY; models = {}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'); run = OUT / 'runs' / stamp; run.mkdir(parents=True)
    sealed = []
    for k in p['leads_weeks']:
        tr = [s for s in S if s['lead'] == k and s['target'] <= p['train_end']]
        ca = [s for s in S if s['lead'] == k and p['calibration'][0] <= s['target'] <= p['calibration'][1] and s['issue'] > p['train_end']]
        te = [s for s in S if s['lead'] == k and p['test'][0] <= s['target'] and s['issue'] > p['calibration'][1]]
        X = np.array([s['x'] for s in tr]); Y = np.array([s['y'] - s['cur'] for s in tr])
        best = None
        for pen in p['penalties']:
            m = fit(X, Y, pen); deltas = predict(m, np.array([s['x'] for s in ca]))
            for db in p['deadbands']:
                err = np.mean([abs(dsci(finish(s['cur'], d, db)) - dsci(s['y'])) for s, d in zip(ca, deltas)])
                if best is None or err < best[0]: best = (err, dict(m, deadband=db))
        m = best[1]; per = np.mean([abs(dsci(s['cur']) - dsci(s['y'])) for s in ca])
        models[str(k)] = dict(model=m, calibration_dsci_mae=float(best[0]), calibration_persistence_dsci_mae=float(per), train=len(tr), calibration=len(ca))
        Xc = np.array([s['x'] for s in ca]); ev_tr = np.array([events(s) for s in tr]); ev_ca = np.array([events(s) for s in ca])
        for j, name in enumerate(('worsen', 'improve')):
            pick = None
            for pen in p['penalties']:
                lm = fit_logistic(X, ev_tr[:, j], pen); q = np.clip(prob(lm, Xc), 1e-6, 1 - 1e-6)
                loss = -np.mean(ev_ca[:, j] * np.log(q) + (1 - ev_ca[:, j]) * np.log(1 - q))
                if pick is None or loss < pick[0]: pick = (loss, lm)
            models[str(k)][name] = dict(pick[1], base_rate=float(ev_tr[:, j].mean()), calibration_log_loss=float(pick[0]))
        for s, d, dn in zip(te, predict(m, np.array([s['x'] for s in te])), predict(m, np.array([Sn[(s['unit'], s['map'], k)]['x'] for s in te]))):
            xn = Sn[(s['unit'], s['map'], k)]['x']; mk = models[str(k)]
            sealed.append(dict(unit=s['unit'], map=s['map'], target=s['target'], lead=k, cur=s['cur'].tolist(),
                               pred_observed_rain=finish(s['cur'], d, m['deadband']).tolist(), pred_normal_rain=finish(s['cur'], dn, m['deadband']).tolist(),
                               p_worsen=float(prob(mk['worsen'], s['x'][None, :])[0]), p_improve=float(prob(mk['improve'], s['x'][None, :])[0]),
                               p_worsen_normal_rain=float(prob(mk['worsen'], xn[None, :])[0]), p_improve_normal_rain=float(prob(mk['improve'], xn[None, :])[0])))
    for name, obj in (('sealed-test-predictions.json', sealed), ('model.json', models), ('policy.json', POLICY)):
        with (run / name).open('x', encoding='utf-8') as f: json.dump(obj, f)
    files = {n: hashlib.sha256((run / n).read_bytes()).hexdigest() for n in ('sealed-test-predictions.json', 'model.json', 'policy.json')}
    save(run / 'manifest.json', dict(created_at=datetime.now(timezone.utc).isoformat(), files=files, samples=len(S)))
    # ---- scoring after sealing ----
    for n, h in files.items():
        if hashlib.sha256((run / n).read_bytes()).hexdigest() != h: raise ValueError('Sealed file changed: ' + n)
    truth = {(s['unit'], s['target']): s['y'] for s in S}
    score = {}
    for k in p['leads_weeks']:
        rows = [q for q in sealed if q['lead'] == k]; res = defaultdict(list)
        for q in rows:
            y = truth[(q['unit'], q['target'])]; cur = np.array(q['cur'])
            for name, pr in (('model_observed_rain', q['pred_observed_rain']), ('model_normal_rain', q['pred_normal_rain']), ('persistence', cur)):
                pr = np.array(pr)
                res[name + '_dsci'].append(abs(dsci(pr) - dsci(y))); res[name + '_cat'].append(category(pr) == category(y))
            if category(y) != category(cur):
                res['changed'].append(1)
                res['changed_hit_observed'].append(category(np.array(q['pred_observed_rain'])) == category(y))
                res['changed_hit_normal'].append(category(np.array(q['pred_normal_rain'])) == category(y))
        prob_scores = {}
        for name in ('worsen', 'improve'):
            obs = np.array([events(dict(cur=np.array(q['cur']), y=truth[(q['unit'], q['target'])]))[0 if name == 'worsen' else 1] for q in rows])
            base = models[str(k)][name]['base_rate']; ref = np.mean((base - obs) ** 2)
            for tag, key in (('observed_rain', 'p_' + name), ('normal_rain', 'p_' + name + '_normal_rain')):
                pp = np.array([q[key] for q in rows]); bs = np.mean((pp - obs) ** 2)
                prob_scores['%s_%s' % (name, tag)] = dict(events=int(obs.sum()), brier=float(bs), brier_skill_vs_base_rate=float(1 - bs / ref) if ref else None, auc=auc(pp, obs))
            # Class step rule: current class, moved one step when a change is more likely than not.
        res2 = []
        for q in rows:
            c = category(np.array(q['cur'])) + (1 if q['p_worsen'] > 0.5 else -1 if q['p_improve'] > 0.5 else 0)
            res2.append(max(0, min(5, c)) == category(truth[(q['unit'], q['target'])]))
        prob_scores['class_with_step_rule'] = float(np.mean(res2))
        score[str(k)] = dict(cases=len(rows), category_changes=len(res['changed']), probabilities=prob_scores,
                             **{n: float(np.mean(v)) for n, v in res.items() if n != 'changed'})
    report = dict(status='Held-out 2019-2026 test of the combined drought model.', policy=POLICY, by_lead_weeks=score,
                  note='DSCI = Drought Severity and Coverage Index (0-500). Category = most severe class covering half the area. '
                       'Statewide and 9 regions pooled; regions are correlated. Drought Monitor maps involve expert judgment.')
    with (run / 'scoreboard.json').open('x', encoding='utf-8') as f: json.dump(report, f, indent=1)
    save(OUT / 'latest.json', dict(run=stamp, **report))
    log('Drought model: trained and tested (run %s).' % stamp)
    for k, s in score.items():
        pr = s['probabilities']
        print('%s week(s): chance of WORSENING: skill %.2f (AUC %.2f), %d events; IMPROVING: skill %.2f (AUC %.2f), %d events; class with step rule %.0f%%  [perfect rain]' % (
              k, pr['worsen_observed_rain']['brier_skill_vs_base_rate'], pr['worsen_observed_rain']['auc'] or 0, pr['worsen_observed_rain']['events'],
              pr['improve_observed_rain']['brier_skill_vs_base_rate'], pr['improve_observed_rain']['auc'] or 0, pr['improve_observed_rain']['events'], 100 * pr['class_with_step_rule']))
        print('          normal rain: worsening skill %.2f (AUC %.2f); improving skill %.2f (AUC %.2f)' % (
              pr['worsen_normal_rain']['brier_skill_vs_base_rate'], pr['worsen_normal_rain']['auc'] or 0, pr['improve_normal_rain']['brier_skill_vs_base_rate'], pr['improve_normal_rain']['auc'] or 0))
        print('%s week(s): DSCI error %.1f (perfect rain) / %.1f (normal rain) vs %.1f unchanged; class right %.0f%% / %.0f%% vs %.0f%%; '
              'when class changed (%d): right %.0f%% / %.0f%% (unchanged 0%%)' % (
              k, s['model_observed_rain_dsci'], s['model_normal_rain_dsci'], s['persistence_dsci'], 100 * s['model_observed_rain_cat'],
              100 * s['model_normal_rain_cat'], 100 * s['persistence_cat'], s['category_changes'], 100 * s.get('changed_hit_observed', 0), 100 * s.get('changed_hit_normal', 0)))


if __name__ == '__main__':
    main()
