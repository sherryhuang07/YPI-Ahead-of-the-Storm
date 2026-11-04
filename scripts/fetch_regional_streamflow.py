"""Public neighboring-state gauge inventory and history, separate from CT experiment."""
import argparse,hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from statewide_common import ROOT,read,save,request_json,log
from fetch_river_network import arc
D=ROOT/'data/regional-streamflow';D.mkdir(exist_ok=True)
BASE='https://api.waterdata.usgs.gov/ogcapi/v1/collections/'
STATES={'25':'Massachusetts','36':'New York','44':'Rhode Island','50':'Vermont','33':'New Hampshire'}
def fetch_pages(url,params):
    rows=[];visited=[]
    while url:
        if url in visited:raise ValueError('Pagination loop')
        v=request_json(url,params,timeout=90);rows.extend(v['features']);visited.append(url)
        url=next((x['href'] for x in v.get('links',[]) if x['rel']=='next'),None);params=None
    return dict(type='FeatureCollection',features=rows,source_pages=visited)
def discover():
    end=datetime.now(ZoneInfo('America/New_York')).date()-timedelta(days=1)
    for state,name in STATES.items():
        path=D/(state+'-metadata.json')
        if not path.exists():save(path,fetch_pages(BASE+'combined-metadata/items',dict(f='json',state_code=state,parameter_code='00060',statistic_id='00003',limit=10000)))
        log('Saved discharge-series inventory for '+name)
    # Gauge locations are a small national layer: select the eastern New York/New England corridor.
    from fetch_river_network import HR
    path=D/'gauge-references.geojson'
    if not path.exists():
        url=HR+'0/query';v=request_json(url,dict(f='geojson',where='1=1',geometry='-76,40,-69,46',geometryType='esriGeometryEnvelope',inSR=4326,outSR=4326,outFields='*',returnGeometry='true',resultRecordCount=2000))
        if v.get('exceededTransferLimit') or len(v.get('features',[]))>=2000:raise ValueError('Gauge references may be truncated')
        save(path,v)
    candidates=[]
    for state,name in STATES.items():
        for f in read(D/(state+'-metadata.json'))['features']:
            p=f['properties']
            if p.get('primary')!='Primary' or p.get('sublocation_identifier') or p.get('unit_of_measure')!='ft^3/s':continue
            if not p.get('end') or p['end'][:10]<str(end-timedelta(days=45)):continue
            candidates.append(dict(gauge_id=p['monitoring_location_id'],series_id=p['id'],name=p['monitoring_location_name'],coordinates=f['geometry']['coordinates'][:2],state=name,state_code=state,metadata_end=p['end'],drainage_area_sq_miles=p.get('drainage_area')))
    save(D/'candidates.json',candidates);log(f'{len(candidates)} recently listed neighboring-state discharge series found; network relevance still to be checked.')
def history():
    gauges=read(ROOT/'outputs/regional-streamflow/relevant-gauges.json');end=datetime.now(ZoneInfo('America/New_York')).date()-timedelta(days=1)
    def one(g):
        path=ROOT/'data/streamflow/history'/(g['gauge_id']+'.json')
        old=read(path) if path.exists() else None
        if old and old.get('requested_end','')>=str(end):return
        if old and (ROOT/'data/regional-prospective/model-v1.json').exists():raise ValueError('Historical model inputs are frozen; use regional_daily.py for new observations')
        start=str(datetime.fromisoformat(old['requested_end']).date()+timedelta(days=1)) if old else '2000-01-01'
        v=fetch_pages(BASE+'daily/items',dict(f='json',time_series_id=g['series_id'],parameter_code='00060',statistic_id='00003',datetime=f'{start}/{end}',limit=10000))
        if old:
            v['features']=old['features']+v['features'];v['prior_history_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();v['source_pages']=old['source_pages']+v['source_pages']
        v.update(series_id=g['series_id'],requested_start='2000-01-01',requested_end=str(end),retrieved_at=datetime.now(ZoneInfo('UTC')).isoformat())
        save(path,v);log(g['name']+': saved '+str(len(v['features']))+' daily observations.')
    failures=[]
    def attempt(g):
        try:one(g)
        except Exception as e:return dict(gauge_id=g['gauge_id'],error=str(e))
    with ThreadPoolExecutor(max_workers=2) as pool:failures=[x for x in pool.map(attempt,gauges) if x]
    save(D/'history-status.json',dict(failures=failures,complete=not failures))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['discover','history']);a=p.parse_args()
    discover() if a.mode=='discover' else history()
