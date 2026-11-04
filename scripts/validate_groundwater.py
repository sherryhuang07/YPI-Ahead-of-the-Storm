import hashlib,math
from datetime import date
from statewide_common import ROOT,read

D=ROOT/'data/groundwater';O=ROOT/'outputs/groundwater';manifest=read(D/'manifest.json');summary=read(O/'summary.json');wells=read(O/'wells.json');links=read(O/'farm-well-links.json');coverage=read(O/'town-coverage.json')
for src in manifest['sources']:assert hashlib.sha256((D/(src['name']+'.json')).read_bytes()).hexdigest()==src['sha256']
assert len(wells)==len({r['id'] for r in wells})==summary['listed_wells']
recent={r['id'] for r in wells if r['recent_observation_count']};assert len(recent)==summary['wells_with_recent_readings']
assert len(coverage)==169 and len({t['town'] for t in coverage})==169
assert sum(t['wells_with_recent_readings']==0 for t in coverage)==summary['towns_without_recent_well']
for r in wells:
 if r['latest']:assert r['age_days']==(date.fromisoformat(summary['snapshot'])-date.fromisoformat(r['latest']['date'])).days
 else:assert r['age_days'] is None and not r['history']
 assert len(r['history'])==r['recent_observation_count']
 assert r['daily_days']==len({v['date'] for v in r['history'] if v['type']=='Daily mean'})
 for v in r['history']:assert summary['window_start']<=v['date']<=summary['window_end'] and math.isfinite(v['depth_below_land_ft'])
for r in links:
 distances=[v['distance_km'] for v in r['nearby_wells']];assert distances==sorted(distances)
 for v in r['nearby_wells']:assert v['well_id'] in recent and v['distance_km']>=0 and not v['farm_measurement'] and v['aquifer_match']=='Not established'
assert len(links)==len(read(ROOT/'outputs/statewide/field-candidates.geojson')['features'])
print('PASS: source hashes, unique wells, observation dates, daily coverage, missing-data states, all 169 towns, and contextual links for every farm candidate.')
