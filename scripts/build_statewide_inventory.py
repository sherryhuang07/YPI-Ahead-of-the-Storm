"""Build auditable spatial joins and review exports. Does not infer farm businesses."""
import csv,sqlite3,hashlib,html
from collections import Counter,defaultdict
from shapely import make_valid,STRtree,prepare
from shapely.geometry import shape,mapping,Polygon,Point
from shapely.ops import transform,unary_union
from pyproj import Transformer
from statewide_common import *

OUT=ROOT/'outputs'/'statewide';OUT.mkdir(parents=True,exist_ok=True)
project=Transformer.from_crs(4326,5070,always_xy=True).transform
def projected(g):return transform(project,g)
def clean(g):return g if g.is_valid else make_valid(g)
def overlaps(g,geoms,tree):
    result=[]
    for index in tree.query(g,predicate='intersects'):
        index=int(index)
        if g.geom_type=='Point':result.append((index,None));continue
        area=g.intersection(geoms[index]).area
        if area>1:result.append((index,area))
    return sorted(result,key=lambda p:p[1] or 0,reverse=True)
def csv_file(name,rows,fields):
    with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
def index(features):
    geoms=[projected(clean(shape(f['geometry']))) for f in features]
    return geoms,STRtree(geoms)

log('Building spatial indexes for towns, watersheds, fields, and properties')
towns=read(DATA/'towns.geojson')['features'];tg,tt=index(towns)
watersheds=read(ROOT/'data/watersheds.geojson')['features'];wg,wt=index(watersheds)
fields=read(DATA/'field-candidates.geojson')['features'];fg,ft=index(fields)
raw=read(DATA/'candidate-parcels.geojson')['features']
ag_ids=set(read(DATA/'ag-parcel-ids.json')['ids'])
groups=defaultdict(list)
for f in raw:
    p=f['properties']; key=p['Town_Name']+'|'+str(p.get('Parcel_ID') or 'record-'+str(p['OBJECTID']))
    groups[key].append(f)
parcels=[];parcel_issues=[]
for key,group in groups.items():
    geoms=[clean(shape(f['geometry'])) for f in group if f.get('geometry')]
    if not geoms:parcel_issues.append({'parcel_key':key,'issue':'Missing geometry'});continue
    geometry=unary_union(geoms)
    if geometry.geom_type not in ('Polygon','MultiPolygon'):
        parcel_issues.append({'parcel_key':key,'issue':'Non-polygon geometry'});continue
    p=group[0]['properties']
    parcels.append({'type':'Feature','properties':{'parcel_key':key,'town':p['Town_Name'],'parcel_id':p['Parcel_ID'],'address':p['Location'],'source_record_ids':[f['properties']['OBJECTID'] for f in group],'collection_years':sorted(set(str(f['properties'].get('Parcel_Collection_Year')) for f in group)),'use_descriptions':sorted(set(f['properties']['State_Use_Description'] for f in group if f['properties']['State_Use_Description'])),'agricultural_description_match':any(f['properties']['OBJECTID'] in ag_ids for f in group),'boundary_kind':'assessor_property','farmer_confirmed':False},'geometry':mapping(geometry)})
pg,pt=index(parcels)
town_rows={f['properties']['Municipality']:{'town':f['properties']['Municipality'],'town_number':f['properties']['MunicipalityNumber'],'satellite_candidates':0,'public_mapped_candidates':0,'agricultural_property_candidates':0,'directory_leads':0,'field_candidates_without_property_match':0,'parcel_records_total':0,'parcel_records_missing_use_description':0,'confirmed_farms':0,'coverage_status':'Sources processed; completeness of farms unknown'} for f in towns}
for label,column in [('all','parcel_records_total'),('missing-use','parcel_records_missing_use_description')]:
    for f in read(DATA/f'parcel-town-{label}.json')['features']:
        p=f['attributes'];name=p['Town_Name']
        if name in town_rows:town_rows[name][column]=p['record_count']
for p in parcels:
    q=p['properties']
    if q['agricultural_description_match'] and q['town'] in town_rows:town_rows[q['town']]['agricultural_property_candidates']+=1

