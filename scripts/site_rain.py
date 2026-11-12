"""Rain at stream gauge drainage areas and groundwater wells, for the rain-aware v2 models.

A rain "day" D is the 24 hours ending about 7 AM on D (12:00 UTC), the convention of the
volunteer rain gauges that make up most stations and of PRISM.

History (training): data/rain-stations/site-rain.npz from scripts/build_site_rain.py (NOAA GHCN-Daily).
Live, for each site and day, the first available of:
  1. station rain (same source as training; NOAA posts it about 2-4 days late)
  2. PRISM for that day (the grid mean over the drainage area, or the cell at a well)
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
    c0, _, qpf = nbm_weather(points, not_after=cutoff)
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
            n = nbm.get(s['id'], {}).get(str(d))
            if n is not None and d >= today - timedelta(days=1): vals.append(n); src.append('NOAA NBM'); continue
            n = saved.get(s['id'], {}).get(str(d))
            if n is not None: vals.append(n); src.append('NOAA NBM (saved)'); continue
            vals.append(normal[d.month]); src.append('normal')
        out[s['id']] = dict(days=[str(d) for d in days], rain=np.array(vals), source=src, kind=s['kind'])
    return out, cycle
