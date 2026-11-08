"""Daily statewide drivers and weekly samples for the combined Connecticut drought model.

Every input is turned into a departure from normal for the time of year, using a climatology
fitted on 2000-2014 only, so training-period statistics never contain test years:

  rain_30/90/180   airport rain over 30/90/180 days, z-score of the total (5 airports, NOAA daily)
  rain_since_map   rain from the last map's valid date to the day before issue (observed)
  rain_ahead_k     rain from issue to the k-th next map (observed in training; NOAA forecast + normal live)
  flow             median over gauges of the z-score of log 7-day mean streamflow (USGS)
  wells            median over wells of the z-score of water-level depth, sign flipped so low = dry
  soil             z-score of mean 0-100 cm soil moisture (NLDAS-2), 6-day publication lag
  bui              fire danger Build Up Index, statewide median airport (1964 NFDRS rebuild)
  water            mean departure of coastal water temperature (NDBC), weak expected link
  pdsi/phdi/z      mean of Connecticut's 3 climate divisions, latest month published by the issue date
                   (a month is treated as published on the 10th of the next month)
  usdm d0..d4      the region's (or state's) current Drought Monitor cumulative percent of area
  change_4w        how much that area's map changed over the previous 4 weeks (momentum)
  season           sin/cos of day of year
  vegdri (v2 only) the area's own USGS VegDRI: mean index, share of vegetated land below -1, and the
                   change in the mean over the previous 4 weeks. VegDRI is already a standardized
                   drought index (Palmer scale), so it is used as is. A week (Monday-Sunday) is treated
                   as available 2 days after it ends (USGS produces it the next morning). Before
                   April 2009 and in winter (out of season) it is missing: 0 with a missing flag.
Missing values become 0 (normal) with a 'missing' flag, never a guessed dry or wet value.
"""
import csv
import glob
import json
from collections import defaultdict
from datetime import date, timedelta
import numpy as np
from statewide_common import ROOT

CLIM_END = '2014-12-31'
D = ROOT / 'data'


def zscore_by_month(series, end=CLIM_END):
    """series: dict day->value. Returns (dict day->z, stats) with monthly mean/sd from days <= end."""
    by = defaultdict(list)
    for d, v in series.items():
        if d <= end and np.isfinite(v): by[int(d[5:7])].append(v)
    stats = {m: (float(np.mean(v)), float(np.std(v)) or 1.0) for m, v in by.items() if len(v) > 10}
    return {d: (v - stats[int(d[5:7])][0]) / stats[int(d[5:7])][1] for d, v in series.items() if int(d[5:7]) in stats and np.isfinite(v)}, stats


def rolling_sum(daily, window):
    days = sorted(daily); first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1]); out = {}
    vals = [daily.get(str(first + timedelta(days=k))) for k in range((last - first).days + 1)]
    for k in range(window - 1, len(vals)):
        w = vals[k - window + 1:k + 1]
        if sum(v is None for v in w) <= window // 10: out[str(first + timedelta(days=k))] = float(np.sum([v for v in w if v is not None]) * window / sum(v is not None for v in w))
    return out


def load_rain():
    per = defaultdict(list)
    for f in glob.glob(str(D / 'fire-danger/weather/*.csv')):
        for r in csv.DictReader(open(f, encoding='utf-8')):
            v = r['ghcn_precip_in'] if r['ghcn_precip_in'] != '' else r['precip_24h_in']
            if v != '': per[r['date']].append(float(v))
    return {d: float(np.mean(v)) for d, v in per.items() if len(v) >= 2}


def load_flow():
    from statewide_common import read
    gauges = {}
    for f in glob.glob(str(D / 'streamflow/history/*.json')):
        vals = {x['properties']['time'][:10]: float(x['properties']['value']) for x in read(f)['features']
                if x['properties'].get('parameter_code') == '00060' and x['properties'].get('statistic_id') == '00003'
                and x['properties'].get('value') not in (None, '') and not x['properties'].get('qualifier')}
        if vals and min(vals) <= '2000-12-31' and max(vals) >= '2026-01-01': gauges[f.split('\\')[-1].split('/')[-1][:-5]] = vals
    # Recent readings from the newest prospective snapshot (the history files are a fixed download).
    snaps = sorted(glob.glob(str(D / 'prospective/snapshots/*/inputs.json')))
    if snaps:
        for gid, vals in read(snaps[-1])['values'].get('streamflow', {}).items():
            if gid in gauges: gauges[gid].update({k: float(v) for k, v in vals.items()})
    z = {}
    for gid, vals in gauges.items():
        logs = {d: np.log1p(max(v, 0)) for d, v in vals.items()}
        m7 = {d: v / 7 for d, v in rolling_sum(logs, 7).items()}
        z[gid], _ = zscore_by_month(m7)
    days = sorted(set().union(*[set(v) for v in z.values()]))
    return {d: float(np.median([z[g][d] for g in z if d in z[g]])) for d in days if sum(d in z[g] for g in z) >= 20}


