"""New, frozen challengers; never modifies the original forecast experiments."""
import json,hashlib,heapq,math
from collections import defaultdict,Counter
from datetime import date,timedelta,datetime,timezone
import numpy as np
from statewide_common import ROOT,read,save,log
from train_streamflow_history import fit,predict,flow

D=ROOT/'data/streamflow-experiments';O=ROOT/'outputs/streamflow-experiments'
START=date(2000,1,1);END=date(2026,11,2)
DATES=np.array([START+timedelta(days=i) for i in range((END-START).days+1)])
LEADS=np.arange(2,16);IX=np.arange(35,len(DATES)-15)
SHA=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def inventory():
    ct=[g for g in read(ROOT/'outputs/streamflow/gauges.json') if (ROOT/'data/streamflow/history'/(g['gauge_id']+'.json')).exists()]
    outside=read(ROOT/'outputs/regional-streamflow/relevant-gauges.json')
    return ct,{g['gauge_id']:g for g in ct+outside}

def load_history(g):
    q=np.full(len(DATES),np.nan)
    for f in read(ROOT/'data/streamflow/history'/(g['gauge_id']+'.json'))['features']:
        p=f['properties']
        if p.get('time_series_id')!=g['series_id'] or p.get('qualifier') or p.get('unit_of_measure')!='ft^3/s':continue
        i=(date.fromisoformat(p['time'][:10])-START).days
        try:v=float(p['value'])
        except (TypeError,ValueError):continue
        if 0<=i<len(q) and np.isfinite(v) and v>=0:q[i]=v
    return q

def features(q,indices,dates=DATES):
    z=np.log1p(q);cols=[z[indices-k] for k in [0,1,2,6,13,27]]
    cols += [np.mean(z[indices[:,None]-np.arange(k)],axis=1) for k in [7,14,28]]
    doy=np.array([dates[i].timetuple().tm_yday for i in indices])
    return np.column_stack(cols+[np.sin(2*np.pi*doy/365.25),np.cos(2*np.pi*doy/365.25)])

def augmented(own,donors,indices,lag,dates=DATES):
    cols=[features(own,indices,dates)]
    for q in donors:
        z=np.log1p(q);i=indices-lag
        cols.append(np.column_stack([z[i],z[i-1],np.mean(z[i[:,None]-np.arange(7)],axis=1)]))
    return np.column_stack(cols)

def masks(indices):
    end=DATES[indices+15];anchor=DATES[indices]
    return [end<date(2021,1,1),(anchor>=date(2021,1,1))&(end<date(2023,1,1))&(indices%14==0),(anchor>=date(2023,1,1))&(end<date(2024,1,1))&(indices%14==0),(anchor>=date(2024,1,1))&(indices%14==0)]

def serial(m):return {k:v.tolist() if isinstance(v,np.ndarray) else v for k,v in m.items()}
def thresholds(q):
    return {str(month):float(np.quantile(q[[i for i,d in enumerate(DATES) if d.year<=2020 and d.month==month and np.isfinite(q[i])]],.2)) for month in range(1,13)}

def metrics(actual,pred,threshold,low=None,high=None):
    obs=actual<threshold;warn=pred<threshold
    result=dict(mae_cfs=float(np.abs(actual-pred).mean()),week1_mae_cfs=float(np.abs(actual[:,:7]-pred[:,:7]).mean()),week2_mae_cfs=float(np.abs(actual[:,7:]-pred[:,7:]).mean()),low_flow_days=int(obs.sum()),missed_low_flow_days=int((obs&~warn).sum()),false_alarm_days=int((~obs&warn).sum()),predicted_low_flow_days=int(warn.sum()),low_flow_mae_cfs=float(np.abs(actual-pred)[obs].mean()) if obs.any() else None)
    if low is not None:result['interval_coverage']=float(((actual>=low)&(actual<=high)).mean())
    return result

