"""Rebuild daily Connecticut fire danger history from airport weather (1964 NFDRS indexes).

Reads data/fire-danger/weather/<station>.csv, runs subroutine DANGER day by day per
station (Build Up Index carried forward from 1997-01-01, starting at 0), and writes
data/fire-danger/history.csv with each station's Spread (grass and timber) and Build Up
indexes plus statewide summaries. A day without complete 1 PM weather and 24-hour rain
has blank indexes; the Build Up Index is then carried unchanged (flagged), never filled
with an assumed dry or wet day.
"""
import csv
import hashlib
import json
from datetime import date, datetime, timezone
import numpy as np
from statewide_common import ROOT, save, log
from fire_danger_model import danger, wet_bulb_f, herb_stage, rating, LEVELS

W = ROOT / 'data/fire-danger/weather'
KNOT_TO_MPH = 1.15078
# Airports measure wind at 10 m (33 ft) in the open; the 1964 system uses 20 ft. Log-profile
# reduction 33 ft -> 20 ft is about 0.87 (physics, not fitted to DEEP ratings).
WIND_HEIGHT_FACTOR = 0.87


def station_series(station):
    rows = list(csv.DictReader((W / (station + '.csv')).open(encoding='utf-8')))
    bui = 0.0; out = {}; gap = 0; prev_day = None
    for r in rows:
        d = date.fromisoformat(r['date'])
        # Hourly ASOS rain exists only from 2012, so for a consistent 30-year history the 24 hours
        # ending 1 PM are estimated from NOAA daily totals: 11/24 of yesterday + 13/24 of today
        # (best match to the true window in 2012+: correlation 0.70-0.80, >0.1 inch decision 86-87%).
        today_p = r['ghcn_precip_in']
        r['rain_est'] = '' if today_p == '' or prev_day in (None, '') else 11 / 24 * float(prev_day) + 13 / 24 * float(today_p)
        # NOAA daily totals arrive a few days late. Until they do, use the airport's exact hourly
        # rain for the 24 hours ending at the 1 PM observation (available from 2012).
        if r['rain_est'] == '' and r['precip_24h_in'] != '' and r['date'] >= '2012-01-01': r['rain_est'] = float(r['precip_24h_in'])
        prev_day = today_p
        ok = all(r[k] != '' for k in ('temp_f', 'dewpoint_f', 'wind_knots', 'rain_est'))
        snow = r['snow_depth_in'] != '' and float(r['snow_depth_in']) >= 1.0
        if not ok:
            gap += 1
            out[r['date']] = dict(missing=True, bui=round(bui, 2), bui_carried_days=gap); continue
        gap = 0
        t = float(r['temp_f']); td = min(float(r['dewpoint_f']), t)
        res = danger(t, wet_bulb_f(t, td), snow, float(r['rain_est']), float(r['wind_knots']) * KNOT_TO_MPH * WIND_HEIGHT_FACTOR, bui, herb_stage(d))
        bui = res['bui']
        out[r['date']] = dict(missing=False, grass=round(res['grass'], 2), timber=round(res['timber'], 2), bui=round(bui, 2),
                              ffm=round(res['ffm'], 2), snow=snow, bui_carried_days=0)
    return out


def main():
    manifest = json.loads((W / 'manifest.json').read_text(encoding='utf-8'))
    stations = sorted(manifest['stations']); series = {s: station_series(s) for s in stations}
    days = sorted(set().union(*[set(v) for v in series.values()]))
    path = ROOT / 'data/fire-danger/history.csv'; counts = {}
    with path.open('w', newline='', encoding='utf-8') as f:
        cols = ['date', 'herb_stage', 'stations_complete']
        for s in stations: cols += [s + '_timber', s + '_grass', s + '_bui']
        cols += ['median_timber', 'median_grass', 'median_bui', 'max_timber', 'max_bui', 'rating_median_buildup', 'rating_max_buildup']
        w = csv.writer(f); w.writerow(cols)
        for d in days:
            vals = [series[s].get(d) for s in stations]; good = [v for v in vals if v and not v['missing']]
            row = [d, herb_stage(date.fromisoformat(d)), len(good)]
            for v in vals:
                row += ['' if not v or v['missing'] else v['timber'], '' if not v or v['missing'] else v['grass'], '' if not v else v['bui']]
            if len(good) >= 3:
                mt = float(np.median([v['timber'] for v in good])); mg = float(np.median([v['grass'] for v in good]))
                mb = float(np.median([v['bui'] for v in good])); xt = max(v['timber'] for v in good); xb = max(v['bui'] for v in good)
                r1 = rating(mt, mb, 'buildup'); r2 = rating(xt, xb, 'buildup')
                row += [round(mt, 2), round(mg, 2), round(mb, 2), xt, xb, LEVELS[r1], LEVELS[r2]]
                counts[LEVELS[r1]] = counts.get(LEVELS[r1], 0) + 1
            else:
                row += [''] * 7
            w.writerow(row)
    info = dict(created_at=datetime.now(timezone.utc).isoformat(), days=len(days), first=days[0], last=days[-1], stations=stations,
                statewide_rule='Median of stations with complete weather (at least 3); class from the Build Up Index (best agreement with 31 DEEP ratings; see validation.json)',
                rating_counts_median=counts, history_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                weather_manifest_sha256=hashlib.sha256((W / 'manifest.json').read_bytes()).hexdigest(),
                missing_days={s: sum(v['missing'] for v in series[s].values()) for s in stations})
    save(ROOT / 'data/fire-danger/history-manifest.json', info)
    log('Fire danger: rebuilt %d days of 1964 NFDRS indexes from %s weather.' % (len(days), ', '.join(stations)))
    print(json.dumps(info, indent=1))


if __name__ == '__main__':
    main()
