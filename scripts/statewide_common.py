from pathlib import Path
import json, time, hashlib, threading
from datetime import datetime, timezone
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'statewide'
DATA.mkdir(exist_ok=True)
PARCEL = 'https://services3.arcgis.com/3FL1kr7L4LvwA2Kb/arcgis/rest/services/Connecticut_CAMA_and_Parcel_Layer/FeatureServer/0'
TOWNS = 'https://services1.arcgis.com/FCaUeJ5SOVtImake/arcgis/rest/services/CT_Municipalities/FeatureServer/0'
FTW = 'https://data.source.coop/ftw/global-data/predictions/vectors/alpha/results-by-admin-conf/admin:country_code=US/'
FIELDS = 'OBJECTID,Town_Name,Location,Parcel_ID,State_Use,State_Use_Description,Land_Acres,Parcel_Collection_Year'
SESSION = requests.Session()
SESSION.headers['User-Agent'] = 'AheadOfTheStormResearch/0.1 (Connecticut farm boundary inventory)'
LOCAL=threading.local()

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def save(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    temp.replace(path)

def log(message):
    print(message,flush=True)
    with (ROOT/'activity.log').open('a',encoding='utf-8') as f:
        f.write(datetime.now(timezone.utc).isoformat()+' | Statewide mapping: '+message+'\n')

def request_json(url, params=None, post=False, timeout=120):
    if not hasattr(LOCAL,'session'):
        LOCAL.session=requests.Session()
        LOCAL.session.headers.update(SESSION.headers)
    error=None
    for attempt in range(4):
        try:
            response=LOCAL.session.post(url,data=params,timeout=timeout) if post else LOCAL.session.get(url,params=params,timeout=timeout)
            response.raise_for_status(); value=response.json()
            if 'error' in value or 'remark' in value: raise RuntimeError(str(value.get('error',value.get('remark'))))
            return value
        except (requests.RequestException,ValueError,RuntimeError) as e:
            error=e
            if attempt<3: time.sleep(2**attempt)
    raise RuntimeError(f'{url}: {error}')

def download(url,path):
    path=Path(path)
    if path.exists() and path.with_suffix(path.suffix+'.source.json').exists(): return
    log('Downloading '+path.name)
    response=SESSION.get(url,stream=True,timeout=(30,180));response.raise_for_status()
    tmp=path.with_suffix(path.suffix+'.part'); digest=hashlib.sha256(); size=0
    with tmp.open('wb') as f:
        for chunk in response.iter_content(1024*1024): f.write(chunk);digest.update(chunk);size+=len(chunk)
    tmp.replace(path)
    save(path.with_suffix(path.suffix+'.source.json'),{'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'bytes':size,'sha256':digest.hexdigest()})

def query(params):
    return request_json(PARCEL+'/query',params,post=True)

def id_query(params):
    result=query(dict(params,f='json',returnIdsOnly='true'))
    if not isinstance(result.get('objectIds'),list): raise RuntimeError('Parcel query did not return an ID list')
    if result.get('exceededTransferLimit'): raise RuntimeError('Parcel ID list was truncated')
    return sorted(set(result['objectIds']))

def fetch_records(ids,folder):
    folder=Path(folder);folder.mkdir(exist_ok=True,parents=True)
    features=[]
    for start in range(0,len(ids),150):
        batch=ids[start:start+150]
        key=hashlib.sha256(','.join(map(str,batch)).encode()).hexdigest()[:16]
        file=folder/(key+'.json')
        value=read(file) if file.exists() else query({'f':'geojson','objectIds':','.join(map(str,batch)),'outFields':FIELDS,'outSR':'4326','returnGeometry':'true'})
        got=[f['properties']['OBJECTID'] for f in value.get('features',[])]
        if value.get('exceededTransferLimit') or set(got)!=set(batch) or len(got)!=len(batch): raise RuntimeError('Missing or duplicate parcel records in batch '+key)
        save(file,value);features.extend(value['features'])
        if start%1500==0: log(f'Property shapes retrieved: {min(start+150,len(ids)):,} of {len(ids):,}')
    return {'type':'FeatureCollection','features':features}
