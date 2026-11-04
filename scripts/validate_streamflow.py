import hashlib,math
from datetime import date
from statewide_common import ROOT,read
from build_streamflow import rolling,percentile_band

day=date(2026,11,1)
assert rolling({'2026-11-01':dict(flow_cfs=0,qualifier=None)},day,1)['mean_cfs']==0
assert rolling({'2026-11-01':dict(flow_cfs=2,qualifier=None)},day,2)['mean_cfs'] is None
thresholds={5:1,10:2,25:3,50:4,75:5,90:6,95:7}
assert percentile_band(.5,thresholds)=='Below the 5th percentile'
assert percentile_band(4.5,thresholds)=='50th–75th percentile band'
assert 'ties possible' in percentile_band(4,thresholds)
assert 'withheld' in percentile_band(-1,thresholds)
D=ROOT/'data/streamflow';O=ROOT/'outputs/streamflow';m=read(D/'manifest.json');s=read(O/'summary.json');records=read(O/'gauges.json')
for src in m['sources']:assert hashlib.sha256((D/(src['name']+'.json')).read_bytes()).hexdigest()==src['sha256']
assert len({r['series_id'] for r in records})==len(records)
recent=[r for r in records if r['history']];assert len({r['gauge_id'] for r in recent})==s['recent_gauges']
raw={}
for f in read(D/'daily.json')['features']:
 p=f['properties'];raw[(p['time_series_id'],p['time'][:10])]=p
for r in recent:
 assert len(r['history'])==len({v['date'] for v in r['history']})==r['days_observed']
 for v in r['history']:
  p=raw[(r['series_id'],v['date'])];assert p['monitoring_location_id']==r['gauge_id'] and p['parameter_code']=='00060' and p['statistic_id']=='00003'
  assert float(p['value'])==v['flow_cfs'] and m['start']<=v['date']<=m['end']
 for n,a in r['averages'].items():
  assert (a['mean_cfs'] is not None)==(a['available_days']==int(n))
  if a['mean_cfs'] is not None:
   eligible=[v['flow_cfs'] for v in r['history'] if 0<=(day-date.fromisoformat(v['date'])).days<int(n)]
   assert math.isclose(a['mean_cfs'],sum(eligible)/int(n),abs_tol=1e-8)
 if r['seasonal_context']:
  c=r['seasonal_context'];assert c['approval_status']=='approved' and c['month_day']==r['latest']['date'][5:]
  vals=[c['thresholds_cfs'][str(p)] for p in [5,10,25,50,75,90,95]];assert vals==sorted(vals)
links=read(O/'farm-gauge-links.json');assert len(links)==len(read(ROOT/'outputs/statewide/field-candidates.geojson')['features'])
for f in links:
 assert [x['distance_km'] for x in f['nearby_gauges']]==sorted(x['distance_km'] for x in f['nearby_gauges'])
 assert all(x['farm_water_access']=='Not established' and x['upstream_downstream']=='Not established' for x in f['nearby_gauges'])
print('PASS: source hashes, raw observations and units, zero versus missing flow, complete rolling windows, percentile bounds/ties, approved baselines, and all farm links.')
