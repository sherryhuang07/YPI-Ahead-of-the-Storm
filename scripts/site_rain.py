"""Rain at stream gauge drainage areas and groundwater wells, for the rain-aware v2 models.

A rain "day" D is the 24 hours ending about 7 AM on D (12:00 UTC), the convention of the
volunteer rain gauges that make up most stations and of PRISM.

History (training): data/rain-stations/site-rain.npz from scripts/build_site_rain.py (NOAA GHCN-Daily).
Live, for each site and day, the first available of:
  1. station rain (same source as training; NOAA posts it about 2-4 days late)
  2. PRISM for that day (the grid mean over the drainage area, or the cell at a well)
  2b. NEWA measured rain (Cornell weather stations, read from the nightly browser capture in data/newa/):
     hourly gauges summed into 7 AM days, the mean of the stations inside the drainage area or the
     inverse-distance mean of the 3 nearest within 25 km; gauges failing the gut-check are left out;
     scaled by newa_scale() to match the NOAA gauges where both measured rain (tipping-bucket undercatch)
  3. NOAA NBM forecast from the newest cycle issued at or before 7 AM yesterday (12:00 UTC), so every
     forecast day is a complete 24 hours of forecast; NBM reaches about 10 days
  3b. for days already past that stations and PRISM have not reached yet: the most recent saved NBM
     forecast for that day (each run saves its NBM values in data/rain-stations/nbm-archive/<set>/)
  4. normal rain for that site and month (2000-2020 mean), flagged
PRISM covers Connecticut only, so it is used only where at least half of a drainage area lies inside it.
Site sets: 'site-rain' (Connecticut gauges and wells) and 'site-rain-regional' (neighboring-state gauges).
"""
import json
from datetime import date, datetime, timedelta, timezone
import numpy as np
from statewide_common import ROOT, read

D = ROOT / 'data/rain-stations'


def history(name='site-rain'):
    z = np.load(D / (name + '.npz'), allow_pickle=False)
    start = date.fromisoformat(str(z['start']))
    return {str(i): z['rain'][k] for k, i in enumerate(z['ids'])}, start


def normal_by_month(series, start, end_year=2020):
    """Mean daily rain per calendar month over 2000..end_year (mm/day)."""
    out = {}
    days = [start + timedelta(days=i) for i in range(len(series))]
    for m in range(1, 13):
        v = [series[i] for i, d in enumerate(days) if d.month == m and d.year <= end_year and np.isfinite(series[i])]
        out[m] = float(np.mean(v)) if v else np.nan
    return out


def window_sum(series, i, n):
    """Sum of days i-n+1..i; NaN if any day is missing."""
    if i - n + 1 < 0 or i >= len(series): return np.nan
    w = series[i - n + 1:i + 1]
    return float(w.sum()) if np.isfinite(w).all() else np.nan


def prism_values(sites_meta):
    """PRISM day -> site -> mm, from the newest prospective snapshot (basin mean or point cell)."""
    import rasterio
    from rasterio.features import geometry_mask
    from shapely.geometry import shape, mapping
    last = read(ROOT / 'outputs/prospective/last-run.json'); snap = read(ROOT / last['snapshot'])
    out = {}; masks = None
    for day, path in sorted(snap['grids'].items()):
        with rasterio.open(ROOT / path) as src:
            arr = src.read(1, masked=True).filled(np.nan)
            if masks is None:
                masks = {}
                for s in sites_meta:
                    bp = D / 'basins' / (s['id'] + '.geojson')
                    if s['kind'] == 'streamflow' and bp.exists():
                        geom = read(bp)['features'][0]['geometry']
                        from rasterio.warp import transform_geom
                        g = transform_geom('EPSG:4326', src.crs, geom)
                        m = geometry_mask([g], out_shape=arr.shape, transform=src.transform, invert=True)
                        from shapely.geometry import box as sbox
                        from rasterio.warp import transform_bounds
                        poly = shape(geom); crop = sbox(*transform_bounds(src.crs, 'EPSG:4326', *src.bounds))
                        if poly.intersection(crop).area < 0.5 * poly.area: continue    # mostly outside the PRISM crop
                        if m.any(): masks[s['id']] = m; continue
                    from rasterio.warp import transform
                    xs, ys = transform('EPSG:4326', src.crs, [s['lon']], [s['lat']])
                    r, c = src.index(xs[0], ys[0]); m = np.zeros(arr.shape, bool)
                    if 0 <= r < arr.shape[0] and 0 <= c < arr.shape[1]: m[r, c] = True
                    masks[s['id']] = m
        for sid, m in masks.items():
            v = arr[m]; v = v[np.isfinite(v)]
            if v.size: out.setdefault(day, {})[sid] = float(v.mean())
    return out


