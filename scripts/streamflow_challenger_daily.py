"""Prospective upstream, paired-control, recovery and NOAA benchmarks; immutable issues."""
import argparse,math
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
import requests
import numpy as np
import prospective_daily as p
from statewide_common import ROOT,read,save,log
from fetch_regional_streamflow import fetch_pages,BASE
from streamflow_experiments import augmented,features
from train_streamflow_history import predict,flow
D=ROOT/'data/streamflow-experiments';O=ROOT/'outputs/streamflow-experiments'

def get_json(url):
    r=requests.get(url,timeout=45);r.raise_for_status();return r.json()

def nwps_metadata(g,folder):
    gid=g['gauge_id'];path=D/'nwps-metadata'/(gid+'.json')
    if path.exists():return gid,read(path),None
    try:
        data=get_json('https://api.water.noaa.gov/nwps/v1/gauges/'+gid.removeprefix('USGS-'))
        if data.get('usgsId')!=gid.removeprefix('USGS-'):raise ValueError('NOAA gauge ID does not match USGS target')
        save(path,data);return gid,data,None
    except Exception as e:return gid,None,str(e)

def daily_noaa(raw,dates,captured):
    """Integrate forecast samples only, never observations; refuse gaps or stale runs."""
    series=[s for s in raw.get('longRange',{}).values() if isinstance(s,dict) and s.get('data')]
    if not series:raise ValueError('NOAA returned no long-range forecast samples')
    latest=max(datetime.fromisoformat(s['referenceTime'].replace('Z','+00:00')) for s in series)
    now=datetime.fromisoformat(captured)
    if latest>now or now-latest>timedelta(hours=36):raise ValueError('NOAA issue is in the future or over 36 hours old')
    members=[]
    for s in series:
        if datetime.fromisoformat(s['referenceTime'].replace('Z','+00:00'))!=latest:continue
        factor={'cfs':1,'ft^3/s':1,'kcfs':1000,'cms':35.3146667,'m^3/s':35.3146667}.get(s.get('units','').lower())
        if factor is None:raise ValueError('Unsupported NOAA flow units: '+str(s.get('units')))
        points={datetime.fromisoformat(v['validTime'].replace('Z','+00:00')).timestamp():float(v['flow'])*factor for v in s['data'] if v.get('flow') is not None}
        x=np.array(sorted(points));y=np.array([points[k] for k in x])
        if not len(x) or not np.isfinite(y).all() or (y<0).any():continue
        vals=[]
        for day in dates:
            start=p.target_start('streamflow',day);end=p.target_start('streamflow',str(date.fromisoformat(day)+timedelta(days=1)))
            a=start.timestamp();b=end.timestamp()
            if x[0]>a or x[-1]<b:raise ValueError('NOAA series does not cover every full future local day')
            lo=max(0,int(np.searchsorted(x,a))-1);hi=min(len(x),int(np.searchsorted(x,b))+1)
            if np.diff(x[lo:hi]).max(initial=0)>6*3600:raise ValueError('NOAA forecast gap exceeds six hours')
            xs=np.r_[a,x[(x>a)&(x<b)],b];ys=np.interp(xs,x,y)
            vals.append(float(np.trapezoid(ys,xs)/(b-a)))
        members.append(vals)
    if not members:raise ValueError('No valid NOAA ensemble members')
    a=np.array(members)
    return a.mean(0).tolist(),dict(noaa_reference_time=latest.isoformat(),ensemble_members=len(a),ensemble_p10=np.quantile(a,.1,axis=0).tolist(),ensemble_p90=np.quantile(a,.9,axis=0).tolist(),aggregation='Linear integration of forecast samples into Connecticut local daily means; ensemble spread is not a calibrated confidence interval')

