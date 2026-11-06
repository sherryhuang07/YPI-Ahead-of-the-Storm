"""Read held-out targets only after checking the sealed prediction hashes."""
import csv
import json
from collections import defaultdict
from datetime import date
import numpy as np
from fetch_root_zone_history import ROOT, digest

def main():
    latest=json.loads((ROOT/'outputs/root-zone/latest.json').read_text())
    out=ROOT/'outputs/root-zone'/latest['run']
    manifest=json.loads((out/'manifest.json').read_text())
    for name,sha in manifest['files'].items():
        if digest(out/name)!=sha: raise ValueError('Sealed artifact changed: '+name)
    source=ROOT/'data/root-zone/prepared/history.npz'
    if digest(source)!=manifest['source_sha256']: raise ValueError('Source changed since predictions')
    if (out/'scoreboard.json').exists():
        print((out/'scoreboard.json').read_text());return
    data=np.load(source);dates={str(d):i for i,d in enumerate(data['dates'])}
    ids={str(v):i for i,v in enumerate(data['ids'])};values=data['moisture']
    policy=json.loads((out/'policy.json').read_text());groups=defaultdict(list);missing=defaultdict(int)
    keys=set();targets=defaultdict(set);by_basin=defaultdict(list)
    with (out/'sealed-hindcasts.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            h=int(row['horizon_days']);issue=date.fromisoformat(row['issue_date']);target=date.fromisoformat(row['target_date'])
            last=date.fromisoformat(row['latest_input_date'])
            if (target-issue).days!=h or (issue-last).days!=policy['input_lag_days']:
                raise ValueError('Timing violation')
            key=(row['watershed_id'],str(issue),h)
            if key in keys: raise ValueError('Duplicate prediction')
            keys.add(key)
            y=values[dates[row['target_date']],ids[row['watershed_id']]]
            if not np.isfinite(y):missing[h]+=1;continue
            pred=float(row['prediction']);base=float(row['persistence'])
            error=pred-y
            groups[h].append((abs(error),error**2,abs(base-y),error,float(row['lower'])<=y<=float(row['upper'])))
            targets[h].add(str(target));by_basin[(row['watershed_id'],h)].append((abs(error),abs(base-y)))
    scores={}
    for h,rows in groups.items():
        a=np.array(rows);mae,rmse,baseline,bias,coverage=a.mean(axis=0)
        scores[str(h)]=dict(scored_cases=len(rows),completed_target_dates=len(targets[h]),missing_targets=missing[h],
            mae=float(mae),rmse=float(np.sqrt(rmse)),persistence_mae=float(baseline),bias=float(bias),
            skill_vs_persistence=float(1-mae/baseline) if baseline else None,interval_coverage=float(coverage))
    basin_scores=[dict(watershed_id=sid,horizon_days=h,mae=float(np.mean(a,axis=0)[0]),
                      persistence_mae=float(np.mean(a,axis=0)[1]),cases=len(a)) for (sid,h),a in by_basin.items()]
    report=dict(status='Historical holdout scored; farm accuracy and live forecast skill not established.',
        units='m3/m3',test_period=[policy['test_start'],policy['test_end']],by_horizon=scores,
        by_watershed=basin_scores,missing_targets_total=sum(missing.values()),
        prediction_sha256=digest(out/'sealed-hindcasts.csv'),
        note='Targets are NLDAS modeled moisture, not independent measurements. Correlated watersheds and overlapping windows are not independent tests.')
    with (out/'scoreboard.json').open('x',encoding='utf-8') as f: json.dump(report,f,indent=2)
    (ROOT/'outputs/root-zone/scoreboard.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='by_watershed'},indent=2))

if __name__=='__main__': main()