def nbm_values(sites_meta, today):
    """Site -> {day: mm} from the newest NBM cycle issued at or before 12:00 UTC yesterday."""
    from fire_danger_forecast import nbm_weather, rain_24h
    cutoff = datetime.combine(today - timedelta(days=1), datetime.min.time(), timezone.utc).replace(hour=12)
    points = {}
    for s in sites_meta:
        bp = D / 'basins' / (s['id'] + '.geojson')
        if s['kind'] == 'streamflow' and bp.exists():
            from shapely.geometry import shape
            c = shape(read(bp)['features'][0]['geometry']).centroid; points[s['id']] = (c.y, c.x)
        else:
            points[s['id']] = (s['lat'], s['lon'])
    # Yesterday's rain day (ending 7 AM yesterday) would need a cycle from two days ago, which NOAA no
    # longer serves; until station or PRISM data arrive, that one day uses normal rain (flagged).
    try:
        c0, _, qpf = nbm_weather(points, not_after=cutoff)
    except RuntimeError:
        # Late-evening runs: NOAA keeps two UTC days, so yesterday's 7 AM cycle can already be gone. Use the newest
        # cycle from before 7 AM today: it covers every day from tomorrow; today's rain day then comes from the
        # forecast saved by an earlier run (live_series falls back to it).
        c0, _, qpf = nbm_weather(points, not_after=cutoff + timedelta(days=1))
    out = {}
    for sid in points:
        for k in range(0, 16):
            d = today + timedelta(days=k); end = datetime.combine(d, datetime.min.time(), timezone.utc).replace(hour=12)
            if end - timedelta(hours=24) < c0: continue          # window must be wholly inside the forecast
            v = rain_24h(qpf, sid, end, c0)
            if v is not None: out.setdefault(sid, {})[str(d)] = float(v)
    return out, c0.isoformat()


def saved_nbm(name, today):
    """site -> {day: mm} from earlier runs' saved NBM forecasts (newest forecast for each day wins)."""
    out = {}
    for f in sorted((D / 'nbm-archive' / name).glob('*.json')):
        if f.stem >= str(today): continue
        for sid, vals in read(f).items(): out.setdefault(sid, {}).update(vals)
    return out


NEWA_INFO = {}              # what the last live_series call did with NEWA (recorded in the sealed snapshot)
NEWA_REACH_KM = 25          # a site uses NEWA stations within this distance (or inside its drainage area)


def _km(lat1, lon1, lat2, lon2):
    import math
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2)); y = math.radians(lat2 - lat1)
    return 6371.0 * math.hypot(x, y)


def newa_station_rain():
    """NEWA measured rain on 7 AM days: station -> {day: mm}, from every nightly capture (newest wins).
    Gauges failing the capture's gut-check (read 0 for the week while the typical station caught rain)
    are left out for that capture's days."""
    from newa_weather import D as NEWA_D, quality
    out = {}
    for f in sorted(NEWA_D.glob('*.json')):
        try: cap = read(f)
        except Exception: continue
        st = {sid: v for sid, v in cap.get('stations', {}).items() if v.get('r7') and v.get('obs')}
        if not st: continue
        _, skip_rain, _ = quality(st)
        for sid, v in st.items():
            if sid in skip_rain: continue
            for d, rain_in, _hours in v['r7']:
                if rain_in is not None: out.setdefault(sid, {})[d] = round(rain_in * 25.4, 2)
    return out


