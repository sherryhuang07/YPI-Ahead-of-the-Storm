"""Well observations and geographic coverage; deliberately no groundwater surface interpolation."""
from collections import defaultdict,Counter
from datetime import date
import csv,math
import numpy as np
from pyproj import Geod
from shapely import STRtree,make_valid
from shapely.geometry import shape,mapping
from statewide_common import ROOT,read,save
from fetch_groundwater import log

D=ROOT/'data/groundwater';O=ROOT/'outputs/groundwater';O.mkdir(exist_ok=True)
manifest=read(D/'manifest.json');asof=date.fromisoformat(manifest['snapshot']);start=manifest['window_start'];end=manifest['window_end']
sites={f['id']:f for f in read(D/'usgs-sites.json')['features']}
assert all(f['properties']['state_code']=='09' and f['properties']['site_type_code']=='GW' for f in sites.values())
towns=read(ROOT/'data/statewide/towns.geojson')['features'];tg=[make_valid(shape(f['geometry'])) for f in towns];tt=STRtree(tg)
basins=read(ROOT/'data/watersheds.geojson')['features'];bg=[make_valid(shape(f['geometry'])) for f in basins];bt=STRtree(bg)
def geography(g):
 return ([towns[i]['properties']['Municipality'] for i in tt.query(g,predicate='intersects')],sorted({str(basins[i]['properties']['SBAS_NO']) for i in bt.query(g,predicate='intersects')}))
observations=defaultdict(list);excluded=Counter()
for source in ['daily','recent-field','latest-daily']:
 for f in read(D/(source+'.json'))['features']:
  p=f['properties'];sid=p['monitoring_location_id']
  if sid not in sites:excluded['Outside CT site inventory']+=1;continue
  if p['parameter_code']!='72019':excluded['Other reference level retained in raw source only']+=1;continue
  if source!='recent-field' and p.get('statistic_id')!='00003':excluded['Non-mean daily statistic']+=1;continue
  if source=='recent-field' and (p.get('reading_type')!='ReferencePrimary' or p.get('qualifier')!=['Static']):excluded['Non-static or non-primary field reading']+=1;continue
  if source!='recent-field' and p.get('qualifier'):excluded['Qualified daily value needs review']+=1;continue
  day=p['time'][:10]
  if day>end:excluded['After snapshot observation cutoff']+=1;continue
  if source!='latest-daily' and day<start:excluded['Before history window']+=1;continue
  try:value=float(p['value'])
  except (TypeError,ValueError):excluded['Missing numeric value']+=1;continue
  if not math.isfinite(value) or p['unit_of_measure']!='ft':excluded['Non-finite or unexpected units']+=1;continue
  observations[sid].append(dict(id=f['id'],date=day,time=p['time'],depth_below_land_ft=value,approval_status=p.get('approval_status'),qualifier=p.get('qualifier'),
   type='Manual field reading' if source=='recent-field' else 'Daily mean',series_id=p.get('time_series_id') or p.get('field_measurements_series_id'),source=source))
records=[];geo=[]
for sid,fs in sites.items():
 p=fs['properties'];g=shape(fs['geometry']);tn,ws=geography(g)
 # A latest-daily item may duplicate an observation already retrieved in daily history.
 unique={}
 for r in observations[sid]:unique[(r['series_id'],r['time'],r['type'])]=r
 obs=sorted(unique.values(),key=lambda r:(r['date'],r['type']=='Daily mean',r['id']))
 recent=[r for r in obs if start<=r['date']<=end];latest=obs[-1] if obs else None
 age=(asof-date.fromisoformat(latest['date'])).days if latest else None
 record=dict(id=sid,name=p['monitoring_location_name'],coordinates=fs['geometry']['coordinates'],towns=tn,watershed_ids=ws,
  county_or_planning_region=p.get('county_name'),aquifer_code=p.get('aquifer_code'),national_aquifer_code=p.get('national_aquifer_code'),aquifer_type_code=p.get('aquifer_type_code'),
  well_depth_ft=p.get('well_constructed_depth'),latest=latest,age_days=age,recent_observation_count=len(recent),daily_days=len({r['date'] for r in recent if r['type']=='Daily mean'}),
  manual_visits=len({r['date'] for r in recent if r['type']=='Manual field reading'}),history=recent,
  status='Reading within past 30 days' if age is not None and age<=30 else 'Reading 31–90 days old' if age is not None and age<=90 else 'Older daily reading only' if latest else 'No usable level found in queried window',
  url='https://waterdata.usgs.gov/monitoring-location/'+sid+'/')
 records.append(record)
 if latest:geo.append(dict(type='Feature',geometry=fs['geometry'],properties={k:v for k,v in record.items() if k not in ['coordinates','history']}))
