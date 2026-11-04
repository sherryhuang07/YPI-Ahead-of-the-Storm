"""Supplement missing gauge references using containing catchment and stream distance."""
import re
import pyogrio
from shapely import from_wkb,STRtree
from shapely.geometry import Point
from shapely.ops import transform
from pyproj import Transformer
from statewide_common import ROOT,read,save,log
D=ROOT/'data/regional-streamflow'
def ident(v):return str(int(v)) if isinstance(v,(int,float)) else str(v)
def norm(s):
    replacements={'r':'river','br':'branch','bk':'brook','w':'west','e':'east','n':'north','s':'south'}
    return ' '.join(replacements.get(w,w) for w in re.findall(r'[a-z]+',(s or '').lower()))
def main():
    net=read(D/'regional-network.json')['reaches'];missing={r['gauge_id'] for r in read(ROOT/'outputs/regional-streamflow/unresolved-gauges.json')}
    candidates=[g for g in read(D/'candidates.json') if g['gauge_id'] in missing];sources=[]
    for folder in sorted((ROOT/'data/hydrography/bulk').glob('*_GDB')):
        gdb=next(folder.rglob('*.gdb'));info=pyogrio.read_info(gdb,layer='NHDPlusCatchment')
        sources.append((gdb,info,Transformer.from_crs(4326,info['crs'],always_xy=True).transform,Transformer.from_crs(info['crs'],5070,always_xy=True).transform))
    matches=[];failed=[];all_found={g['gauge_id']:{} for g in candidates}
    for gdb,info,project,metric in sources:
        pending=[]
        log('Reading catchment index once for '+gdb.name)
        meta,table=pyogrio.read_arrow(gdb,layer='NHDPlusCatchment',columns=['nhdplusid'])
        polygons=from_wkb(table[meta['geometry_name']].to_numpy());ids=table['nhdplusid'].to_numpy();tree=STRtree(polygons)
        for g in candidates:
            x,y=project(*g['coordinates']);a,b,c,d=info['total_bounds']
            if not(a<=x<=c and b<=y<=d):continue
            pt=Point(x,y);metric_pt=transform(metric,pt)
            for j in tree.query(pt,predicate='covered_by'):
                rid=ident(float(ids[j]))
                if rid not in net:continue
                river=norm(net[rid].get('gnis_name'))
                if river and river in norm(g['name']):pending.append((g,rid,metric_pt))
        needed=sorted({rid for g,rid,pt in pending});geoms={}
        for i in range(0,len(needed),150):
            lm,lt=pyogrio.read_arrow(gdb,layer='NHDFlowline',columns=['nhdplusid'],where='nhdplusid IN ('+','.join(needed[i:i+150])+')')
            for line in lt.to_pylist():geoms[ident(line['nhdplusid'])]=transform(metric,from_wkb(line[lm['geometry_name']]))
        for g,rid,pt in pending:
            if rid not in geoms:continue
            distance=geoms[rid].distance(pt)
            if distance<=100:all_found[g['gauge_id']][rid]=dict(gauge_id=g['gauge_id'],hr_reach_id=rid,distance_m=distance,river_name=net[rid]['gnis_name'],method='Coordinate inside HR catchment; matching waterway name; stream within 100 m. Spatial association, not an official gauge reference.')
        log('Checked containing catchments and stream names in '+gdb.name)
    for g in candidates:
        found=all_found[g['gauge_id']]
        if len(found)==1:matches.append(next(iter(found.values())))
        else:failed.append(dict(gauge_id=g['gauge_id'],reason='No unique catchment/name/distance match',candidate_matches=list(found)))
    save(D/'supplemental-gauge-matches.json',matches);save(D/'unmatched-spatial-gauges.json',failed)
    log(f'Added {len(matches)} catchment-and-name-checked gauge associations; {len(failed)} remain unresolved by this method.')
if __name__=='__main__':main()