def newa_values(sites_meta):
    """site -> {day: mm}: mean of the NEWA stations inside a gauge's drainage area (2 km margin), otherwise
    inverse-distance mean of the 3 nearest stations within 25 km (wells always use the latter).
    Returns ({}, {}) when there is no capture with measured 7 AM rain."""
    rain = newa_station_rain()
    if not rain: return {}, {}
    from shapely.geometry import shape, Point
    meta = {s['sid']: s for s in read(ROOT / 'scripts/newa_stations.json')['stations'] if s['sid'] in rain}
    out, used = {}, {}
    for s in sites_meta:
        bp = D / 'basins' / (s['id'] + '.geojson'); inside = []
        if s['kind'] == 'streamflow' and bp.exists():
            poly = shape(read(bp)['features'][0]['geometry']).buffer(0.02)
            inside = [sid for sid, m in meta.items() if poly.contains(Point(m['lon'], m['lat']))]
        if inside:
            wts = {sid: 1.0 for sid in inside}
        else:
            near = sorted((_km(s['lat'], s['lon'], m['lat'], m['lon']), sid) for sid, m in meta.items())
            near = [(k, sid) for k, sid in near if k <= NEWA_REACH_KM][:3]
            wts = {sid: 1.0 / max(k, 1.0) ** 2 for k, sid in near}
        if not wts: continue
        days = sorted({d for sid in wts for d in rain[sid]})
        for d in days:
            have = {sid: w for sid, w in wts.items() if d in rain[sid]}
            if have:
                out.setdefault(s['id'], {})[d] = round(sum(rain[sid][d] * w for sid, w in have.items()) / sum(have.values()), 2)
        used[s['id']] = sorted(wts)
    return out, used


def newa_scale(newa, hist, start):
    """NEWA's tipping-bucket gauges catch less than the NOAA volunteer gauges the models were trained on.
    Scale = station total / NEWA total over site-days where both exist and the station caught >= 1 mm.
    Needs 10 such site-days, else 1.0; kept between 0.8 and 1.3 (about the most undercatch reported for
    tipping buckets, so one unusual storm can't push it further)."""
    a = b = 0.0; n = 0
    for sid, vals in newa.items():
        h = hist.get(sid)
        if h is None: continue
        for d, v in vals.items():
            i = (date.fromisoformat(d) - start).days
            if 0 <= i < len(h) and np.isfinite(h[i]) and h[i] >= 1.0: a += float(h[i]); b += v; n += 1
    if n < 10 or b <= 0: return 1.0, n
    return float(min(1.3, max(0.8, a / b))), n


def live_series(today, back=120, ahead=15, name='site-rain'):
    """site -> (array of daily rain for days today-back .. today+ahead-1, list of sources, normals)."""
    hist, start = history(name)
    meta = read(D / (name + '.json'))['sites']
    prism = prism_values(meta)
    try:
        nbm, cycle = nbm_values(meta, today)
        arch = D / 'nbm-archive' / name; arch.mkdir(parents=True, exist_ok=True)
        (arch / (str(today) + '.json')).write_text(json.dumps(nbm), encoding='utf-8')
    except Exception as e:                       # NOAA unreachable: forecasts fall back to "no rain forecast" inputs
        nbm, cycle = {}, 'unavailable (%s)' % type(e).__name__
    saved = saved_nbm(name, today)
    NEWA_INFO.clear()
    try:
        newa, _ = newa_values(meta)
        scale, n = newa_scale(newa, hist, start)
        NEWA_INFO.update(scale=round(scale, 3), matched_site_days=n, captures=sorted(f.name for f in (ROOT / 'data/newa').glob('*.json')))
        newa = {sid: {d: round(v * scale, 2) for d, v in vals.items()} for sid, vals in newa.items()}
    except Exception as e:                       # a bad capture must never stop the forecast
        newa = {}; NEWA_INFO.update(error=type(e).__name__)
    days = [today - timedelta(days=back) + timedelta(days=k) for k in range(back + ahead)]
    out = {}
    for s in meta:
        h = hist[s['id']]; normal = normal_by_month(h, start)
        vals = []; src = []
        for d in days:
            i = (d - start).days; v = h[i] if 0 <= i < len(h) else np.nan
            if np.isfinite(v): vals.append(float(v)); src.append('station'); continue
            p = prism.get(str(d), {}).get(s['id'])
            if p is not None and d < today: vals.append(p); src.append('PRISM'); continue
            w = newa.get(s['id'], {}).get(str(d))
            if w is not None and d <= today: vals.append(w); src.append('NEWA'); continue
            n = nbm.get(s['id'], {}).get(str(d))
            if n is not None and d >= today - timedelta(days=1): vals.append(n); src.append('NOAA NBM'); continue
            n = saved.get(s['id'], {}).get(str(d))
            if n is not None: vals.append(n); src.append('NOAA NBM (saved)'); continue
            vals.append(normal[d.month]); src.append('normal')
        out[s['id']] = dict(days=[str(d) for d in days], rain=np.array(vals), source=src, kind=s['kind'])
    return out, cycle
