import math, hashlib
from collections import Counter
import pyarrow as pa
import pyarrow.parquet as pq
from shapely import from_wkb, make_valid, normalize, to_wkb, prepare
from shapely.geometry import shape, mapping, Polygon, MultiPolygon, Point, LineString
from shapely.ops import unary_union, polygonize, transform
from shapely.geometry.polygon import orient
from pyproj import Transformer
from statewide_common import *

project=Transformer.from_crs(4326,5070,always_xy=True).transform
def area(g): return transform(project,g).area
def polygon_only(g):
    if g.geom_type in ('Polygon','MultiPolygon'): return g
    parts=[p for p in getattr(g,'geoms',[]) if p.geom_type in ('Polygon','MultiPolygon')]
    return unary_union(parts) if parts else Polygon()
towns=read(DATA/'towns.geojson')['features']
state=unary_union([make_valid(shape(f['geometry'])) for f in towns])
prepare(state)
state_bounds=state.bounds
save(DATA/'connecticut-mask.geojson',{'type':'FeatureCollection','features':[{'type':'Feature','properties':{'source':'CT DOT Municipalities union'},'geometry':mapping(state)}]})
records=[];seen=set();audit={'ftw_raw_rows_by_partition':{},'ftw_year_counts':Counter(),'geometry_repairs':0,'exact_geometry_duplicates_removed':0,'outside_ct_removed':0,'osm_geometry_issues':[],'source_metadata_warnings':[]}
for partition in ['ct','ny','ma','ri']:
    table=pq.read_table(DATA/f'ftw-{partition}.parquet')
    geo=json.loads(table.schema.metadata[b'geo'])['columns']['geometry']
    if geo.get('crs') not in (None,):
        raise RuntimeError('Review unexpected source CRS before processing')
    table=table.set_column(table.schema.get_field_index('determination:datetime'),'determination:datetime',table['determination:datetime'].cast(pa.string()))
    audit['ftw_raw_rows_by_partition'][partition]=table.num_rows
    # Per-row bbox is checked against real geometry; collection metadata bbox is not trusted.
    source_bbox=geo.get('bbox')
    actual_bounds=[]
    for row_index,row in enumerate(table.to_pylist()):
        if row_index%10000==0:log(f'Checking {partition.upper()} satellite records: {row_index:,} of {table.num_rows:,}')
        year=row['determination:datetime'][:4]
        g=from_wkb(row['geometry'])
        if not g.is_valid:g=polygon_only(make_valid(g));audit['geometry_repairs']+=1
        if g.is_empty or not state.intersects(g):audit['outside_ct_removed']+=1;continue
        clipped=g if state.covers(g) else polygon_only(g.intersection(state))
        if clipped.is_empty or area(clipped)<1:continue
        audit['ftw_year_counts'][year]+=1
        if source_bbox and not (source_bbox[0]<=g.centroid.x<=source_bbox[2] and source_bbox[1]<=g.centroid.y<=source_bbox[3]):
            warning=f'{partition}: source GeoParquet collection bbox inconsistent with actual CT-area geometry; used actual geometries'
            if warning not in audit['source_metadata_warnings']:audit['source_metadata_warnings'].append(warning)
        if year!='2025':continue
        key=hashlib.sha256(to_wkb(normalize(g))).hexdigest()
        if key in seen:audit['exact_geometry_duplicates_removed']+=1;continue
        seen.add(key)
        confidence=row.get('confidence')
        if confidence is not None and not math.isfinite(confidence):confidence=None
        props={'candidate_id':f'ftw-2025-{partition}-{row["id"]}','source':'FTW Sentinel-2 model','source_id':row['id'],'source_partition':partition.upper(),'source_year':2025,'boundary_kind':'satellite_field_candidate','name':None,'review_status':'Unreviewed','farm_operator_id':None,'farmer_confirmed':False,'recommendations_ready':False,'source_reliability_score':confidence,'score_interpretation':'500 m neighborhood model score; not boundary accuracy or probability','ct_area_acres':area(clipped)/4046.8564224,'state_line_clipped':not g.equals(clipped),'source_date':row['determination:datetime'],'source_url':FTW+f'US_{partition.upper()}.parquet','license':'CC-BY-4.0'}
        records.append({'type':'Feature','properties':props,'geometry':mapping(clipped)})
    log(f'Satellite fields processed from {partition.upper()}; {len(records):,} current CT candidates retained')

