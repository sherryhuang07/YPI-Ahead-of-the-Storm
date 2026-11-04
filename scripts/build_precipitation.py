"""Strict cumulative depths and equal-area polygon/grid overlap summaries."""
import argparse, csv, math
from collections import defaultdict
from datetime import date, timedelta
import numpy as np
import rasterio
from shapely import box, STRtree, transform as shp_transform, make_valid
from shapely.geometry import shape
from shapely.ops import unary_union
from pyproj import Transformer
from statewide_common import ROOT, read, save
from fetch_prism import log

WINDOWS=(7,14,30,60,90)
def project(g,source=4326):
    return shp_transform(g,Transformer.from_crs(source,5070,always_xy=True).transform,interleaved=False)

def cumulative(stack,days):
    recent=stack[-days:]
    if len(recent)!=days: raise ValueError('Insufficient days')
    return np.where(np.isfinite(recent).all(axis=0),np.sum(recent,axis=0,dtype=np.float64),np.nan)

def weighted(values,weights):
    valid=np.isfinite(values)
    coverage=float(weights[valid].sum())
    return (float(np.dot(values,weights)) if valid.all() and abs(weights.sum()-1)<1e-6 else None),coverage

def main():
    p=argparse.ArgumentParser(); p.add_argument('--snapshot',default='2026-11-02'); a=p.parse_args()
    folder=ROOT/'data/prism'/a.snapshot; out=ROOT/'outputs/precipitation'; out.mkdir(exist_ok=True)
    manifest=read(folder/'manifest.json'); dates=manifest['dates']
    expected=[str(date.fromisoformat(manifest['start'])+timedelta(days=i)) for i in range(manifest['days'])]
    if dates!=expected or dates[-1]!=manifest['end']: raise ValueError('Dates are not consecutive')
    stack=[]; profile=None
    for day in dates:
        with rasterio.open(folder/f'{day}.tif') as src:
            if profile and (src.transform!=profile['transform'] or src.shape!=(profile['height'],profile['width']) or src.crs!=profile['crs']): raise ValueError('Daily grids do not align')
            profile=src.profile.copy(); stack.append(src.read(1,masked=True).filled(np.nan))
    stack=np.stack(stack); totals={n:cumulative(stack,n) for n in WINDOWS}
    for n,grid in totals.items():
        target=out/f'cumulative-{n}-days.tif'; pr=profile.copy();pr.update(dtype='float64',nodata=-9999)
        with rasterio.open(target,'w',**pr) as dst:
            dst.write(np.where(np.isfinite(grid),grid,-9999),1)
            dst.update_tags(units='mm',end=manifest['end'],days=n,source=manifest['attribution'],status='Provisional')
    h,w=stack.shape[1:]; affine=profile['transform']
    rows,cols=np.indices((h,w)); x=affine.c+cols.ravel()*affine.a; y=affine.f+rows.ravel()*affine.e
    cells=project(box(x,y+affine.e,x+affine.a,y),4269); tree=STRtree(cells)
    mask=unary_union([shape(f['geometry']) for f in read(ROOT/'data/statewide/connecticut-mask.geojson')['features']])
    records=[]; links=[]
    def summarize(identifier,name,kind,g,extra=None):
        g=project(make_valid(g)); indices=tree.query(g,predicate='intersects')
        if g.geom_type=='Point':
            indices=indices[:1]; weights=np.ones(len(indices)); method='Grid containing mapped point; no farm area known'
        else:
            areas=np.array([g.intersection(cells[i]).area for i in indices]); keep=areas>0
            indices=indices[keep]; weights=areas[keep]/g.area; method='Area-weighted grid overlap in equal-area projection'
        result=dict(id=identifier,name=name,kind=kind,method=method,grid_cells=len(indices),totals={},**(extra or {}))
        if not len(indices) or abs(weights.sum()-1)>1e-6: raise ValueError('Grid does not cover '+identifier)
        for n,grid in totals.items():
            mm,coverage=weighted(grid.ravel()[indices],weights)
            result['totals'][str(n)]=dict(mm=mm,inches=None if mm is None else mm/25.4,coverage_fraction=coverage,
                status='Complete provisional estimate' if mm is not None else 'Missing data; total withheld')
        for i,weight in zip(indices,weights): links.append((identifier,int(i//w),int(i%w),float(weight)))
        records.append(result); return result
    fields=read(ROOT/'outputs/statewide/field-candidates.geojson')['features']
    for i,f in enumerate(fields):
        props=f['properties']; addresses=props.get('parcel_addresses') or []
        label=props.get('name') or ((str(addresses[0])+' | '+props['candidate_id']) if addresses else props['candidate_id'])
        summarize(props['candidate_id'],label,'farm_candidate',shape(f['geometry']),dict(town=props['town'],boundary_status='Unconfirmed',parcel_addresses=addresses,watershed_ids=props.get('watershed_ids',[])))
        if (i+1)%2000==0: log(f'Calculated precipitation for {i+1:,} mapped farm candidates.')
    groups=defaultdict(list); names={}
    for f in read(ROOT/'data/watersheds.geojson')['features']:
        key=str(f['properties']['SBAS_NO']);groups[key].append(make_valid(shape(f['geometry']))); names[key]=f['properties']['SUBREGION']
    for key,geoms in groups.items():
        g=unary_union(geoms).intersection(mask)
        if not g.is_empty and g.area>0: summarize('watershed-'+key,names[key],'watershed',g,dict(watershed_id=key,scope='Connecticut portion only'))
    yale=read(ROOT/'data/yale-farm/farm-outline.geojson')['features'][0]
    pilot=summarize('yale-farm-new-haven','Yale Farm','pilot',shape(yale['geometry']),dict(boundary_status='Provisional',town='New Haven'))
    summary=dict(**manifest,windows=list(WINDOWS),candidate_count=len(fields),watershed_count=sum(r['kind']=='watershed' for r in records),
        missing_candidate_counts={str(n):sum(r['kind']=='farm_candidate' and r['totals'][str(n)]['mm'] is None for r in records) for n in WINDOWS},
        yale=pilot,day_definition='24 hours ending at 12:00 UTC on the labeled date',
        interpretation='Past rain and melted-snow equivalent. Not a forecast, drought rating, soil moisture measurement, or irrigation recommendation.',
        status='Provisional snapshot; no automatic refresh',grid_shape=[h,w])
    save(out/'summary.json',summary);save(out/'records.json',records)
    save(out/'watersheds.json',[r for r in records if r['kind']=='watershed'])
    towns=defaultdict(list)
    for r in records:
        if r['kind']=='farm_candidate':towns[r['town']].append(r)
    save(out/'town-index.json',sorted(towns))
    for town,items in towns.items(): save(out/'towns'/(town+'.json'),items)
    with (out/'grid-overlaps.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['id','crop_row','crop_column','area_fraction']);writer.writerows(links)
    with (out/'cumulative-precipitation.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f);writer.writerow(['id','name','kind','days','end_date','mm','inches','coverage_fraction','status'])
        for r in records:
            for n,t in r['totals'].items():writer.writerow([r['id'],r['name'],r['kind'],n,manifest['end'],t['mm'],t['inches'],t['coverage_fraction'],t['status']])
    log(f'Precipitation ready: {len(fields):,} farm candidates, {summary["watershed_count"]} Connecticut watershed portions, and Yale Farm.')
    print(pilot,flush=True)

if __name__=='__main__':main()
