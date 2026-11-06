"""Continuous 2000-present daily root-zone soil moisture for the drought model.

- 2000-2020: USGS NLDAS-2 watershed archive (daily means; data/root-zone/prepared/history.npz).
- 2021 to the start of live inputs: NASA NLDAS-2 v2.0 at a single hour per day (17 UTC, about
  noon in Connecticut) through the same OPeNDAP subsets and watershed weights as the live
  inputs. In the 2020 overlap, a single 17 UTC hour differed from the 24-hour mean by 0.0004
  m3/m3 on average (max 0.0125), acceptable for a drought percentile input, not for the
  standalone soil-moisture model.
- Latest weeks: data/root-zone/daily-inputs/latest.csv (24-hour means).
Output: data/drought/soil-moisture-daily.csv with the mean over the 69 watersheds and the
number of watersheds present. Needs NASA sign-in (run via root-zone-update.ps1 style launcher).
"""
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import numpy as np
from root_zone_live import ROOT, login_session, fetch_hour, load_weights, watershed_means, daterange
from statewide_common import save, log

OUT = ROOT / 'data/drought/soil-moisture-daily.csv'


def main():
    values = {}
    h = np.load(ROOT / 'data/root-zone/prepared/history.npz')
    for d, row in zip(h['dates'], h['moisture']):
        if str(d) >= '2000-01-01' and np.isfinite(row).sum() >= 35: values[str(d)] = (float(np.nanmean(row)), int(np.isfinite(row).sum()), 'USGS archive daily mean')
    live = {}
    for r in csv.DictReader((ROOT / 'data/root-zone/daily-inputs/latest.csv').open(encoding='utf-8')):
        if r['moisture_m3m3']: live.setdefault(r['date'], []).append(float(r['moisture_m3m3']))
    first_live = min(live) if live else str(date.today())
    weights = load_weights(); session = login_session()
    days = daterange(date(2021, 1, 1), date.fromisoformat(first_live) - timedelta(days=1))
    hours = [datetime(d.year, d.month, d.day, 17, tzinfo=timezone.utc) for d in days]
    print('Fetching %d single-hour NLDAS grids (cached hours reused)...' % len(hours), flush=True)
    done = [0]
    failed = []
    def one(t):
        # A failed hour stays missing (and is retried on the next run); it never stops the series.
        try: g = fetch_hour(session, t, weights['box'])
        except RuntimeError: g = None; failed.append(str(t.date()))
        done[0] += 1
        if done[0] % 200 == 0: print('  %d / %d' % (done[0], len(hours)), flush=True)
        return t, g
    with ThreadPoolExecutor(max_workers=8) as pool: grids = dict(pool.map(one, hours))
    for t, g in grids.items():
        if g is None: continue
        m = [v / 1000 for v, f in watershed_means(g, weights).values() if np.isfinite(v)]
        if len(m) >= 35: values[str(t.date())] = (float(np.mean(m)), len(m), 'NLDAS v2.0 single hour 17 UTC')
    for d, v in live.items():
        if len(v) >= 35: values[d] = (float(np.mean(v)), len(v), 'NLDAS v2.0 24-hour mean (live inputs)')
    with OUT.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['date', 'soil_moisture_m3m3', 'watersheds', 'source'])
        for d in sorted(values): w.writerow([d, round(values[d][0], 5), values[d][1], values[d][2]])
    days_all = sorted(values)
    save(ROOT / 'data/drought/soil-moisture-manifest.json', dict(created_at=datetime.now(timezone.utc).isoformat(), first=days_all[0], last=days_all[-1], days=len(days_all),
                                                               missing_since_2021=len(days) - sum(1 for d in days if str(d) in values)))
    log('Drought model: soil moisture series %s to %s (%d days).' % (days_all[0], days_all[-1], len(days_all)))
    print('done', days_all[0], days_all[-1], len(days_all), 'failed hours:', len(failed))


if __name__ == '__main__':
    main()
