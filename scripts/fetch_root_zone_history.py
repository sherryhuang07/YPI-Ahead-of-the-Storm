"""Retrieve the public USGS NLDAS-2 watershed release, without Earthdata login.

Only three soil layers and metadata are downloaded. No CPC data is accepted.
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import requests
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data/root-zone/usgs'
RELEASE = 'https://www.sciencebase.gov/catalog/item/62fa7a89d34e25bd092879cc?format=json'
NAMES = ['SoilM_0_10cm_gagesII.csv','SoilM_10_40cm_gagesII.csv',
         'SoilM_40_100cm_gagesII.csv','projectmetadata_NLDAS_GAGESII.xml']

def digest(path, algorithm='sha256'):
    h=hashlib.new(algorithm)
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def fetch(item):
    path=DEST/item['name']
    if not path.exists():
        print('Downloading '+item['name'],flush=True)
        with requests.get(item['url'],stream=True,timeout=(30,180)) as r:
            r.raise_for_status()
            with path.with_suffix(path.suffix+'.part').open('wb') as f:
                for chunk in r.iter_content(1024*1024): f.write(chunk)
        part=path.with_suffix(path.suffix+'.part')
        if part.stat().st_size!=item['size'] or (not item['name'].endswith('.xml') and digest(part,'md5')!=item['checksum']['value']):
            raise ValueError('USGS checksum/size mismatch: '+item['name'])
        if item['name'].endswith('.xml'): ET.parse(part)
        part.replace(path)
    verified=digest(path,'md5')==item['checksum']['value']
    if path.stat().st_size!=item['size'] or (not item['name'].endswith('.xml') and not verified):
        raise ValueError('USGS checksum/size mismatch: '+item['name'])
    print(('Verified ' if verified else 'WARNING: publisher checksum differs for documentation file ')+item['name'],flush=True)
    return dict(name=item['name'], url=item['url'], bytes=path.stat().st_size,
                sha256=digest(path), publisher_md5=item['checksum']['value'],
                publisher_checksum_verified=verified, downloaded_md5=digest(path,'md5'))

def main():
    DEST.mkdir(parents=True,exist_ok=True)
    r=requests.get(RELEASE,timeout=60);r.raise_for_status();meta=r.json()
    (DEST/'release.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    items={v['name']:v for v in meta['files']}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(fetch,[items[n] for n in NAMES]))
    manifest=dict(captured_at=datetime.now(timezone.utc).isoformat(),doi='10.5066/P9IKHEM3',
                  files=results, source='USGS aggregation of NLDAS-2 Noah',
                  coverage='1980-2020; GAGES-II watershed means, not farm observations')
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Historical source download complete.',flush=True)

if __name__=='__main__': main()
