"""Assemble complete daily 0-100 cm root-zone inputs for the 69 watersheds.

    assemble_root_zone_inputs.py live [--through YYYY-MM-DD]
        Builds every day the live forecast needs (28-day window ending six days
        before the issue date) plus any later published days, from hourly NLDAS-2.
    assemble_root_zone_inputs.py check-archive --start 2020-06-01 --end 2020-07-15
        Rebuilds days that the USGS archive also covers and compares them, for
        several candidate daily boundaries, so spatial support and day alignment
        are measured rather than assumed.

A day is complete only when all 24 hourly grids exist. Incomplete or failed
days are recorded as missing and never filled.
"""
import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import numpy as np
from root_zone_live import (ROOT, INPUTS, login_session, fetch_hour, day_hours, load_weights,
                            watershed_means, daterange, parse_day, DEFAULT_DAY_START_UTC_HOUR)

POLICY = json.loads((ROOT / 'root-zone-policy.json').read_text(encoding='utf-8'))
WINDOW = 28


def build_days(session, days, start_hour, weights, workers=8):
    """Return {day: {sid: (m3/m3, valid_fraction)} or None if incomplete}."""
    box = weights['box']
    hours = sorted({h for d in days for h in day_hours(d, start_hour)})
    print('Fetching %d hourly NLDAS grids (cached hours are reused)...' % len(hours), flush=True)
    grids = {}; done = [0]

    def one(h):
        g = fetch_hour(session, h, box)
        done[0] += 1
        if done[0] % 100 == 0: print('  %d / %d hours' % (done[0], len(hours)), flush=True)
        return h, g

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for h, g in pool.map(one, hours):
            grids[h] = g
    out = {}
    for d in days:
        hs = day_hours(d, start_hour)
        if any(grids[h] is None for h in hs):
            out[d] = None; continue
        stack = np.stack([grids[h] for h in hs])
        # A cell's daily mean needs all 24 hours; otherwise that cell is missing.
        daily = np.where(np.all(np.isfinite(stack), axis=0), stack.mean(axis=0), np.nan)
        out[d] = {sid: (v / 1000.0 if np.isfinite(v) else float('nan'), f)
                  for sid, (v, f) in watershed_means(daily, weights).items()}
    return out


