"""Independent models using only each well's or gauge's own daily observations."""
import argparse,hashlib
from collections import defaultdict
from datetime import date,timedelta
import numpy as np
from statewide_common import ROOT,read,save
from forecast_methods import fit_and_test

def main():
 parser=argparse.ArgumentParser();parser.add_argument('variable',choices=['groundwater','streamflow']);kind=parser.parse_args().variable
 source=ROOT/'outputs'/kind/('wells.json' if kind=='groundwater' else 'gauges.json');records=read(source)
 out=ROOT/'outputs/forecasts'/kind;out.mkdir(parents=True,exist_ok=True)
 start=date(2026,8,4);cutoff=date(2026,11,1);issue=date(2026,11,2);days=[str(start+timedelta(days=i)) for i in range(90)];future=[str(issue+timedelta(days=i)) for i in range(1,15)]
 results=[]
 for r in records:
  history={}
  for v in r['history']:
   if kind=='groundwater' and v['type']!='Daily mean':continue
   if v.get('qualifier'):continue
   key=v['date'];value=v['depth_below_land_ft'] if kind=='groundwater' else v['flow_cfs']
   if key in history and history[key]!=value:raise ValueError('Ambiguous daily series')
   history[key]=value
  x=np.array([history.get(d,np.nan) for d in days]);model=fit_and_test(x,kind)
  results.append(dict(id=r['id'] if kind=='groundwater' else r['gauge_id'],series_id=None if kind=='groundwater' else r['series_id'],
   name=r['name'],towns=r['towns'],watershed_ids=r['watershed_ids'],coordinates=r['coordinates'],variable=kind,
   units='feet below land surface at monitored well' if kind=='groundwater' else 'cubic feet per second at stream gauge',
   training_days=int(np.isfinite(x).sum()),forecast_dates=future,**model))
 successful=[r for r in results if r['status']=='experimental']
 summary=dict(variable=kind,status='experimental',source_cutoff=str(cutoff),issue_date=str(issue),unobserved_gap_days=1,forecast_dates=future,
  release_status='Research only; operational accuracy not established',
  input_variable_allowlist=[kind],input_sources=[str(source.relative_to(ROOT))],input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
  candidates=['persistence','damped_trend','autoregression'],tuning_cutoffs=[days[41],days[55]],heldout_start=days[76],heldout_end=days[89],
  forecast_locations=len(successful),unavailable_locations=len(results)-len(successful),
  heldout_mean_station_mae=float(np.mean([r['heldout']['mae'] for r in successful])) if successful else None,
  stations_beating_persistence=sum(r['heldout']['beats_persistence'] for r in successful),
  independent_heldout_time_blocks=1,coverage='Monitored wells only; no farm aquifer predictions' if kind=='groundwater' else 'Supported CT gauges only; no ungauged rivers, lakes or reservoirs',
  uncertainty_note='No calibrated prediction intervals. Short retrospective test uses saved revised observations; it is not real-time forecast verification.')
 save(out/'summary.json',summary);save(out/'location-forecasts.json',results)
 if kind=='groundwater':
  # These are coverage records, deliberately not spatially interpolated groundwater forecasts.
  available={r['id'] for r in successful};links=read(ROOT/'outputs/groundwater/farm-well-links.json');farms=[]
  for f in links:farms.append(dict(candidate_id=f['candidate_id'],town=f['town'],status='unavailable',daily_groundwater_level=None,
   reason='No confirmed farm well or validated aquifer connection. Nearby observations cannot determine groundwater beneath this farm.',
   nearby_monitoring_context=[dict(**v,well_forecast_available=v['well_id'] in available) for v in f['nearby_wells']]))
  save(out/'farm-coverage.json',farms)
 print(kind,summary,flush=True)

if __name__=='__main__':main()
