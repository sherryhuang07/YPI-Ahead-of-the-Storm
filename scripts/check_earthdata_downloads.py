"""Download and read one recent NLDAS and SMAP granule; no model changes."""
import contextlib
import hashlib
import io
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import earthaccess
import h5py
import netCDF4
import numpy as np

ROOT=Path(__file__).resolve().parents[1]

def verify(path,product):
    if product=='NLDAS_NOAH0125_H':
        with netCDF4.Dataset(path) as f:
            name='SoilM_0_100cm'
            v=f.variables[name]
            vals=np.ma.masked_invalid(v[:]).compressed()
            result=dict(variable=name,units=str(v.units),shape=list(v.shape),valid_values=int(len(vals)))
    else:
        with h5py.File(path,'r') as f:
            name='Geophysical_Data/sm_rootzone'
            v=f[name];a=v[:];fill=v.attrs.get('_FillValue',-9999)
            vals=a[np.isfinite(a)&(a!=fill)&(a>=0)&(a<=1)]
            units=v.attrs.get('units','unspecified')
            if isinstance(units,bytes):units=units.decode()
            result=dict(variable=name,units=str(units),shape=list(v.shape),valid_values=int(len(vals)))
    if not len(vals):raise ValueError('No usable soil moisture values')
    result.update(minimum=float(vals.min()),maximum=float(vals.max()))
    return result

def main():
    logging.disable(logging.CRITICAL)
    now=datetime.now(timezone.utc);stamp=now.strftime('%Y%m%dT%H%M%S%fZ')
    folder=ROOT/'data/root-zone/download-checks'/stamp;folder.mkdir(parents=True)
    report=dict(checked_at=now.isoformat(),authenticated=False,results=[],scope='One recent sample per dataset; no forecasts or model training changed.')
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        auth=earthaccess.login(strategy='environment',persist=False)
    if not auth.authenticated:raise RuntimeError('NASA sign-in failed')
    report['authenticated']=True
    for product,version in [('NLDAS_NOAH0125_H','2.0'),('SPL4SMGP','008')]:
        item=dict(product=product,version=version,status='failed');stage='search'
        print('Checking '+product+'...',flush=True)
        try:
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                records=earthaccess.search_data(short_name=product,version=version,count=1,
                    temporal=((now-timedelta(days=30)).isoformat(),now.isoformat()),
                    bounding_box=(-73.75,40.95,-71.7,42.1),sort_key='-start_date')
            if not records:raise ValueError('No granules found in last 30 days')
            rec=records[0];umm=rec.get('umm',{})
            item['granule_id']=umm.get('GranuleUR')
            item['data_period']=umm.get('TemporalExtent')
            (folder/(product+'-metadata.json')).write_text(json.dumps(dict(rec),indent=2),encoding='utf-8')
            stage='download'
            print('Downloading one '+product+' file...',flush=True)
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                paths=earthaccess.download(records,local_path=folder/product,threads=1,show_progress=False)
            if not paths:raise ValueError('No file downloaded')
            stage='read_soil_moisture'
            files=[]
            for filename in paths:
                path=Path(filename)
                if path.suffix.lower() not in ('.nc','.nc4','.h5','.hdf5'):continue
                contents=verify(path,product)
                h=hashlib.sha256()
                with path.open('rb') as f:
                    for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
                files.append(dict(path=str(path.relative_to(ROOT)),bytes=path.stat().st_size,sha256=h.hexdigest(),**contents))
            if not files:raise ValueError('No supported science data file found')
            item.update(status='verified',files=files)
            print(product+': download and soil-moisture read verified.',flush=True)
        except Exception as exc:
            # Exceptions from HTTP libraries can contain credentials/signed URLs.
            item.update(failed_stage=stage,error_type=type(exc).__name__)
            print(product+': failed during '+stage+' ('+type(exc).__name__+').',flush=True)
        report['results'].append(item)
        (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    target=ROOT/'data/root-zone/access/earthdata-download-status.json'
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if all(v['status']=='verified' for v in report['results']) else 1

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('Download check stopped ('+type(exc).__name__+'). No credential details were logged.')
        raise SystemExit(1)