def select_model(X,Y,ix):
    a,b,cal,test=masks(ix)
    if a.sum()<730 or min(b.sum(),cal.sum(),test.sum())<12:return None
    candidates={}
    for alpha in [1,10,100,1000]:
        m=fit(X[a],Y[a],alpha);candidates[alpha]=float(abs(flow(predict(m,X[b]))-flow(Y[b])).mean())
    alpha=min(candidates,key=candidates.get)
    cm=fit(X[DATES[ix+15]<date(2023,1,1)],Y[DATES[ix+15]<date(2023,1,1)],alpha)
    residual=abs(Y[cal]-predict(cm,X[cal]));rank=min(len(residual),math.ceil((len(residual)+1)*.9))
    width=np.sort(residual,axis=0)[rank-1]
    frozen=fit(X[DATES[ix+15]<date(2024,1,1)],Y[DATES[ix+15]<date(2024,1,1)],alpha)
    return dict(model=serial(frozen),alpha=alpha,selection_mae=candidates[alpha],width=width.tolist(),counts=[int(m.sum()) for m in [a,b,cal,test]])

def connections(ct,allgauges,hist):
    net=read(ROOT/'data/regional-streamflow/regional-network.json');up=defaultdict(list)
    for a,b in net['edges']:up[b].append(a)
    refs={g['gauge_id']:g['hr_reach_id'] for g in allgauges.values() if 'hr_reach_id' in g}
    for g in read(ROOT/'outputs/river-network/gauge-reach-candidates.json'):
        if len(g['official_hr_reaches'])==1:refs[g['gauge_id']]=g['official_hr_reaches'][0]
    byreach=defaultdict(list)
    for gid,rid in refs.items():
        if gid in hist and np.isfinite(hist[gid][DATES<date(2021,1,1)]).sum()>=800:byreach[rid].append(gid)
    result={}
    for g in ct:
        gid=g['gauge_id'];start=refs.get(gid);found=[];heap=[(0,start)] if start else [];seen=set()
        while heap:
            dist,node=heapq.heappop(heap)
            if node in seen:continue
            seen.add(node)
            if node!=start:
                for donor in byreach[node]:found.append(dict(gauge_id=donor,network_distance_km=dist))
            for n in up.get(node,[]):
                if n not in seen:heapq.heappush(heap,(dist+float(net['reaches'][n].get('lengthkm') or 0),n))
        found.sort(key=lambda r:(r['network_distance_km'],r['gauge_id']))
        # Include nearest external upstream station when available, chosen without target outcomes.
        chosen=found[:3];external=next((r for r in found if 'state' in allgauges[r['gauge_id']]),None)
        if external and external not in chosen:chosen=chosen[:2]+[external]
        result[gid]=dict(reach=start,all_upstream=found,selected=chosen)
    return result

def coverage(ct,gauges,hist,links):
    counts=Counter();unlinked=[]
    for f in read(ROOT/'outputs/river-network/farm-drainage-links.json'):
        for gid in f.get('downstream_gauges_via_hr_network',[]):counts[gid]+=1
        if not f.get('downstream_gauges_via_hr_network'):unlinked.append(dict(candidate_id=f['candidate_id'],town=f['town'],catchments=f['catchments']))
    outside=[]
    for r in read(ROOT/'outputs/regional-streamflow/trained/results.json'):
        if 'forecast' in r:continue
        gid=r['gauge_id'];q=hist[gid];reason=r['status'];recent='Recent 28-day' in reason
        outside.append(dict(gauge_id=gid,name=r['name'],reason=reason,clean_days=int(np.isfinite(q).sum()),missing_recent_dates=[str(DATES[i]) for i in range(len(q)-28,len(q)) if not np.isfinite(q[i])],category='Recent-input gap only' if recent and 'Fewer' not in reason else 'Historical coverage insufficient',action='Keep listed; automatically retry inputs daily under a separately frozen eligible model' if recent and 'Fewer' not in reason else 'Needs more independent history/calibration windows; do not lower requirements to manufacture skill',connected_ct_features=gauges[gid]['connected_ct_features']))
    priority=sorted([dict(gauge_id=g['gauge_id'],name=g['name'],candidate_fields_in_mapped_drainage=counts[g['gauge_id']],upstream_gauges=len(links[g['gauge_id']]['all_upstream']),official_reach=links[g['gauge_id']]['reach']) for g in ct],key=lambda r:-r['candidate_fields_in_mapped_drainage'])
    save(O/'coverage-audit.json',dict(regional_gaps=outside,priorities=priority,unlinked_candidate_fields=unlinked,unresolved_regional_gauges=read(ROOT/'outputs/regional-streamflow/unresolved-gauges.json'),note='Candidate fields and drainage relationships are not confirmed water supplies or withdrawal rights. Yale Farm is the only confirmed partner in this project; supply/intake location remains unknown.'))

