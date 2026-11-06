"""Causal predictors for a standalone 1-14 day root-zone moisture experiment."""
import numpy as np
from datetime import date

def features(series, issue_index, target_day, lag=6):
    last=issue_index-lag
    if last<27: return None
    window=series[last-27:last+1]
    if len(window)!=28 or not np.all(np.isfinite(window)): return None
    phase=2*np.pi*(date.fromisoformat(str(target_day)).timetuple().tm_yday-1)/365.2425
    return np.array([window[-1],np.mean(window[-7:]),np.mean(window),window[-1]-window[-8],
                     np.sin(phase),np.cos(phase),np.sin(2*phase),np.cos(2*phase)])

def fit(x,y,penalty=1.0):
    mean=x.mean(axis=0);scale=x.std(axis=0);scale[scale<1e-12]=1
    z=np.column_stack([np.ones(len(x)),(x-mean)/scale])
    regularizer=np.eye(z.shape[1])*penalty;regularizer[0,0]=0
    coef=np.linalg.solve(z.T@z+regularizer,z.T@y)
    return dict(mean=mean.tolist(),scale=scale.tolist(),coef=coef.tolist())

def predict(model,x):
    z=np.column_stack([np.ones(len(x)),(x-np.array(model['mean']))/np.array(model['scale'])])
    return np.clip(z@np.array(model['coef']),0,1)

def history_features(series, lag=6):
    """Four causal history features at each issue index; gaps stay NaN."""
    out=np.full((len(series),4),np.nan)
    windows=np.lib.stride_tricks.sliding_window_view(series,28)
    for issue in range(27+lag,len(series)):
        w=windows[issue-lag-27]
        if np.all(np.isfinite(w)):
            out[issue]=[w[-1],w[-7:].mean(),w.mean(),w[-1]-w[-8]]
    return out
