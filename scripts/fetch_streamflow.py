"""Fixed, reproducible initial streamflow snapshot, including USGS seasonal statistics."""
import hashlib,time
from datetime import datetime,timezone
import requests
from statewide_common import ROOT,read,save

D=ROOT/'data/streamflow';D.mkdir(exist_ok=True)
BASE='https://api.waterdata.usgs.gov/ogcapi/v1/collections/'
QUERIES={
 'metadata':(BASE+'combined-metadata/items',dict(f='json',state_code='09',parameter_code='00060',limit=10000)),
 'latest-daily':(BASE+'latest-daily/items',dict(f='json',state_code='09',parameter_code='00060',statistic_id='00003',limit=10000)),
 'daily':(BASE+'daily/items',dict(f='json',bbox='-73.75,40.95,-71.78,42.06',parameter_code='00060',statistic_id='00003',datetime='2026-08-04/2026-11-01',limit=10000)),
 'percentiles':('https://api.waterdata.usgs.gov/statistics/v0/observationNormals',dict(state_code='US:09',parameter_code='00060',computation_type='percentile',start_date='08-04',end_date='11-01',page_size=10000))}

def log(message):
 print(message,flush=True)
 with (ROOT/'activity.log').open('a',encoding='utf-8') as f:f.write(datetime.now(timezone.utc).isoformat()+' | Streamflow: '+message+'\n')

def main():
 sources=[]
 for name,(url,params) in QUERIES.items():
  path=D/(name+'.json');request_url=requests.Request('GET',url,params=params).prepare().url
  if not path.exists():
   features=[];next_url=request_url;visited=[]
   while next_url:
    if next_url in visited:raise ValueError('Pagination loop')
    visited.append(next_url);response=requests.get(next_url,timeout=180);response.raise_for_status();v=response.json()
    if 'features' not in v:raise ValueError('Missing API features')
    features.extend(v['features']);next_url=next((l['href'] for l in v.get('links',[]) if l['rel']=='next'),None)
    if name=='percentiles' and v.get('next'):
     token=v['next']
     next_url=token if isinstance(token,str) and token.startswith('https://') else requests.Request('GET',url,params=dict(params,next_token=token)).prepare().url
    log(f'Downloaded {len(features):,} records for {name}.');time.sleep(1)
   save(path,dict(type='FeatureCollection',features=features,source_pages=visited))
  v=read(path)
  if v.get('next') or any(l['rel']=='next' for l in v.get('links',[])):raise ValueError('Incomplete cached response')
  sources.append(dict(name=name,url=request_url,features=len(v['features']),saved_at=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
 save(D/'manifest.json',dict(snapshot='2026-11-02',start='2026-08-04',end='2026-11-01',sources=sources,
  attribution='U.S. Geological Survey Water Data APIs and Statistics API, accessed November 2, 2026'))
 log('Streamflow observations and official historical percentiles are saved.')

if __name__=='__main__':main()
