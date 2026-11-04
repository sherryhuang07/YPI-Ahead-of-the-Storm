"""PRISM-only expected-amount baseline, attached to farm geometries using existing grid overlaps."""
import csv,hashlib
from datetime import date,timedelta
from collections import defaultdict
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import shape,mapping
from shapely.ops import unary_union
from statewide_common import ROOT,read,save

def main():
 source=ROOT/'data/prism/2026-11-02';out=ROOT/'outputs/forecasts/precipitation';out.mkdir(parents=True,exist_ok=True)
 manifest=read(source/'manifest.json');dates=manifest['dates'];assert len(dates)==90
 stack=[];hashes=[]
 for day in dates:
  path=source/f'{day}.tif'
  with rasterio.open(path) as s:stack.append(s.read(1,masked=True).filled(np.nan));profile=s.profile.copy()
  digest=hashlib.sha256(path.read_bytes()).hexdigest();assert digest==read(source/f'{day}.json')['crop_sha256'];hashes.append(dict(date=day,sha256=digest))
 x=np.stack(stack).astype(float);mask=unary_union([shape(f['geometry']) for f in read(ROOT/'data/statewide/connecticut-mask.geojson')['features']])
 inside=geometry_mask([mapping(mask)],x.shape[1:],profile['transform'],invert=True)
 scores={}
 for window in (14,28,42):
  scores[window]=float(np.mean([np.mean(abs((14*np.mean(x[t-window:t],axis=0)-np.sum(x[t+1:t+15],axis=0))[inside])) for t in (42,56)]))
 window=min(scores,key=scores.get);daily=np.mean(x[-window:],axis=0);test_pred=14*np.mean(x[75-window:75],axis=0);test_actual=np.sum(x[76:90],axis=0)
 benchmark=np.sum(x[61:75],axis=0)
 links=defaultdict(list)
 for row in csv.DictReader((ROOT/'outputs/precipitation/grid-overlaps.csv').open(encoding='utf-8')):links[row['id']].append((int(row['crop_row']),int(row['crop_column']),float(row['area_fraction'])))
 names={r['id']:r for r in read(ROOT/'outputs/precipitation/records.json') if r['kind'] in ['farm_candidate','pilot']}
 results=[]
 for identifier,record in names.items():
  overlap=links[identifier];weights=np.array([v[2] for v in overlap]);rr=[v[0] for v in overlap];cc=[v[1] for v in overlap]
  if not abs(weights.sum()-1)<1e-6:raise ValueError('Invalid farm area weights')
  arrays=[a[rr,cc] for a in [daily,test_pred,test_actual]]
  valid=all(np.isfinite(a).all() for a in arrays)
  if valid:rate,pred,actual=[float(np.dot(a,weights)) for a in arrays]
  else:rate=pred=actual=None
  results.append(dict(id=identifier,name=record['name'],town=record.get('town'),status='experimental' if valid else 'unavailable',
   variable='precipitation',method=f'trailing_{window}_day_mean',daily_expected_mm=[rate]*14 if valid else None,
   total_14_day_mm=14*rate if valid else None,total_14_day_inches=14*rate/25.4 if valid else None,
   heldout_14_day_prediction_mm=pred,heldout_14_day_observed_mm=actual,heldout_14_day_absolute_error_mm=abs(pred-actual) if valid else None,
   uncertainty_interval=None,boundary_status='Unconfirmed',interpretation='Expected-amount baseline from past rain only; daily values do not predict storm timing. No atmospheric forecast inputs.'))
 end=date.fromisoformat(manifest['end']);issue=date(2026,11,2);future=[str(issue+timedelta(days=i)) for i in range(1,15)]
 summary=dict(variable='precipitation',status='experimental',source_cutoff=str(end),forecast_dates=future,method=f'trailing_{window}_day_mean',
  issue_date=str(issue),unobserved_gap_days=1,release_status='Research only; operational accuracy not established',
  day_definition='PRISM date labels: 24 hours ending at 12 UTC. These are not local-midnight days.',
  input_variable_allowlist=['precipitation'],input_sources=['PRISM daily precipitation'],grid_hashes=hashes,
  tuning_windows_days=[14,28,42],tuning_origins=[dates[41],dates[55]],tuning_mae_14_day_total_mm=scores,
  heldout=dict(start=dates[76],end=dates[89],mean_grid_absolute_error_14_day_mm=float(np.mean(abs(test_pred-test_actual)[inside])),
   repeat_previous_fortnight_mae_mm=float(np.mean(abs(benchmark-test_actual)[inside])),independent_time_blocks=1),
  farm_candidate_count=sum(r['id']!='yale-farm-new-haven' for r in results),available_count=sum(r['status']=='experimental' for r in results),
  uncertainty_note='Not calibrated. One held-out fortnight and correlated grid cells cannot establish reliable weather forecasting skill.',
  known_limitations=['No incoming-storm information','Only 90 days of history, not a seasonal climatology','Source grids may include later revisions','Shared grid cells do not provide independent farm-scale weather'],
  yale=next(r for r in results if r['id']=='yale-farm-new-haven'))
 summary['heldout']['beats_repeat_previous_fortnight']=summary['heldout']['mean_grid_absolute_error_14_day_mm']<summary['heldout']['repeat_previous_fortnight_mae_mm']
 save(out/'summary.json',summary);save(out/'farm-forecasts.json',results)
 towns=defaultdict(list)
 for r in results:
  if r['id']!='yale-farm-new-haven':towns[r['town']].append(r)
 for town,items in towns.items():save(out/'towns'/(town+'.json'),items)
 save(out/'town-index.json',sorted(towns))
 profile.update(dtype='float64',nodata=-9999)
 with rasterio.open(out/'expected-14-day-precipitation-mm.tif','w',**profile) as dst:
  dst.write(np.where(np.isfinite(daily),14*daily,-9999),1);dst.update_tags(units='mm',status='EXPERIMENTAL HISTORY-ONLY BASELINE',start=future[0],end=future[-1])
 print('Precipitation:',summary['method'],summary['heldout'], 'Yale inches:',summary['yale']['total_14_day_inches'],flush=True)

if __name__=='__main__':main()
