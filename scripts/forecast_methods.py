"""Small univariate baselines. No weather/soil/other-variable predictors."""
import numpy as np

HORIZON=14
METHODS=('persistence','damped_trend','autoregression')

def predict(history,method,kind,horizon=HORIZON):
 x=np.asarray(history,dtype=float)
 if len(x)<14 or not np.isfinite(x[-1]):raise ValueError('Latest observation or history unavailable')
 if kind=='streamflow' and np.any(x[np.isfinite(x)]<0):raise ValueError('Signed reverse-flow series needs a separate model')
 z=np.log1p(x) if kind=='streamflow' else x.copy()
 if method=='persistence':future=np.repeat(z[-1],horizon)
 elif method=='damped_trend':
  y=z[-14:];t=np.arange(len(y));ok=np.isfinite(y)
  if ok.sum()<10:raise ValueError('Insufficient recent measurements')
  slope=np.polyfit(t[ok],y[ok],1)[0]
  future=z[-1]+slope*np.cumsum(.8**np.arange(1,horizon+1))
 elif method=='autoregression':
  y=z[-42:];a,b=y[:-1],y[1:];ok=np.isfinite(a)&np.isfinite(b);a,b=a[ok],b[ok]
  if len(a)<25:raise ValueError('Insufficient consecutive pairs')
  phi=float(np.clip(np.dot(a-a.mean(),b-b.mean())/np.dot(a-a.mean(),a-a.mean()),0,.98)) if np.var(a)>1e-12 else 0.
  intercept=b.mean()-phi*a.mean();future=[];v=z[-1]
  for _ in range(horizon):v=intercept+phi*v;future.append(v)
  future=np.array(future)
 else:raise ValueError('Unknown method')
 return np.maximum(np.expm1(future),0) if kind=='streamflow' else future

def fit_and_test(history,kind):
 x=np.asarray(history,dtype=float)
 if len(x)!=90 or np.isfinite(x).sum()<70:return dict(status='unavailable',reason='At least 70 daily observations in the 90-day window are required.')
 if not np.isfinite(x[-1]):return dict(status='unavailable',reason='No observation on the forecast cutoff date.')
 scores={}
 for method in METHODS:
  errors=[]
  try:
   for origin in (42,56):
    forecast=predict(x[:origin],method,kind,horizon=15)[1:];actual=x[origin+1:origin+15];valid=np.isfinite(actual)
    if valid.sum()<12:raise ValueError('Insufficient tuning observations')
    errors.extend(abs(forecast[valid]-actual[valid]).tolist())
   scores[method]=float(np.mean(errors))
  except ValueError:continue
 if not scores:return dict(status='unavailable',reason='Insufficient clean daily history for the declared models.')
 method=min(scores,key=scores.get)
 try:
  heldout=predict(x[:75],method,kind,horizon=15)[1:];benchmark=predict(x[:75],'persistence',kind,horizon=15)[1:];actual=x[76:90];valid=np.isfinite(actual)
  if valid.sum()<12:raise ValueError('Fewer than 12 held-out observations')
  prediction=predict(x,method,kind,horizon=15)[1:]
 except ValueError as e:return dict(status='unavailable',reason=str(e))
 mae=float(np.mean(abs(heldout[valid]-actual[valid])));base=float(np.mean(abs(benchmark[valid]-actual[valid])))
 return dict(status='experimental',method=method,daily_prediction=prediction.tolist(),tuning_mae=scores,
  heldout=dict(origin_index=75,unobserved_gap_days=1,days_scored=int(valid.sum()),mae=mae,persistence_mae=base,beats_persistence=mae<base,
   prediction=heldout.tolist(),observed=[float(v) if np.isfinite(v) else None for v in actual]),
  uncertainty_interval=None,uncertainty_note='No calibrated prediction interval: only one held-out fortnight is available. Test error is not a confidence interval.')