def main():
    D.mkdir(parents=True,exist_ok=True);O.mkdir(parents=True,exist_ok=True)
    if (D/'model-v1.json').exists():raise SystemExit('Frozen experiment exists; use daily runner. New training requires a new version.')
    policy=dict(created_at=datetime.now(timezone.utc).isoformat(),historical_cutoff=str(END),training='Labels before 2021',selection='2021–2022',calibration='2023',testing='2024 through November 2 2026; no prospective outcomes',upstream_selection='At most three nearest directed upstream gauges, including nearest external gauge when present; no outcome-based geographic selection',lag_candidates=[0,1,3,7],ridge_candidates=[1,10,100,1000],low_flow='Below target monthly 20th percentile of clean 2000–2020 readings; not a legal or ecological threshold',policy='All eligible challengers retained regardless of retrospective performance. Historical records are latest downloaded revisions, not original-vintage hindcasts. Evaluation fortnights disjoint within gauge; gauges remain correlated.')
    if not (D/'preregistered-policy.json').exists():save(D/'preregistered-policy.json',policy)
    ct,gauges=inventory();hist={gid:load_history(g) for gid,g in gauges.items()};links=connections(ct,gauges,hist)
    save(O/'upstream-connections.json',links);coverage(ct,gauges,hist,links)
    own={};upstream={};results=[];skipped=[]
    # Own-gauge comparators trained without any held-out target outcomes.
    for gid,q in hist.items():
        X=features(q,IX);Y=np.log1p(q[IX[:,None]+LEADS]);ok=np.isfinite(X).all(1)&np.isfinite(Y).all(1)
        r=select_model(X[ok],Y[ok],IX[ok])
        if r:own[gid]=dict(r,gauge_id=gid,name=gauges[gid]['name'],monthly_low_threshold_cfs=thresholds(q))
    save(O/'own-model-eligibility.json',dict(eligible=list(own),unavailable=[gid for gid in gauges if gid not in own]))
    for g in ct:
        gid=g['gauge_id'];donors=[r['gauge_id'] for r in links[gid]['selected']]
        if gid not in own or not donors:skipped.append(dict(gauge_id=gid,reason='No eligible own-history comparator or verified upstream donor'));continue
        q=hist[gid];Y=np.log1p(q[IX[:,None]+LEADS]);sets={lag:augmented(q,[hist[d] for d in donors],IX,lag) for lag in [0,1,3,7]}
        ok=np.isfinite(Y).all(1)
        for X in sets.values():ok &= np.isfinite(X).all(1)
        ix=IX[ok];Y=Y[ok];options=[]
        for lag,X in sets.items():
            r=select_model(X[ok],Y,ix)
            if r:options.append(dict(r,lag=lag))
        if not options:skipped.append(dict(gauge_id=gid,reason='Too few shared complete training/selection/calibration/test windows',donors=donors));continue
        winner=min(options,key=lambda r:r['selection_mae']);lag=winner['lag'];test=masks(ix)[3];testix=ix[test]
        baseline=select_model(features(q,ix),Y,ix)
        z=predict(winner['model'],sets[lag][ok][test]);actual=flow(Y[test]);pred=flow(z);ownpred=flow(predict(baseline['model'],features(q,testix)))
        threshold=np.array([[own[gid]['monthly_low_threshold_cfs'][str(DATES[i+h].month)] for h in LEADS] for i in testix])
        width=np.array(winner['width']);pm=metrics(actual,pred,threshold,flow(z-width),flow(z+width));bm=metrics(actual,ownpred,threshold)
        record=dict(gauge_id=gid,name=g['name'],donors=donors,selected_lag_days=lag,test_fortnights=int(test.sum()),upstream=pm,own_history=bm,persistence=metrics(actual,np.repeat(q[testix,None],14,axis=1),threshold),mae_reduction_percent=100*(1-pm['mae_cfs']/bm['mae_cfs']) if bm['mae_cfs'] else None)
        results.append(record);upstream[gid]=dict(winner,gauge_id=gid,name=g['name'],donors=donors,monthly_low_threshold_cfs=own[gid]['monthly_low_threshold_cfs'],paired_own_model=baseline)
        log(g['name']+': upstream challenger compared on identical historical dates.')
    save(O/'upstream-results.json',results);save(O/'upstream-unavailable.json',skipped)
    # Strict leave-one-gauge-out transfer: donor selection uses geography/static basin descriptors only.
    attributes=read(D/'basin-attributes.json') if (D/'basin-attributes.json').exists() else {}
    ungauged=[]
    for target in ct:
        gid=target['gauge_id'];area=target.get('drainage_area_sq_miles')
        if not area:continue
        candidates=[]
        for donor,m in own.items():
            if donor==gid:continue
            g=gauges[donor];da=g.get('drainage_area_sq_miles')
            if not da or not .25<=area/da<=4:continue
            dx=(target['coordinates'][0]-g['coordinates'][0])*82;dy=(target['coordinates'][1]-g['coordinates'][1])*111;km=math.hypot(dx,dy)
            if km>150:continue
            score=km/100+abs(math.log(area/da));used=[]
            keys=['slope','forest_pct','clay_pct','developed_pct']
            if all(k in attributes.get(gid,{}) for k in keys) and not all(k in attributes.get(donor,{}) for k in keys):continue
            for key,scale in [('slope',10),('forest_pct',50),('clay_pct',30),('developed_pct',30)]:
                a=attributes.get(gid,{}).get(key);b=attributes.get(donor,{}).get(key)
                if a is not None and b is not None:score+=abs(a-b)/scale;used.append(key)
            candidates.append((score,donor,area/da,used))
        if not candidates:continue
        _,donor,ratio,used=min(candidates);q=hist[donor];X=features(q,IX);actual=hist[gid][IX[:,None]+LEADS]
        ok=(DATES[IX]>=date(2024,1,1))&(IX%14==0)&np.isfinite(X).all(1)&np.isfinite(actual).all(1)
        if ok.sum()<12:continue
        pred=flow(predict(own[donor]['model'],X[ok]))*ratio;obs=actual[ok]
        ungauged.append(dict(gauge_id=gid,name=target['name'],donor=donor,area_ratio=ratio,descriptor_fields_used=used,test_fortnights=int(ok.sum()),mae_cfs=float(abs(obs-pred).mean()),week1_mae_cfs=float(abs(obs[:,:7]-pred[:,:7]).mean()),week2_mae_cfs=float(abs(obs[:,7:]-pred[:,7:]).mean()),mean_observed_cfs=float(obs.mean()),normalized_mae=float(abs(obs-pred).mean()/obs.mean()) if obs.mean() else None,rule='Entire target history excluded from donor selection, training and calibration; target observations used only to evaluate. No deployment to ungauged waters.'))
    save(O/'withheld-gauge-results.json',ungauged)
    registry=dict(version='upstream-v1',created_at=datetime.now(timezone.utc).isoformat(),policy=policy,own=own,upstream=upstream,gauges=gauges,sources=[dict(path=str((ROOT/'data/streamflow/history'/(gid+'.json')).relative_to(ROOT)),sha256=SHA(ROOT/'data/streamflow/history'/(gid+'.json'))) for gid in gauges])
    registry['sources'].append(dict(path=str((D/'preregistered-policy.json').relative_to(ROOT)),sha256=SHA(D/'preregistered-policy.json')))
    if attributes:registry['sources'].append(dict(path=str((D/'basin-attributes.json').relative_to(ROOT)),sha256=SHA(D/'basin-attributes.json')))
    code=D/'training-code.py';code.write_bytes(__import__('pathlib').Path(__file__).read_bytes());registry['sources'].append(dict(path=str(code.relative_to(ROOT)),sha256=SHA(code)))
    with (D/'model-v1.json').open('x',encoding='utf-8') as f:json.dump(registry,f,allow_nan=False)
    save(O/'summary.json',dict(upstream_targets=len(upstream),historical_improvements=sum(r['upstream']['mae_cfs']<r['own_history']['mae_cfs'] for r in results),median_mae_reduction_percent=float(np.median([r['mae_reduction_percent'] for r in results])) if results else None,withheld_gauge_tests=len(ungauged),own_models=len(own),prospective_status='Not yet evaluated; daily runner must issue future-only predictions',limitations=['No weather inputs in upstream challenger','Static spatial transfer is a research test, not verified ungauged coverage','Historical revised records are not original-vintage forecasts','Dams, withdrawals and within-reach travel time remain unresolved']))
    print(read(O/'summary.json'))

if __name__=='__main__':main()
