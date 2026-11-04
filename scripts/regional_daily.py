"""Daily neighboring-gauge context in a separate prospective archive."""
from datetime import timedelta
from pathlib import Path
import prospective_daily as p
from statewide_common import ROOT,read,save,log
from fetch_regional_streamflow import fetch_pages,BASE

def main():
    p.D=ROOT/'data/regional-prospective';p.O=ROOT/'outputs/regional-prospective';p.O.mkdir(parents=True,exist_ok=True)
    c=p.db();p.verify(c);registry=p.D/'model-v1.json';reg=read(registry)
    # Check this separate registry against previous issue hashes before using it.
    for path, in c.execute('SELECT path FROM forecasts'):
        for source in read(ROOT/path)['sources']:
            if source['path']==str(registry.relative_to(ROOT)) and source['sha256']!=p.digest(registry):raise ValueError('Regional model registry changed')
    folder=p.D/'snapshots'/p.stamp();folder.mkdir(parents=True);end=p.utc().astimezone(p.LOCAL).date()-timedelta(days=1)
    gauges=read(ROOT/'outputs/regional-streamflow/relevant-gauges.json');errors=[]
    try:
        # The common eastern NY/New England extent includes the connected upper Connecticut basin.
        raw=fetch_pages(BASE+'daily/items',dict(f='json',bbox='-76,40,-69,46',parameter_code='00060',statistic_id='00003',datetime=f'{end-timedelta(days=89)}/{end}',limit=10000))
        p.exclusive(folder/'streamflow-raw.json',raw)
        values={g['gauge_id']:{d:v for d,v in p.clean(raw['features'],g['series_id'],'00060','ft^3/s').items() if str(end-timedelta(days=89))<=d<=str(end)} for g in gauges}
    except Exception as e:
        errors.append(str(e));values={g['gauge_id']:{} for g in gauges}
    snap=dict(captured_at=p.utc().isoformat(),values=dict(streamflow=values,groundwater={}),grids={},errors=errors,purpose='Neighboring-gauge context; separate from CT-v1')
    snapshot=folder/'inputs.json';p.exclusive(snapshot,snap)
    code=folder/'regional-runner.py'
    with code.open('xb') as f:f.write(Path(__file__).read_bytes())
    rows,missing=p.make_water('streamflow',reg,snap)
    p.seal(c,'streamflow',rows,missing,snapshot,snap,registry,model_version='regional-v1',extra_sources=[dict(path=str(code.relative_to(ROOT)),sha256=p.digest(code))])
    p.record_observations(c,snap,snapshot,{});new=p.score(c)
    latest=[]
    for g in gauges:
        history=values[g['gauge_id']];day=max(history) if history else None
        latest.append(dict(gauge_id=g['gauge_id'],date=day,flow_cfs=history[day] if day else None))
    save(p.O/'latest-observations.json',latest)
    save(p.O/'last-run.json',dict(completed_at=p.utc().isoformat(),source_errors=errors,new_comparisons=new,snapshot=str(snapshot.relative_to(ROOT)),available_forecasts=len(rows),unavailable_forecasts=len(missing),model_version='regional-v1'))
    log(f'Neighboring-gauge daily context: {len(rows)} forecasts sealed or already present; {new} new comparisons.')
    if errors:raise SystemExit('Regional observations unavailable; see regional-prospective/last-run.json')
if __name__=='__main__':main()