def load_wells():
    from statewide_common import read
    run = sorted(glob.glob(str(D / 'groundwater-history/*/manifest.json')))[-1].rsplit('manifest.json', 1)[0]
    wells = {}
    for f in glob.glob(run + 'USGS-*.json'):
        wells[f.split('\\')[-1].split('/')[-1][:-5]] = {x['properties']['time'][:10]: float(x['properties']['value']) for x in read(f)['features']
                                                         if x['properties'].get('value') not in (None, '') and not x['properties'].get('qualifier')}
    snaps = sorted(glob.glob(str(D / 'prospective/snapshots/*/inputs.json')))
    if snaps:
        for wid, vals in read(snaps[-1])['values'].get('groundwater', {}).items():
            if wid in wells: wells[wid].update({k: float(v) for k, v in vals.items()})
    z = {}
    for wid, vals in wells.items():
        zz, _ = zscore_by_month(vals); z[wid] = {d: -v for d, v in zz.items()}       # deeper water = drier
    days = sorted(set().union(*[set(v) for v in z.values()]))
    out = {}
    for d in days:
        vals = [z[w][d] for w in z if d in z[w]]
        if len(vals) >= 2: out[d] = float(np.median(vals))
    return out


def load_soil():
    s = {r['date']: float(r['soil_moisture_m3m3']) for r in csv.DictReader(open(D / 'drought/soil-moisture-daily.csv', encoding='utf-8'))}
    return zscore_by_month(s)[0]


def load_bui():
    return {r['date']: float(r['median_bui']) for r in csv.DictReader(open(D / 'fire-danger/history.csv', encoding='utf-8')) if r['median_bui'] != ''}


def load_water():
    by = defaultdict(dict)
    for r in csv.DictReader(open(D / 'water-temp/daily.csv', encoding='utf-8')): by[r['station']][r['date']] = float(r['water_temp_c'])
    z = {s: zscore_by_month(v)[0] for s, v in by.items()}
    days = sorted(set().union(*[set(v) for v in z.values()]))
    return {d: float(np.mean([z[s][d] for s in z if d in z[s]])) for d in days if sum(d in z[s] for s in z) >= 2}


def load_palmer():
    by = defaultdict(lambda: defaultdict(list))
    for r in csv.DictReader(open(D / 'drought/palmer-divisions.csv', encoding='utf-8')):
        for k in ('pdsi', 'phdi', 'zindex'):
            if r[k] != '': by[r['month']][k].append(float(r[k]))
    return {m: {k: float(np.mean(v)) for k, v in vals.items()} for m, vals in by.items() if len(vals.get('pdsi', [])) == 3}


def palmer_on(palmer, day):
    """Latest month published by `day` (month m treated as published on the 10th of month m+1)."""
    d = date.fromisoformat(day); y, m = (d.year, d.month - 1) if d.day >= 10 else (d.year, d.month - 2)
    while m <= 0: y, m = y - 1, m + 12
    for _ in range(3):
        key = '%d-%02d' % (y, m)
        if key in palmer: return palmer[key]
        m -= 1
        if m == 0: y, m = y - 1, 12
    return None


def load_usdm():
    by = defaultdict(dict)
    for r in csv.DictReader(open(D / 'drought/usdm-weekly.csv', encoding='utf-8')):
        by[r['unit']][r['map_date']] = np.array([float(r[k]) for k in ('d0', 'd1', 'd2', 'd3', 'd4')])
    return by


def load_vegdri():
    """unit -> sorted list of (available_day, mean, share below -1) from data/drought/vegdri-weekly.csv."""
    path = D / 'drought/vegdri-weekly.csv'; by = defaultdict(list)
    if not path.exists(): return {}
    for r in csv.DictReader(open(path, encoding='utf-8')):
        if r['mean'] in ('', 'None'): continue
        avail = str(date.fromisoformat(r['week_end']) + timedelta(days=VEGDRI_LAG_DAYS))
        by[r['unit']].append((avail, float(r['mean']), float(r['pct_below_minus1']) / 100))
    return {u: sorted(v) for u, v in by.items()}


