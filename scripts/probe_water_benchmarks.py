"""Read-only public-source discovery, with responses preserved for inspection."""
from statewide_common import ROOT,save
import requests
from datetime import datetime,timezone

def main():
    out=ROOT/'data/streamflow-experiments/discovery';out.mkdir(parents=True,exist_ok=True)
    urls={
        'nwps-schema':'https://api.water.noaa.gov/nwps/v1/docs/swagger.json',
        'nwps-gauges':'https://api.water.noaa.gov/nwps/v1/gauges?bbox.xmin=-74&bbox.ymin=40.9&bbox.xmax=-71.7&bbox.ymax=42.1&srid=EPSG_4326',
        'nwps-farmington':'https://api.water.noaa.gov/nwps/v1/gauges/01189995',
        'nwps-farmington-long':'https://api.water.noaa.gov/nwps/v1/reaches/6109139/streamflow?series=long_range',
        'streamstats-parameters':'https://streamstats.usgs.gov/streamstatsservices/parameters?rcode=CT&f=json',
        'gages-catalog':'https://www.sciencebase.gov/catalog/items?q=10.5066%2FP96CPHOT&format=json',
        'gages-item':'https://www.sciencebase.gov/catalog/item/631405bbd34e36012efa304a?format=json',
    }
    results=[]
    for name,url in urls.items():
        try:
            r=requests.get(url,timeout=45);r.raise_for_status();v=r.json();save(out/(name+'.json'),v)
            results.append(dict(name=name,url=url,status='downloaded',captured_at=datetime.now(timezone.utc).isoformat()))
            print(name,str(v)[:500],flush=True)
        except Exception as e:results.append(dict(name=name,url=url,error=str(e)));print(name,str(e),flush=True)
    save(out/'status.json',results)
if __name__=='__main__':main()