def water_rows(reg,snap,today):
    end=today-timedelta(days=1);days=[end-timedelta(days=89-i) for i in range(90)]
    dates=[str(today+timedelta(days=i)) for i in range(1,15)];values=snap['values']['streamflow'];rows={k:[] for k in ['upstream','paired-own','regional-recovery']};missing={k:[] for k in rows}
    original={g['gauge_id'] for g in read(ROOT/'data/regional-prospective/model-v1.json')['streamflow']}
    for gid,m in reg['upstream'].items():
        try:
            arrays={g:np.array([values.get(g,{}).get(str(d),np.nan) for d in days]) for g in [gid]+m['donors']}
            ownx=features(arrays[gid],np.array([89]),days)
            if not np.isfinite(ownx).all():raise ValueError('Target recent inputs incomplete')
            thresholds=[m['monthly_low_threshold_cfs'][str(date.fromisoformat(d).month)] for d in dates]
            common=dict(id=gid,name=m['name'],dates=dates,baseline=[float(arrays[gid][-1])]*14,source_last_day=str(end),units='cfs',low_threshold_cfs=thresholds)
            for key,model,x in [('paired-own',m['paired_own_model'],ownx),('upstream',m,augmented(arrays[gid],[arrays[g] for g in m['donors']],np.array([89]),m['lag'],days))]:
                if not np.isfinite(x).all():missing[key].append(dict(id=gid,reason='Required upstream input missing or qualified'));continue
                z=predict(model['model'],x)[0];width=np.array(model['width'])
                rows[key].append(dict(common,prediction=flow(z).tolist(),lower_90_cfs=flow(z-width).tolist(),upper_90_cfs=flow(z+width).tolist(),upstream_gauges=m['donors'] if key=='upstream' else [],lag_days=m['lag'] if key=='upstream' else None))
        except ValueError as e:
            for key in ['paired-own','upstream']:missing[key].append(dict(id=gid,reason=str(e)))
    for gid,m in reg['own'].items():
        if gid in original or 'state' not in reg['gauges'][gid]:continue
        q=np.array([values.get(gid,{}).get(str(d),np.nan) for d in days]);x=features(q,np.array([89]),days)
        if not np.isfinite(x).all():missing['regional-recovery'].append(dict(id=gid,reason='Recent own-gauge inputs still incomplete'));continue
        z=predict(m['model'],x)[0];w=np.array(m['width'])
        rows['regional-recovery'].append(dict(id=gid,name=m['name'],dates=dates,prediction=flow(z).tolist(),baseline=[float(q[-1])]*14,source_last_day=str(end),units='cfs',lower_90_cfs=flow(z-w).tolist(),upper_90_cfs=flow(z+w).tolist(),low_threshold_cfs=[m['monthly_low_threshold_cfs'][str(date.fromisoformat(d).month)] for d in dates]))
    return rows,missing

