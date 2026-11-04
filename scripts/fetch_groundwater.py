"""Cached, paginated USGS groundwater snapshot. No credentials required at low volume."""
import argparse,hashlib,time
from datetime import datetime,timezone
import requests
from statewide_common import ROOT,read,save

BASE='https://api.waterdata.usgs.gov/ogcapi/v1/collections/'
QUERIES={
 'usgs-sites':('monitoring-locations',dict(state_code='09',site_type_code='GW')),
 'latest-daily':('latest-daily',dict(state_code='09',site_type_code='GW')),
 'recent-field':('field-measurements',dict(state_code='09',site_type_code='GW',datetime='2026-08-04T00:00:00Z/2026-11-02T23:59:59Z')),
 'daily':('daily',dict(bbox='-73.75,40.95,-71.78,42.06',parameter_code='72019',datetime='2026-08-04/2026-11-02')),
 'parameter-codes':('parameter-codes',dict(filter="id IN ('72019','62610','62611')"))}

def log(message):
 print(message,flush=True)
 with (ROOT/'activity.log').open('a',encoding='utf-8') as f:f.write(datetime.now(timezone.utc).isoformat()+' | Groundwater: '+message+'\n')

def main():
 p=argparse.ArgumentParser();p.add_argument('--refresh',action='store_true');a=p.parse_args()
 folder=ROOT/'data/groundwater';folder.mkdir(exist_ok=True)
 sources=[]
 for name,(collection,params) in QUERIES.items():
  path=folder/(name+'.json');url=requests.Request('GET',BASE+collection+'/items',params=dict(f='json',limit=10000,**params)).prepare().url
  if a.refresh or not path.exists():
   features=[];visited=set();next_url=url
   while next_url:
    if next_url in visited:raise ValueError('Pagination loop')
    visited.add(next_url);r=requests.get(next_url,timeout=120);r.raise_for_status();page=r.json()
    if 'features' not in page:raise ValueError('Missing features')
    features.extend(page['features']);next_url=next((l['href'] for l in page.get('links',[]) if l['rel']=='next'),None);time.sleep(1)
   save(path,dict(type='FeatureCollection',features=features,source_pages=list(visited)))
  value=read(path)
  if any(l['rel']=='next' for l in value.get('links',[])):raise ValueError('Incomplete cached page: '+name)
  ids=[f['id'] for f in value['features']]
  if len(ids)!=len(set(ids)):raise ValueError('Duplicate records')
  sources.append(dict(name=name,url=url,records=len(ids),saved_at=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
  log(f'Available: {len(ids):,} records in {name}.')
 save(folder/'manifest.json',dict(snapshot='2026-11-02',window_start='2026-08-04',window_end='2026-11-01',sources=sources,
  ngwmn=dict(status='Documented SOS endpoint returned HTTP 404; membership and non-USGS providers not imported',url='https://cida.usgs.gov/ngwmn_cache/sos',documentation='https://www.usgs.gov/apps/ngwmn/web-services.jsp'),
  attribution='U.S. Geological Survey, Water Data APIs, accessed November 2, 2026'))

if __name__=='__main__':main()
