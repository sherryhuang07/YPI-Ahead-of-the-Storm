"""Download NOAA NBM QPF grids clipped to Connecticut and area-weight farms."""
import csv, hashlib, json, re, sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests, numpy as np, rasterio
from rasterio.warp import transform
from shapely.geometry import shape
from statewide_common import ROOT, read, save

BASE='https://nomads.ncep.noaa.gov'; OUT=ROOT/'data/noaa-nbm'; USER={'User-Agent':'Connecticut agricultural water forecast research'}

def get(url,params=None):
 r=requests.get(url,params=params,headers=USER,timeout=90);r.raise_for_status();return r

def locate(min_last_hour=240, not_after=None):
 # Newest cycle whose upload has reached hour 240 (NOAA posts a cycle's hours over about an hour; taking a cycle
 # as soon as f001 appears gave the fire danger and drought jobs only a few hours of forecast).
 # If no cycle in the last two days reaches it, fall back to the newest cycle that has f001.
 # not_after: ignore cycles issued after this UTC time (fire danger needs a cycle that still covers 1 PM today).
 now=datetime.now(timezone.utc);days=[now.strftime('%Y%m%d'),(now-timedelta(days=1)).strftime('%Y%m%d')];fallback=None
 for day in days:
  html=get(BASE+'/pub/data/nccf/com/blend/prod/blend.'+day+'/').text
  cycles=re.findall(r'href="(\d{2})/"',html)
  for cycle in sorted(cycles,key=int,reverse=True):
   if not_after is not None and datetime.strptime(day+cycle,'%Y%m%d%H').replace(tzinfo=timezone.utc)>not_after:continue
   url=f'{BASE}/pub/data/nccf/com/blend/prod/blend.{day}/{cycle}/core/'
   try:text=get(url).text
   except requests.RequestException:continue
   files=re.findall(r'href="(blend\.t\d{2}z\.core\.f\d{3}\.co\.grib2)"',text)
   if 'blend.t'+cycle+'z.core.f001.co.grib2' in files:
    if max(int(re.search(r'f(\d{3})',x).group(1)) for x in files)>=min_last_hour:
     return day,cycle,files,url
    fallback=fallback or (day,cycle,files,url)
 if fallback:return fallback
 raise RuntimeError('No current NBM CONUS forecast cycle found')

