"""Watershed boundaries and NLDAS 1/8-degree cell weights for the 69 root-zone watersheds.

Boundaries: USGS NLDI gauge basins (already cached under data/hydrography/nldi
for most gauges; missing ones are fetched to data/root-zone/basins/nldi). These
are NHDPlus-derived and approximate the GAGES-II boundaries the USGS archive used.
Each boundary's area is compared with the GAGES-II drainage area; the archive
alignment check (assemble_root_zone_inputs.py --check-archive) measures how
closely the resulting watershed means reproduce the archive values.
"""
import json
import math
import time
from datetime import datetime, timezone
import numpy as np
import requests
from shapely.geometry import box as cellbox, shape
from shapely.ops import unary_union
from root_zone_live import ROOT, BASINS, LON0, LAT0, STEP, cell_lon, cell_lat

NLDI = 'https://api.water.usgs.gov/nldi/linked-data/nwissite/USGS-%s/basin'
HEADERS = {'User-Agent': 'AheadOfTheStormResearch/0.1 (root-zone watershed boundaries)'}


def load_basin(sid):
    candidates = [ROOT / 'data/hydrography/nldi-split' / ('USGS-%s-basin.geojson' % sid),
                  ROOT / 'data/hydrography/nldi' / ('USGS-%s-basin.geojson' % sid),
                  BASINS / 'nldi' / ('USGS-%s-basin.geojson' % sid)]
    found = [(p, json.loads(p.read_text(encoding='utf-8'))) for p in candidates if p.exists()]
    if not found:
        path = candidates[-1]; path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(4):
            try:
                r = requests.get(NLDI % sid, params=dict(f='json', simplified='false'), headers=HEADERS, timeout=120)
                if r.status_code == 404:
                    return None
                r.raise_for_status(); value = r.json(); break
            except Exception:
                if attempt == 3: raise
                time.sleep(5 * (attempt + 1))
        path.write_text(json.dumps(value), encoding='utf-8')
        found = [(path, value)]
    return found


def area_km2(geom):
    # Local equal-area approximation adequate for basin-size comparison.
    lat = geom.centroid.y
    return geom.area * (111.32 ** 2) * math.cos(math.radians(lat))


def main():
    prepared = json.loads((ROOT / 'data/root-zone/prepared/manifest.json').read_text(encoding='utf-8'))
    ids = list(prepared['sites'])
    polys = {}; meta = {}
    for sid in ids:
        options = load_basin(sid)
        if not options:
            meta[sid] = dict(status='No NLDI basin available'); continue
        published = float(prepared['sites'][sid]['DRAIN_SQKM'])
        best = None
        for path, value in options:
            g = unary_union([shape(f['geometry']) for f in value['features']])
            a = area_km2(g); ratio = a / published
            if best is None or abs(math.log(ratio)) < abs(math.log(best[2])):
                best = (path, g, ratio, a)
        path, g, ratio, a = best
        polys[sid] = g
        meta[sid] = dict(source=str(path.relative_to(ROOT)), boundary_area_km2=round(a, 2),
                         gagesii_drain_sqkm=published, area_ratio=round(ratio, 3),
                         status='Area within 10% of GAGES-II' if abs(ratio - 1) <= .10 else
                                'Review: boundary area differs from GAGES-II by more than 10%')
        print('%s boundary area ratio %.3f' % (sid, ratio), flush=True)
    bounds = np.array([g.bounds for g in polys.values()])
    i0 = int(math.floor((bounds[:, 0].min() - LON0) / STEP + 0.5)) - 1
    i1 = int(math.floor((bounds[:, 2].max() - LON0) / STEP + 0.5)) + 1
    j0 = int(math.floor((bounds[:, 1].min() - LAT0) / STEP + 0.5)) - 1
    j1 = int(math.floor((bounds[:, 3].max() - LAT0) / STEP + 0.5)) + 1
    weights = {}
    h = STEP / 2
    for sid, g in polys.items():
        cells = []
        for j in range(j0, j1 + 1):
            for i in range(i0, i1 + 1):
                c = cellbox(cell_lon(i) - h, cell_lat(j) - h, cell_lon(i) + h, cell_lat(j) + h)
                if not c.intersects(g): continue
                frac = c.intersection(g).area
                if frac > 0:
                    cells.append([j, i, frac * math.cos(math.radians(cell_lat(j)))])
        s = sum(c[2] for c in cells)
        weights[sid] = [[j, i, w / s] for j, i, w in cells]
        meta[sid]['nldas_cells'] = len(cells)
    out = dict(created_at=datetime.now(timezone.utc).isoformat(), box=[j0, j1, i0, i1],
               box_degrees=dict(lat=[cell_lat(j0), cell_lat(j1)], lon=[cell_lon(i0), cell_lon(i1)]),
               grid='NLDAS-2 0.125 degree, cell centres lon -124.9375 + 0.125 i, lat 25.0625 + 0.125 j',
               weighting='Fraction of each cell inside the boundary x cos(latitude); normalised per watershed',
               watersheds=weights, boundaries=meta,
               missing=[s for s in ids if s not in polys])
    BASINS.mkdir(parents=True, exist_ok=True)
    (BASINS / 'weights.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    print(json.dumps(dict(watersheds=len(weights), missing=out['missing'], box=out['box'],
                          review=[s for s, m in meta.items() if m.get('status', '').startswith('Review')]), indent=2))


if __name__ == '__main__':
    main()
