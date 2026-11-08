"""Download USGS VegDRI (Vegetation Drought Response Index) weekly maps and keep Connecticut only.

VegDRI is a weekly 1 km national map (2009-present) from USGS EROS that blends satellite
vegetation greenness (NDVI) with climate drought indices and land cover. Values below about -1
indicate drought stress in vegetation; above +1 unusually moist. Water, urban and other
non-vegetated pixels carry no VegDRI value.

Source: USGS EarthExplorer machine-to-machine API, dataset `vegdri`, one national file per week.
Each file is downloaded, clipped to Connecticut's 9 planning regions (data/drought/raw/planning-regions.geojson),
summarised, and deleted, so only the small Connecticut table is kept:

  data/drought/vegdri-weekly.csv   week_start, week_end, unit (CT or region id), mean, pct_below_minus1,
                                   pct_below_minus2, pixels, entity, first_seen (UTC time this computer first had it)

Credentials: USGS_USERNAME / USGS_TOKEN from the environment (set by the USGS launcher from the
encrypted saved sign-in); never logged.

  --recent    only weeks not in the table yet (nightly run)
  --limit N   at most N new weeks this run
"""
import argparse
import csv
import json
import shutil
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import requests
from statewide_common import ROOT, log

OUT = ROOT / 'data/drought/vegdri-weekly.csv'
REGIONS = ROOT / 'data/drought/raw/planning-regions.geojson'
CT_BOX = dict(lowerLeft=dict(latitude=40.95, longitude=-73.75), upperRight=dict(latitude=42.06, longitude=-71.78))
FIELDS = ['week_start', 'week_end', 'unit', 'mean', 'pct_below_minus1', 'pct_below_minus2', 'pixels', 'pct_out_of_season', 'entity', 'first_seen']


def scenes(m):
    sf = dict(spatialFilter=dict(filterType='mbr', **CT_BOX), acquisitionFilter=dict(start='2009-01-01', end=str(datetime.now(timezone.utc).date())))
    out = {}; start = 1
    for _ in range(50):
        r = m.call('scene-search', dict(datasetName='vegdri', sceneFilter=sf, maxResults=500, startingNumber=start, sortField='acquisitionDate', sortDirection='ASC'))
        new = [x for x in r['results'] if x['entityId'] not in out]
        for x in new: out[x['entityId']] = x
        if not new or not r.get('nextRecord') or r['nextRecord'] <= start or r['nextRecord'] > r['totalHits']: break
        start = r['nextRecord']
    weeks = {}
    for x in out.values():       # several product versions can exist for one week: keep the highest version suffix
        tc = x['temporalCoverage']; key = (tc['startDate'][:10], tc['endDate'][:10])
        if key not in weeks or x['entityId'][-2:] > weeks[key]['entityId'][-2:]: weeks[key] = x
    return weeks


def region_masks(transform, shape, crs):
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom
    regions = json.loads(REGIONS.read_text(encoding='utf-8'))['features']; masks = {}
    for f in regions:
        g = transform_geom('EPSG:4326', crs, f['geometry'])
        masks['%s|%s' % (f['properties']['GEOID'], f['properties']['NAME'])] = geometry_mask([g], out_shape=shape, transform=transform, invert=True)
    masks['CT'] = np.any(list(masks.values()), axis=0)
    return masks


def summarise(tif):
    """Connecticut-clipped VegDRI summaries per planning region and statewide."""
    import rasterio
    from rasterio.windows import from_bounds
    from rasterio.warp import transform_bounds
    with rasterio.open(tif) as src:
        b = transform_bounds('EPSG:4326', src.crs, -73.80, 40.90, -71.70, 42.10)
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        arr = src.read(1, window=win).astype(float); tr = src.window_transform(win)
        nodata = src.nodata; scale = src.scales[0] if src.scales else 1.0; offset = src.offsets[0] if src.offsets else 0.0
        crs = src.crs
    valid = np.isfinite(arr)
    if nodata is not None: valid &= arr != nodata
    vals = to_index(arr, valid)
    valid &= np.isfinite(vals)
    out = {}
    for unit, mask in region_masks(tr, arr.shape, crs).items():
        v = vals[mask & valid]; season = arr[mask] == 254
        out[unit] = dict(mean=None, pct_below_minus1=None, pct_below_minus2=None, pixels=0, pct_out_of_season=round(float(season.mean() * 100), 1)) if v.size < 20 else \
            dict(mean=round(float(v.mean()), 4), pct_below_minus1=round(float((v < -1).mean() * 100), 2),
                 pct_below_minus2=round(float((v < -2).mean() * 100), 2), pixels=int(v.size), pct_out_of_season=round(float(season.mean() * 100), 1))
    return out


def to_index(dn, valid):
    """VegDRI GeoTIFFs are 8-bit: index = (DN - 128) / 16, on the Palmer scale (about -8..+8).
    253 = water, 254 = out of season (winter), 255 = other land cover (urban, barren): no value."""
    return np.where(valid & (dn <= 252), (dn - 128) / 16.0, np.nan)


