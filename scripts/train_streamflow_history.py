"""Discharge-only direct 14-day forecasts, with chronological validation."""
import hashlib
from datetime import date,timedelta
import numpy as np
from statewide_common import ROOT,read,save,log

OUT=ROOT/'outputs/streamflow-trained'
START=date(2000,1,1);END=date(2026,11,2)
DATES=np.array([START+timedelta(days=i) for i in range((END-START).days+1)])
LEADS=np.arange(2,16) # Issue Nov 3; Nov 3 unavailable; targets Nov 4-17.

def matrix(q):
    z=np.log1p(q);indices=np.arange(28,len(q)-15)
    def row(i):
        a=[z[i-k] for k in [0,1,2,6,13,27]]
        a += [np.mean(z[i-k+1:i+1]) for k in [7,14,28]]
        day=DATES[i].timetuple().tm_yday
        return a+[np.sin(2*np.pi*day/365.25),np.cos(2*np.pi*day/365.25)]
    X=np.array([row(i) for i in indices]);Y=np.array([z[i+LEADS] for i in indices])
    ok=np.isfinite(X).all(axis=1)&np.isfinite(Y).all(axis=1)
    return indices[ok],X[ok],Y[ok],np.array(row(len(q)-1))

def fit(X,Y,alpha):
    mean=X.mean(0);scale=X.std(0);scale[scale<1e-8]=1
    a=np.column_stack([np.ones(len(X)),(X-mean)/scale]);pen=np.eye(a.shape[1])*alpha;pen[0,0]=0
    beta=np.linalg.solve(a.T@a+pen,a.T@Y)
    return dict(mean=mean,scale=scale,beta=beta)

def predict(model,X):return np.column_stack([np.ones(len(X)),(X-model['mean'])/model['scale']])@model['beta']
def flow(z):return np.expm1(np.clip(z,0,20))

def train(g):
    path=ROOT/'data/streamflow/history'/(g['gauge_id']+'.json')
    if not path.exists():return dict(gauge_id=g['gauge_id'],status='History download unavailable')
    q=np.full(len(DATES),np.nan);qualified=0
    for f in read(path)['features']:
        p=f['properties'];assert p['time_series_id']==g['series_id'] and p['unit_of_measure']=='ft^3/s'
        if p.get('qualifier'):qualified+=1;continue
        i=(date.fromisoformat(p['time'][:10])-START).days
        try:v=float(p['value'])
        except (ValueError,TypeError):continue
        if 0<=i<len(q) and np.isfinite(v) and v>=0:q[i]=v
    ix,X,Y,last=matrix(q);target_end=DATES[ix+15]
    masks=[target_end<date(2021,1,1),(DATES[ix]>=date(2021,1,1))&(target_end<date(2023,1,1)),(DATES[ix]>=date(2023,1,1))&(target_end<date(2024,1,1)),DATES[ix]>=date(2024,1,1)]
    # Disjoint evaluation fortnights; all training labels precede next period.
    masks[1:]=[m&(ix%14==0) for m in masks[1:]]
    base=dict(gauge_id=g['gauge_id'],name=g['name'],coordinates=g['coordinates'],unit='cubic feet per second',source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),usable_days=int(np.isfinite(q).sum()),excluded_qualified_days=qualified)
    reasons=[]
    if masks[0].sum()<730:reasons.append('Fewer than 730 clean training windows before 2021')
    for label,mask in zip(['2021–2022 selection','2023 uncertainty calibration','2024–2026 testing'],masks[1:]):
        if mask.sum()<12:reasons.append('Fewer than 12 complete fortnights for '+label)
    if not np.isfinite(last).all():reasons.append('Recent 28-day input window includes missing or qualified readings')
    if reasons:return dict(base,status='Forecast withheld: '+'; '.join(reasons),coverage_counts=[int(m.sum()) for m in masks])
    a,b,c,t=masks
    scores={};models={}
    scores['persistence']=float(np.mean(abs(flow(Y[b])-q[ix[b],None])))
    for alpha in [1,10,100,1000]:
        model=fit(X[a],Y[a],alpha);key=str(alpha);models[key]=model
        scores[key]=float(np.mean(abs(flow(predict(model,X[b]))-flow(Y[b]))))
    choice=min(scores,key=scores.get)
    def fitted_prediction(trainmask,testmask):
        if choice=='persistence':return np.repeat(np.log1p(q[ix[testmask],None]),14,axis=1)
        return predict(fit(X[trainmask],Y[trainmask],float(choice)),X[testmask])
    calibration=fitted_prediction(target_end<date(2023,1,1),c)
    errors=abs(Y[c]-calibration);n=len(errors);rank=min(n,int(np.ceil((n+1)*.9)))
    width=np.sort(errors,axis=0)[rank-1]
    test=fitted_prediction(target_end<date(2024,1,1),t)
    actual=flow(Y[t]);pred=flow(test);baseline=np.repeat(q[ix[t],None],14,axis=1)
    metrics=dict(test_start=str(DATES[ix[t][0]+2]),test_end=str(DATES[ix[t][-1]+15]),test_fortnights=int(t.sum()),mae_cfs=float(abs(actual-pred).mean()),persistence_mae_cfs=float(abs(actual-baseline).mean()),interval_coverage=float(((Y[t]>=test-width)&(Y[t]<=test+width)).mean()),per_lead_mae_cfs=abs(actual-pred).mean(0).tolist())
    if choice=='persistence':future=np.repeat(np.log1p(q[-1]),14);artifact=dict(method='persistence')
    else:
        model=fit(X,Y,float(choice));future=predict(model,last[None,:])[0]
        artifact={k:v.tolist() for k,v in model.items()};artifact.update(method='ridge_log_discharge',alpha=float(choice))
    forecasts=[dict(date=str(END+timedelta(days=int(h))),flow_cfs=float(flow(z)),lower_90_cfs=float(flow(z-w)),upper_90_cfs=float(flow(z+w))) for h,z,w in zip(LEADS,future,width)]
    result=dict(base,status='Experimental history-only forecast',issued='2026-11-03',last_observation='2026-11-02',selected_method=choice,tuning_mae_cfs=scores,metrics=metrics,forecast=forecasts,calibration_fortnights=n,model=artifact)
    save(OUT/'gauges'/(g['gauge_id']+'.json'),result)
    log(g['name']+': trained and tested on later years.')
    return result

def main():
    gauges=[g for g in read(ROOT/'outputs/streamflow/gauges.json') if g.get('age_days') is not None and g['age_days']<=7]
    results=[train(g) for g in gauges];good=[r for r in results if 'forecast' in r]
    save(OUT/'results.json',results)
    save(OUT/'summary.json',dict(issued='2026-11-03',requested_gauges=len(gauges),trained_gauges=len(good),beat_persistence=sum(r['metrics']['mae_cfs']<r['metrics']['persistence_mae_cfs'] for r in good),selected_persistence=sum(r['selected_method']=='persistence' for r in good),inputs='Only each gauge discharge history and calendar date; no precipitation or groundwater',training='2000–2020',selection='2021–2022',interval_calibration='2023',testing='2024–2026, fixed model trained through 2023',limitations=['No predictions for ungauged waters.','Intervals are empirical, daily and not simultaneous; temporal changes can reduce coverage.','Historical provisional observations are not reconstructed as they were known at each past issue date.','No future rainfall, dam releases or withdrawals included.']))

if __name__=='__main__':main()
