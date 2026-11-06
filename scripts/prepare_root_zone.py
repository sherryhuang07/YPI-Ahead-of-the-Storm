"""Validate USGS files and extract watersheds with outlets in Connecticut."""
import csv
import io
import json
import zipfile
from datetime import date, datetime, timedelta
import numpy as np
from fetch_root_zone_history import ROOT, DEST, digest

def main():
    manifest=json.loads((DEST/'manifest.json').read_text())
    for f in manifest['files']:
        if digest(DEST/f['name'])!=f['sha256']: raise ValueError('Source checksum mismatch: '+f['name'])
        if f['name'].endswith('.csv') and not f['publisher_checksum_verified']:
            raise ValueError('Numeric source did not pass publisher checksum')
    catalog=ROOT/'data/streamflow-experiments/bas_char_gagesII.zip'
    with zipfile.ZipFile(catalog) as outer:
        with zipfile.ZipFile(io.BytesIO(outer.read('spreadsheets-in-csv-format.zip'))) as inner:
            rows=csv.DictReader(io.StringIO(inner.read('conterm_basinid.txt').decode('utf-8-sig')))
            sites={r['STAID']:r for r in rows if r['STATE']=='CT'}
    dates=None; ids=None; layers=[]; missing=[]
    for name,thickness in [('SoilM_0_10cm_gagesII.csv',100),('SoilM_10_40cm_gagesII.csv',300),('SoilM_40_100cm_gagesII.csv',600)]:
        with (DEST/name).open(newline='',encoding='utf-8-sig') as f:
            reader=csv.reader(f); header=next(reader)
            columns={v.strip().lstrip('X').zfill(8):i for i,v in enumerate(header[1:],1)}
            selected=sorted(set(sites)&set(columns))
            if ids is None: ids=selected;missing=sorted(set(sites)-set(ids))
            if ids!=selected: raise ValueError('Layer watershed IDs differ')
            ds=[];values=[]
            for row in reader:
                if len(row)!=len(header): raise ValueError('Wrong column count')
                ds.append(datetime.strptime(row[0],'%m-%d-%Y').date().isoformat())
                vals=[]
                for sid in ids:
                    try: v=float(row[columns[sid]])
                    except ValueError: v=float('nan')
                    vals.append(v if np.isfinite(v) and 0<=v<=thickness else float('nan'))
                values.append(vals)
        if dates is None: dates=ds
        if ds!=dates: raise ValueError('Layer dates differ')
        layers.append(np.array(values,dtype=float))
    n=(date(2020,12,31)-date(1980,1,1)).days+1
    expected=[(date(1980,1,1)+timedelta(days=i)).isoformat() for i in range(n)]
    if dates!=expected: raise ValueError('Unexpected missing/duplicate dates or archive span')
    if not ids: raise ValueError('No CT watershed columns matched')
    moisture=sum(layers)/1000.0  # mm water / 1000 mm soil = volumetric fraction
    folder=ROOT/'data/root-zone/prepared';folder.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(folder/'history.npz',dates=np.array(dates),ids=np.array(ids),moisture=moisture)
    info=dict(source_manifest_sha256=digest(DEST/'manifest.json'),history_sha256=digest(folder/'history.npz'),
        catalog_sha256=digest(catalog),units='m3/m3',start=dates[0],end=dates[-1],days=len(dates),
        watersheds=len(ids),missing_values=int(np.sum(~np.isfinite(moisture))),
        missing_catalog_watersheds=missing,sites={i:sites[i] for i in ids},
        coverage='Watersheds with CT outlets; watershed means, not farm measurements')
    (folder/'manifest.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in info.items() if k!='sites'},indent=2))

if __name__=='__main__': main()
