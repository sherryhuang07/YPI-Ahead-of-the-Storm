"""Keep the current 3DHP identifiers separate, with explicit spatial associations."""
from collections import Counter
from shapely.geometry import shape,Point
from shapely.ops import transform
from shapely import STRtree,make_valid
from pyproj import Transformer
from statewide_common import ROOT,read,save,log
D=ROOT/'data/hydrography';O=ROOT/'outputs/river-network'
project=Transformer.from_crs(4326,5070,always_xy=True).transform
def geo(f):return transform(project,make_valid(shape(f['geometry'])))
def main():
    lines=read(D/'3dhp-flowlines.geojson')['features'];lg=[geo(f) for f in lines];lt=STRtree(lg)
    hs={f['properties']['hydrosequence']:f['properties']['id3dhp'] for f in lines}
    edges=[];water={};catch={}
    for f in lines:
        p=f['properties'];rid=p['id3dhp']
        edges.append(dict(id3dhp=rid,downstream=hs.get(p.get('dnhydrosequence')),outside_download_hydrosequence=p.get('dnhydrosequence') if p.get('dnhydrosequence') not in hs else None,waterbody_id=p.get('waterbodyid3dhp'),catchment_id=p.get('catchmentid3dhp'),workunit=p.get('workunitid')))
        if p.get('waterbodyid3dhp'):water.setdefault(p['waterbodyid3dhp'],[]).append(rid)
        if p.get('catchmentid3dhp'):catch.setdefault(p['catchmentid3dhp'],[]).append(rid)
    save(O/'3dhp-directed-reaches.json',edges)
    gauges=[]
    for g in read(ROOT/'outputs/streamflow/gauges.json'):
        if not (g.get('age_days') is not None and g['age_days']<=7):continue
        pt=transform(project,Point(g['coordinates']));j=int(lt.nearest(pt))
        gauges.append(dict(gauge_id=g['gauge_id'],nearest_3dhp_reach=lines[j]['properties']['id3dhp'],distance_m=pt.distance(lg[j]),relationship='Proximity candidate only, not an authoritative gauge-to-reach crosswalk'))
    save(O/'gauge-3dhp-candidates.json',gauges)
    bodies=read(D/'3dhp-waterbodies.geojson')['features']
    save(O/'3dhp-waterbody-links.json',[dict(id3dhp=f['properties']['id3dhp'],flowline_ids=water.get(f['properties']['id3dhp'],[]),forecast=None) for f in bodies])
    cats=read(D/'3dhp-catchments.geojson')['features'];cg=[geo(f) for f in cats];ct=STRtree(cg);rows=[]
    for f in read(ROOT/'outputs/statewide/field-candidates.geojson')['features']:
        g=geo(f);links=[]
        for j in ct.query(g,predicate='intersects'):
            frac=g.intersection(cg[j]).area/g.area if g.area else float(cg[j].covers(g))
            if frac>1e-8:
                cid=cats[j]['properties']['id3dhp'];links.append(dict(id3dhp=cid,fraction=frac,flowline_ids=catch.get(cid,[])))
        rows.append(dict(candidate_id=f['properties']['candidate_id'],catchments=links))
    save(O/'farm-3dhp-links.json',rows)
    save(O/'3dhp-summary.json',dict(flowlines=len(lines),waterbodies=len(bodies),catchments=len(cats),farms_with_catchment=sum(bool(r['catchments']) for r in rows),flowline_workunits=dict(Counter(f['properties'].get('workunitid') for f in lines)),note='NHD workunit indicates legacy-derived mapping, not a newly surveyed 3D watershed. Proximity links are not confirmed connectivity.'))
    log('Current 3DHP topology and separate farm/gauge associations saved.')
if __name__=='__main__':main()