recent=[r for r in records if r['recent_observation_count']>0];geod=Geod(ellps='WGS84')
lons=np.array([r['coordinates'][0] for r in recent]);lats=np.array([r['coordinates'][1] for r in recent])
def nearest(g,watersheds):
 point=g.representative_point();_,_,meters=geod.inv(np.full(len(recent),point.x),np.full(len(recent),point.y),lons,lats)
 return [dict(well_id=recent[i]['id'],name=recent[i]['name'],distance_km=float(meters[i]/1000),age_days=recent[i]['age_days'],same_surface_watershed=bool(set(watersheds)&set(recent[i]['watershed_ids'])),
  aquifer_match='Not established',farm_measurement=False) for i in np.argsort(meters)[:3]]
farm_links=[]
for f in read(ROOT/'outputs/statewide/field-candidates.geojson')['features']:
 p=f['properties'];farm_links.append(dict(candidate_id=p['candidate_id'],town=p['town'],nearby_wells=nearest(shape(f['geometry']),p['watershed_ids'])))
yale=read(ROOT/'data/yale-farm/farm-outline.geojson')['features'][0];yg=shape(yale['geometry']);_,yw=geography(yg)
pilot=nearest(yg,yw)
coverage=[]
for f in towns:
 town=f['properties']['Municipality'];all_here=[r for r in records if town in r['towns']];recent_here=[r for r in recent if town in r['towns']]
 coverage.append(dict(town=town,listed_wells=len(all_here),wells_with_recent_readings=len(recent_here),wells_with_readings_within_30_days=sum(r['age_days']<=30 for r in recent_here),
  recent_well_ids=[r['id'] for r in recent_here]))
summary=dict(snapshot=str(asof),window_start=start,window_end=end,source='USGS Water Data APIs; not a complete NGWMN inventory',listed_wells=len(records),
 wells_with_recent_readings=len(recent),wells_with_readings_within_30_days=sum(r['age_days']<=30 for r in recent),wells_with_daily_history=sum(r['daily_days']>0 for r in recent),
 wells_with_manual_history=sum(r['manual_visits']>0 for r in recent),towns_with_recent_well=sum(r['wells_with_recent_readings']>0 for r in coverage),
 towns_without_recent_well=sum(r['wells_with_recent_readings']==0 for r in coverage),yale_nearby_wells=pilot,exclusions=dict(excluded),
 caveat='Nearby wells provide context only. Groundwater aquifers need not follow surface watershed boundaries. No farm groundwater level, drought rating, well yield or irrigation recommendation is inferred.',
 attribution=manifest['attribution'],ngwmn=manifest['ngwmn'])
save(O/'summary.json',summary);save(O/'wells.json',records);save(O/'well-observations.geojson',dict(type='FeatureCollection',features=geo));save(O/'town-coverage.json',coverage);save(O/'farm-well-links.json',farm_links)
with (O/'observations.csv').open('w',newline='',encoding='utf-8') as f:
 writer=csv.writer(f);writer.writerow(['well_id','date','type','depth_below_land_ft','approval_status','series_id'])
 for r in recent:
  for obs in r['history']:writer.writerow([r['id'],obs['date'],obs['type'],obs['depth_below_land_ft'],obs['approval_status'],obs['series_id']])
log(f'Groundwater ready: {len(recent)} wells with readings in the 90-day window; {summary["towns_without_recent_well"]} towns have none in the imported sources.')
print(summary)
