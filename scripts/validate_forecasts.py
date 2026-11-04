"""Verify forecast dates, strict variable separation, missing coverage and temporal holdout isolation."""
import hashlib
from datetime import date,timedelta
import numpy as np
from statewide_common import ROOT,read
from forecast_methods import fit_and_test,predict

O=ROOT/'outputs/forecasts';expected=[str(date(2026,11,2)+timedelta(days=i)) for i in range(1,15)]
summaries={v:read(O/v/'summary.json') for v in ['precipitation','groundwater','streamflow']}
for variable,s in summaries.items():
 assert s['input_variable_allowlist']==[variable]
 assert s['forecast_dates']==expected and len(set(s['forecast_dates']))==14
 assert s['source_cutoff']=='2026-11-01' and s['unobserved_gap_days']==1
 assert s['release_status'].startswith('Research only')
 if variable!='precipitation':assert hashlib.sha256((ROOT/s['input_sources'][0]).read_bytes()).hexdigest()==s['input_sha256']
# Changing only held-out outcomes must not alter model selection or held-out predictions.
x=10+np.linspace(0,4,90)+.1*np.sin(np.arange(90))
original=fit_and_test(x,'groundwater');changed=x.copy();changed[76:]+=100
perturbed=fit_and_test(changed,'groundwater')
assert original['method']==perturbed['method'] and original['tuning_mae']==perturbed['tuning_mae']
assert np.array_equal(original['heldout']['prediction'],perturbed['heldout']['prediction'])
assert original['heldout']['mae']!=perturbed['heldout']['mae']
assert fit_and_test(np.full(90,np.nan),'groundwater')['status']=='unavailable'
assert fit_and_test(np.r_[np.ones(89),np.nan],'streamflow')['status']=='unavailable'
assert np.all(predict(np.zeros(90),'persistence','streamflow')==0)
for kind in ['groundwater','streamflow']:
 records=read(O/kind/'location-forecasts.json');ok=[r for r in records if r['status']=='experimental']
 assert len(ok)==summaries[kind]['forecast_locations']
 for r in ok:
  assert len(r['daily_prediction'])==14 and np.isfinite(r['daily_prediction']).all()
  assert r['uncertainty_interval'] is None and r['heldout']['origin_index']==75 and r['heldout']['unobserved_gap_days']==1
  assert r['heldout']['days_scored']>=12 and r['forecast_dates']==expected
  if kind=='streamflow':assert min(r['daily_prediction'])>=0
farmids={f['properties']['candidate_id'] for f in read(ROOT/'outputs/statewide/field-candidates.geojson')['features']}
rain=read(O/'precipitation/farm-forecasts.json');assert {r['id'] for r in rain}==farmids|{'yale-farm-new-haven'}
for r in rain:
 if r['status']=='experimental':
  assert len(r['daily_expected_mm'])==14 and np.isfinite(r['daily_expected_mm']).all() and min(r['daily_expected_mm'])>=0
  assert abs(sum(r['daily_expected_mm'])-r['total_14_day_mm'])<1e-8
  assert abs(r['total_14_day_inches']*25.4-r['total_14_day_mm'])<1e-8
farms=read(O/'groundwater/farm-coverage.json');assert {r['candidate_id'] for r in farms}==farmids
assert all(r['status']=='unavailable' and r['daily_groundwater_level'] is None for r in farms)
print('PASS: all farm IDs, 14 future date labels, source hashes/variable separation, holdout perturbation, zero/missing handling, finite values and unsupported groundwater kept null.')
