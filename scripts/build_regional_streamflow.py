"""Trace regional HR topology to every mapped CT waterbody and waterway group."""
from collections import defaultdict,Counter
from pathlib import Path
import pyogrio
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.prepared import prep
from statewide_common import ROOT,read,save,log
D=ROOT/'data/regional-streamflow';O=ROOT/'outputs/regional-streamflow'
def ident(v):return str(int(v)) if isinstance(v,(int,float)) else str(v)
def graph():
    p=D/'regional-network.json'
    if p.exists():
        cached=read(p)
        if cached.get('policy_version')==2:return cached
    reaches={};edges=set();marine=set()
    for folder in sorted((ROOT/'data/hydrography/bulk').glob('*_GDB')):
        gdb=next(folder.rglob('*.gdb'))
        _,table=pyogrio.read_arrow(gdb,layer='NHDWaterbody',columns=['permanent_identifier','ftype'],read_geometry=False)
        marine.update(r['permanent_identifier'] for r in table.to_pylist() if r['ftype'] in [445,493])
        _,table=pyogrio.read_arrow(gdb,layer='NHDFlowline',columns=['nhdplusid','gnis_id','gnis_name','reachcode','wbarea_permanent_identifier','ftype','innetwork','lengthkm'],read_geometry=False)
        for r in table.to_pylist():
            if r['nhdplusid'] and r['innetwork']==1 and r['ftype']!=566:reaches[ident(r['nhdplusid'])]=r
        _,table=pyogrio.read_arrow(gdb,layer='NHDPlusFlow',columns=['fromnhdpid','tonhdpid','direction'],read_geometry=False)
        for r in table.to_pylist():
            if r['direction']==709 and r['fromnhdpid'] and r['tonhdpid']:edges.add((ident(r['fromnhdpid']),ident(r['tonhdpid'])))
        log('Loaded full upstream/downstream network for '+folder.name)
    reaches={k:v for k,v in reaches.items() if v['wbarea_permanent_identifier'] not in marine}
    edges=[list(e) for e in sorted(edges) if e[0] in reaches and e[1] in reaches and e[0]!=e[1]]
    data=dict(policy_version=2,reaches=reaches,edges=edges,marine_waterbody_ids=sorted(marine),note='Merged regional NHDPlusFlow tables, direction 709, nonzero endpoints; coastlines, estuaries and sea/ocean paths excluded from fluvial tracing.')
    save(p,data);return data