def osm_shape(e):
    if e['type']=='node':return Point(e['lon'],e['lat'])
    if e['type']=='way':
        coords=[(n['lon'],n['lat']) for n in e.get('geometry',[]) if n]
        if len(coords)<4 or coords[0]!=coords[-1]:raise ValueError('Open or incomplete mapped outline')
        return Polygon(coords)
    if e['type']=='relation':
        rings={'outer':[],'inner':[]}
        for m in e.get('members',[]):
            role=m.get('role','') or 'outer'
            if m.get('type')=='way' and role in rings:
                coords=[(n['lon'],n['lat']) for n in m.get('geometry',[]) if n]
                if len(coords)>1:rings[role].append(LineString(coords))
        outer=unary_union(list(polygonize(unary_union(rings['outer']))))
        inner=unary_union(list(polygonize(unary_union(rings['inner']))))
        if outer.is_empty:raise ValueError('Relation has no closed outer outline')
        return outer.difference(inner)
    raise ValueError('Unsupported OSM type')

osm=read(DATA/'osm-agriculture.json')
for e in osm['elements']:
    try:
        g=osm_shape(e)
        if not g.is_valid:g=make_valid(g);audit['geometry_repairs']+=1
        if not state.intersects(g):continue
        clipped=g if state.covers(g) else g.intersection(state)
        if clipped.geom_type!='Point':clipped=polygon_only(clipped)
        if clipped.is_empty:continue
        tags=e.get('tags',{})
        landuse=tags.get('landuse',tags.get('garden:type',tags.get('place','unknown')))
        props={'candidate_id':f'osm-{e["type"]}-{e["id"]}','source':'OpenStreetMap public mapping','source_id':str(e['id']),'source_year':None,'boundary_kind':'mapped_location_only' if g.geom_type=='Point' else 'public_mapped_agricultural_outline','landuse':landuse,'name':tags.get('name'),'review_status':'Unreviewed','farm_operator_id':None,'farmer_confirmed':False,'recommendations_ready':False,'source_reliability_score':None,'ct_area_acres':None if g.geom_type=='Point' else area(clipped)/4046.8564224,'state_line_clipped':not g.equals(clipped),'source_date':e.get('timestamp'),'source_version':e.get('version'),'source_url':f'https://www.openstreetmap.org/{e["type"]}/{e["id"]}','license':'ODbL; OpenStreetMap contributors'}
        records.append({'type':'Feature','properties':props,'geometry':mapping(clipped)})
    except Exception as error:
        audit['osm_geometry_issues'].append({'type':e['type'],'id':e['id'],'reason':str(error)})
assert len({f['properties']['candidate_id'] for f in records})==len(records)
save(DATA/'field-candidates.geojson',{'type':'FeatureCollection','features':records})
audit['ftw_year_counts']=dict(audit['ftw_year_counts']);audit['candidate_counts']=dict(Counter(f['properties']['source'] for f in records))
save(DATA/'source-processing-audit.json',audit)

# Spatial queries request properties that touch candidate areas, not only agriculture-coded land.
# Use unioned polygons per batch so ArcGIS ring parity cannot cancel overlapping candidates.
batches=[]
for start in range(0,len(records),30):
    group=records[start:start+30]
    shapes=[]
    for f in group:
        g=shape(f['geometry'])
        if g.geom_type=='Point':g=g.buffer(0.00001) # Search tolerance only, never saved as a farm boundary.
        shapes.append(g)
    merged=polygon_only(unary_union(shapes))
    polys=[merged] if merged.geom_type=='Polygon' else list(merged.geoms)
    rings=[]
    for p in polys:
        p=orient(p,sign=-1) # ArcGIS exterior clockwise, holes counterclockwise.
        rings.append(list(p.exterior.coords));rings.extend(list(r.coords) for r in p.interiors)
    geometry={'rings':rings,'spatialReference':{'wkid':4326}}
    key=hashlib.sha256(json.dumps(geometry,sort_keys=True).encode()).hexdigest()[:20]
    batches.append({'key':key,'candidate_ids':[f['properties']['candidate_id'] for f in group],'geometry':geometry})
save(DATA/'field-query-batches.json',batches)
log(f'Prepared {len(records):,} boundary/location candidates and {len(batches)} property-comparison batches')
