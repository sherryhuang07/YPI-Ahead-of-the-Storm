"""Spatial crosswalks retain source identity and distinguish proximity from drainage."""
from shapely.geometry import shape,Point
from shapely.ops import transform,unary_union
from shapely import STRtree,make_valid
from pyproj import Transformer
from statewide_common import ROOT,read,save,log

D=ROOT/'data/hydrography';O=ROOT/'outputs/river-network'
project=Transformer.from_crs(4326,5070,always_xy=True).transform
def geom(f):return transform(project,make_valid(shape(f['geometry'])))
def ident(v):return str(int(v)) if isinstance(v,(int,float)) and float(v).is_integer() else str(v)
def load(name):
    p=D/(name+'.geojson');return read(p)['features'] if p.exists() else []
def main():
    farms=read(ROOT/'outputs/statewide/field-candidates.geojson')['features']
    basins=[];bg=[];basin_methods=[];basin_quality=[]
    gauge_inventory={g['gauge_id']:g for g in read(ROOT/'outputs/streamflow/gauges.json')}
    for p in sorted((D/'nldi').glob('*-basin.geojson')):
        refined=D/'nldi-split'/p.name
        fs=read(refined if refined.exists() else p)['features']
        if not fs:continue
        gid=p.name.replace('-basin.geojson','');g=unary_union([geom(f) for f in fs])
        published=gauge_inventory[gid].get('drainage_area_sq_miles')
        mismatch=abs(g.area/2589988.11/published-1) if published else None
        basins.append(gid);bg.append(g);basin_methods.append('Split at gauge position' if refined.exists() else 'Whole local catchment: may include land downstream of gauge')
        basin_quality.append('Review: differs from published gauge drainage area by over 25%' if mismatch is not None and mismatch>.25 else 'No large area discrepancy detected; boundary remains approximate')
    bt=STRtree(bg)
    catches=load('hr-catchments');cg=[geom(f) for f in catches];ct=STRtree(cg)
    lines=load('hr-flowlines');lg=[geom(f) for f in lines];lt=STRtree(lg);line_ids={ident(f['properties']['nhdplusid']) for f in lines}
    rows=[]
    for f in farms:
        g=geom(f);basinlinks=[];catchlinks=[]
        for j in bt.query(g,predicate='intersects'):
            frac=g.intersection(bg[j]).area/g.area if g.area else float(bg[j].covers(g))
            if frac>1e-8:basinlinks.append(dict(gauge_id=basins[j],fraction=frac,basin_method=basin_methods[j],quality=basin_quality[j],relationship='Mapped drainage association, subject to outlet and boundary accuracy; not a water-access entitlement'))
        for j in ct.query(g,predicate='intersects'):
            frac=g.intersection(cg[j]).area/g.area if g.area else float(cg[j].covers(g))
            if frac>1e-8:
                cid=ident(catches[j]['properties']['nhdplusid'])
                catchlinks.append(dict(nhdplusid=cid,fraction=frac,source_feature_class=catches[j]['properties'].get('sourcefc'),has_downloaded_network_reach=cid in line_ids))
        rows.append(dict(candidate_id=f['properties']['candidate_id'],town=f['properties'].get('town'),watershed_ids=f['properties'].get('watershed_ids',[]),upstream_of_gauges=basinlinks,catchments=catchlinks))
    save(O/'farm-drainage-links.json',rows)
    # Directed HR topology, not an ID join to the different NLDI V2 network.
    hs={str(f['properties']['hydroseq']):str(f['properties']['nhdplusid']) for f in lines}
    edges=[];water={}
    for f in lines:
        p=f['properties'];rid=str(p['nhdplusid']);down=[];outside=[]
        for key in ['dnhydroseq','dnminorhyd']:
            h=str(p.get(key,0))
            if h in hs and hs[h]!=rid:down.append(hs[h])
            elif p.get(key,0):outside.append(h)
        edges.append(dict(nhdplusid=rid,downstream=list(set(down)),outside_download_hydroseq=outside,waterbody_id=p.get('wbarea_permanent_identifier')))
        if p.get('wbarea_permanent_identifier'):water.setdefault(p['wbarea_permanent_identifier'],[]).append(rid)
    save(O/'directed-reaches.json',edges)
    bodies=[];edgeby={e['nhdplusid']:e for e in edges};upstream={}
    for e in edges:
        for down in e['downstream']:upstream.setdefault(down,[]).append(e['nhdplusid'])
    for f in load('hr-waterbodies'):
        p=f['properties'];wid=p['permanent_identifier'];members=set(water.get(wid,[]))
        outlets=[rid for rid in members if any(n not in members for n in edgeby[rid]['downstream']) or edgeby[rid]['outside_download_hydroseq']]
        inlets=sorted({u for rid in members for u in upstream.get(rid,[]) if u not in members})
        bodies.append(dict(waterbody_id=wid,name=p.get('gnis_name'),flowline_ids=sorted(members),candidate_inlet_reaches=inlets,candidate_outlet_reaches=outlets,forecast=None,reason='No individually trained outlet discharge record linked; lake level is not streamflow'))
    save(O/'waterbody-links.json',bodies)
    dams=[]
    for f in load('public-dams'):
        if not f.get('geometry'):continue
        g=geom(f);j=int(lt.nearest(g)) if lines else None;dist=g.distance(lg[j]) if j is not None else None
        dams.append(dict(properties=f['properties'],nearest_reach=str(lines[j]['properties']['nhdplusid']) if j is not None else None,distance_m=dist,relationship='Proximity only; operating rules and hydraulic connection unverified'))
    save(O/'dam-reach-links.json',dams)
    gauges=[];official={};line_props={ident(f['properties']['nhdplusid']):f['properties'] for f in lines}
    for f in load('hr-gauges'):
        p=f['properties'];sid=str(p.get('sourceid','')).removeprefix('USGS-')
        rid=ident(p.get('nhdplusid') or p.get('catchment'))
        if p.get('onnetwork')!=0 and rid in edgeby and p.get('reachcode')==line_props[rid].get('reachcode'):
            official.setdefault('USGS-'+sid,set()).add(rid)
    for g in read(ROOT/'outputs/streamflow/gauges.json'):
        if g['gauge_id'] not in basins:continue
        pt=transform(project,Point(g['coordinates']));j=int(lt.nearest(pt)) if lines else None
        official_ids=sorted(official.get(g['gauge_id'],[]))
        gauges.append(dict(gauge_id=g['gauge_id'],official_hr_reaches=official_ids,nearest_hr_reach=str(lines[j]['properties']['nhdplusid']) if j is not None else None,distance_m=pt.distance(lg[j]) if j is not None else None,relationship='Official HR catchment and matching reach-code reference; within-reach gauge position still matters' if official_ids else 'Geometric candidate only; NLDI basin mapping retained separately'))
    save(O/'gauge-reach-candidates.json',gauges)
    downstream_gauges={}
    for gauge in gauges:
        if len(gauge['official_hr_reaches'])!=1:continue
        stack=list(gauge['official_hr_reaches']);visited=set()
        while stack:
            rid=stack.pop()
            if rid in visited:continue
            visited.add(rid);downstream_gauges.setdefault(rid,[]).append(gauge['gauge_id'])
            stack.extend(upstream.get(rid,[]))
    for row in rows:
        row['downstream_gauges_via_hr_network']=sorted({g for c in row['catchments'] for g in downstream_gauges.get(c['nhdplusid'],[])})
    save(O/'farm-drainage-links.json',rows)
    comparisons=[]
    for p in (D/'streamstats').glob('USGS-*.json'):
        v=read(p);parts=[]
        for group in v.get('bcrequest',{}).get('wsresp',{}).get('featurecollection',[]):
            for item in group:
                if item.get('name')=='globalwatershed':
                    parts += [geom(f) for f in item['feature']['features'] if f.get('properties',{}).get('GlobalWshd',f.get('properties',{}).get('globalWshd'))==1]
        if parts and p.stem in basins:
            a=unary_union(parts);b=bg[basins.index(p.stem)]
            overlap=a.intersection(b).area/a.union(b).area
            comparisons.append(dict(gauge_id=p.stem,streamstats_area_sq_km=a.area/1e6,nldi_area_sq_km=b.area/1e6,intersection_over_union=overlap,status='Review required: outlet placement or delineation discrepancy' if overlap<.8 else 'Broad agreement; not field validated',used_for_farm_links=False))
    save(O/'drainage-boundary-comparison.json',comparisons)
    save(O/'summary.json',dict(farms=len(rows),farms_in_monitored_basins=sum(bool(r['upstream_of_gauges']) for r in rows),farms_with_hr_catchment=sum(bool(r['catchments']) for r in rows),gauge_basins=len(basins),flowlines=len(lines),catchments=len(catches),waterbodies=len(bodies),public_dams=len(dams),limitations=['Farm boundaries are candidates, not verified farm parcels.','HR network is bounded to Connecticut plus a border buffer; NLDI gauge basins extend outside Connecticut.','NLDI V2 COMIDs and NHDPlus HR IDs are distinct.','Public CT dam layer excludes public water-supply dams.','Ungauged water bodies have no trained forecast.']))
    log('Farm, gauge, catchment, waterbody and dam crosswalks saved.')

if __name__=='__main__':main()
