"""Daily observed rain at each stream gauge's drainage area and each groundwater well, 2000-present.

Source: NOAA NCEI GHCN-Daily station precipitation (airports, cooperative observers, CoCoRaHS
volunteers) for every station within 40.6-42.4 N, 74.2-71.3 W that reported rain in 2000 or later.
Values flagged by NOAA's quality checks are dropped; missing days stay missing (never zero).

  Stream gauges: mean of the stations inside the gauge's upstream drainage area (USGS NLDI boundary,
                 widened by 5 km); on days with none reporting, an inverse-distance mean of the 3 nearest
                 reporting stations within 30 km of the area's centre.
  Wells:         inverse-distance mean of the 3 nearest reporting stations within 25 km.

Station days are as reported (most volunteer gauges read at about 7 AM, airports at midnight), so a
day's total can straddle two calendar days; this mixes timing by up to a day.

Output: data/rain-stations/site-rain.npz (sites x days, mm) and site-rain.json (sites, method,
stations used). `--recent` refreshes only the last 60 days from the NCEI data service.
"""
import argparse
import csv
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, datetime, timezone
import numpy as np
import requests
from shapely.geometry import shape, Point
from statewide_common import ROOT, read, log

D = ROOT / 'data/rain-stations'; RAW = D / 'raw'; BASINS = D / 'basins'
START = date(2000, 1, 1)
UA = {'User-Agent': 'Connecticut agricultural water forecast research'}
# Site sets. 'ct' (Connecticut gauges and wells) is frozen with its v2 models; 'regional' (neighboring-state
# gauges, up to the upper Connecticut River) keeps its own file so the Connecticut inputs never change.
SETS = {'ct': dict(box=(40.6, 42.4, -74.2, -71.3), registry='data/prospective/model-v1.json', out='site-rain', near_basins=False),
        'regional': dict(box=(40.4, 45.5, -76.4, -69.6), registry='data/regional-prospective/model-v1.json', out='site-rain-regional', near_basins=True)}
BOX = SETS['ct']['box']


def stations(box=None):
    box = box or BOX; inv = {}
    for line in open(D / 'ghcnd-inventory.txt', encoding='utf-8'):
        sid, lat, lon, el, y0, y1 = line.split()
        lat, lon = float(lat), float(lon)
        if el == 'PRCP' and int(y1) >= 2000 and box[0] <= lat <= box[1] and box[2] <= lon <= box[3]: inv[sid] = (lat, lon, int(y0), int(y1))
    return inv


def days_until(end): return [START + timedelta(days=i) for i in range((end - START).days + 1)]


def parse_access(text):
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        v = (r.get('PRCP') or '').strip()
        if not v: continue
        attrs = (r.get('PRCP_ATTRIBUTES') or '').split(',')
        if len(attrs) > 1 and attrs[1].strip(): continue          # failed a NOAA quality check
        if r['DATE'] >= str(START): out[r['DATE']] = int(v) / 10.0  # tenths of mm -> mm
    return out


def fetch_full(sid):
    path = RAW / (sid + '.json')
    if path.exists(): return sid, read(path)
    for a in range(4):
        try:
            r = requests.get('https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/%s.csv' % sid, headers=UA, timeout=180)
            if r.status_code == 404: vals = {}; break
            r.raise_for_status(); vals = parse_access(r.text); break
        except requests.RequestException:
            if a == 3: raise
            time.sleep(10 * (a + 1))
    path.write_text(json.dumps(vals), encoding='utf-8'); return sid, vals


def fetch_recent(ids, days=60):
    """Last `days` days for active stations from the NCEI data service (50 stations per request)."""
    end = date.today(); start = end - timedelta(days=days); out = {}
    for k in range(0, len(ids), 50):
        chunk = ids[k:k + 50]; r = None
        # NOAA's service sometimes answers 503 for a while: retry, and skip only a batch that keeps failing.
        for attempt in range(4):
            try:
                r = requests.get('https://www.ncei.noaa.gov/access/services/data/v1', headers=UA, timeout=300, params=dict(
                    dataset='daily-summaries', stations=','.join(chunk), dataTypes='PRCP', startDate=str(start), endDate=str(end),
                    units='metric', format='json', includeAttributes='true'))
                r.raise_for_status(); break
            except requests.RequestException as e:
                r = None; print('NOAA station service: %s (attempt %d of 4)' % (type(e).__name__, attempt + 1), flush=True)
                time.sleep(30 * (attempt + 1))
        if r is None:
            print('Skipped %d stations this run; their saved rain is used.' % len(chunk)); continue
        for row in r.json():
            v = row.get('PRCP'); attrs = (row.get('PRCP_ATTRIBUTES') or '').split(',')
            if v in (None, '') or (len(attrs) > 1 and attrs[1].strip()): continue
            out.setdefault(row['STATION'], {})[row['DATE'][:10]] = float(v)
    return out


def basin(gauge_id):
    path = BASINS / (gauge_id + '.geojson')
    if not path.exists():
        r = requests.get('https://api.water.usgs.gov/nldi/linked-data/nwissite/%s/basin' % gauge_id, params=dict(f='json'), headers=UA, timeout=180)
        r.raise_for_status(); path.write_bytes(r.content)
    g = read(path)
    return shape(g['features'][0]['geometry'])


