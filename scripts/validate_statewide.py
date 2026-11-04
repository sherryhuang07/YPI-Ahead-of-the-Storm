"""Checks real output coverage, provenance, cross-boundary joins, and pilot regression."""
import csv,math
from collections import defaultdict,Counter
from shapely.geometry import shape,Polygon,Point,MultiPolygon
from shapely import STRtree
from statewide_common import *
OUT=ROOT/'outputs'/'statewide'
summary=read(OUT/'summary.json');fields=read(OUT/'field-candidates.geojson')['features'];towns=read(OUT/'town-coverage.json')
assert len(towns)==169 and len({t['town'] for t in towns})==169
assert len(fields)==summary['candidate_records']
assert len({f['properties']['candidate_id'] for f in fields})==len(fields)
assert summary['confirmed_farm_boundaries']==0 and summary['complete_farm_coverage'] is False
assert all(not f['properties']['farmer_confirmed'] and not f['properties']['recommendations_ready'] and f['properties']['farm_operator_id'] is None for f in fields)
assert all(shape(f['geometry']).is_valid and not shape(f['geometry']).is_empty for f in fields)
assert all(f['properties']['source_year']==2025 for f in fields if f['properties']['source'].startswith('FTW'))
assert all(f['properties']['towns'] for f in fields), 'Every retained CT candidate must have town coverage'
pilot=[f for f in fields if f['properties']['candidate_id']=='osm-way-45092131']
assert len(pilot)==1
assert 'New Haven|14057' in pilot[0]['properties']['parcel_keys']
assert '5302' in pilot[0]['properties']['watershed_ids']
assert abs(pilot[0]['properties']['ct_area_acres']-0.7235)<0.01
by_id={f['properties']['candidate_id']:f for f in fields}
shares=defaultdict(float)
for r in csv.DictReader((OUT/'field-town-links.csv').open(encoding='utf-8-sig')):
    if r['share_of_candidate']:shares[r['candidate_id']]+=float(r['share_of_candidate'])
bad_shares={k:v for k,v in shares.items() if not .995<=v<=1.005}
assert not bad_shares, f'Town area coverage issue: {list(bad_shares.items())[:5]}'
for r in csv.DictReader((OUT/'field-property-links.csv').open(encoding='utf-8-sig')):
    assert r['candidate_id'] in by_id
    if r['share_of_candidate']:assert 0<float(r['share_of_candidate'])<=1.00001
    if r['share_of_property']:assert 0<float(r['share_of_property'])<=1.00001
# Geometry semantics important for field assignment: holes excluded, all components kept,
# and a field crossing two regions retains both intersections.
with_hole=Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(4,4),(6,4),(6,6),(4,6)]])
assert not with_hole.covers(Point(5,5))
split=Polygon([(4,1),(6,1),(6,2),(4,2)])
left=Polygon([(0,0),(5,0),(5,5),(0,5)]);right=Polygon([(5,0),(10,0),(10,5),(5,5)])
assert split.intersection(left).area==1 and split.intersection(right).area==1
assert len(STRtree([left,right]).query(split,predicate='intersects'))==2
assert MultiPolygon([left,Polygon([(20,0),(21,0),(21,1),(20,1)])]).covers(Point(20.5,.5))
report={'status':'passed','towns':169,'candidate_count':len(fields),'checks':['unique candidate identifiers','valid nonempty geometry','all records unconfirmed','2025-only satellite inventory','town-area fractions conserve candidate area','parcel overlap fractions bounded','Yale pilot parcel/watershed regression','holes, multipart shapes, and cross-boundary geometry semantics'],'known_limitations':['Not a recall or precision validation against every Connecticut farm','No statewide manual aerial review','Source errors and missing farms remain possible']}
save(OUT/'validation.json',report)
log('Validation passed: 169-town audit, geometry, overlap fractions, and Yale Farm regression')