def main():
 day,cycle,files,folder=locate();hours=sorted({int(re.search(r'f(\d{3})',f).group(1)) for f in files if 1<=int(re.search(r'f(\d{3})',f).group(1))<=264})
 # NBM hourly QPF is available to hour 264; retain every published interval.
 target=OUT/f'{day}{cycle}z';target.mkdir(parents=True,exist_ok=True)
 farms=read(ROOT/'data/statewide/field-candidates.geojson')['features']
 points=[]
 for f in farms:
  g=shape(f['geometry']);p=g.representative_point();points.append((f['properties'].get('candidate_id') or f['properties'].get('id'),p.x,p.y))
 points.append(('yale-farm-new-haven',-72.93,41.31))
 # Fetch only the Connecticut geographic window; the GRIB is small and contains native grid coordinates.
 def one(h):
  name=f'blend.t{cycle}z.core.f{h:03d}.co.grib2';path=target/name
  if not path.exists():
   r=get(BASE+'/cgi-bin/filter_blend.pl',dict(file=name,dir=f'/blend.{day}/{cycle}/core',var_APCP='on',lev_surface='on',subregion='',leftlon=-74,rightlon=-71,toplat=42.2,bottomlat=40.9))
   if not r.content.startswith(b'GRIB'):raise RuntimeError(f'NOAA filter did not return GRIB for forecast hour {h}: '+r.text[:150])
   with path.open('xb') as f:f.write(r.content)
  return h,path
 with ThreadPoolExecutor(max_workers=6) as pool: grids=dict(pool.map(one,hours))
 # Files carry several overlapping accumulations (QPF01, QPF06, QPF24 ending at the same time).
 # Summing whichever band comes first double-counted rain (a QPF24 band is listed first every
 # 6 hours). Instead, chain non-overlapping intervals forward from the cycle time: at each
 # valid time take the accumulation that starts exactly where coverage ended (shortest first).
 cycle_start=datetime.strptime(day+cycle,'%Y%m%d%H').replace(tzinfo=timezone.utc)
 xs=ys=None;candidates={};pop_by_end={}
 for h,path in sorted(grids.items()):
  with rasterio.open(path) as src:
   if xs is None:xs,ys=transform('EPSG:4326',src.crs,[p[1] for p in points],[p[2] for p in points])
   for i in range(1,src.count+1):
    element=str(src.tags(i).get('GRIB_ELEMENT',''));m=re.fullmatch(r'(QPF|PoP)(\d+)',element)
    if not m:continue
    end=datetime.fromtimestamp(int(src.tags(i)['GRIB_VALID_TIME']),timezone.utc);hours_=int(m.group(2))
    values=[None if np.ma.is_masked(v[0]) else float(v[0]) for v in src.sample(list(zip(xs,ys)),indexes=i,masked=True)]
    if m.group(1)=='QPF':candidates.setdefault(end,[]).append((hours_,h,values))
    elif hours_==min([hours_]+[k for k,_ in pop_by_end.get(end,[])]):pop_by_end[end]=[(hours_,values)]
 # Hourly files later switch to 6-hour windows on a different alignment, so find the furthest
 # time reachable by contiguous intervals, then walk back taking the shortest interval at each step.
 reachable={cycle_start}
 for end in sorted(candidates):
  if any(end-timedelta(hours=c[0]) in reachable for c in candidates[end]):reachable.add(end)
 chosen=[];node=max(reachable)
 while node!=cycle_start:
  c=min((c for c in candidates[node] if node-timedelta(hours=c[0]) in reachable),key=lambda c:c[0])
  chosen.append((node,)+c);node=node-timedelta(hours=c[0])
 chosen.reverse()
 rows={}
 for end,interval,h,values in chosen:
  start=end-timedelta(hours=interval);pops=pop_by_end.get(end,[(None,[None]*len(points))])[0][1]
  for (identifier,_,_),value,pv in zip(points,values,pops):
   probability=pv/100 if pv is not None else None
   if value is None and probability is None:continue
   rows.setdefault(identifier,[]).append(dict(start=start.isoformat(),end=end.isoformat(),mm=max(0,value) if value is not None else None,probability=probability,forecast_hour=h,interval_hours=interval))
 forecast=[]
 for identifier,intervals in rows.items():
  totals={};coverage={};probabilities={};prism={};prism_cov={}
  for item in intervals:
    # Also total each interval on PRISM's day (12:00 UTC to 12:00 UTC, labelled by its end date), so the
    # forecast can be scored against PRISM on exactly the same 24 hours (scripts/noaa_precip_daily.py).
    if item['mm'] is not None:
     b=datetime.fromisoformat(item['end'])-timedelta(hours=item['interval_hours']);e=datetime.fromisoformat(item['end'])
     while b<e:
      noon=b.replace(hour=12,minute=0,second=0,microsecond=0);noon=noon if noon>b else noon+timedelta(days=1)
      stop=min(e,noon);lab=noon.date().isoformat();frac=(stop-b).total_seconds()/(item['interval_hours']*3600)
      prism[lab]=prism.get(lab,0)+item['mm']*frac;prism_cov[lab]=prism_cov.get(lab,0)+(stop-b).total_seconds()/3600;b=stop
    zone=__import__('zoneinfo').ZoneInfo('America/New_York');finish=datetime.fromisoformat(item['end']);begin=finish-timedelta(hours=item['interval_hours']);full=(finish-begin).total_seconds()
    # The GRIB period is attached below; split multi-hour intervals at local midnight.
    while begin<finish:
     next_midnight=datetime.combine(begin.astimezone(zone).date()+timedelta(days=1),datetime.min.time(),zone).astimezone(timezone.utc)
     stop=min(finish,next_midnight);local=begin.astimezone(zone).date().isoformat();portion=(stop-begin).total_seconds()/full
     if item['mm'] is not None:totals[local]=totals.get(local,0)+item['mm']*portion;coverage[local]=coverage.get(local,0)+(stop-begin).total_seconds()/3600
     if item['probability'] is not None:probabilities[local]=max(probabilities.get(local,0),item['probability'])
     begin=stop
  forecast.append(dict(id=identifier,daily_precipitation_mm={k:v for k,v in totals.items() if coverage.get(k,0)>=23.99},daily_max_hourly_pop=probabilities,interval_count=len(intervals),
                       prism_day_mm={k:round(v,4) for k,v in sorted(prism.items()) if prism_cov.get(k,0)>=23.99}))
 # Keep only future local days. For days 12–14 use a transparent 50/50 extension of the
 # recent NBM daily mean and the preceding 42-day PRISM farm mean; do not call it NBM.
 from zoneinfo import ZoneInfo
 from datetime import date
 local_today=datetime.now(ZoneInfo('America/New_York')).date();dates=[str(local_today+timedelta(days=i)) for i in range(1,15)]
 latest_input=read(ROOT/'outputs/prospective/last-run.json');snap=read(ROOT/latest_input['snapshot'])
 sys.path.insert(0,str(ROOT/'scripts'));import prospective_daily as pd
 hist=pd.grid_values(snap)
 expanded=[]
 for f in forecast:
  h=hist.get(f['id'],{});end=max(h) if h else None
  recent=[h.get(str(date.fromisoformat(end)-timedelta(days=i))) for i in range(42)] if end else []
  baseline=float(np.mean(recent)) if len(recent)==42 and all(v is not None for v in recent) else None
  amounts=[f['daily_precipitation_mm'].get(d) for d in dates]
  direct=[v for v in amounts if v is not None]
  extension=[v for v in direct[-3:] if v is not None]
  tail=float((np.mean(extension)+baseline)/2) if len(extension)==3 and baseline is not None else None
  wet=[v for v in recent if v is not None and v>=0.254];wet_frequency=len(wet)/42 if len(recent)==42 else None;wet_mean=float(np.mean(wet)) if wet else None
  methods=[]
  for i,v in enumerate(amounts):
   if v is not None:methods.append('NOAA NBM QPF grid')
   elif f['daily_max_hourly_pop'].get(dates[i]) is not None and wet_mean is not None:
    ppop=f['daily_max_hourly_pop'][dates[i]];amounts[i]=min(wet_mean,baseline*ppop/max(wet_frequency or 1,0.05));methods.append('NBM hourly precipitation probability × recent PRISM wet-day amount (experimental)')
   elif baseline is not None:amounts[i]=baseline;methods.append('Trailing 42-day PRISM mean; no complete NBM guidance')
   else:methods.append('Unavailable')
  # Days 12–14 combine the preceding three-day NBM probability-guided estimate
  # with the farm's recent PRISM mean; retain the estimate's experimental label.
  if baseline is not None and all(amounts[i] is not None for i in (8,9,10)):
   extended=float((np.mean([amounts[i] for i in (8,9,10)])+baseline)/2)
   for i in (11,12,13):amounts[i]=extended;methods[i]='50/50 blend: preceding NBM probability-guided estimate + trailing 42-day PRISM mean'
  # Otherwise blend a probability-based day 12–14 estimate with the PRISM mean, once. (Before 2026-11-11 this
  # step also ran on days already blended above, mixing in the PRISM mean twice: 25% NBM / 75% PRISM.)
  if baseline is not None:
   for i in range(11,14):
    if methods[i].startswith('50/50 blend: preceding'):continue
    if amounts[i] is not None and f['daily_max_hourly_pop'].get(dates[i]) is not None:
     amounts[i]=(amounts[i]+baseline)/2;methods[i]='50/50 blend: NBM probability-adjusted PRISM estimate + trailing 42-day PRISM mean'
  expanded.append(dict(id=f['id'],daily_precipitation_mm=amounts,prism_day_precipitation_mm=f['prism_day_mm'],day_sources=methods,daily_max_hourly_pop=[f['daily_max_hourly_pop'].get(d) for d in dates],history_42day_mean_mm=baseline,nbm_interval_count=f['interval_count'],boundary_status='Provisional candidate' if f['id']!='yale-farm-new-haven' else 'Pilot boundary provisional'))
 manifest=dict(variable='precipitation',source='NOAA National Blend of Models (NBM), CONUS core QPF',dataset_name='blend',cycle=f'{day}T{cycle}:00Z',retrieved_at=datetime.now(timezone.utc).isoformat(),issued_at=datetime.now(timezone.utc).isoformat(),forecast_dates=dates,forecast_hours=hours,files=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in grids.values()],source_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),prism_snapshot=snap.get('grids',{}),units='mm liquid-water equivalent per Connecticut calendar day',farm_count=len(expanded),forecasts=expanded,limitations=['Native NBM grid sampled at each mapped parcel representative point; mapped fields are candidates, not confirmed farm boundaries.','NBM supplies direct QPF only through the available 264-hour forecast. Final three days are a 50/50 extension of its preceding three-day mean and the trailing 42-day PRISM farm mean; that extension is not a weather-model forecast and has no calibrated uncertainty interval.','Local calendar-day totals are aggregated from GRIB accumulation intervals; missing intervals are never treated as zero.'])
 out=ROOT/'outputs/forecasts/precipitation/noaa-live';out.mkdir(parents=True,exist_ok=True)
 today=str(local_today);latest_path=out/'latest.json'
 previous=read(latest_path) if latest_path.exists() else None
 if previous and previous.get('issue_local_date')==today:
  prior=read(ROOT/previous['path'])
  if prior.get('source_code_sha256')==manifest.get('source_code_sha256'):
   print('A live NOAA precipitation issue from this code version is already recorded today; original retained.');return
  manifest['correction_of_sha256']=previous['sha256'];manifest['correction_reason']='Reissued by a changed code version (source_code_sha256 differs from the original); see audit/ for the specific reason; original retained.'
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');issued=out/'issued'/today;issued.mkdir(parents=True,exist_ok=True)
 issue_path=issued/(stamp+'.json')
 with issue_path.open('x',encoding='utf-8') as f:json.dump(manifest,f,allow_nan=False)
 save(target/'farm-qpf.json',manifest)
 towns={}
 rec={x['id']:x for x in read(ROOT/'outputs/precipitation/records.json')}
 for r in expanded:
  t=rec.get(r['id'],{}).get('town')
  if t:towns.setdefault(t,[]).append(r)
 for t,items in towns.items():save(out/'towns'/(t+'.json'),items)
 save(latest_path,dict(path=str(issue_path.relative_to(ROOT)),sha256=hashlib.sha256(issue_path.read_bytes()).hexdigest(),cycle=manifest['cycle'],issue_local_date=today,farm_count=len(expanded)))
 print(dict(cycle=manifest['cycle'],forecast_hours=len(hours),farms=len(forecast),example=forecast[-1] if forecast else None))
if __name__=='__main__':main()
