"""Resumable public hydrography and observed discharge download. No credentials."""
import argparse, hashlib
from concurrent.futures import ThreadPoolExecutor
from statewide_common import ROOT, read, save, request_json, download, log

D=ROOT/'data/hydrography'
HR='https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/'
HP='https://3dhp.nationalmap.gov/arcgis/rest/services/usgs_3dhp_all/FeatureServer/'

def arc(name,url):
    dest=D/(name+'.geojson')
    if dest.exists(): return
    meta=request_json(url,dict(f='json'));save(D/(name+'-schema.json'),meta)
    query=dict(f='json',where='1=1',geometry='-73.8,40.9,-71.7,42.1',geometryType='esriGeometryEnvelope',inSR=4326,spatialRel='esriSpatialRelIntersects',returnIdsOnly='true')
    inventory=D/(name+'-ids.json')
    if not inventory.exists():
        log('Requesting the full feature inventory for '+name)
        save(inventory,request_json(url+'/query',query,post=True,timeout=60))
    result=read(inventory)
    if result.get('exceededTransferLimit'): raise ValueError('Truncated ID inventory')
    ids=sorted(result.get('objectIds') or []);features=[]
    def batch(i):
        part=D/'parts'/name/(str(i)+'.json')
        if not part.exists():
            v=request_json(url+'/query',dict(f='geojson',objectIds=','.join(map(str,ids[i:i+200])),outFields='*',outSR=4326,returnGeometry='true'))
            if len(v.get('features',[]))!=len(ids[i:i+200]):raise ValueError('Incomplete feature batch '+name)
            save(part,v)
        records=read(part)['features']
        if len(records)!=len(ids[i:i+200]):raise ValueError('Cached batch size mismatch')
        return i,records
    with ThreadPoolExecutor(max_workers=4) as pool:
        for start in range(0,len(ids),800):
            for i,records in pool.map(batch,range(start,min(start+800,len(ids)),200)):
                features.extend(records)
                if i%10000==0:log(f'{name}: saved {len(features):,} of {len(ids):,} map features.')
    save(dest,dict(type='FeatureCollection',features=features,source=url,selection=query))
    save(dest.with_suffix('.source.json'),dict(url=url,count=len(features),sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))

def history(g):
    path=ROOT/'data/streamflow/history'/ (g['gauge_id']+'.json')
    if path.exists():return
    url='https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items'
    params=dict(f='json',time_series_id=g['series_id'],parameter_code='00060',statistic_id='00003',datetime='2000-01-01/2026-11-02',limit=10000)
    records=[];pages=[]
    while url:
        v=request_json(url,params);records.extend(v['features']);pages.append(url)
        url=next((x['href'] for x in v.get('links',[]) if x['rel']=='next'),None);params=None
        if url in pages:raise ValueError('Pagination loop')
    save(path,dict(type='FeatureCollection',features=records,request=params,series_id=g['series_id'],source_pages=pages,requested_start='2000-01-01',requested_end='2026-11-02'))
    log(f"{g['name']}: saved {len(records):,} historical daily observations.")

def basin(g):
    base='https://api.water.usgs.gov/nldi/linked-data/nwissite/'+g['gauge_id']
    for suffix,endpoint in [('site',''),('basin','/basin?f=json&simplified=false')]:
        path=D/'nldi'/(g['gauge_id']+'-'+suffix+'.geojson')
        if not path.exists():save(path,request_json(base+endpoint))
    log('Saved upstream drainage area for '+g['name'])

def streamstats(g):
    path=D/'streamstats'/(g['gauge_id']+'.json')
    if not path.exists():
        lon,lat=g['coordinates']
        save(path,request_json('https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/CT',dict(lat=lat,lon=lon)))
    log('Saved StreamStats delineation for '+g['name'])

def splitbasin(g):
    path=D/'nldi-split'/(g['gauge_id']+'-basin.geojson')
    if not path.exists():save(path,request_json('https://api.water.usgs.gov/nldi/linked-data/nwissite/'+g['gauge_id']+'/basin',dict(f='json',simplified='false',splitCatchment='true')))
    log('Saved gauge-position drainage boundary for '+g['name'])

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['maps','modern','support','archive','history','basins','streamstats','splitbasins']);mode=parser.parse_args().mode
    gauges=[g for g in read(ROOT/'outputs/streamflow/gauges.json') if g.get('age_days') is not None and g['age_days']<=7]
    failures=[]
    if mode in ['maps','modern','support','archive']:
        jobs=[('hr-flowlines',HR+'3'),('hr-catchments',HR+'10'),('hr-waterbodies',HR+'9'),('hr-gauges',HR+'0'),('public-dams','https://services1.arcgis.com/FjPcSmEFuDYlIdKC/arcgis/rest/services/Dams_Public/FeatureServer/0')]+[('3dhp-'+n,HP+str(i)) for n,i in [('flowlines',50),('waterbodies',60),('catchments',80),('outlets',20),('workunits',90)]]
        if mode=='support':jobs=[j for j in jobs if j[0] in ['hr-waterbodies','hr-gauges','public-dams']]
        if mode=='archive':jobs=[]
        if mode=='modern':jobs=[j for j in jobs if not j[0].startswith('hr-')]
        for name,url in jobs:
            try:arc(name,url)
            except Exception as e:failures.append(dict(dataset=name,error=str(e)));log(name+' could not finish: '+str(e))
        for f in read(D/'ctssue-metadata.json').get('files',[]):
            if f['name'].endswith(('.txt','.accdb')):
                try:download(f['url'],D/f['name'])
                except Exception as e:failures.append(dict(dataset=f['name'],error=str(e)))
    else:
        fn={'history':history,'basins':basin,'streamstats':streamstats,'splitbasins':splitbasin}[mode]
        def attempt(g):
            try:fn(g)
            except Exception as e:return dict(dataset=g['gauge_id'],error=str(e))
        with ThreadPoolExecutor(max_workers=2) as pool:
            failures=[x for x in pool.map(attempt,gauges) if x]
    save(D/(mode+'-download-status.json'),dict(failures=failures,complete=not failures))
    log(mode+' download finished; '+str(len(failures))+' unresolved downloads.')

if __name__=='__main__':main()
