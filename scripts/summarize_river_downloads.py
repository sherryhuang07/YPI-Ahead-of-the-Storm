import hashlib
from datetime import datetime,timezone
from statewide_common import ROOT,read,save
D=ROOT/'data/hydrography'
def main():
    names=['hr-flowlines','hr-catchments','hr-waterbodies','hr-gauges','public-dams','3dhp-flowlines','3dhp-waterbodies','3dhp-catchments','3dhp-outlets','3dhp-workunits'];sources=[]
    for name in names:
        p=D/(name+'.geojson');assert p.exists(),name
        meta=read(p.with_suffix('.source.json'));digest=hashlib.sha256(p.read_bytes()).hexdigest();assert digest==meta['sha256'],name
        sources.append(dict(dataset=name,features=meta['count'],bytes=p.stat().st_size,sha256=digest,source=meta))
    histories=[]
    for p in sorted((ROOT/'data/streamflow/history').glob('*.json')):
        v=read(p);histories.append(dict(gauge_id=p.stem,records=len(v['features']),series_id=v['series_id'],sha256=hashlib.sha256(p.read_bytes()).hexdigest(),endpoint='https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items',parameters=dict(time_series_id=v['series_id'],parameter_code='00060',statistic_id='00003',datetime='2000-01-01/2026-11-02')))
    save(D/'inventory.json',dict(checked_at=datetime.now(timezone.utc).isoformat(),map_layers=sources,histories=histories,observations=sum(x['records'] for x in histories),nldi_basins=len(list((D/'nldi').glob('*-basin.geojson'))),streamstats_delineation_responses=len(list((D/'streamstats').glob('USGS-*.json'))),refined_nldi_basins=len(list((D/'nldi-split').glob('*-basin.geojson'))) if (D/'nldi-split').exists() else 0,optional_refinement_status='Split-catchment requests failed with HTTP 502; whole-catchment association explicitly retained',ctsswue_database_bytes=(D/'CT-SSWUE-V1.0.0.accdb').stat().st_size))
    print('PASS: all ten mapping layers present with matching hashes; '+str(sum(x['records'] for x in histories))+' historical observations indexed.')
if __name__=='__main__':main()
