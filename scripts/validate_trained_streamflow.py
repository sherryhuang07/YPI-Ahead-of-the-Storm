import numpy as np
from datetime import date
from statewide_common import ROOT,read
from train_streamflow_history import matrix,fit,predict,DATES

results=read(ROOT/'outputs/streamflow-trained/results.json')
assert len(results)==69
for r in results:
    if 'forecast' not in r:continue
    assert len(r['forecast'])==14
    assert r['forecast'][0]['date']=='2026-11-04' and r['forecast'][-1]['date']=='2026-11-17'
    for d in r['forecast']:assert 0<=d['lower_90_cfs']<=d['flow_cfs']<=d['upper_90_cfs']
    assert r['metrics']['test_start']>='2024-01-01'
    assert 0<=r['metrics']['interval_coverage']<=1
# Perturb future observations: all pre-2021 training features/targets/weights must remain identical.
q=20+np.sin(np.arange(len(DATES))/11)
i,x,y,_=matrix(q);m=DATES[i+15]<date(2021,1,1);a=fit(x[m],y[m],10)
q[DATES>=date(2021,1,1)]=9999
j,xx,yy,_=matrix(q);n=DATES[j+15]<date(2021,1,1);b=fit(xx[n],yy[n],10)
assert np.array_equal(x[m],xx[n]) and np.array_equal(y[m],yy[n])
assert np.allclose(a['beta'],b['beta'])
print('PASS: forecast dates, nonnegative ordered ranges, test periods, and future-data leakage check.')