def fetch_file(url, folder, entity, attempts=30):
    """Download one staged file; the staging URL answers with a page until the file is ready."""
    for _ in range(attempts):
        try:
            r = requests.get(url, timeout=600, stream=True)
            if r.status_code == 200 and 'html' not in r.headers.get('content-type', ''):
                name = (r.headers.get('content-disposition', '').split('filename=')[-1].strip('"; ') or entity + '.tar')
                path = folder / name
                with path.open('wb') as fh:
                    for ch in r.iter_content(1 << 20): fh.write(ch)
                return path
        except requests.RequestException:
            pass
        time.sleep(15)
    raise RuntimeError('Download not ready for ' + entity)


def request_batch(m, batch, label):
    """Ask USGS to stage a batch of weeks; returns entity -> download URL."""
    opts = m.call('download-options', dict(datasetName='vegdri', entityIds=[x['entityId'] for x in batch]))
    pick = {}
    for o in opts:
        if o.get('available') and o['entityId'] not in pick: pick[o['entityId']] = o['id']
    if not pick: return {}
    req = m.call('download-request', dict(downloads=[dict(entityId=e, productId=pid) for e, pid in pick.items()], label=label))
    urls = {d['entityId']: d['url'] for d in req.get('availableDownloads', []) + req.get('preparingDownloads', []) if d.get('entityId')}
    for _ in range(20):
        if len(urls) >= len(pick): break
        time.sleep(10)
        rd = m.call('download-retrieve', dict(label=label))
        for d in rd.get('available', []) + rd.get('requested', []):
            if d.get('entityId') and d.get('url'): urls.setdefault(d['entityId'], d['url'])
    return urls


def process(x, url):
    eid = x['entityId']; tc = x['temporalCoverage']; tmp = Path(tempfile.mkdtemp(prefix='vegdri-'))
    try:
        res = summarise(find_tif(fetch_file(url, tmp, eid), tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    seen = datetime.now(timezone.utc).isoformat()
    return [dict(week_start=tc['startDate'][:10], week_end=tc['endDate'][:10], unit=u, entity=eid, first_seen=seen, **v) for u, v in res.items()]


def find_tif(path, folder):
    """The weekly file is a tar (or zip) holding VegDRI, its weekly change, PASG and a picture: keep VegDRI."""
    import tarfile
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as t:
            members = [x for x in t.getmembers() if x.isfile() and Path(x.name).name.lower().startswith('vegdri') and 'diff' not in x.name.lower()
                       and Path(x.name).suffix.lower() in ('.tif', '.tiff')]
            if not members: raise RuntimeError('No VegDRI raster in ' + path.name + ': ' + ', '.join(x.name for x in t.getmembers()))
            m = members[0]; target = folder / Path(m.name).name
            with t.extractfile(m) as src, target.open('wb') as dst: shutil.copyfileobj(src, dst)
            return target
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if Path(n).name.lower().startswith('vegdri') and 'diff' not in n.lower() and n.lower().endswith(('.tif', '.tiff'))]
            if not names: raise RuntimeError('No VegDRI raster in ' + path.name)
            target = folder / Path(names[0]).name; target.write_bytes(z.read(names[0])); return target
    return path


def main():
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from usgs_m2m import M2M
    ap = argparse.ArgumentParser(); ap.add_argument('--recent', action='store_true'); ap.add_argument('--limit', type=int, default=10000)
    ap.add_argument('--workers', type=int, default=4); ap.add_argument('--batch', type=int, default=24); a = ap.parse_args()
    have = {r['entity'] for r in csv.DictReader(OUT.open(encoding='utf-8'))} if OUT.exists() else set()
    m = M2M(); done = 0; failed = []
    try:
        weeks = scenes(m)
        todo = [weeks[k] for k in sorted(weeks) if weeks[k]['entityId'] not in have][:a.limit]
        print('VegDRI weeks available: %d; new: %d' % (len(weeks), len(todo)), flush=True)
        for b in range(0, len(todo), a.batch):
            batch = todo[b:b + a.batch]
            urls = request_batch(m, batch, 'aots-vegdri-%s-%d' % (datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S'), b))
            with ThreadPoolExecutor(a.workers) as pool:
                jobs = {pool.submit(process, x, urls[x['entityId']]): x for x in batch if x['entityId'] in urls}
                failed += [x['entityId'] for x in batch if x['entityId'] not in urls]
                for fut in as_completed(jobs):
                    x = jobs[fut]
                    try: rows = fut.result()
                    except Exception as e: failed.append(x['entityId']); print('failed:', x['entityId'], str(e)[:120], flush=True); continue
                    write(rows); done += 1
                    ct = next((r for r in rows if r['unit'] == 'CT'), {})
                    print('%s week ending %s: CT mean %s, %s%% below -1' % (x['entityId'], rows[0]['week_end'], ct.get('mean'), ct.get('pct_below_minus1')), flush=True)
    finally:
        m.close()
    log('VegDRI: %d new weeks summarised for Connecticut%s.' % (done, '; %d failed (retried next run)' % len(failed) if failed else ''))
    print('done: %d new weeks, %d failed' % (done, len(failed)))
    return 1 if failed and not done else 0


def write(rows):
    """Append one week's rows, unless another run (e.g. the nightly job) already saved that week."""
    if OUT.exists() and rows and rows[0]['entity'] in {r['entity'] for r in csv.DictReader(OUT.open(encoding='utf-8'))}: return
    new = not OUT.exists()
    with OUT.open('a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new: w.writeheader()
        w.writerows(rows)


if __name__ == '__main__':
    raise SystemExit(main())
