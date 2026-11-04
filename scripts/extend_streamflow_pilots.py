"""Coverage-only extension for the three named pilots; original test results retained."""
from collections import defaultdict
from datetime import datetime,timezone
import heapq,json
import numpy as np
from shapely.geometry import shape,Point
from shapely import STRtree
from shapely.ops import transform
from pyproj import Transformer
import streamflow_experiments as e
from statewide_common import ROOT,read,save,log
from train_streamflow_history import predict,flow
from match_regional_gauges import norm

def main():
    path=e.D/'pilot-extension-v1.json'
    if path.exists():raise SystemExit('Pilot extension frozen; refusing to retrain')
    policy=dict(created_at=datetime.now(timezone.utc).isoformat(),reason='Three named pilots lacked joint-window coverage or a verified reach. Extension does not change the 15 original challenger results.',selection='Choose first geographically ranked single donor with sufficient pre-2024 training, selection and calibration coverage. No donor chosen by test-period accuracy. Lag and ridge selection use 2021–2022 only.',targets=['USGS-01189995','USGS-01200500','USGS-01184000'])
    save(e.D/'pilot-extension-policy.json',policy)
    reg=read(e.D/'model-v1.json');gauges=reg['gauges'];hist={gid:e.load_history(g) for gid,g in gauges.items()};net=read(ROOT/'data/regional-streamflow/regional-network.json');links=read(e.O/'upstream-connections.json')
    ctref=links['USGS-01184000']['reach'];association=None
    if not ctref:
        g=gauges['USGS-01184000'];pt=Point(g['coordinates']);catches=read(ROOT/'data/hydrography/hr-catchments.geojson')['features'];matches=[];project=Transformer.from_crs(4326,5070,always_xy=True).transform
        candidates={str(int(f['properties']['nhdplusid'])) for f in catches if shape(f['geometry']).covers(pt)}
        for f in read(ROOT/'data/hydrography/hr-flowlines.geojson')['features']:
            rid=str(int(f['properties']['nhdplusid']));name=f['properties'].get('gnis_name')
            if rid not in candidates or not name or norm(name) not in norm(g['name']):continue
            distance=transform(project,shape(f['geometry'])).distance(transform(project,pt))
            if distance<=100:matches.append(dict(reach=rid,distance_m=distance,method='Containing HR catchment, matching river name, stream within 100 m; spatial association needs field review'))
        if len(matches)==1:association=matches[0];ctref=association['reach']
    up=defaultdict(list)
    for a,b in net['edges']:up[b].append(a)
    refs={r['reach']:gid for gid,r in links.items() if r['reach']}
    refs.update({g['hr_reach_id']:gid for gid,g in gauges.items() if g.get('hr_reach_id')})
    artifacts={};results=[];unavailable=[]
    for gid in policy['targets']:
        target=gauges[gid];rid=ctref if gid=='USGS-01184000' else links[gid]['reach'];heap=[(0,rid)] if rid else [];seen=set();donors=[]
        while heap:
            dist,node=heapq.heappop(heap)
            if node in seen:continue
            seen.add(node)
            if node!=rid and node in refs and refs[node] in reg['own']:donors.append((dist,refs[node]))
            for n in up.get(node,[]):
                if n not in seen:heapq.heappush(heap,(dist+float(net['reaches'][n].get('lengthkm') or 0),n))
        q=hist[gid];rawY=np.log1p(q[e.IX[:,None]+e.LEADS]);chosen=None
        for dist,donor in sorted(donors):
            sets={lag:e.augmented(q,[hist[donor]],e.IX,lag) for lag in [0,1,3,7]};ok=np.isfinite(rawY).all(1)
            for X in sets.values():ok &= np.isfinite(X).all(1)
            ix=e.IX[ok];a,b,c,t=e.masks(ix)
            if a.sum()>=730 and min(b.sum(),c.sum())>=12:chosen=(donor,dist,sets,ok,ix,rawY[ok]);break
        if not chosen:unavailable.append(dict(gauge_id=gid,reason='No spatially verified upstream donor with enough pre-2024 common history',association=association if gid=='USGS-01184000' else None));continue
        donor,dist,sets,ok,ix,Y=chosen;options=[]
        for lag,X in sets.items():
            r=e.select_model(X[ok],Y,ix)
            if r:options.append(dict(r,lag=lag))
        if not options:unavailable.append(dict(gauge_id=gid,reason='Preselected donor lacks enough later test windows',donor=donor));continue
        m=min(options,key=lambda x:x['selection_mae']);control=e.select_model(e.features(q,ix),Y,ix);test=e.masks(ix)[3];ti=ix[test];z=predict(m['model'],sets[m['lag']][ok][test]);obs=flow(Y[test]);pred=flow(z);own=flow(predict(control['model'],e.features(q,ti)));threshold=np.array([[reg['own'][gid]['monthly_low_threshold_cfs'][str(e.DATES[i+h].month)] for h in e.LEADS] for i in ti]);w=np.array(m['width']);pm=e.metrics(obs,pred,threshold,flow(z-w),flow(z+w));bm=e.metrics(obs,own,threshold)
        result=dict(gauge_id=gid,name=target['name'],donors=[donor],selected_lag_days=m['lag'],test_fortnights=int(test.sum()),upstream=pm,own_history=bm,mae_reduction_percent=100*(1-pm['mae_cfs']/bm['mae_cfs']),extension=True,association=association if gid=='USGS-01184000' else 'Existing official HR match')
        results.append(result);artifacts[gid]=dict(m,gauge_id=gid,name=target['name'],donors=[donor],monthly_low_threshold_cfs=reg['own'][gid]['monthly_low_threshold_cfs'],paired_own_model=control,association=result['association'])
        log(target['name']+': single-donor coverage extension evaluated; original challenger results retained.')
    save(e.O/'pilot-extension-results.json',results);save(e.O/'pilot-extension-unavailable.json',unavailable)
    with path.open('x',encoding='utf-8') as f:json.dump(dict(policy=policy,parent_sha256=e.SHA(e.D/'model-v1.json'),upstream=artifacts,training_code_sha256=e.SHA(__import__('pathlib').Path(__file__))),f,allow_nan=False)
    (e.D/'pilot-extension-training-code.py').write_bytes(__import__('pathlib').Path(__file__).read_bytes())
    print([(r['name'],round(r['mae_reduction_percent'],2)) for r in results]);print(unavailable)
if __name__=='__main__':main()
