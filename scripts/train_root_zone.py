"""Fit/select on 1980-2014 only, then seal holdout predictions before scoring.
Later values enter only as lagged inputs to later issue dates, never as targets
for fitting, model selection or interval calibration.
"""
import csv
import json
from datetime import date, datetime, timezone
import numpy as np
from fetch_root_zone_history import ROOT, digest
from root_zone_model import history_features, fit, predict

def main():
    policy_path=ROOT/'root-zone-policy.json';p=json.loads(policy_path.read_text())
    source=ROOT/'data/root-zone/prepared/history.npz'
    meta=json.loads(source.with_name('manifest.json').read_text())
    if digest(source)!=meta['history_sha256']: raise ValueError('History checksum mismatch')
    data=np.load(source);dates=data['dates'];ids=data['ids'];values=data['moisture']
    phases=np.array([2*np.pi*(date.fromisoformat(str(d)).timetuple().tm_yday-1)/365.2425 for d in dates])
    seasons=np.column_stack([np.sin(phases),np.cos(phases),np.sin(2*phases),np.cos(2*phases)])
    now=datetime.now(timezone.utc);stamp=now.strftime('%Y%m%dT%H%M%S%fZ')
    out=ROOT/'outputs/root-zone'/stamp;out.mkdir(parents=True,exist_ok=False)
    models={}; counts={}; exclusions=[]
    with (out/'sealed-hindcasts.csv').open('x',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['watershed_id','issue_date','latest_input_date','target_date',
            'horizon_days','prediction','persistence','lower','upper','method'])
        for column,sid in enumerate(ids):
            series=values[:,column];models[str(sid)]={}
            past=history_features(series,p['input_lag_days'])
            for h in p['horizons_days']:
                groups={'train':[],'calibration':[],'test':[]}
                for issue in range(33,len(dates)-h):
                    target=issue+h; day=str(dates[target])
                    group=('train' if day<=p['train_end'] else
                        'calibration' if p['calibration_start']<=day<=p['calibration_end'] and str(dates[issue])>p['train_end'] else
                        'test' if p['test_start']<=day<=p['test_end'] and str(dates[issue])>p['calibration_end'] else None)
                    if group is None:continue
                    if not np.all(np.isfinite(past[issue])):continue
                    x=np.concatenate([past[issue],seasons[target]])
                    if group!='test' and not np.isfinite(series[target]):continue
                    groups[group].append((issue,target,x))
                tr=groups['train'];cal=groups['calibration'];test=groups['test']
                if len(tr)<p['minimum_training_examples'] or len(cal)<p['minimum_calibration_examples']:
                    exclusions.append(dict(watershed_id=str(sid),horizon=h,reason='Insufficient complete examples'));continue
                model=fit(np.array([r[2] for r in tr]),np.array([series[r[1]] for r in tr]),p['ridge_penalty'])
                cx=np.array([r[2] for r in cal]);cy=np.array([series[r[1]] for r in cal])
                cp=predict(model,cx);base=cx[:,0]
                method='ridge' if np.mean(abs(cp-cy))<np.mean(abs(base-cy)) else 'persistence'
                selected=cp if method=='ridge' else base
                radius=float(np.quantile(abs(selected-cy),.9))
                models[str(sid)][str(h)]=dict(model=model,method=method,interval_radius=radius,
                    training_examples=len(tr),calibration_examples=len(cal),calibration_mae=float(np.mean(abs(selected-cy))))
                counts[str(h)]=counts.get(str(h),0)+len(test)
                if test:
                    tx=np.array([r[2] for r in test]);pred=predict(model,tx) if method=='ridge' else tx[:,0]
                    for (issue,target,x),v in zip(test,pred):
                        w.writerow([sid,dates[issue],dates[issue-p['input_lag_days']],dates[target],h,
                            float(v),float(x[0]),float(max(0,v-radius)),float(min(1,v+radius)),method])
            print('Trained and sealed historical predictions for '+str(sid),flush=True)
    (out/'model.json').write_text(json.dumps(models,indent=2),encoding='utf-8')
    (out/'policy.json').write_bytes(policy_path.read_bytes())
    record=dict(created_at=now.isoformat(),status='Historical model trained; live forecast withheld: recent inputs not connected.',
        experiment='Standalone root-zone moisture only; no drought score',source_sha256=digest(source),
        source_manifest_sha256=digest(source.with_name('manifest.json')),
        files={name:digest(out/name) for name in ['model.json','policy.json','sealed-hindcasts.csv']},
        predicted_cases_by_horizon=counts,excluded=exclusions,watersheds=len(ids),
        first_data_date=str(dates[0]),last_data_date=str(dates[-1]),
        evaluation_note=p['evaluation_note'],daily_period_note=p['daily_period_note'])
    (out/'manifest.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    (ROOT/'outputs/root-zone/latest.json').write_text(json.dumps(dict(run=stamp,**record),indent=2),encoding='utf-8')
    print('Sealed predictions. Run score_root_zone.py separately to inspect held-out outcomes.')

if __name__=='__main__': main()