parcel_edges=[];watershed_edges=[];town_edges=[];review=[];cross_source_edges=[]
for i,f in enumerate(fields):
    p=f['properties'];g=fg[i];aid=p['candidate_id'];denom=g.area if g.geom_type!='Point' else None
    town_match=overlaps(g,tg,tt)
    p['town']=towns[town_match[0][0]]['properties']['Municipality'] if town_match else None
    p['towns']=[towns[j]['properties']['Municipality'] for j,a in town_match]
    for j,a in town_match:
        name=towns[j]['properties']['Municipality']
        town_edges.append({'candidate_id':aid,'town':name,'overlap_acres':None if a is None else a/4046.8564224,'share_of_candidate':None if a is None else a/denom})
        town_rows[name]['satellite_candidates' if p['source'].startswith('FTW') else 'public_mapped_candidates']+=1
    matches=overlaps(g,pg,pt);p['parcel_keys']=[parcels[j]['properties']['parcel_key'] for j,a in matches]
    p['parcel_addresses']=[parcels[j]['properties']['address'] for j,a in matches]
    for j,a in matches:
        parcel_edges.append({'candidate_id':aid,'parcel_key':parcels[j]['properties']['parcel_key'],'overlap_acres':None if a is None else a/4046.8564224,'share_of_candidate':None if a is None else a/denom,'share_of_property':None if a is None else a/pg[j].area})
    basin_area=defaultdict(float);basin_names={}
    for j,a in overlaps(g,wg,wt):
        code=str(watersheds[j]['properties']['SBAS_NO']);basin_area[code]+=a or 0;basin_names[code]=watersheds[j]['properties']['SUBREGION']
    p['watershed_ids']=sorted(basin_area)
    for code,a in basin_area.items():watershed_edges.append({'candidate_id':aid,'watershed_id':code,'watershed_name':basin_names[code],'overlap_acres':a/4046.8564224 if denom else None,'share_of_candidate':a/denom if denom else None})
    evidence=[]
    for j in ft.query(g,predicate='intersects'):
        j=int(j)
        if j==i or fields[j]['properties']['source']==p['source'] or not denom or fg[j].geom_type=='Point':continue
        common=g.intersection(fg[j]).area
        if common>1 and common/denom>=0.1:
            evidence.append(fields[j]['properties']['candidate_id'])
            if i<j:cross_source_edges.append({'candidate_id':aid,'other_candidate_id':fields[j]['properties']['candidate_id'],'overlap_acres':common/4046.8564224})
    p['overlapping_other_source_ids']=evidence
    p['review_priority']='Multiple sources overlap; still unverified' if evidence else 'Single mapped source; review needed'
    flags=[]
    if not matches:
        flags.append('No intersecting property found')
        for name in p['towns']:town_rows[name]['field_candidates_without_property_match']+=1
    if not basin_area:flags.append('No watershed match')
    if len(p['watershed_ids'])>1:flags.append('Crosses watershed boundaries')
    if not denom:flags.append('Location only; no boundary')
    if p.get('landuse')=='meadow':flags.append('Meadow may be unmanaged grassland')
    if p['source'].startswith('FTW') and p.get('source_reliability_score') is None:flags.append('Source reliability score unavailable')
    if p.get('source_reliability_score') is not None and p['source_reliability_score']<69:flags.append('Source neighborhood score below publisher suggested screen')
    p['review_flags']=flags
    review.append({'candidate_id':aid,'town':p['town'],'name':p.get('name'),'source':p['source'],'boundary_kind':p['boundary_kind'],'approx_outline_acres':p['ct_area_acres'],'parcel_keys':'; '.join(p['parcel_keys']),'watersheds':'; '.join(p['watershed_ids']),'review_status':'Unreviewed','flags':'; '.join(flags),'source_url':p['source_url']})
    if i%1000==0:log(f'Geographic joins completed: {i:,} of {len(fields):,} candidate records')

directory=read(DATA/'directory-leads.json')
for p in directory:
    p['nearby_outline_ids']=[];p['town']=None
    if p['geometry']:
        g=projected(shape(p['geometry']));town_match=overlaps(g,tg,tt)
        if town_match:
            p['town']=towns[town_match[0][0]]['properties']['Municipality'];town_rows[p['town']]['directory_leads']+=1
        # 100 m radius is a search aid around an interpolated street location, not a farm assignment.
        p['nearby_outline_ids']=[fields[int(j)]['properties']['candidate_id'] for j in ft.query(g.buffer(100),predicate='intersects')]
    p['boundary_review_need']='Review nearby outlines; address proximity does not establish operated land' if p['nearby_outline_ids'] else 'No outline near address, or address unresolved; manual location needed'
    p['nearby_outline_ids']='; '.join(p['nearby_outline_ids'])
    p['categories']='; '.join(p['categories'])

