"""Download a reproducible, dated PRISM snapshot; retain CT crops and metadata."""
import argparse, hashlib, math, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, datetime, timezone
import numpy as np
import rasterio
from rasterio.windows import from_bounds, Window
from shapely.geometry import shape
from pyproj import Transformer
from shapely.ops import transform, unary_union
from statewide_common import ROOT, read, save, SESSION

def log(message):
    print(message, flush=True)
    with (ROOT/'activity.log').open('a', encoding='utf-8') as f:
        f.write(datetime.now(timezone.utc).isoformat()+' | Precipitation: '+message+'\n')

def main():
    p=argparse.ArgumentParser(); p.add_argument('--end',default='2026-11-01'); p.add_argument('--days',type=int,default=90)
    p.add_argument('--snapshot',default='2026-11-02'); a=p.parse_args()
    end=date.fromisoformat(a.end); start=end-timedelta(days=a.days-1)
    folder=ROOT/'data/prism'/a.snapshot; folder.mkdir(parents=True,exist_ok=True)
    mask=read(ROOT/'data/statewide/connecticut-mask.geojson')
    geom=unary_union([shape(f['geometry']) for f in mask['features']])
    bounds=transform(Transformer.from_crs(4326,4269,always_xy=True).transform,geom).bounds
    release_url=f'https://services.nacse.org/prism/data/get/releaseDate/us/800m/ppt/{start:%Y%m%d}/{end:%Y%m%d}?json=true'
    if not (folder/'releases.json').exists():
        r=SESSION.get(release_url,timeout=120); r.raise_for_status(); save(folder/'releases.json',r.json())
    dates=[start+timedelta(days=i) for i in range(a.days)]
    available={r[0] for r in read(folder/'releases.json')}
    if not {str(d) for d in dates} <= available: raise ValueError('PRISM has not published every requested day')
    def fetch(item):
        i,d=item
        target=folder/f'{d}.tif'; meta=folder/f'{d}.json'
        if target.exists() and meta.exists(): return
        url=f'https://services.nacse.org/prism/data/get/us/800m/ppt/{d:%Y%m%d}'
        sample=ROOT/'data/prism'/f'{d:%Y%m%d}.zip'
        archive=sample if sample.exists() else folder/f'{d}.zip'
        if not archive.exists():
            r=SESSION.get(url,stream=True,timeout=(30,180)); r.raise_for_status()
            partial=archive.with_suffix('.part')
            with partial.open('wb') as f:
                for chunk in r.iter_content(1024*1024): f.write(chunk)
            partial.replace(archive)
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive) as z:
            name=next(n for n in z.namelist() if n.endswith('.tif'))
            xml=z.read(next(n for n in z.namelist() if n.endswith('.xml') and not n.endswith('.aux.xml'))).decode()
            if '<attrunit>Millimeters</attrunit>' not in xml: raise ValueError('Unrecognized precipitation units')
            info=z.read(next(n for n in z.namelist() if n.endswith('.info.txt'))).decode()
        with rasterio.open('/vsizip/'+archive.as_posix()+'/'+name) as src:
            if src.crs.to_epsg()!=4269 or src.scales!=(1.0,) or src.offsets!=(0.0,): raise ValueError('Unexpected source grid')
            if not math.isclose(src.transform.a,1/120,abs_tol=1e-10) or not math.isclose(src.transform.e,-1/120,abs_tol=1e-10): raise ValueError('Expected 30-arcsecond resolution')
            w=from_bounds(*bounds,transform=src.transform)
            c0=math.floor(w.col_off)-1; r0=math.floor(w.row_off)-1
            window=Window(c0,r0,math.ceil(w.col_off+w.width)+1-c0,math.ceil(w.row_off+w.height)+1-r0)
            data=src.read(1,window=window)
            if np.any((data<0)&(data!=src.nodata)): raise ValueError('Negative precipitation')
            profile=src.profile.copy(); profile.update(width=data.shape[1],height=data.shape[0],transform=src.window_transform(window))
            tmp=target.with_suffix('.tmp.tif')
            with rasterio.open(tmp,'w',**profile) as dst: dst.write(data,1); dst.update_tags(**src.tags(),units='mm')
            tmp.replace(target)
            save(meta,dict(date=str(d),url=url,retrieved_at=datetime.now(timezone.utc).isoformat(),archive_sha256=digest,
                crop_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),source_info=info,source_tags=src.tags(),units='mm',
                day_ends_utc=str(d)+'T12:00:00Z',status='Provisional; PRISM may revise recent six months'))
        if archive!=sample: archive.unlink()
        log(f'Loaded day {i+1} of {len(dates)}: {d}. Saved the Connecticut grid.')
        time.sleep(2)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(fetch,enumerate(dates)))
    save(folder/'manifest.json',dict(start=str(start),end=str(end),days=a.days,snapshot=a.snapshot,release_url=release_url,
        attribution='PRISM Group, Oregon State University, https://prism.oregonstate.edu, accessed '+a.snapshot,
        resolution='30 arcseconds (nominal 800 meters)',units='mm',dates=[str(d) for d in dates]))
    log('All requested daily precipitation grids are saved. Ready to calculate cumulative totals.')

if __name__=='__main__': main()