def report_scores(c,key):
    groups={};pending=0;missing=0;completed=set();bydate={};now=p.utc()
    for path,sha in c.execute('SELECT path,sha256 FROM forecasts'):
        record=read(ROOT/path)
        for r in record['forecasts']:
            for i,day in enumerate(r['dates']):
                end=p.target_start('streamflow',str(date.fromisoformat(day)+timedelta(days=1)))
                if end<=now:completed.add(day)
                actual=c.execute('SELECT value FROM observations WHERE variable=? AND location=? AND day=?',('streamflow',r['id'],day)).fetchone()
                if not actual:
                    if p.target_start('streamflow',day)+timedelta(days=2)<=now:missing+=1
                    else:pending+=1
                    continue
                label=(r['id'],1 if i<7 else 2);g=groups.setdefault(label,dict(gauge_id=r['id'],week=label[1],comparisons=0,absolute_error_sum=0,baseline_error_sum=0,low_flow_days=0,missed_low_flow_days=0,false_alarm_days=0,interval_hits=0,interval_tests=0))
                y=actual[0];pred=r['prediction'][i];g['comparisons']+=1;g['absolute_error_sum']+=abs(y-pred);g['baseline_error_sum']+=abs(y-r['baseline'][i])
                if 'low_threshold_cfs' in r:
                    low=y<r['low_threshold_cfs'][i];warn=pred<r['low_threshold_cfs'][i];g['low_flow_days']+=int(low);g['missed_low_flow_days']+=int(low and not warn);g['false_alarm_days']+=int(warn and not low)
                if 'lower_90_cfs' in r:g['interval_tests']+=1;g['interval_hits']+=int(r['lower_90_cfs'][i]<=y<=r['upper_90_cfs'][i])
    for g in groups.values():g['mae_cfs']=g.pop('absolute_error_sum')/g['comparisons'];g['persistence_mae_cfs']=g.pop('baseline_error_sum')/g['comparisons']
    result=dict(model=key,completed_target_dates=len(completed),pending_comparisons=pending,missing_due_observations=missing,by_gauge_and_week=list(groups.values()),note='Overlapping windows and connected gauges are correlated; counts are not independent trials.')
    save(p.O/'detailed-scoreboard.json',result);return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    reg=read(D/'model-v1.json');today=p.utc().astimezone(p.LOCAL).date();end=today-timedelta(days=1)
    folder=D/'daily'/p.stamp();folder.mkdir(parents=True);errors=[]
    if args.offline:
        paths=[ROOT/read(ROOT/'outputs'/r/'last-run.json')['snapshot'] for r in ['prospective','regional-prospective']]
        snaps=[read(path) for path in paths];values={}
        for s in snaps:values.update(s['values']['streamflow'])
        captured=max(s['captured_at'] for s in snaps)
        if any(datetime.fromisoformat(s['captured_at']).astimezone(p.LOCAL).date()!=today for s in snaps):raise ValueError('Offline inputs must have been captured today')
    else:
        raw=fetch_pages(BASE+'daily/items',dict(f='json',bbox='-76,40,-69,46',parameter_code='00060',statistic_id='00003',datetime=f'{end-timedelta(days=89)}/{end}',limit=10000));p.exclusive(folder/'usgs-raw.json',raw)
        values={gid:p.clean(raw['features'],g['series_id'],'00060','ft^3/s') for gid,g in reg['gauges'].items()};captured=p.utc().isoformat()
    values={gid:{d:v for d,v in h.items() if d<=str(end)} for gid,h in values.items()}
    snap=dict(captured_at=captured,values=dict(streamflow=values,groundwater={}),grids={},errors=errors)
    snapshot=folder/'inputs.json';p.exclusive(snapshot,snap);rows,missing=water_rows(reg,snap,today)
    dates=[str(today+timedelta(days=i)) for i in range(1,15)];rows['noaa-long-range']=[];missing['noaa-long-range']=[]
    targets=[g for gid,g in reg['gauges'].items() if 'state' not in g]
    if not args.offline:
        def noaa(g):
            gid,meta,error=nwps_metadata(g,folder)
            if error:return None,dict(id=gid,reason='NOAA metadata unavailable: '+error)
            try:
                rid=meta.get('reachId')
                if not rid:raise ValueError('NOAA has no gauge-to-model reach match')
                raw=get_json(f'https://api.water.noaa.gov/nwps/v1/reaches/{rid}/streamflow?series=long_range');p.exclusive(folder/(gid+'-noaa.json'),raw)
                pred,extra=daily_noaa(raw,dates,p.utc().isoformat());h=values.get(gid,{})
                if str(end) not in h:raise ValueError('No clean yesterday reading for a paired persistence comparison')
                row=dict(id=gid,name=g['name'],dates=dates,prediction=pred,baseline=[h[str(end)]]*14,source_last_day=str(end),units='cfs',noaa_reach_id=rid,**extra)
                if gid in reg['own']:row['low_threshold_cfs']=[reg['own'][gid]['monthly_low_threshold_cfs'][str(date.fromisoformat(d).month)] for d in dates]
                return row,None
            except Exception as e:return None,dict(id=gid,reason=str(e))
        with ThreadPoolExecutor(max_workers=3) as pool:
            for row,miss in pool.map(noaa,targets):
                if row:rows['noaa-long-range'].append(row)
                if miss:missing['noaa-long-range'].append(miss)
    else:missing['noaa-long-range']=[dict(id=g['gauge_id'],reason='Offline run: NOAA not requested') for g in targets]
    noaa_captured=p.utc().isoformat();reports={};code=folder/'daily-runner.py';code.write_bytes(Path(__file__).read_bytes())
    sources=[dict(path=str(code.relative_to(ROOT)),sha256=p.digest(code))]
    sources.extend(dict(path=str(f.relative_to(ROOT)),sha256=p.digest(f)) for f in folder.glob('*-noaa.json'))
    for key in rows:
        # Offline evaluation must not occupy the daily NOAA issuance slot.
        if args.offline and key=='noaa-long-range':continue
        p.D=ROOT/'data/challenger-prospective'/key;p.O=ROOT/'outputs/challenger-prospective'/key;p.O.mkdir(parents=True,exist_ok=True);c=p.db();p.verify(c)
        model=p.D/'model-v1.json'
        if not model.exists():p.exclusive(model,dict(version=key+'-v1',registry_path=str((D/'model-v1.json').relative_to(ROOT)),registry_sha256=p.digest(D/'model-v1.json'),policy='Frozen challenger, no tuning from prospective scores'))
        if read(model)['registry_sha256']!=p.digest(D/'model-v1.json'):raise ValueError('Challenger training registry changed')
        ss=snap;sp=snapshot
        if key=='noaa-long-range':ss=dict(snap,captured_at=noaa_captured);sp=folder/'noaa-inputs.json';p.exclusive(sp,ss)
        p.seal(c,'streamflow',rows[key],missing[key],sp,ss,model,model_version=key+'-v1',extra_sources=sources+[dict(path=str((D/'model-v1.json').relative_to(ROOT)),sha256=p.digest(D/'model-v1.json'))])
        p.record_observations(c,snap,snapshot,{});p.score(c);reports[key]=dict(available=len(rows[key]),unavailable=missing[key],scores=report_scores(c,key))
    save(O/'daily-check.json',dict(completed_at=p.utc().isoformat(),input_snapshot=str(snapshot.relative_to(ROOT)),offline=args.offline,models=reports))
    log('Streamflow challenger check: '+', '.join(k+' '+str(v['available'])+' available' for k,v in reports.items())+'. Original forecasts retained.')
    print({k:dict(available=v['available'],unavailable=len(v['unavailable'])) for k,v in reports.items()})

if __name__=='__main__':main()
