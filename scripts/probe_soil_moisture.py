"""Check official public soil moisture access; never logs credentials."""
import json
from datetime import datetime, timezone
from pathlib import Path
import requests
import time

ROOT = Path(__file__).resolve().parents[1]
URLS = {
    'epa_api_schema': 'https://qed.epa.gov/hms/api_doc/swagger/',
    'nasa_catalog': 'https://cmr.earthdata.nasa.gov/search/collections.json?short_name=NLDAS_NOAH0125_H&version=2.0',
}

def main():
    folder = ROOT / 'data/root-zone/access'
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for name, url in URLS.items():
        try:
            r = requests.get(url, timeout=45)
            r.raise_for_status()
            payload = r.json()
            (folder / (name+'.json')).write_text(json.dumps(payload), encoding='utf-8')
            results.append(dict(source=name, status='reachable', url=url))
        except (requests.RequestException, ValueError) as e:
            results.append(dict(source=name, status='failed', error=str(e), url=url))
    url = 'https://qed.epa.gov/hms/rest/api/v3/hydrology/soilmoisture/'
    payload = dict(layers=['0-100'], source='nldas',
        dateTimeSpan=dict(startDate='01/01/2020 00:00:00',endDate='01/03/2020 00:00:00'),
        geometry=dict(point=dict(latitude=41.32, longitude=-72.92)),
        temporalResolution='daily', timeLocalized=False, dataValueFormat='E6')
    try:
        r = requests.post(url, json=payload, timeout=60)
        r.raise_for_status()
        body=r.json()
        if 'job_id' in body:
            job=body['job_id']
            for _ in range(6):
                response=requests.get('https://qed.epa.gov/hms/rest/api/v2/hms/data',params={'job_id':job},timeout=45)
                response.raise_for_status()
                body=response.json()
                if 'data' in body or 'ERROR' in str(body): break
                time.sleep(5)
        (folder/'epa_probe.json').write_text(json.dumps(body),encoding='utf-8')
        usable=bool(body.get('data',{}).get('data')) and 'ERROR' not in str(body)
        results.append(dict(source='epa_data_request', status='data_received' if usable else 'failed', response=body))
    except (requests.RequestException,ValueError) as e:
        results.append(dict(source='epa_data_request',status='failed',error=str(e)))
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(), results=results)
    (folder/'status.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return int(any(r['status']=='failed' for r in results))

if __name__ == '__main__':
    raise SystemExit(main())
