"""Append a transparent final-three-day blend correction to the current NBM issue."""
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from statewide_common import ROOT,read,save,log

def main():
 out=ROOT/'outputs/forecasts/precipitation/noaa-live';ptr=read(out/'latest.json');old=ROOT/ptr['path'];d=read(old)
 if d.get('tail_blend_applied'):print('Tail blend already present; no change.');return
 for row in d['forecasts']:
  values=row['daily_precipitation_mm'];base=row.get('history_42day_mean_mm')
  recent=[values[i] for i in (8,9,10)]
  if base is None or any(v is None for v in recent):
   continue
  estimate=(sum(recent)/3+base)/2
  for i in (11,12,13):
   values[i]=estimate;row['day_sources'][i]='50/50 blend: preceding NBM probability-guided estimate + trailing 42-day PRISM mean'
 d['tail_blend_applied']=True;d['correction_of_sha256']=ptr['sha256'];d['correction_reason']='Explicitly applied requested 50/50 blend for forecast days 12–14; original issue retained.'
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');day=ptr['issue_local_date'];target=out/'issued'/day/(stamp+'-correction.json');target.parent.mkdir(parents=True,exist_ok=True)
 with target.open('x',encoding='utf-8') as f:json.dump(d,f,allow_nan=False)
 sha=hashlib.sha256(target.read_bytes()).hexdigest();save(out/'latest.json',dict(path=str(target.relative_to(ROOT)),sha256=sha,cycle=d['cycle'],issue_local_date=day,farm_count=len(d['forecasts'])))
 log('NOAA live precipitation issue corrected: last three days blend NBM probability guidance with trailing PRISM means; original retained.')
 print('Corrected',len(d['forecasts']),'farm locations. Original issue retained at',old)
if __name__=='__main__':main()