def sites(registry='data/prospective/model-v1.json'):
    reg = read(ROOT / registry); out = []
    for g in reg['streamflow']:
        out.append(dict(id=g['gauge_id'], kind='streamflow', lon=g['coordinates'][0], lat=g['coordinates'][1]))
    for w in reg['groundwater']:
        out.append(dict(id=w['id'], kind='groundwater', lon=w['coordinates'][0], lat=w['coordinates'][1]))
    return out


def km(lat1, lon1, lat2, lon2):
    return 6371 * np.sqrt((np.radians(lat2 - lat1)) ** 2 + (np.radians(lon2 - lon1) * np.cos(np.radians((lat1 + lat2) / 2))) ** 2)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--recent', action='store_true'); ap.add_argument('--set', choices=sorted(SETS), default='ct'); a = ap.parse_args()
    cfg = SETS[a.set]
    RAW.mkdir(parents=True, exist_ok=True); BASINS.mkdir(parents=True, exist_ok=True)
    inv = stations(cfg['box'])
    site_list = sites(cfg['registry'])
    if cfg['near_basins']:
        # Only stations within about 30 km of a drainage area (keeps the download to what is used).
        from shapely.ops import unary_union
        shapes = []
        for s_ in site_list:
            try: shapes.append(basin(s_['id']))
            except Exception: shapes.append(Point(s_['lon'], s_['lat']))
        zone = unary_union([g.buffer(0.35) for g in shapes])
        inv = {k: v for k, v in inv.items() if zone.contains(Point(v[1], v[0]))}
    ids = sorted(inv)
    with ThreadPoolExecutor(8) as pool: data = dict(pool.map(fetch_full, ids))
    if a.recent:
        active = [s for s in ids if inv[s][3] >= date.today().year - 1]
        for sid, vals in fetch_recent(active).items():
            data.setdefault(sid, {}).update(vals)
            (RAW / (sid + '.json')).write_text(json.dumps(data[sid]), encoding='utf-8')
    all_days = days_until(date.today()); index = {str(d): i for i, d in enumerate(all_days)}
    S = np.full((len(ids), len(all_days)), np.nan)
    for i, sid in enumerate(ids):
        for d, v in data[sid].items():
            if d in index and 0 <= v < 400: S[i, index[d]] = v
    lat = np.array([inv[s][0] for s in ids]); lon = np.array([inv[s][1] for s in ids])
    meta = []; R = np.full((0, len(all_days)), np.nan)
    for site in site_list:
        if site['kind'] == 'streamflow':
            try:
                poly = basin(site['id']); c = poly.centroid; buf = poly.buffer(0.05)    # about 5 km
                inside = np.array([buf.contains(Point(x, y)) for x, y in zip(lon, lat)])
                clat, clon, radius, method = c.y, c.x, 30, 'basin'
            except Exception as e:
                inside = np.zeros(len(ids), bool); clat, clon, radius, method = site['lat'], site['lon'], 30, 'point (no basin: %s)' % type(e).__name__
        else:
            inside = np.zeros(len(ids), bool); clat, clon, radius, method = site['lat'], site['lon'], 25, 'point'
        dist = km(clat, clon, lat, lon); near = np.where(dist <= radius)[0]
        series = np.full(len(all_days), np.nan); used_inside = np.zeros(len(all_days), int)
        if inside.any():
            sub = S[inside]; n = np.isfinite(sub).sum(0)
            ok = n > 0; series[ok] = np.nansum(np.nan_to_num(sub[:, ok]), axis=0) / n[ok]; used_inside = n
        need = ~np.isfinite(series)
        if need.any() and len(near):
            order = near[np.argsort(dist[near])]
            for t in np.where(need)[0]:
                rep = [k for k in order if np.isfinite(S[k, t])][:3]
                if rep:
                    w = 1 / np.maximum(dist[rep], 1.0) ** 2; series[t] = float(np.sum(w * S[rep, t]) / w.sum())
        R = np.vstack([R, series]); meta.append(dict(site, method=method, stations_inside=int(inside.sum()), stations_within_km=int(len(near)),
                                                    radius_km=radius, days_with_rain=int(np.isfinite(series).sum())))
    np.savez_compressed(D / (cfg['out'] + '.npz'), rain=R, start=str(START), ids=np.array([m['id'] for m in meta]))
    (D / (cfg['out'] + '.json')).write_text(json.dumps(dict(created_at=datetime.now(timezone.utc).isoformat(), start=str(START), days=len(all_days),
                                                     stations=len(ids), sites=meta), indent=1), encoding='utf-8')
    have = [int(np.isfinite(R[:, k]).sum()) for k in range(len(all_days))]
    last = max(k for k in range(len(all_days)) if have[k] >= 0.8 * len(meta))
    log('Site rain (' + a.set + '): %d sites from %d NOAA stations, %s to %s (80%% of sites covered through %s).' % (len(meta), len(ids), all_days[0], all_days[-1], all_days[last]))
    print('sites', len(meta), 'stations', len(ids), 'complete through', all_days[last])


if __name__ == '__main__':
    main()