def main():
    net=graph();reaches=net['reaches'];down=defaultdict(list);up=defaultdict(list)
    for a,b in net['edges']:down[a].append(b);up[b].append(a)
    ct=prep(unary_union([shape(f['geometry']) for f in read(ROOT/'data/statewide/connecticut-mask.geojson')['features']]))
    bodies={};members=defaultdict(set);ct_reaches=set()
    for f in read(ROOT/'data/hydrography/hr-waterbodies.geojson')['features']:
        if not ct.intersects(shape(f['geometry'])):continue
        p=f['properties'];key='waterbody:'+p['permanent_identifier']
        bodies[key]=dict(id=key,name=p.get('gnis_name') or 'Unnamed mapped waterbody',kind='waterbody',gnis_id=p.get('gnis_id'),source_id=p['permanent_identifier'],outside_gauges=[])
    for rid,p in reaches.items():
        key='waterbody:'+str(p.get('wbarea_permanent_identifier'))
        if key in bodies:members[rid].add(key)
    for f in read(ROOT/'data/hydrography/hr-flowlines.geojson')['features']:
        p=f['properties'];rid=ident(p['nhdplusid'])
        if rid not in reaches or p['ftype'] not in [460,558] or not ct.intersects(shape(f['geometry'])):continue
        ct_reaches.add(rid);gnis=p.get('gnis_id');key='river:'+gnis if gnis else 'unnamed-reach:'+rid
        if key not in bodies:bodies[key]=dict(id=key,name=p.get('gnis_name') or 'Unnamed stream/network reach',kind='named_waterway' if gnis else 'unnamed_reach',gnis_id=gnis,source_id=gnis or rid,outside_gauges=[])
        members[rid].add(key)
    references=defaultdict(set)
    for f in read(D/'gauge-references.geojson')['features']:
        p=f['properties'];rid=ident(p.get('nhdplusid') or p.get('catchment'))
        if rid in reaches and p.get('reachcode')==reaches[rid].get('reachcode') and p.get('onnetwork')!=0:
            references['USGS-'+str(p['sourceid']).removeprefix('USGS-')].add(rid)
    supplemental={r['gauge_id']:r for r in read(D/'supplemental-gauge-matches.json')} if (D/'supplemental-gauge-matches.json').exists() else {}
    for gid,r in supplemental.items():
        if not references.get(gid) and r['hr_reach_id'] in reaches:references[gid].add(r['hr_reach_id'])
    grouped=defaultdict(list)
    for g in read(D/'candidates.json'):grouped[g['gauge_id']].append(g)
    relevant=[];unresolved=[]
    for gid,series in grouped.items():
        if len(series)!=1:unresolved.append(dict(gauge_id=gid,reason='Multiple recent primary daily series; not selected automatically'));continue
        g=series[0];refs=references.get(gid,set())
        if len(refs)!=1:unresolved.append(dict(gauge_id=gid,reason='No unique official HR catchment/reach reference in regional layer'));continue
        rid=next(iter(refs));relations=defaultdict(set)
        # Starting reach membership is approximate because gauge position within the reach matters.
        for key in members.get(rid,[]):relations[key].add('same mapped reach or waterbody; within-reach position matters')
        for adj,label in [(down,'upstream of Connecticut water feature'),(up,'downstream of Connecticut water feature')]:
            stack=list(adj.get(rid,[]));seen={rid}
            while stack:
                node=stack.pop()
                if node in seen:continue
                seen.add(node)
                for key in members.get(node,[]):relations[key].add(label)
                stack.extend(adj.get(node,[]))
        if not relations:continue
        method=supplemental[gid]['method'] if gid in supplemental else 'Official gauge catchment and reach-code reference'
        g=dict(g,hr_reach_id=rid,gnis_id=reaches[rid].get('gnis_id'),gnis_name=reaches[rid].get('gnis_name'),connected_ct_features=len(relations),association_method=method,connectivity='Directed regional HR network; no travel-time or reservoir routing model')
        relevant.append(g)
        for key,labels in relations.items():
            bodies[key]['outside_gauges'].append(dict(gauge_id=gid,state=g['state'],relationships=sorted(labels),same_named_waterway=bool(bodies[key]['gnis_id'] and bodies[key]['gnis_id']==g['gnis_id'])))
    for b in bodies.values():
        b['outside_gauges'].sort(key=lambda g:(not g['same_named_waterway'],g['state'],g['gauge_id']))
        b['coverage']='Connected neighboring-state gauge context available' if b['outside_gauges'] else 'No connected neighboring-state gauge established in this inventory'
    save(O/'water-feature-context.json',list(bodies.values()));save(O/'relevant-gauges.json',relevant);save(O/'unresolved-gauges.json',unresolved)
    save(O/'summary.json',dict(regional_reaches=len(reaches),regional_edges=len(net['edges']),ct_water_features=len(bodies),ct_named_waterways=sum(b['kind']=='named_waterway' for b in bodies.values()),ct_waterbody_polygons=sum(b['kind']=='waterbody' for b in bodies.values()),features_with_external_context=sum(bool(b['outside_gauges']) for b in bodies.values()),relevant_gauges=len(relevant),gauges_by_state=dict(Counter(g['state'] for g in relevant)),unresolved_recent_gauges=len(unresolved),scope='NY, MA, RI, plus connected VT/NH headwaters; public USGS daily discharge',limitations=['A network relationship is context, not a transferred discharge forecast.','Gauges without a unique official network reference remain unresolved.','No marine routing, tidal reversal, reservoir operations or travel-time prediction.','An absent outside-state gauge is a coverage result, not zero flow.']))
    log(f'Connected {len(relevant)} out-of-state gauges to Connecticut water features.')
if __name__=='__main__':main()
