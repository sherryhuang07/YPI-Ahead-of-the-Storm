"""Streamflow summaries without filling missing days or inferring farm water access."""
import csv,math
from collections import defaultdict,Counter
from datetime import date,timedelta
import numpy as np
from pyproj import Geod
from shapely import STRtree,make_valid
from shapely.geometry import shape
from statewide_common import ROOT,read,save
from fetch_streamflow import log

def rolling(observations,end,days):
 dates=[str(end-timedelta(days=i)) for i in range(days)];values=[observations[d]['flow_cfs'] for d in dates if d in observations]
 return dict(days=days,available_days=len(values),mean_cfs=sum(values)/days if len(values)==days else None,
  qualified_days=sum(bool(observations[d]['qualifier']) for d in dates if d in observations))

def percentile_band(flow,thresholds):
 if flow<0:return 'Signed reverse flow; percentile interpretation withheld'
 equal=[p for p,v in thresholds.items() if flow==v]
 if equal:return 'At historical threshold(s): '+', '.join(str(p)+'th' for p in equal)+'; ties possible'
 lower=[p for p,v in thresholds.items() if v<flow];upper=[p for p,v in thresholds.items() if v>flow]
 if not lower:return 'Below the 5th percentile'
 if not upper:return 'Above the 95th percentile'
 return f'{max(lower)}th–{min(upper)}th percentile band'

