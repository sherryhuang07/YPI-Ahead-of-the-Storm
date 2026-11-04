"""Prospective, append-only forecast ledger. Never backdates or replaces a forecast."""
import argparse,csv,gzip,hashlib,json,math,sqlite3,subprocess,sys
from collections import defaultdict
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import rasterio
from statewide_common import ROOT,read,save,request_json,log
from forecast_methods import predict as water_predict

D=ROOT/'data/prospective';O=ROOT/'outputs/prospective';UTC=timezone.utc
LOCAL=ZoneInfo('America/New_York')
CODE_BYTES=Path(__file__).read_bytes()
def utc():return datetime.now(UTC)
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def stamp():return utc().strftime('%Y%m%dT%H%M%S%fZ')
def exclusive(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,allow_nan=False)
def db():
    D.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(D/'ledger.sqlite');c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''CREATE TABLE IF NOT EXISTS forecasts (issue_day TEXT, variable TEXT, issued_at TEXT, path TEXT, sha256 TEXT, PRIMARY KEY(issue_day,variable));
    CREATE TABLE IF NOT EXISTS observations (variable TEXT, location TEXT, day TEXT, value REAL, captured_at TEXT, snapshot TEXT, PRIMARY KEY(variable,location,day));
    CREATE TABLE IF NOT EXISTS scores (forecast_sha TEXT, variable TEXT, location TEXT, day TEXT, lead INTEGER, predicted REAL, observed REAL, absolute_error REAL, baseline_error REAL, scored_at TEXT, PRIMARY KEY(forecast_sha,location,day));
    CREATE TABLE IF NOT EXISTS exclusions (forecast_sha TEXT PRIMARY KEY, recorded_at TEXT, reason TEXT);''')
    for table in ['forecasts','observations','scores','exclusions']:
        for action in ['UPDATE','DELETE']:
            c.execute(f"CREATE TRIGGER IF NOT EXISTS no_{action.lower()}_{table} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Prospective records are append-only'); END")
    return c
def verify(c):
    indexed={str((ROOT/r[0]).resolve()) for r in c.execute('SELECT path FROM forecasts')}
    orphans=[p for p in (O/'issued').glob('**/*.json') if str(p.resolve()) not in indexed]
    if orphans:raise ValueError('Unindexed sealed forecast needs explicit recovery; refusing a silent replacement: '+str(orphans[0]))
    for path,sha in c.execute('SELECT path,sha256 FROM forecasts'):
        if digest(ROOT/path)!=sha:raise ValueError('Sealed forecast hash mismatch: '+path)
        record=read(ROOT/path)
        for source in record.get('sources',[]):
            if source['path'].replace('\\','/').endswith('/model-v1.json') and digest(ROOT/source['path'])!=source['sha256']:
                raise ValueError('Frozen model registry changed; create a separately tracked model version')

def model_registry():
    p=D/'model-v1.json'
    series={r['gauge_id']:r['series_id'] for r in read(ROOT/'outputs/streamflow/gauges.json')}
    if not p.exists():
        streams=[r for r in read(ROOT/'outputs/streamflow-trained/results.json') if 'forecast' in r]
        for r in streams:r['series_id']=series[r['gauge_id']]
        wells=[r for r in read(ROOT/'outputs/forecasts/groundwater/location-forecasts.json') if r['status']=='experimental']
        lookup={r['id']:r for r in read(ROOT/'outputs/groundwater/wells.json')}
        for r in wells:
            ids={h['series_id'] for h in lookup[r['id']]['history'] if h['type']=='Daily mean'}
            if len(ids)!=1:raise ValueError('Ambiguous groundwater series')
            r['series_id']=next(iter(ids))
        exclusive(p,dict(created_at=utc().isoformat(),version='v1',streamflow=streams,groundwater=wells,precipitation_window=42,
            policy='Frozen streamflow weights and method choices; groundwater coefficients update only from observations captured before issuance. No automatic model selection from prospective scores.'))
    registry=read(p)
    if any('series_id' not in r for r in registry['streamflow']):
        if list((O/'issued').glob('**/*.json')):raise ValueError('Cannot migrate an issued model registry')
        for r in registry['streamflow']:r['series_id']=series[r['gauge_id']]
        save(p,registry)
    return registry

def seed(reg):
    values={'streamflow':{},'groundwater':{}}
    for r in reg['streamflow']:
        rows=read(ROOT/'data/streamflow/history'/(r['gauge_id']+'.json'))['features'];values['streamflow'][r['gauge_id']]=clean(rows,r['series_id'],'00060','ft^3/s')
    wells={r['id']:r for r in read(ROOT/'outputs/groundwater/wells.json')}
    for r in reg['groundwater']:
        values['groundwater'][r['id']]={h['date']:h['depth_below_land_ft'] for h in wells[r['id']]['history'] if h['type']=='Daily mean' and not h.get('qualifier') and h['series_id']==r['series_id']}
    return values

def clean(rows,series,param,unit):
    result={}
    for f in rows:
        p=f['properties']
        if p.get('time_series_id')!=series or p.get('parameter_code')!=param or p.get('statistic_id')!='00003' or p.get('unit_of_measure')!=unit or p.get('qualifier'):continue
        try:v=float(p['value'])
        except (ValueError,TypeError):continue
        if not math.isfinite(v) or (param=='00060' and v<0):continue
        day=p['time'][:10]
        if day in result and result[day]!=v:raise ValueError('Conflicting daily observations')
        result[day]=v
    return result

def collect(reg,offline=False):
    folder=D/'snapshots'/stamp();folder.mkdir(parents=True);values=seed(reg);end=utc().astimezone(LOCAL).date()-timedelta(days=1);errors=[]
    for kind,param,unit in [('streamflow','00060','ft^3/s'),('groundwater','72019','ft')]:
        if offline:continue
        try:
            url='https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items';rows=[];pages=[]
            params=dict(f='json',bbox='-73.8,40.9,-71.7,42.1',parameter_code=param,statistic_id='00003',datetime=f'{end-timedelta(days=89)}/{end}',limit=10000)
            while url:
                v=request_json(url,params,timeout=60);rows.extend(v['features']);pages.append(url)
                url=next((x['href'] for x in v.get('links',[]) if x['rel']=='next'),None);params=None
                if url in pages:raise ValueError('Pagination loop')
            exclusive(folder/(kind+'-raw.json'),dict(features=rows,pages=pages,requested_end=str(end),captured_at=utc().isoformat()))
            for r in reg[kind]:
                identifier=r['gauge_id'] if kind=='streamflow' else r['id']
                # Replace the requested window, so removed/qualified readings cannot survive from an older cache.
                values[kind][identifier]={k:v for k,v in values[kind][identifier].items() if k<str(end-timedelta(days=89))}
                values[kind][identifier].update({k:v for k,v in clean(rows,r['series_id'],param,unit).items() if k<=str(end)})
        except Exception as e:errors.append(kind+': '+str(e))
    grids={}
    for p in sorted((ROOT/'data/prism').glob('**/????-??-??.tif')):
        if p.stem<=str(end) and p.with_suffix('.json').exists():grids[p.stem]=p
    if not offline:
        try:
            releases=request_json(f'https://services.nacse.org/prism/data/get/releaseDate/us/800m/ppt/{end-timedelta(days=89):%Y%m%d}/{end:%Y%m%d}',dict(json='true'),timeout=60)
            exclusive(folder/'prism-releases.json',releases)
            # Catch up missing published dates; never silently substitute a missing grid with zero rain.
            for day in sorted({x[0] for x in releases if x[0]<=str(end)}):
                if day in grids:continue
                snapshot='prospective/'+folder.name
                subprocess.run([sys.executable,str(ROOT/'scripts/fetch_prism.py'),'--end',day,'--days','1','--snapshot',snapshot],check=True)
                grids[day]=ROOT/'data/prism'/snapshot/(day+'.tif')
        except Exception as e:errors.append('precipitation: '+str(e))
    # Trim historical observations to a rolling input window; full source archives remain preserved.
    start=str(end-timedelta(days=89))
    values={kind:{loc:{day:v for day,v in rows.items() if start<=day<=str(end)} for loc,rows in locations.items()} for kind,locations in values.items()}
    snap=dict(captured_at=utc().isoformat(),values=values,grids={k:str(v.relative_to(ROOT)) for k,v in grids.items() if start<=k<=str(end)},errors=errors,offline_seed=offline)
    exclusive(folder/'inputs.json',snap)
    return folder/'inputs.json',snap

def target_start(kind,day):
    d=date.fromisoformat(day)
    return datetime.combine(d-timedelta(days=1),datetime.min.time(),UTC)+timedelta(hours=12) if kind=='precipitation' else datetime.combine(d,datetime.min.time(),LOCAL).astimezone(UTC)

def seal(c,kind,rows,unavailable,snapshot,snap,model_path,model_version='v1',extra_sources=()):
    now=utc();today=str(now.astimezone(LOCAL).date())
    if c.execute('SELECT 1 FROM forecasts WHERE substr(issue_day,1,10)=? AND variable=? AND sha256 NOT IN (SELECT forecast_sha FROM exclusions)',(today,kind)).fetchone():return
    if datetime.fromisoformat(snap['captured_at'])>now:raise ValueError('Inputs were captured after issuance')
    for r in rows:
        for d in r['dates']:
            if target_start(kind,d)<=now:raise ValueError('Target period has already started; refusing to backdate forecast')
    code_sha=hashlib.sha256(CODE_BYTES).hexdigest();code_path=D/'code'/(code_sha+'.py');code_path.parent.mkdir(exist_ok=True)
    if not code_path.exists():
        with code_path.open('xb') as f:f.write(CODE_BYTES)
    sources=[dict(path=str(snapshot.relative_to(ROOT)),sha256=digest(snapshot)),dict(path=str(model_path.relative_to(ROOT)),sha256=digest(model_path)),dict(path=str(code_path.relative_to(ROOT)),sha256=code_sha)]
    sources.extend(extra_sources)
    if kind=='precipitation':
        for day,path in snap['grids'].items():sources.append(dict(path=path,sha256=digest(ROOT/path)))
        sources.append(dict(path='outputs/precipitation/grid-overlaps.csv',sha256=digest(ROOT/'outputs/precipitation/grid-overlaps.csv')))
    record=dict(variable=kind,issued_at=now.isoformat(),model_version=model_version,snapshot_captured_at=snap['captured_at'],sources=sources,forecasts=rows,unavailable=unavailable,
        rules='Only observations captured before issuance. All target periods start after issuance. Earlier retrospective forecasts are excluded from this prospective ledger.')
    issue_id=today+'/'+stamp();path=O/'issued'/today/(kind+'-'+stamp()+'.json');exclusive(path,record)
    c.execute('INSERT INTO forecasts VALUES (?,?,?,?,?)',(issue_id,kind,record['issued_at'],str(path.relative_to(ROOT)),digest(path)));c.commit()
    log(f'Forecast sealed: {kind}, {len(rows)} locations. Original values will not be replaced.')

def make_water(kind,reg,snap):
    now=utc();today=now.astimezone(LOCAL).date();rows=[];missing=[]
    for r in reg[kind]:
        loc=r['gauge_id'] if kind=='streamflow' else r['id'];history=snap['values'][kind][loc]
        try:
            last=date.fromisoformat(max(history));age=(today-last).days
            if age<1 or age>7:raise ValueError('Latest clean reading is absent or more than seven days old')
            days=[last-timedelta(days=89-i) for i in range(90)];q=np.array([history.get(str(d),np.nan) for d in days])
            first=today+timedelta(days=1);dates=[str(first+timedelta(days=i)) for i in range(14)]
            if kind=='streamflow':
                if age!=1:raise ValueError('Frozen streamflow model requires yesterday’s clean observation to cover all 14 future days')
                if not np.isfinite(q[-28:]).all():raise ValueError('Recent streamflow input window is incomplete')
                z=np.log1p(q);features=[z[-1-k] for k in [0,1,2,6,13,27]]+[np.mean(z[-k:]) for k in [7,14,28]]
                doy=last.timetuple().tm_yday;features += [np.sin(2*np.pi*doy/365.25),np.cos(2*np.pi*doy/365.25)]
                m=r['model']
                pred=np.repeat(q[-1],14) if m['method']=='persistence' else np.expm1(np.clip(np.r_[1,(np.array(features)-m['mean'])/m['scale']]@np.array(m['beta']),0,20))
            else:
                if np.isfinite(q).sum()<70:raise ValueError('Fewer than 70 clean daily readings in 90 days')
                lead=(first-last).days;pred=water_predict(q,r['method'],kind,horizon=lead+13)[lead-1:]
            rows.append(dict(id=loc,name=r['name'],dates=dates,prediction=pred.tolist(),baseline=[float(q[-1])]*14,source_last_day=str(last),units='cfs' if kind=='streamflow' else 'feet below land surface at monitored well'))
        except (ValueError,KeyError) as e:missing.append(dict(id=loc,reason=str(e)))
    return rows,missing

def grid_values(snap):
    arrays={};template=None
    for day,path in sorted(snap['grids'].items()):
        with rasterio.open(ROOT/path) as src:
            signature=(src.shape,tuple(src.transform),str(src.crs))
            if template is not None and signature!=template:raise ValueError('PRISM grid alignment changed')
            template=signature;arrays[day]=src.read(1,masked=True).filled(np.nan)
    links=defaultdict(list)
    with (ROOT/'outputs/precipitation/grid-overlaps.csv').open() as f:
        for r in csv.DictReader(f):links[r['id']].append((int(r['crop_row']),int(r['crop_column']),float(r['area_fraction'])))
    ids=[r['id'] for r in read(ROOT/'outputs/precipitation/records.json') if r['kind'] in ['farm_candidate','pilot']]
    values={}
    for identifier in ids:
        entries=links[identifier];rr,cc,weights=zip(*entries)
        if abs(sum(weights)-1)>1e-6:raise ValueError('Farm area weights do not sum to one')
        values[identifier]={day:float(np.dot(a[list(rr),list(cc)],weights)) for day,a in arrays.items() if np.isfinite(a[list(rr),list(cc)]).all()}
    return values

def make_rain(values):
    now=utc();first=now.date()+timedelta(days=1 if now.hour<12 else 2);dates=[str(first+timedelta(days=i)) for i in range(14)];rows=[];missing=[]
    for loc,history in values.items():
        try:
            last=date.fromisoformat(max(history))
            if (now.date()-last).days>7:raise ValueError('Precipitation input is over seven days old')
            x=[history.get(str(last-timedelta(days=i)),np.nan) for i in range(42)]
            if not np.isfinite(x).all():raise ValueError('The 42-day rainfall window is incomplete')
            rate=float(np.mean(x));baseline=float(np.mean(x[:14]))
            rows.append(dict(id=loc,dates=dates,prediction=[rate]*14,baseline=[baseline]*14,source_last_day=str(last),units='mm per PRISM reporting day',method='Frozen 42-day historical-mean baseline; no storm timing prediction'))
        except ValueError as e:missing.append(dict(id=loc,reason=str(e)))
    return rows,missing

def record_observations(c,snap,snapshot,rain):
    captured=snap['captured_at'];now=utc();values=dict(snap['values'],precipitation=rain)
    wanted=defaultdict(set)
    for kind,path in c.execute('SELECT variable,path FROM forecasts WHERE sha256 NOT IN (SELECT forecast_sha FROM exclusions)'):
        for r in read(ROOT/path)['forecasts']:wanted[kind].update(r['dates'])
    for kind,locations in values.items():
        for loc,history in locations.items():
            for day,value in history.items():
                if day not in wanted[kind]:continue
                # Conservative water-day completion gate: two UTC midnights after its date.
                end=target_start(kind,day)+timedelta(days=1 if kind=='precipitation' else 2)
                if end>now or not math.isfinite(value):continue
                c.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)',(kind,loc,day,value,captured,str(snapshot.relative_to(ROOT))))
    c.commit()

def score(c):
    verify(c);new=0
    for kind,path,sha,issued in c.execute('SELECT variable,path,sha256,issued_at FROM forecasts WHERE sha256 NOT IN (SELECT forecast_sha FROM exclusions)').fetchall():
        f=read(ROOT/path)
        for r in f['forecasts']:
            for lead,(day,pred,base) in enumerate(zip(r['dates'],r['prediction'],r['baseline']),1):
                actual=c.execute('SELECT value,captured_at FROM observations WHERE variable=? AND location=? AND day=?',(kind,r['id'],day)).fetchone()
                if actual is None:continue
                if actual[1]<=issued:raise ValueError('Observation was available before forecast issuance')
                result=c.execute('INSERT OR IGNORE INTO scores VALUES (?,?,?,?,?,?,?,?,?,?)',(sha,kind,r['id'],day,lead,pred,actual[0],abs(pred-actual[0]),abs(base-actual[0]),utc().isoformat()));new+=result.rowcount
    c.commit();summaries=[]
    for row in c.execute('SELECT variable,lead,COUNT(*),AVG(absolute_error),AVG(baseline_error) FROM scores GROUP BY variable,lead'):
        summaries.append(dict(variable=row[0],forecast_day=row[1],comparisons=row[2],mae=row[3],baseline_mae=row[4]))
    issues=[dict(day=a[:10],issue_id=a,variable=b,issued_at=t,sha256=h) for a,b,t,h in c.execute('SELECT issue_day,variable,issued_at,sha256 FROM forecasts WHERE sha256 NOT IN (SELECT forecast_sha FROM exclusions) ORDER BY issue_day,variable')]
    complete=c.execute("SELECT COUNT(*),AVG(ABS(predicted-observed)) FROM (SELECT forecast_sha,location,SUM(predicted) predicted,SUM(observed) observed FROM scores WHERE variable='precipitation' GROUP BY forecast_sha,location HAVING COUNT(*)=14)").fetchone()
    exclusions=[dict(sha256=h,recorded_at=t,reason=r) for h,t,r in c.execute('SELECT * FROM exclusions')]
    save(O/'scoreboard.json',dict(updated_at=utc().isoformat(),issues=issues,excluded_setup_records=exclusions,by_variable_and_lead=summaries,new_comparisons=new,precipitation_complete_fortnights=dict(count=complete[0],total_amount_mae_mm=complete[1]),
        note='First available clean observations are the frozen scoring target. Subsequent source snapshots retain USGS revisions separately. Correlated fields and overlapping forecast windows are not independent tests. Farm groundwater and ungauged streams remain unsupported.'))
    return new

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');a=parser.parse_args()
    O.mkdir(parents=True,exist_ok=True);c=db();verify(c);reg=model_registry()
    snapshot,snap=collect(reg,a.offline);rain=grid_values(snap)
    for kind in ['streamflow','groundwater']:
        rows,missing=make_water(kind,reg,snap);seal(c,kind,rows,missing,snapshot,snap,D/'model-v1.json')
    rows,missing=make_rain(rain);seal(c,'precipitation',rows,missing,snapshot,snap,D/'model-v1.json')
    record_observations(c,snap,snapshot,rain);new=score(c)
    # NOAA NBM guidance is issued into its own timestamped farm-level archive;
    # it never replaces the already sealed historical-baseline forecast above.
    try:subprocess.run([sys.executable,str(ROOT/'scripts/fetch_noaa_precip.py')],check=True,cwd=ROOT)
    except Exception as e:snap['errors'].append('NOAA NBM precipitation: '+str(e))
    save(O/'last-run.json',dict(completed_at=utc().isoformat(),snapshot=str(snapshot.relative_to(ROOT)),source_errors=snap['errors'],new_comparisons=new,offline=a.offline))
    log(f'Daily prospective check complete: {new} new comparisons; {len(snap["errors"])} source errors. No earlier forecast changed.')
    if snap['errors']:raise SystemExit('Partial data update: see outputs/prospective/last-run.json')
if __name__=='__main__':main()