def save_table(path, result, ids, start_hour, note):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['date', 'watershed_id', 'moisture_m3m3', 'valid_area_fraction', 'status'])
        for d in sorted(result):
            for sid in ids:
                if result[d] is None:
                    w.writerow([d.isoformat(), sid, '', '', 'day incomplete: not all 24 hourly grids published'])
                else:
                    v, frac = result[d][sid]
                    w.writerow([d.isoformat(), sid, '' if not np.isfinite(v) else '%.6f' % v, '%.4f' % frac,
                                'ok' if np.isfinite(v) else 'missing: insufficient valid land cells'])
    meta = dict(created_at=datetime.now(timezone.utc).isoformat(), source='NASA GES DISC NLDAS_NOAH0125_H v2.0 SoilM_0_100cm via OPeNDAP',
                units='m3/m3 (kg m-2 / 1000 mm)', day_start_utc_hour=start_hour,
                day_definition='Mean of 24 hourly instantaneous grids starting at %02d:00 UTC on the labelled date' % start_hour,
                first_day=min(result).isoformat(), last_day=max(result).isoformat(),
                complete_days=sum(r is not None for r in result.values()),
                incomplete_days=[d.isoformat() for d, r in sorted(result.items()) if r is None], note=note)
    path.with_suffix('.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    return meta


def check_archive(args):
    weights = load_weights(); session = login_session()
    hist = np.load(ROOT / 'data/root-zone/prepared/history.npz')
    hdates = {str(d): i for i, d in enumerate(hist['dates'])}
    hids = [str(s) for s in hist['ids']]
    days = daterange(parse_day(args.start), parse_day(args.end))
    report = dict(created_at=datetime.now(timezone.utc).isoformat(), period=[args.start, args.end],
                  purpose='Compare rebuilt NLDAS v2.0 watershed means with the USGS archive used for training.',
                  offsets={})
    for start_hour in args.offsets:
        result = build_days(session, days, start_hour, weights)
        diffs = []; per = {}
        for d, r in result.items():
            if r is None: continue
            for sid in hids:
                v = r[sid][0]; a = hist['moisture'][hdates[d.isoformat()], hids.index(sid)]
                if np.isfinite(v) and np.isfinite(a):
                    diffs.append((v, a)); per.setdefault(sid, []).append((v, a))
        x = np.array(diffs)
        per_ws = {sid: dict(mae=float(np.mean(abs(np.array(p)[:, 0] - np.array(p)[:, 1]))),
                            bias=float(np.mean(np.array(p)[:, 0] - np.array(p)[:, 1])),
                            correlation=float(np.corrcoef(np.array(p).T)[0, 1]) if len(p) > 2 else None,
                            boundary=weights['boundaries'][sid].get('status'))
                  for sid, p in per.items()}
        report['offsets'][str(start_hour)] = dict(
            day_start_utc_hour=start_hour, compared_values=len(x),
            mae=float(np.mean(abs(x[:, 0] - x[:, 1]))), bias=float(np.mean(x[:, 0] - x[:, 1])),
            max_abs_difference=float(np.max(abs(x[:, 0] - x[:, 1]))),
            correlation=float(np.corrcoef(x.T)[0, 1]),
            day_to_day_change_mae=float(np.mean(abs(np.diff(hist['moisture'][[hdates[d.isoformat()] for d in days]], axis=0)))),
            worst_watersheds=sorted(per_ws.items(), key=lambda kv: -kv[1]['mae'])[:8], by_watershed=per_ws)
        o = report['offsets'][str(start_hour)]
        print('Day start %02d UTC: MAE %.5f m3/m3, bias %+.5f, correlation %.5f (typical day-to-day change %.5f)'
              % (start_hour, o['mae'], o['bias'], o['correlation'], o['day_to_day_change_mae']), flush=True)
    best = min(report['offsets'].values(), key=lambda o: o['mae'])
    report['best_day_start_utc_hour'] = best['day_start_utc_hour']
    report['interpretation'] = ('The day boundary with the smallest difference from the archive is used for live inputs. '
                                'Remaining differences come from boundary delineation (NLDI vs GAGES-II), NLDAS version, '
                                'and aggregation method; they are inputs-mismatch error not included in the historical score.')
    out = INPUTS / 'archive-check.json'; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding='utf-8')
    print('Best matching day start: %02d:00 UTC. Report: %s' % (best['day_start_utc_hour'], out.relative_to(ROOT)))


def live(args):
    weights = load_weights(); session = login_session()
    check = INPUTS / 'archive-check.json'
    start_hour = (json.loads(check.read_text())['best_day_start_utc_hour'] if check.exists()
                  else DEFAULT_DAY_START_UTC_HOUR)
    issue = parse_day(args.issue) if args.issue else datetime.now(ZoneInfo('America/New_York')).date()
    lag = POLICY['input_lag_days']
    first = issue - timedelta(days=lag + WINDOW - 1)
    through = parse_day(args.through) if args.through else datetime.now(timezone.utc).date() - timedelta(days=1)
    days = daterange(first, through)
    result = build_days(session, days, start_hour, weights)
    # Trailing days that are not yet published are dropped; gaps inside are kept as missing.
    while days and result[days[-1]] is None:
        result.pop(days[-1]); days.pop()
    ids = list(weights['watersheds'])
    meta = save_table(INPUTS / 'latest.csv', result, ids, start_hour,
                      'Live inputs for issue date %s: the model uses %s through %s (lag %d days).'
                      % (issue, first, issue - timedelta(days=lag), lag))
    meta.update(issue_date=issue.isoformat(), required_window=[first.isoformat(), (issue - timedelta(days=lag)).isoformat()],
                alignment_source='archive-check.json' if check.exists() else 'default UTC day; archive check not yet run')
    (INPUTS / 'latest.json').write_text(json.dumps(meta, indent=2), encoding='utf-8')
    print(json.dumps(meta, indent=2))


def main():
    p = argparse.ArgumentParser(); sub = p.add_subparsers(dest='mode', required=True)
    c = sub.add_parser('check-archive'); c.add_argument('--start', default='2020-06-01'); c.add_argument('--end', default='2020-07-15')
    c.add_argument('--offsets', type=int, nargs='+', default=[0, 5, 6])
    l = sub.add_parser('live'); l.add_argument('--issue'); l.add_argument('--through')
    a = p.parse_args()
    check_archive(a) if a.mode == 'check-archive' else live(a)


if __name__ == '__main__':
    main()