def main():
 D=ROOT/'data/streamflow';O=ROOT/'outputs/streamflow';O.mkdir(exist_ok=True);manifest=read(D/'manifest.json');end=date.fromisoformat(manifest['end'])
 metadata=read(D/'metadata.json')['features'];series={f['id']:f for f in metadata if f['properties']['data_type']=='Daily values' and f['properties']['statistic_id']=='00003' and f['properties']['primary']=='Primary' and f['properties']['state_code']=='09'}
 assert len(series)==len([f for f in metadata if f['properties']['data_type']=='Daily values' and f['properties']['statistic_id']=='00003' and f['properties']['primary']=='Primary' and f['properties']['state_code']=='09'])
 observations=defaultdict(dict);excluded=Counter()
 for source in ['latest-daily','daily']:
  for f in read(D/(source+'.json'))['features']:
   p=f['properties'];sid=p['time_series_id'];day=p['time'][:10]
   if sid not in series:excluded['Not a CT primary daily-mean series']+=1;continue
   if day>manifest['end']:excluded['After observation cutoff']+=1;continue
   if p['parameter_code']!='00060' or p['statistic_id']!='00003' or p['unit_of_measure']!='ft^3/s':raise ValueError('Unexpected measurement')
   try:flow=float(p['value'])
   except (ValueError,TypeError):excluded['Missing/non-numeric reading']+=1;continue
   if not math.isfinite(flow):excluded['Non-finite reading']+=1;continue
   item=dict(date=day,flow_cfs=flow,approval_status=p['approval_status'],qualifier=p.get('qualifier'))
   if day in observations[sid] and observations[sid][day]!=item:raise ValueError('Conflicting daily observations')
   observations[sid][day]=item
 stats={}
 for f in read(D/'percentiles.json')['features']:
  for group in f['properties']['data']:
   if group['parameter_code']!='00060' or group['parent_statistic_id']!='00003' or group['unit_of_measure']!='ft^3/s':continue
   for entry in group['values']:
    if entry['time_of_year_type']!='day_of_year' or entry['computation']!='percentile':continue
    key=(group['parent_time_series_id'],entry['time_of_year'])
    if key in stats:raise ValueError('Duplicate seasonal statistics')
    try:thresholds={int(float(p)):float(v) for p,v in zip(entry['percentiles'],entry['values'],strict=True)}
    except (ValueError,TypeError):continue
    if set(thresholds)!={5,10,25,50,75,90,95} or not all(math.isfinite(v) for v in thresholds.values()):continue
    if [thresholds[p] for p in sorted(thresholds)]!=sorted(thresholds.values()):raise ValueError('Non-monotonic percentile thresholds')
    stats[key]=dict(thresholds_cfs=thresholds,sample_count=entry['sample_count'],approval_status=entry['approval_status'],month_day=entry['time_of_year'])
 towns=read(ROOT/'data/statewide/towns.geojson')['features'];tg=[make_valid(shape(f['geometry'])) for f in towns];tt=STRtree(tg)
 basins=read(ROOT/'data/watersheds.geojson')['features'];bg=[make_valid(shape(f['geometry'])) for f in basins];bt=STRtree(bg)
 records=[]
 for sid,f in series.items():
  p=f['properties'];g=shape(f['geometry']);allobs=observations[sid];history=[v for d,v in sorted(allobs.items()) if manifest['start']<=d<=manifest['end']];latest=allobs[max(allobs)] if allobs else None
  context=None
  if latest:
   context=stats.get((sid,latest['date'][5:])) if latest['date']>=manifest['start'] else None
   if context:
    context=dict(context);context['band']=percentile_band(latest['flow_cfs'],context['thresholds_cfs']) if context['sample_count']>=10 and not latest['qualifier'] else 'Interpretation withheld: short baseline or qualified observation'
  record=dict(series_id=sid,gauge_id=p['monitoring_location_id'],name=p['monitoring_location_name'],coordinates=f['geometry']['coordinates'],
   towns=[towns[i]['properties']['Municipality'] for i in tt.query(g,predicate='intersects')],watershed_ids=sorted({str(basins[i]['properties']['SBAS_NO']) for i in bt.query(g,predicate='intersects')}),
   huc=p['hydrologic_unit_code'],drainage_area_sq_miles=p['drainage_area'],latest=latest,history=history,days_observed=len(history),
   age_days=(date.fromisoformat(manifest['snapshot'])-date.fromisoformat(latest['date'])).days if latest else None,
   averages={str(n):rolling(allobs,end,n) for n in (7,14,30,90)},seasonal_context=context,
   series_begin=p['begin'],series_end=p['end'],sublocation=p.get('sublocation_identifier'),
   url='https://waterdata.usgs.gov/monitoring-location/'+p['monitoring_location_id']+'/',connectivity='Upstream/downstream connection to a farm not established')
  records.append(record)
 recent=[r for r in records if r['history']];by_gauge=defaultdict(list)
 for r in recent:by_gauge[r['gauge_id']].append(r)
 candidates=[v[0] for v in by_gauge.values() if len(v)==1]
 for group in by_gauge.values():
  for r in group:r['multiple_recent_series_at_gauge']=len(group)>1
 geod=Geod(ellps='WGS84');lons=np.array([r['coordinates'][0] for r in candidates]);lats=np.array([r['coordinates'][1] for r in candidates])
 def nearby(g,watersheds):
  point=g.representative_point();_,_,meters=geod.inv(np.full(len(candidates),point.x),np.full(len(candidates),point.y),lons,lats)
  return [dict(gauge_id=candidates[i]['gauge_id'],series_id=candidates[i]['series_id'],name=candidates[i]['name'],distance_km=float(meters[i]/1000),same_surface_watershed=bool(set(watersheds)&set(candidates[i]['watershed_ids'])),upstream_downstream='Not established',farm_water_access='Not established') for i in np.argsort(meters)[:3]]
 farm_links=[]
 for f in read(ROOT/'outputs/statewide/field-candidates.geojson')['features']:
  p=f['properties'];farm_links.append(dict(candidate_id=p['candidate_id'],town=p['town'],nearby_gauges=nearby(shape(f['geometry']),p['watershed_ids'])))
 yale=shape(read(ROOT/'data/yale-farm/farm-outline.geojson')['features'][0]['geometry']);yw={str(basins[i]['properties']['SBAS_NO']) for i in bt.query(yale,predicate='intersects')}
 coverage=[dict(town=f['properties']['Municipality'],recent_gauges=len({r['gauge_id'] for r in recent if f['properties']['Municipality'] in r['towns']})) for f in towns]
 summary=dict(**manifest,daily_mean_series=len(records),gauges_with_daily_series=len({r['gauge_id'] for r in records}),recent_gauges=len(by_gauge),recent_series=len(recent),
  gauges_reporting_on_end_date=len({r['gauge_id'] for r in recent if r['latest']['date']==manifest['end']}),
  recent_series_with_percentile_context=sum(r['seasonal_context'] is not None for r in recent),
  towns_with_recent_gauge=sum(r['recent_gauges']>0 for r in coverage),yale_nearby_gauges=nearby(yale,yw),
  excluded=dict(excluded),ambiguous_gauges_excluded_from_nearby_links=[k for k,v in by_gauge.items() if len(v)>1],
  interpretation='Gauge-level context only. No river routing, available irrigation supply, or farm drought rating is inferred. Snapshot is not refreshed automatically.')
 save(O/'summary.json',summary);save(O/'gauges.json',records);save(O/'farm-gauge-links.json',farm_links);save(O/'town-coverage.json',coverage)
 save(O/'gauge-observations.geojson',dict(type='FeatureCollection',features=[dict(type='Feature',geometry=dict(type='Point',coordinates=r['coordinates']),properties={k:v for k,v in r.items() if k not in ['coordinates','history']}) for r in recent]))
 with (O/'daily-discharge.csv').open('w',newline='',encoding='utf-8') as f:
  writer=csv.writer(f);writer.writerow(['gauge_id','series_id','date','daily_mean_cfs','approval_status','qualifier'])
  for r in recent:
   for v in r['history']:writer.writerow([r['gauge_id'],r['series_id'],v['date'],v['flow_cfs'],v['approval_status'],str(v['qualifier'])])
 log(f'Streamflow ready: {summary["recent_gauges"]} gauges with recent daily readings; {summary["recent_series_with_percentile_context"]} series with official seasonal percentile thresholds.')
 print({k:v for k,v in summary.items() if k!='sources'})

if __name__=='__main__':main()