save(OUT/'field-candidates.geojson',{'type':'FeatureCollection','features':fields})
save(OUT/'property-candidates.geojson',{'type':'FeatureCollection','features':parcels})
save(OUT/'directory-leads.json',directory)
save(OUT/'town-coverage.json',sorted(town_rows.values(),key=lambda r:r['town']))
csv_file('boundary-review.csv',review,list(review[0]))
csv_file('town-coverage.csv',list(town_rows.values()),list(next(iter(town_rows.values()))))
csv_file('field-property-links.csv',parcel_edges,['candidate_id','parcel_key','overlap_acres','share_of_candidate','share_of_property'])
csv_file('field-watershed-links.csv',watershed_edges,['candidate_id','watershed_id','watershed_name','overlap_acres','share_of_candidate'])
csv_file('field-town-links.csv',town_edges,['candidate_id','town','overlap_acres','share_of_candidate'])
csv_file('cross-source-overlaps.csv',cross_source_edges,['candidate_id','other_candidate_id','overlap_acres'])
csv_file('directory-review.csv',directory,['directory_id','name','address','town','categories','geocode_status','directory_listing_kind','boundary_review_need','nearby_outline_ids','source_url'])
linked={r['parcel_key'] for r in parcel_edges}
property_review=[dict(p['properties'],review_status='Unreviewed',reason='Agricultural assessor description without a mapped field') for p in parcels if p['properties']['agricultural_description_match'] and p['properties']['parcel_key'] not in linked]
csv_file('property-without-field-review.csv',property_review,['parcel_key','town','address','use_descriptions','review_status','reason'])
source_counts=dict(Counter(f['properties']['source'] for f in fields))
summary={'scope':'Statewide candidate inventory, not a census of confirmed farms','towns_processed':len(towns),'towns_with_field_or_public_candidates':sum(r['satellite_candidates']+r['public_mapped_candidates']>0 for r in town_rows.values()),'candidate_records':len(fields),'source_counts':source_counts,'property_records_downloaded':len(raw),'unique_property_keys':len(parcels),'agricultural_property_keys':sum(p['properties']['agricultural_description_match'] for p in parcels),'agricultural_properties_without_mapped_field':len(property_review),'field_property_links':len(parcel_edges),'candidates_without_property_match':sum(not f['properties']['parcel_keys'] for f in fields),'candidates_without_watershed_match':sum(not f['properties']['watershed_ids'] for f in fields),'cross_watershed_candidates':sum(len(f['properties']['watershed_ids'])>1 for f in fields),'directory_listings':len(directory),'directory_approximate_locations':sum(p['geometry'] is not None for p in directory),'directory_without_nearby_outline':sum(not p['nearby_outline_ids'] for p in directory),'confirmed_farm_boundaries':0,'complete_farm_coverage':False,'farms_missing_from_all_sources':'Unknown; not measurable from these sources alone','built_at':datetime.now(timezone.utc).isoformat(),'parcel_geometry_issues':parcel_issues,'source_processing_audit':read(DATA/'source-processing-audit.json')}
save(OUT/'summary.json',summary)

# A compact app-ready database keeps geometries, evidence, and review status together.
db=sqlite3.connect(OUT/'inventory.sqlite')
db.executescript('DROP TABLE IF EXISTS candidates; DROP TABLE IF EXISTS properties; DROP TABLE IF EXISTS directory; CREATE TABLE candidates(id TEXT PRIMARY KEY,town TEXT,source TEXT,name TEXT,review_status TEXT,properties_json TEXT,geometry_json TEXT); CREATE TABLE properties(id TEXT PRIMARY KEY,properties_json TEXT,geometry_json TEXT); CREATE TABLE directory(id TEXT PRIMARY KEY,properties_json TEXT);')
db.executemany('INSERT INTO candidates VALUES(?,?,?,?,?,?,?)',[(f['properties']['candidate_id'],f['properties']['town'],f['properties']['source'],f['properties'].get('name'),'Unreviewed',json.dumps(f['properties']),json.dumps(f['geometry'])) for f in fields])
db.executemany('INSERT INTO properties VALUES(?,?,?)',[(p['properties']['parcel_key'],json.dumps(p['properties']),json.dumps(p['geometry'])) for p in parcels])
db.executemany('INSERT INTO directory VALUES(?,?)',[(p['directory_id'],json.dumps(p)) for p in directory])
db.execute('CREATE INDEX IF NOT EXISTS candidate_town ON candidates(town)');db.commit();db.close()

# Town files are easy to browse from the existing plain-English terminal.
town_dir=OUT/'towns';town_dir.mkdir(exist_ok=True)
for town in towns:
    name=town['properties']['Municipality'];number=town['properties']['MunicipalityNumber']
    selected=[f for f in fields if name in f['properties']['towns']]
    save(town_dir/f'{number:03d}.json',{'town':name,'summary':town_rows[name],'candidates':[f['properties'] for f in selected]})
    save(town_dir/f'{number:03d}.geojson',{'type':'FeatureCollection','features':selected})
log(f'Inventory saved: {len(fields):,} candidate records, {len(parcels):,} property keys, all 169 towns audited')
print(json.dumps({k:v for k,v in summary.items() if k not in ('source_processing_audit','parcel_geometry_issues')},indent=2))