VEGDRI_LAG_DAYS = 2


def vegdri_on(series, day, max_age_days=21):
    """Latest VegDRI week available by `day` (and no older than 3 weeks), or None."""
    best = None
    for avail, mean, share in series or []:
        if avail > day: break
        best = (avail, mean, share)
    if best is None or (date.fromisoformat(day) - date.fromisoformat(best[0])).days > max_age_days: return None
    return best


def vegdri_drivers(a, unit, issue):
    s = a.get('vegdri', {}).get(unit)
    now = vegdri_on(s, issue)
    if now is None: return [0.0, 0.0, 0.0, 1.0]
    then = vegdri_on(s, str(date.fromisoformat(now[0]) - timedelta(days=28)), 10)
    return [now[1], now[2], 0.0 if then is None else now[1] - then[1], 0.0]


def load_all():
    rain = load_rain()
    return dict(vegdri=load_vegdri(), rain=rain, rain_z={w: zscore_by_month(rolling_sum(rain, w))[0] for w in (30, 90, 180)}, flow=load_flow(), wells=load_wells(),
                soil=load_soil(), bui=load_bui(), water=load_water(), palmer=load_palmer(), usdm=load_usdm())


def rain_between(rain, a, b):
    """Total rain on days a..b inclusive; None if more than a quarter of days are missing."""
    a, b = date.fromisoformat(a), date.fromisoformat(b)
    if b < a: return 0.0
    days = [str(a + timedelta(days=k)) for k in range((b - a).days + 1)]; v = [rain.get(d) for d in days]
    if sum(x is None for x in v) > len(v) / 4: return None
    return float(np.sum([x for x in v if x is not None]) * len(v) / sum(x is not None for x in v))


def normal_rain_per_day(rain):
    return float(np.mean([v for d, v in rain.items() if d <= CLIM_END]))


NAMES = ['rain_30', 'rain_90', 'rain_180', 'rain_since_map', 'rain_ahead', 'flow', 'wells', 'soil', 'bui', 'water', 'pdsi', 'phdi', 'zindex',
         'd0', 'd1', 'd2', 'd3', 'd4', 'change_4w', 'sin', 'cos', 'lead']


def drivers(a, unit, map_date, issue, target, rain_ahead, vegdri=False):
    """Feature vector (with missing flags) for one unit, last map `map_date`, issue day and target map.
    vegdri=True (drought-v2) appends VegDRI mean, share below -1, 4-week change and its missing flag;
    with vegdri=False the vector is exactly drought-v1's."""
    before = str(date.fromisoformat(issue) - timedelta(days=1)); soil_day = str(date.fromisoformat(issue) - timedelta(days=6))
    def last(series, day, back=10):
        d = date.fromisoformat(day)
        for k in range(back):
            v = series.get(str(d - timedelta(days=k)))
            if v is not None: return v
        return None
    p = palmer_on(a['palmer'], issue) or {}
    cur = a['usdm'][unit].get(map_date)
    normal_day = normal_rain_per_day(a['rain'])
    since = rain_between(a['rain'], map_date, before)
    days_since = (date.fromisoformat(before) - date.fromisoformat(map_date)).days + 1
    vals = [last(a['rain_z'][30], before), last(a['rain_z'][90], before), last(a['rain_z'][180], before),
            None if since is None else since - normal_day * days_since,
            None if rain_ahead is None else rain_ahead - normal_day * ((date.fromisoformat(target) - date.fromisoformat(issue)).days + 1),
            last(a['flow'], before), last(a['wells'], before, 30), last(a['soil'], soil_day), last(a['bui'], before), last(a['water'], before),
            p.get('pdsi'), p.get('phdi'), p.get('zindex')]
    if cur is None: return None
    doy = 2 * np.pi * (date.fromisoformat(target).timetuple().tm_yday - 1) / 365.2425
    lead = (date.fromisoformat(target) - date.fromisoformat(map_date)).days / 7
    prev = a['usdm'][unit].get(str(date.fromisoformat(map_date) - timedelta(days=28)))
    change = 0.0 if prev is None else float(np.sum(cur - prev) / 100)      # DSCI change over the last 4 weeks (x100)
    x = [0.0 if v is None else float(v) for v in vals] + list(cur / 100) + [change, np.sin(doy), np.cos(doy), lead]
    flags = [1.0 if v is None else 0.0 for v in vals]
    return np.array(x + flags + (vegdri_drivers(a, unit, issue) if vegdri else []))
