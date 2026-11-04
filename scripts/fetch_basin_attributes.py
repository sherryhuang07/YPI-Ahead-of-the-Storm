"""Download static USGS GAGES-II descriptors, not discharge outcomes."""
import requests,zipfile,io,re,csv,hashlib
from datetime import datetime,timezone
from statewide_common import ROOT,save,read
D=ROOT/'data/streamflow-experiments'
def main():
    D.mkdir(parents=True,exist_ok=True)
    catalog=read(D/'discovery/gages-item.json')
    url=next(f['url'] for f in catalog['files'] if f['name']=='basinchar_and_report_sept_2011.zip');path=D/'bas_char_gagesII.zip'
    if not path.exists():
        r=requests.get(url,timeout=120);r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:print(z.namelist()[:12])
        path.write_bytes(r.content)
    with zipfile.ZipFile(path) as z:
        tables=zipfile.ZipFile(io.BytesIO(z.read('spreadsheets-in-csv-format.zip')))
        mapping={'conterm_soils.txt':{'CLAYAVE':'clay_pct','HGA':'soil_group_a_pct'},'conterm_topo.txt':{'SLOPE_PCT':'slope'},'conterm_lc06_basin.txt':{'FORESTNLCD06':'forest_pct','DEVNLCD06':'developed_pct'},'conterm_hydromod_dams.txt':{'NDAMS_2009':'dams_2009','DDENS_2009':'dam_density_2009'}}
        data={}
        for name,columns in mapping.items():
            for row in csv.DictReader(io.StringIO(tables.read(name).decode('utf-8-sig'))):
                gid='USGS-'+row['STAID'];out=data.setdefault(gid,{})
                for source,target in columns.items():
                    try:value=float(row[source])
                    except (ValueError,TypeError):continue
                    if value>=0:out[target]=value
        save(D/'basin-attributes.json',data)
        print('Saved static descriptors for',len(data),'gauges')
    save(D/'attributes-source.json',dict(url=url,captured_at=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),note='Static historical basin descriptors; land cover and infrastructure may have changed.'))
if __name__=='__main__':main()
