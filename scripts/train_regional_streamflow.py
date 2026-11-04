"""New neighboring-gauge experiment; never alters the sealed Connecticut models."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import numpy as np
import train_streamflow_history as model
from statewide_common import ROOT,read,save,log
def main():
    today=datetime.now(ZoneInfo('America/New_York')).date();model.END=today-timedelta(days=1)
    model.DATES=np.array([model.START+timedelta(days=i) for i in range((model.END-model.START).days+1)])
    model.OUT=ROOT/'outputs/regional-streamflow/trained';registry=ROOT/'data/regional-prospective/model-v1.json'
    if registry.exists():raise RuntimeError('Regional model registry already frozen; do not overwrite it')
    gauges=read(ROOT/'outputs/regional-streamflow/relevant-gauges.json');results=[]
    for g in gauges:
        r=model.train(g);r.update(series_id=g['series_id'],state=g['state'],hr_reach_id=g['hr_reach_id'],issued=str(today),last_observation=str(model.END),model_version='regional-v1')
        results.append(r)
        if 'forecast' in r:save(model.OUT/'gauges'/(g['gauge_id']+'.json'),r)
    good=[r for r in results if 'forecast' in r]
    save(model.OUT/'results.json',results)
    save(model.OUT/'summary.json',dict(issued=str(today),gauges_examined=len(results),trained=len(good),beat_persistence=sum(r['metrics']['mae_cfs']<r['metrics']['persistence_mae_cfs'] for r in good),input_variables=['streamflow'],purpose='Context at connected out-of-state gauges; not a routed prediction at Connecticut waterbodies',evaluation='Selection 2021–2022, calibration 2023, retrospective test 2024 onward; future ledger starts only at actual issuance'))
    registry.parent.mkdir(parents=True,exist_ok=True)
    from prospective_daily import exclusive
    exclusive(registry,dict(created_at=datetime.now(ZoneInfo('UTC')).isoformat(),version='regional-v1',streamflow=good,groundwater=[],policy='Frozen neighboring-gauge models; each uses only its own discharge history and calendar date. Scored separately from CT-v1.'))
    log(f'Regional context: {len(good)} models trained; remaining gauges have explicit unavailable reasons.')
if __name__=='__main__':main()
