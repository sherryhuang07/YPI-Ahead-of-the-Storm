"""Build the farmer web app (app/*.html) from the latest sealed forecasts.

Plain static pages with the data built in, so they open straight from disk in any browser,
with no server or internet connection. Rebuilt at the end of each nightly run and by
`Open Farm App.cmd`. Every number shown comes from the sealed forecast files; nothing is
computed here except averages over areas and unit conversions for display.
"""
import csv
import glob
import json
import shutil
from collections import defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np
from statewide_common import ROOT

APP = ROOT / 'app'; LOCAL = ZoneInfo('America/New_York')


def j(p): return json.loads((ROOT / p).read_text(encoding='utf-8-sig')) if (ROOT / p).exists() else None
def latest(pattern):
    files = sorted(glob.glob(str(ROOT / pattern)))
    return files[-1] if files else None


def issue_of(last_run):
    r = j(last_run)
    return (j(r['sealed_today']), r) if r and r.get('sealed_today') else (None, r)


def latest_issue(kind):
    """Newest non-empty sealed issue of a variable in the main ledger."""
    for f in sorted(glob.glob(str(ROOT / ('outputs/prospective/issued/*/%s-*.json' % kind))), reverse=True):
        r = json.loads(open(f, encoding='utf-8').read())
        if r['forecasts']: return r
    return None


# ---------------------------------------------------------------- data
def regions_svg():
    from shapely.geometry import shape
    g = j('data/drought/raw/planning-regions.geojson'); paths = {}
    lon0, lat0, k = -73.75, 42.07, 500; c = np.cos(np.radians(41.5))
    for f in g['features']:
        geom = shape(f['geometry']).simplify(0.004); polys = geom.geoms if hasattr(geom, 'geoms') else [geom]; d = ''
        for p in polys:
            pts = list(p.exterior.coords); d += 'M' + 'L'.join('%.1f,%.1f' % ((x - lon0) * k * c, (lat0 - y) * k) for x, y in pts) + 'Z'
        paths['%s|%s' % (f['properties']['GEOID'], f['properties']['NAME'])] = d
    return paths


def calibration_loss(trained):
    """Mean 2015-2018 calibration log loss (worsening and improving, all leads) of a trained drought version."""
    t = j(trained + '/latest.json'); m = t and j('%s/runs/%s/model.json' % (trained, t['run']))
    return float(np.mean([v[e]['calibration_log_loss'] for v in m.values() for e in ('worsen', 'improve')])) if m else None


def drought_version():
    """Rule fixed before v2 was trained: v2 (with VegDRI) leads only if its calibration log loss is lower than v1's
    and it has sealed a forecast; otherwise v1."""
    v1, v2 = calibration_loss('outputs/drought'), calibration_loss('outputs/drought-v2')
    if v1 is not None and v2 is not None and v2 < v1 and (j('outputs/drought-v2-prospective/last-run.json') or {}).get('sealed_today'):
        return 'v2', 'outputs/drought-v2-prospective/last-run.json', 'outputs/drought-v2/latest.json'
    return 'v1', 'outputs/drought-prospective/last-run.json', 'outputs/drought/latest.json'


def drought():
    version, last_run, trained = drought_version()
    issue, run = issue_of(last_run)
    test = j(trained) or {}
    farms = (j('data/drought/farm-regions.json') or {}).get('by_region', {})
    areas = {}
    for f in (issue or {}).get('forecasts', []):
        areas[f['id']] = dict(name='Connecticut (statewide)' if f['id'] == 'CT' else f['id'].split('|')[1], now=f['current_class'], map_date=f['current_map'],
                              dates=f['dates'], classes=f['dominant_class'], worse=f['chance_worse'], better=f['chance_better'],
                              cum=f['cumulative_percent_d0_to_d4'], farms=farms.get(f['id'], 0))
    probs = {k: v['probabilities'] for k, v in test.get('by_lead_weeks', {}).items()}
    veg = {}
    if (ROOT / 'data/drought/vegdri-weekly.csv').exists():
        import csv
        for r in csv.DictReader((ROOT / 'data/drought/vegdri-weekly.csv').open(encoding='utf-8')):
            if r['mean'] not in ('', 'None') and r['week_end'] >= veg.get(r['unit'], {}).get('week_end', ''):
                veg[r['unit']] = dict(week_end=r['week_end'], mean=round(float(r['mean']), 2), stressed=round(float(r['pct_below_minus1'])))
    return dict(issued=(issue or {}).get('issued_at'), version=version, vegdri=veg, areas=areas, test=dict(
        auc_worse=[probs.get(k, {}).get('worsen_normal_rain', {}).get('auc') for k in ('1', '2', '3')],
        auc_better=[probs.get(k, {}).get('improve_normal_rain', {}).get('auc') for k in ('1', '2', '3')],
        class_right=[probs.get(k, {}).get('class_with_step_rule') for k in ('1', '2', '3')],
        unchanged_right=[test.get('by_lead_weeks', {}).get(k, {}).get('persistence_cat') for k in ('1', '2', '3')]))


def rain():
    l = j('outputs/forecasts/precipitation/noaa-live/latest.json')
    if not l: return None
    r = j(l['path']); fr = (j('data/drought/farm-regions.json') or {}).get('farms', {})
    by = defaultdict(list); normal = defaultdict(list); src = defaultdict(lambda: defaultdict(int))
    for f in r['forecasts']:
        vals = [np.nan if v is None else v / 25.4 for v in f['daily_precipitation_mm']]
        for key in ('CT', fr.get(f['id'])):
            if key is None: continue
            by[key].append(vals)
            if f.get('history_42day_mean_mm') is not None: normal[key].append(f['history_42day_mean_mm'] / 25.4)
        for i, s in enumerate(f['day_sources']): src[i][s] += 1
        if f['id'] == 'yale-farm-new-haven': by['yale'].append(vals); normal['yale'].append((f.get('history_42day_mean_mm') or 0) / 25.4)
    kinds = []
    for i in range(len(r['forecast_dates'])):
        s = max(src[i], key=src[i].get) if src[i] else ''
        kinds.append('forecast' if s.startswith('NOAA NBM QPF') else 'estimate')
    return dict(dates=r['forecast_dates'], cycle=r['cycle'], kinds=kinds,
                areas={k: dict(daily=[round(float(np.nanmean(c)), 3) for c in zip(*v)], recent_daily_normal=round(float(np.mean(normal[k])), 3) if normal[k] else None)
                       for k, v in by.items()})


def fire():
    issue, run = issue_of('outputs/fire-danger-prospective/last-run.json')
    deep = j('data/fire-danger/deep-ratings.json') or {'ratings': {}}
    last = max(deep['ratings']) if deep['ratings'] else None
    val = (j('data/fire-danger/validation.json') or {}).get('results', {}).get('timber/median/buildup', {})
    f = issue['forecasts'][0] if issue and issue['forecasts'] else None
    return dict(issued=issue and issue['issued_at'], dates=f and f['dates'], levels=f and f['levels'], spread=f and f['spread_index'], buildup=f and f['buildup_index'],
                sources=f and ['forecast' if m.startswith('NOAA') else 'pattern' for m in f['methods']],
                official=dict(date=last, level=deep['ratings'][last]['level'], note=deep['ratings'][last].get('note')) if last else None,
                match=dict(exact=val.get('exact'), within_one=val.get('within_one'), n=val.get('dates')))


def soil():
    l = j('outputs/root-zone/live/latest.json')
    if not l: return None
    rows = list(csv.DictReader(open(ROOT / 'outputs/root-zone/live' / l['run'] / 'forecast.csv', encoding='utf-8')))
    by = defaultdict(list); latest_obs = []
    for r in rows:
        by[r['target_date']].append(float(r['prediction']) * 100)
        if r['horizon_days'] == '1' and r['newest_published_value']: latest_obs.append(float(r['newest_published_value']) * 100)
    dates = sorted(by)
    score = j(latest('outputs/root-zone/*/scoreboard.json').replace(str(ROOT) + '\\', '').replace(str(ROOT) + '/', '')) if latest('outputs/root-zone/*/scoreboard.json') else None
    return dict(issued=l['issue_date'], dates=dates, median=[round(float(np.median(by[d])), 1) for d in dates], low=[round(float(np.percentile(by[d], 10)), 1) for d in dates],
                high=[round(float(np.percentile(by[d], 90)), 1) for d in dates], latest=round(float(np.median(latest_obs)), 1) if latest_obs else None,
                latest_date=rows[0]['newest_published_date'] if rows else None, watersheds=l['watersheds_forecast'],
                test=dict((h, score['by_horizon'][h]) for h in ('1', '7', '14')) if score else None)


def rain_aware(kind):
    """Today's v2 (rain-aware) issue if its frozen adopt rule passed and it is sealed today; else None."""
    run = j('outputs/%s-v2-prospective/last-run.json' % kind)
    if run and run.get('adopted_for_app') and run.get('sealed_today'):
        r = j(run['sealed_today'])
        if r and r['forecasts']: return r
    return None


def streams():
    r = rain_aware('streamflow') or latest_issue('streamflow')
    if not r: return None
    return dict(issued=r['issued_at'], with_rain=r.get('model_version') == 'streamflow-v2', gauges=[dict(name=g['name'], dates=g['dates'], flow=[round(v, 1) for v in g['prediction']], last=g['baseline'][0], last_day=g['source_last_day'])
                                             for g in sorted(r['forecasts'], key=lambda g: g['name'])], withheld=len(r['unavailable']))


def wells():
    r = rain_aware('groundwater') or latest_issue('groundwater')
    if not r: return None
    return dict(issued=r['issued_at'], with_rain=r.get('model_version') == 'groundwater-v2', wells=[dict(name=g['name'], dates=g['dates'], depth=[round(v, 2) for v in g['prediction']], last=g['baseline'][0], last_day=g['source_last_day'])
                                            for g in r['forecasts']])


def coast():
    issue, run = issue_of('outputs/water-temp-prospective/last-run.json')
    names = {k: v['name'] for k, v in (j('data/water-temp/manifest.json') or {}).get('stations', {}).items()}
    test = (j('outputs/water-temp/latest.json') or {}).get('by_forecast_day', {})
    if not issue: return None
    return dict(issued=issue['issued_at'], stations=[dict(name=names.get(f['id'], f['id']), dates=f['dates'], temp_f=[round(v * 1.8 + 32, 1) for v in f['prediction']],
                                                          lo=[round(v * 1.8 + 32, 1) for v in f['lower']], hi=[round(v * 1.8 + 32, 1) for v in f['upper']],
                                                          last_f=round(f['baseline'][0] * 1.8 + 32, 1)) for f in issue['forecasts']],
                stopped=[names.get(m['id'], m['id']) for m in issue['unavailable']],
                test={h: dict(err_f=round(test[h]['mae_c'] * 1.8, 1), unchanged_f=round(test[h]['persistence_mae_c'] * 1.8, 1)) for h in ('1', '7', '14') if h in test})


def reservoirs():
    r = j('data/reservoirs/2024-11-12.json')
    if not r: return None
    return dict(report_date=r['report_date'], systems=[dict(name=s['name'], county=s['county_served'].title(), full=s['percent_full'], normal=s['historical_average_percent_full'],
                                                            pct_normal=s['percent_of_normal'], trend=s['trend'], date=s['reading_date'], status=s['status']) for s in r['systems']])


def accuracy():
    out = []
    def add(name, page, board, kind, unit, scale=1.0, fmt='%.2f'):
        b = j(board)
        rows = [x for x in (b or {}).get('by_variable_and_lead', []) if x['variable'] == kind]
        n = sum(x['comparisons'] for x in rows); d1 = next((x for x in rows if x['forecast_day'] == 1), None)
        out.append(dict(name=name, page=page, comparisons=n, day1=None if not d1 else dict(err=fmt % (d1['mae'] * scale), simple=fmt % (d1['baseline_mae'] * scale), unit=unit)))
    add('Rain (NOAA forecast shown in the app)', 'rain.html', 'outputs/noaa-rain-prospective/scoreboard.json', 'precipitation', 'in', 1 / 25.4)
    add('Rain (history-based baseline)', 'rain.html', 'outputs/prospective/scoreboard.json', 'precipitation', 'in', 1 / 25.4)
    add('Groundwater wells', 'wells.html', 'outputs/prospective/scoreboard.json', 'groundwater', 'ft')
    add('Groundwater wells, with NOAA rain (v2)', 'wells.html', 'outputs/groundwater-v2-prospective/scoreboard.json', 'groundwater', 'ft')
    add('Streams (Connecticut gauges)', 'streams.html', 'outputs/prospective/scoreboard.json', 'streamflow', 'cfs', fmt='%.1f')
    add('Streams, with NOAA rain (v2)', 'streams.html', 'outputs/streamflow-v2-prospective/scoreboard.json', 'streamflow', 'cfs', fmt='%.1f')
    add('Soil moisture', 'soil.html', 'outputs/root-zone-prospective/scoreboard.json', 'root-zone', '% soil water', 100, '%.2f')
    add('Fire danger', 'fire.html', 'outputs/fire-danger-prospective/scoreboard.json', 'fire-danger', 'classes')
    add('Coastal water temperature', 'coast.html', 'outputs/water-temp-prospective/scoreboard.json', 'water-temp', '°F', 1.8, '%.1f')
    add('Drought', 'drought.html', 'outputs/drought-prospective/scoreboard.json', 'drought', 'index points', fmt='%.1f')
    add('Drought, version 2 (with satellite plant stress)', 'drought.html', 'outputs/drought-v2-prospective/scoreboard.json', 'drought', 'index points', fmt='%.1f')
    return out


# ---------------------------------------------------------------- pages
MODELS = [('drought', 'Drought outlook', 'Will drought develop or ease?', 'drop'), ('rain', 'Rain', 'How much rain is coming', 'rain'),
          ('soil', 'Soil moisture', 'Water in the top 3 feet of soil', 'soil'), ('streams', 'Streams and rivers', 'Flow at river gauges', 'river'),
          ('wells', 'Groundwater', 'Water level in monitoring wells', 'well'), ('fire', 'Fire danger', 'Forest fire danger rating', 'fire'),
          ('coast', 'Coastal water', 'Long Island Sound temperature', 'wave'), ('reservoirs', 'Reservoirs', 'Drinking-water supply levels', 'dam'),
          ('accuracy', 'How accurate are we?', 'Forecasts checked against what happened', 'check'),
          ('report', "Today's report", 'Forecasts, new checks and what the learning versions changed', 'check')]
ICONS = {
    'drop': '<path d="M12 3c3 4.5 6 8 6 11a6 6 0 0 1-12 0c0-3 3-6.5 6-11z"/>',
    'rain': '<path d="M7 15a4 4 0 1 1 1-7.9A5 5 0 0 1 17.6 9 3.5 3.5 0 0 1 17 16H7z"/><path d="M8 19l-1 2M12 19l-1 2M16 19l-1 2"/>',
    'soil': '<path d="M3 9h18M3 14h18M3 19h18"/><path d="M12 9V4M9 6l3-2 3 2"/>',
    'river': '<path d="M3 8c3-2 6 2 9 0s6-2 9 0M3 13c3-2 6 2 9 0s6-2 9 0M3 18c3-2 6 2 9 0s6-2 9 0"/>',
    'well': '<path d="M6 21V10h12v11M4 10h16M8 10V6h8v4M12 13v5"/>',
    'fire': '<path d="M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-3 2-4 2-6 1 1 2 2 2 3 1-2 1-4 1-7z"/>',
    'wave': '<path d="M3 15c2-2 4-2 6 0s4 2 6 0 4-2 6 0M3 20c2-2 4-2 6 0s4 2 6 0 4-2 6 0"/><circle cx="16" cy="7" r="3"/>',
    'dam': '<path d="M3 19h18M5 19V9l14-2v12M5 13h14"/>',
    'check': '<path d="M5 12l4 4 10-10"/>'}

CSS = r"""
:root{--bg:#f6f7f4;--surface:#fff;--surface2:#eef1ea;--text:#1d2420;--muted:#5c665f;--line:#d9ded6;--accent:#2f6f4e;--accent-ink:#fff;
--rain:#2b6cb0;--warn:#b7791f;--bad:#c53030;--ok:#2f855a;--shadow:0 1px 2px rgba(0,0,0,.06),0 4px 14px rgba(0,0,0,.05);
--d0:#e8d84a;--d1:#f0b860;--d2:#e8891c;--d3:#d23c2a;--d4:#7a1d14;--f0:#3a8f5c;--f1:#3b7dc4;--f2:#d9a400;--f3:#e06c00;--f4:#c0262d}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121614;--surface:#1b201d;--surface2:#232a26;--text:#e8ece9;--muted:#a3ada6;--line:#323a35;--accent:#7cc59b;--accent-ink:#0d1a12;--rain:#7fb3ea;--shadow:none}}
:root[data-theme="dark"]{--bg:#121614;--surface:#1b201d;--surface2:#232a26;--text:#e8ece9;--muted:#a3ada6;--line:#323a35;--accent:#7cc59b;--accent-ink:#0d1a12;--rain:#7fb3ea;--shadow:none}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:17px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}.wrap{max-width:1040px;margin:0 auto;padding:0 16px}
header.top{background:var(--accent);color:var(--accent-ink)}header.top .wrap{display:flex;align-items:center;gap:12px;padding:14px 16px;flex-wrap:wrap}
header.top a{color:inherit;text-decoration:none;font-weight:700;font-size:1.15rem}header.top .sub{opacity:.85;font-size:.9rem;margin-left:auto}
h1{font-size:1.7rem;line-height:1.25;margin:22px 0 6px}h2{font-size:1.2rem;margin:28px 0 10px}p{margin:8px 0}
.lead{font-size:1.1rem;color:var(--muted)}.muted{color:var(--muted)}.small{font-size:.88rem}
.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:var(--shadow)}
.grid{display:grid;gap:14px}.g2{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}.g3{grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.picker{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0}
select{font:inherit;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:var(--surface);color:var(--text);min-width:min(100%,320px)}
.status{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:center}
.badge{display:inline-block;padding:4px 10px;border-radius:999px;font-weight:700;font-size:.9rem;color:#111;white-space:nowrap}
.big{font-size:2.2rem;font-weight:800;line-height:1}.chance{font-size:1.05rem}
.meter{height:12px;background:var(--surface2);border-radius:999px;overflow:hidden;margin:6px 0 2px}.meter>i{display:block;height:100%;background:var(--warn)}
.strip{display:grid;grid-template-columns:repeat(14,minmax(54px,1fr));gap:6px;overflow-x:auto;padding-bottom:6px}
.day{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:8px 4px;text-align:center;font-size:.85rem;min-width:54px}
.day .dw{font-weight:700}.day .rainbar{height:46px;display:flex;align-items:flex-end;justify-content:center;margin:6px 0}
.day .rainbar i{width:18px;background:var(--rain);border-radius:4px 4px 0 0;min-height:2px}.day.est .rainbar i{opacity:.45}
.day .fire{font-size:.72rem;border-radius:6px;padding:2px 0;margin-top:4px;color:#111;font-weight:700}
.day.map{outline:2px solid var(--warn);outline-offset:-2px}.day .mapnote{font-size:.7rem;color:var(--warn);font-weight:700}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.tile{display:flex;gap:12px;align-items:flex-start;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:16px;text-decoration:none;color:var(--text);box-shadow:var(--shadow);min-height:92px}
.tile:hover,.tile:focus-visible{border-color:var(--accent);outline:none}
.tile svg{flex:none;width:34px;height:34px;stroke:var(--accent);fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.tile b{display:block;font-size:1.05rem}.tile span{color:var(--muted);font-size:.9rem}
table{width:100%;border-collapse:collapse;font-size:.95rem}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:.82rem;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.03em}.num{text-align:right;font-variant-numeric:tabular-nums}
.tablewrap{overflow-x:auto}.chart svg{width:100%;height:auto;display:block}.chart text{fill:var(--muted);font-size:11px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:.85rem;color:var(--muted);margin-top:6px}.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.mapbox svg{width:100%;height:auto;max-height:360px}.mapbox path{stroke:var(--surface);stroke-width:1.5;cursor:pointer}.mapbox path.sel{stroke:var(--text);stroke-width:3}
.note{border-left:4px solid var(--warn);background:var(--surface);padding:10px 14px;border-radius:0 10px 10px 0;margin:14px 0}
details{margin:10px 0}summary{cursor:pointer;font-weight:600}footer{margin:40px 0 30px;color:var(--muted);font-size:.85rem}
.back{display:inline-block;margin-top:16px;text-decoration:none;font-weight:600}
@media (max-width:560px){h1{font-size:1.4rem}.big{font-size:1.8rem}.status{grid-template-columns:1fr}}
"""

JS = r"""
const $=s=>document.querySelector(s);const fmtDate=d=>{const t=new Date(d+'T12:00:00'),o={weekday:'short',month:'short',day:'numeric'};if(t.getFullYear()!=new Date().getFullYear())o.year='numeric';return t.toLocaleDateString(undefined,o)};
const dow=d=>new Date(d+'T12:00:00').toLocaleDateString(undefined,{weekday:'short'});const md=d=>new Date(d+'T12:00:00').toLocaleDateString(undefined,{month:'numeric',day:'numeric'});
const pct=x=>x==null?'–':Math.round(x*100)+'%';
const DROUGHT_COLORS={None:'#cfe3d4',D0:'var(--d0)',D1:'var(--d1)',D2:'var(--d2)',D3:'var(--d3)',D4:'var(--d4)'};
const DROUGHT_WORDS={None:'No drought',D0:'Abnormally dry',D1:'Moderate drought',D2:'Severe drought',D3:'Extreme drought',D4:'Exceptional drought'};
const FIRE_SHORT={LOW:'LOW',MODERATE:'MOD',HIGH:'HIGH','VERY HIGH':'V HIGH',EXTREME:'EXTR'};
const FIRE_COLORS={LOW:'var(--f0)',MODERATE:'var(--f1)',HIGH:'var(--f2)','VERY HIGH':'var(--f3)',EXTREME:'var(--f4)'};
function chanceWords(p){return p<.1?'Very unlikely':p<.25?'Unlikely':p<.5?'Possible':p<.75?'Likely':'Very likely'}
// Simple accessible SVG line chart: series [{name,values,color,dash}], optional band {lo,hi}
function lineChart(el,labels,series,opt={}){const W=640,H=opt.h||220,L=48,R=12,T=12,B=30;const all=series.flatMap(s=>s.values).concat(opt.band?opt.band.lo.concat(opt.band.hi):[]).filter(v=>v!=null);
let lo=Math.min(...all),hi=Math.max(...all);if(opt.zero)lo=Math.min(0,lo);if(hi-lo<1e-6){hi+=1;lo-=1}const pad=(hi-lo)*.1;lo-=pad;hi+=pad;
const x=i=>L+(W-L-R)*(labels.length<2?0:i/(labels.length-1));const y=v=>opt.invert?T+(H-T-B)*(v-lo)/(hi-lo):H-B-(H-T-B)*(v-lo)/(hi-lo);
let s=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${opt.label||''}">`;for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4;s+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${L-6}" y="${y(v)+4}" text-anchor="end">${(+v.toFixed(opt.dp??1))}</text>`}
labels.forEach((d,i)=>{if(labels.length<=14||i%2==0)s+=`<text x="${x(i)}" y="${H-10}" text-anchor="middle">${md(d)}</text>`});
if(opt.band){let p=opt.band.hi.map((v,i)=>`${x(i)},${y(v)}`).join(' ')+' '+opt.band.lo.map((v,i)=>`${x(i)},${y(v)}`).reverse().join(' ');s+=`<polygon points="${p}" fill="var(--accent)" opacity=".13"/>`}
series.forEach(se=>{const pts=se.values.map((v,i)=>v==null?null:`${x(i)},${y(v)}`).filter(Boolean).join(' ');s+=`<polyline points="${pts}" fill="none" stroke="${se.color}" stroke-width="2.5" ${se.dash?'stroke-dasharray="5 4"':''}/>`;
se.values.forEach((v,i)=>{if(v!=null)s+=`<circle cx="${x(i)}" cy="${y(v)}" r="3" fill="${se.color}"><title>${fmtDate(labels[i])}: ${v} ${opt.unit||''}</title></circle>`})});
el.innerHTML=s+'</svg>';if(series.length>1||opt.band){el.insertAdjacentHTML('beforeend','<div class="legend">'+series.map(se=>`<span><i style="background:${se.color}"></i>${se.name}</span>`).join('')+(opt.band?`<span><i style="background:var(--accent);opacity:.3"></i>${opt.band.name}</span>`:'')+'</div>')}}
"""


def page(name, title, body, data, script):
    now = datetime.now(LOCAL).strftime('%B %d, %Y at %I:%M %p').replace(' 0', ' ')
    nav = '' if name == 'index' else '<a class="back" href="index.html">&larr; Back to the outlook</a>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · Ahead of the Storm</title><link rel="stylesheet" href="style.css"></head><body>
<header class="top"><div class="wrap"><a href="index.html">Ahead of the Storm</a><span class="sub">Connecticut farm water outlook</span></div></header>
<main class="wrap">{nav}{body}{nav}
<footer>Updated {now}. Research forecasts from public data (NOAA, NASA, USGS, Connecticut DEEP and DPH, U.S. Drought Monitor), checked every day against what happens.
They describe conditions; they are not instructions for your farm. Always follow official warnings and local rules.</footer></main>
<script src="app.js"></script><script>const DATA={json.dumps(data, separators=(',', ':'), default=str)};{script}</script></body></html>"""


def tiles(skip=None):
    out = '<div class="tiles">'
    for key, title, sub, icon in MODELS:
        if key == skip: continue
        out += f'<a class="tile" href="{key}.html"><svg viewBox="0 0 24 24" aria-hidden="true">{ICONS[icon]}</svg><div><b>{title}</b><span>{sub}</span></div></a>'
    return out + '</div>'


def build():
    APP.mkdir(exist_ok=True)
    (APP / 'style.css').write_text(CSS, encoding='utf-8'); (APP / 'app.js').write_text(JS, encoding='utf-8')
    D = drought(); R = rain(); F = fire(); S = soil(); ST = streams(); W = wells(); C = coast(); RS = reservoirs(); A = accuracy()
    shapes = regions_svg()
    write = lambda n, html: (APP / (n + '.html')).write_text(html, encoding='utf-8')

    # ---------------- home
    home = dict(drought=D, rain=R, fire=dict(dates=F['dates'], levels=F['levels'], official=F['official']) if F else None, shapes=shapes)
    write('index', page('index', 'Your 14-day outlook', """
<h1>Your 14-day drought outlook</h1><p class="lead">Is your area heading toward drought in the next two weeks? Pick your area to see.</p>
<div class="picker"><label for="area"><b>Area</b></label><select id="area"></select></div>
<div class="grid g2"><section class="card" aria-live="polite"><div class="status"><div><span class="badge" id="nowBadge"></span></div><div><div class="muted small">Drought right now</div><div class="big" id="nowWords"></div></div></div>
<div id="chances" style="margin-top:14px"></div><p class="small muted" id="nowNote"></p></section>
<section class="card mapbox"><b>Chance drought gets worse by <span id="mapDate"></span></b><div id="map"></div><div class="legend"><span><i style="background:#f6e7c8"></i>low</span><span><i style="background:#f0a14a"></i>higher</span><span>Tap a region to select it</span></div></section></div>
<h2>Day by day</h2><p class="muted small">Rain each day (taller bar = more rain; faded bars are rough estimates beyond the weather forecast), the forest fire danger, and the two days the U.S. Drought Monitor map is updated.</p>
<div class="strip" id="strip"></div><div id="stripnote" class="small muted"></div>
<h2>See each part of the forecast</h2>""" + tiles() + """
<div class="note small">How this works: every night the app pulls fresh public data, makes its forecasts, and seals them before the days arrive. Later it checks them against what really happened. See <a href="accuracy.html">How accurate are we?</a></div>""",
        home, r"""
const A=DATA.drought.areas, ids=Object.keys(A).sort((a,b)=>a=='CT'?-1:b=='CT'?1:A[a].name.localeCompare(A[b].name));
const sel=$('#area');sel.innerHTML=ids.map(i=>`<option value="${i}">${A[i].name}${A[i].farms?` (${A[i].farms.toLocaleString()} mapped farms)`:''}</option>`).join('')+(DATA.drought.areas['09170|South Central Connecticut Planning Region']?'<option value="yale">Yale Farm, New Haven (South Central region)</option>':'');
let cur=localStorage.getItem('area')||'CT';try{if(!A[cur]&&cur!='yale')cur='CT'}catch(e){cur='CT'};sel.value=cur;
function show(id){try{localStorage.setItem('area',id)}catch(e){};const key=id=='yale'?'09170|South Central Connecticut Planning Region':id,a=A[key];
 $('#nowBadge').textContent=a.now;$('#nowBadge').style.background=DROUGHT_COLORS[a.now];$('#nowWords').textContent=DROUGHT_WORDS[a.now];
 $('#chances').innerHTML=a.dates.map((d,i)=>`<div class="chance"><b>${chanceWords(a.worse[i])}</b> to get worse by ${fmtDate(d)} &mdash; ${pct(a.worse[i])} chance<div class="meter"><i style="width:${Math.max(2,a.worse[i]*100)}%"></i></div>`+
   (a.now!='None'?`<span class="small muted">Chance it eases: ${pct(a.better[i])}</span>`:'')+`</div>`).join('')+`<p><b>Expected:</b> ${a.classes.map((c,i)=>`${DROUGHT_WORDS[c].toLowerCase()} on ${fmtDate(a.dates[i])}`).join(', then ')}.</p>`;
 $('#nowNote').textContent=`Based on the U.S. Drought Monitor map for ${fmtDate(a.map_date)}.`+(id=='yale'?' Yale Farm uses its region’s forecast.':'');
 document.querySelectorAll('#map path').forEach(p=>p.classList.toggle('sel',p.dataset.id==key));
 const r=DATA.rain&&(DATA.rain.areas[id=='yale'?'yale':key]||DATA.rain.areas.CT);strip(r)}
function strip(r){const f=DATA.fire,dates=r?DATA.rain.dates:(f?f.dates:[]),maps=A.CT.dates,max=Math.max(.25,...(r?r.daily:[0]));
 $('#strip').innerHTML=dates.map((d,i)=>{const v=r?r.daily[i]:null,fi=f&&f.dates?f.dates.indexOf(d):-1,m=maps.indexOf(d);
  return `<div class="day ${r&&DATA.rain.kinds[i]=='estimate'?'est':''} ${m>=0?'map':''}"><div class="dw">${dow(d)}</div><div class="small muted">${md(d)}</div>
  <div class="rainbar" title="${v==null?'':v.toFixed(2)+' in'}"><i style="height:${v==null?2:Math.max(2,44*v/max)}px"></i></div><div class="small">${v==null?'–':v<0.01?'dry':v.toFixed(2)+'"'}</div>
  ${fi>=0?`<div class="fire" title="Fire danger ${f.levels[fi]}" style="background:${FIRE_COLORS[f.levels[fi]]}">${FIRE_SHORT[f.levels[fi]]}</div>`:''}${m>=0?'<div class="mapnote">Drought map</div>':''}</div>`}).join('');
 $('#stripnote').innerHTML=`Fire danger (MOD = moderate, V HIGH = very high, EXTR = extreme): <span class="badge" style="background:var(--f0)">LOW</span> <span class="badge" style="background:var(--f1)">MODERATE</span> <span class="badge" style="background:var(--f2)">HIGH</span> <span class="badge" style="background:var(--f3)">VERY HIGH</span> <span class="badge" style="background:var(--f4)">EXTREME</span>`}
const sh=DATA.shapes;let xs=[],ys=[];Object.values(sh).forEach(d=>d.replace(/[MLZ]/g,' ').trim().split(/\s+/).forEach(p=>{const[a,b]=p.split(',').map(Number);xs.push(a);ys.push(b)}));
const vb=`${Math.min(...xs)-4} ${Math.min(...ys)-4} ${Math.max(...xs)-Math.min(...xs)+8} ${Math.max(...ys)-Math.min(...ys)+8}`;
const col=p=>`hsl(${32-14*Math.min(1,p/.5)},${70+20*Math.min(1,p/.5)}%,${88-38*Math.min(1,p/.5)}%)`;
$('#map').innerHTML=`<svg viewBox="${vb}" role="img" aria-label="Map of Connecticut planning regions">`+Object.entries(sh).map(([id,d])=>A[id]?`<path d="${d}" data-id="${id}" fill="${col(A[id].worse[1])}"><title>${A[id].name}: ${pct(A[id].worse[1])} chance of worse drought</title></path>`:'').join('')+'</svg>';
$('#mapDate').textContent=fmtDate(A.CT.dates[1]);document.querySelectorAll('#map path').forEach(p=>p.onclick=()=>{sel.value=p.dataset.id;show(p.dataset.id)});
sel.onchange=()=>show(sel.value);show(sel.value);"""))

    # ---------------- drought detail
    write('drought', page('drought', 'Drought outlook', """
<h1>Drought outlook</h1><p class="lead">The U.S. Drought Monitor publishes a drought map every Thursday (for that Tuesday). We forecast the next two maps for Connecticut and its 9 regions.</p>
<div class="card tablewrap"><table id="t"></table></div>
<h2>What the drought levels mean</h2><div class="grid g3" id="levels"></div>
<h2>Plant stress seen from space</h2><div class="card" id="veg"></div>
<h2>How sure are we?</h2><div class="card" id="sure"></div>
<details><summary>What goes into this forecast</summary><p>Rain (recent and NOAA's forecast for the coming days), river flows at 109 gauges, groundwater wells, soil moisture, the fire danger "build up" of dry fuels, coastal water temperature, the Palmer Drought Severity Index, and the current Drought Monitor map and how it has been changing. Each is compared with what's normal for the time of year.</p>
<p>Drought maps are drawn by experts and change slowly, so the forecast focuses on the <b>chance</b> that your region's drought level changes.</p><p id="vernote" class="small muted"></p></details>""" + '<h2>Other parts of the forecast</h2>' + tiles('drought'),
        D, r"""
const A=DATA.areas,ids=Object.keys(A).sort((a,b)=>a=='CT'?-1:b=='CT'?1:A[a].name.localeCompare(A[b].name)),d=A.CT.dates;
$('#t').innerHTML=`<thead><tr><th>Area</th><th>Now</th><th>${fmtDate(d[0])}</th><th>${fmtDate(d[1])}</th><th class="num">Farms</th></tr></thead><tbody>`+ids.map(i=>{const a=A[i];
 return `<tr><td>${a.name}</td><td><span class="badge" style="background:${DROUGHT_COLORS[a.now]}">${a.now}</span></td>`+a.classes.map((c,k)=>`<td><span class="badge" style="background:${DROUGHT_COLORS[c]}">${c}</span><div class="small muted">${pct(a.worse[k])} chance worse</div></td>`).join('')+`<td class="num">${a.farms?a.farms.toLocaleString():''}</td></tr>`}).join('')+'</tbody>';
$('#levels').innerHTML=Object.entries(DROUGHT_WORDS).map(([k,v])=>`<div class="card"><span class="badge" style="background:${DROUGHT_COLORS[k]}">${k}</span> <b>${v}</b></div>`).join('');
const t=DATA.test;$('#sure').innerHTML=`<p>We tested the forecast on 2019–2026, years it never saw while learning (including the 2020, 2022 and 2024 droughts).</p><ul>
<li>When drought really got worse, our chance was higher than on other weeks <b>${pct(t.auc_worse[0])}</b> of the time one week ahead and <b>${pct(t.auc_worse[1])}</b> two weeks ahead.</li>
<li>When drought really eased, the same was true <b>${pct(t.auc_better[0])}</b> and <b>${pct(t.auc_better[1])}</b> of the time.</li>
<li>The drought level itself was right <b>${pct(t.class_right[0])}</b> of the time one week ahead (assuming no change would be right ${pct(t.unchanged_right[0])}).</li></ul>
<p class="small muted">This means the forecast is good at warning which weeks are likely to change, but it can't promise exactly what next week's map will say.</p>`;
const V=DATA.vegdri,vw=v=>v<=-4?'Extreme stress':v<=-3?'Severe stress':v<=-2?'Moderate stress':v<=-1?'Early stress':v<1?'Near normal':'Unusually moist';
$('#veg').innerHTML=V.CT?`<p>USGS's Vegetation Drought Response Index (VegDRI) compares how green crops, pasture and forest look from satellites with what's normal, together with recent weather. Week ending ${fmtDate(V.CT.week_end)}.</p><div class="tablewrap"><table><thead><tr><th>Area</th><th>Plants</th><th class="num">Land showing stress</th></tr></thead><tbody>`+
 ids.filter(i=>V[i]).map(i=>`<tr><td>${A[i].name}</td><td>${vw(V[i].mean)}</td><td class="num">${V[i].stressed}%</td></tr>`).join('')+'</tbody></table></div>':'<p class="muted">Satellite plant data not downloaded yet.</p>';
$('#vernote').textContent=DATA.version=='v2'?'This forecast also uses the satellite plant stress index above (version 2).':'Satellite plant stress is shown for reference. A version of the forecast that uses it is being tested; it replaces this one only if it scores better on 2015–2018 checks.';"""))

    # ---------------- rain
    write('rain', page('rain', 'Rain', """
<h1>Rain</h1><p class="lead">How much rain is expected each day for the next 14 days, from NOAA's National Blend of Models weather forecast.</p>
<div class="picker"><label for="area"><b>Area</b></label><select id="area"></select></div>
<div class="card"><div class="chart" id="c"></div><p id="tot"></p></div>
<div class="note small">Days marked as estimates are beyond NOAA's detailed forecast (about 10 days). They use NOAA's chance of rain and recent rainfall patterns, so treat them as rough.</div>
<h2>How sure are we?</h2><div class="card"><p>Weather forecasts are usually good for the first few days and less certain after a week. The app checks NOAA's rain forecasts against measured rainfall over time; see <a href="accuracy.html">How accurate are we?</a></p></div>""" + '<h2>Other parts of the forecast</h2>' + tiles('rain'),
        dict(rain=R, names={k: v['name'] for k, v in D['areas'].items()}), r"""
const R=DATA.rain,ids=Object.keys(R.areas).filter(k=>k!='yale').sort((a,b)=>a=='CT'?-1:b=='CT'?1:(DATA.names[a]||a).localeCompare(DATA.names[b]||b));
$('#area').innerHTML=ids.map(i=>`<option value="${i}">${DATA.names[i]||i}</option>`).join('')+'<option value="yale">Yale Farm, New Haven</option>';
let cur=localStorage.getItem('area')||'CT';if(!R.areas[cur])cur='CT';$('#area').value=cur;
function show(id){try{localStorage.setItem('area',id)}catch(e){};const a=R.areas[id],est=R.kinds.map((k,i)=>k=='estimate'?a.daily[i]:null),fc=R.kinds.map((k,i)=>k=='forecast'?a.daily[i]:null);
 lineChart($('#c'),R.dates,[{name:'NOAA forecast',values:fc,color:'var(--rain)'},{name:'Rough estimate',values:est,color:'var(--rain)',dash:1}],{unit:'inches',zero:1,dp:2,label:'Daily rain forecast in inches'});
 const tot=a.daily.reduce((s,v)=>s+(v||0),0),norm=a.recent_daily_normal?a.recent_daily_normal*14:null;
 $('#tot').innerHTML=`<b>About ${tot.toFixed(1)} inches</b> expected over the 14 days`+(norm?`, compared with about ${norm.toFixed(1)} inches over a typical 14 days recently.`:'.')}
$('#area').onchange=e=>show(e.target.value);show(cur);"""))

    # ---------------- soil
    write('soil', page('soil', 'Soil moisture', """
<h1>Soil moisture</h1><p class="lead">How much water is in the top 3 feet (1 meter) of soil, averaged over Connecticut's watersheds, for the next 14 days.</p>
<div class="card"><div class="chart" id="c"></div><p id="s"></p></div>
<details><summary>What do the numbers mean?</summary><p>30% means 30% of the soil's volume is water. In Connecticut this usually ranges from about 20% (dry late summer) to about 40% (wet spring). The shaded band shows the range across watersheds, from the drier ones to the wetter ones.</p>
<p>These are NASA computer-model estimates for whole watersheds, not readings from a sensor in your field.</p></details>
<h2>How sure are we?</h2><div class="card" id="sure"></div>""" + '<h2>Other parts of the forecast</h2>' + tiles('soil'),
        S, r"""
const S=DATA;lineChart($('#c'),S.dates,[{name:'Typical watershed',values:S.median,color:'var(--accent)'}],{unit:'% water',band:{lo:S.low,hi:S.high,name:'Drier to wetter watersheds'},label:'Soil water forecast'});
$('#s').innerHTML=`Latest measured (${fmtDate(S.latest_date)}): <b>${S.latest}%</b> water in a typical watershed. In 14 days: about <b>${S.median[S.median.length-1]}%</b>.`;
const t=S.test;$('#sure').innerHTML=t?`<p>Tested on 2015–2020, years kept out of training: the forecast was off by about <b>${(t['1'].mae*100).toFixed(1)}</b> percentage points one day ahead and <b>${(t['14'].mae*100).toFixed(1)}</b> two weeks ahead (assuming no change: ${(t['14'].persistence_mae*100).toFixed(1)}).</p>`:'<p>Test results not available.</p>';"""))

    # ---------------- streams
    write('streams', page('streams', 'Streams and rivers', """
<h1>Streams and rivers</h1><p class="lead">Expected river flow at USGS gauges for the next 14 days.</p><p class="small muted" id="how"></p>
<div class="picker"><label for="g"><b>River gauge</b></label><select id="g"></select></div>
<div class="card"><div class="chart" id="c"></div><p id="s"></p></div>
<div class="note small">These forecasts use only each river's past flow, so they can't see a coming storm. Flow is in cubic feet per second (cfs).</div>""" + '<h2>Other parts of the forecast</h2>' + tiles('streams'),
        ST, r"""
$('#how').textContent=DATA&&DATA.with_rain?"Uses each river's recent flow, the rain that has fallen in its drainage area, and NOAA's rain forecast for the next 10 days.":"Based on each river's own recent flow history.";const G=DATA?DATA.gauges:[];$('#g').innerHTML=G.map((g,i)=>`<option value="${i}">${g.name}</option>`).join('');
const mill=G.findIndex(g=>/MILL RIVER/i.test(g.name));if(mill>=0)$('#g').value=mill;
function show(i){const g=G[i];lineChart($('#c'),g.dates,[{name:'Expected flow',values:g.flow,color:'var(--rain)'}],{unit:'cfs',zero:1,label:'Expected river flow'});
 const ch=(g.flow[g.flow.length-1]-g.last)/g.last;$('#s').innerHTML=`Last reading (${fmtDate(g.last_day)}): <b>${g.last} cfs</b>. Expected in 14 days: <b>${g.flow[g.flow.length-1]} cfs</b> (${ch>.1?'higher':ch<-.1?'lower':'about the same'}).`}
if(G.length){$('#g').onchange=e=>show(e.target.value);show($('#g').value)}else $('#c').textContent='No stream forecast is available yet today.';"""))

    # ---------------- wells
    write('wells', page('wells', 'Groundwater', """
<h1>Groundwater</h1><p class="lead">Water level in USGS monitoring wells for the next 14 days. Measured as depth below the ground: a bigger number means the water is lower.</p><p class="small muted" id="how"></p>
<div class="picker"><label for="g"><b>Well</b></label><select id="g"></select></div>
<div class="card"><div class="chart" id="c"></div><p id="s"></p></div>
<div class="note small">These are a few public monitoring wells, not the water under your farm. Wells nearby can tap different underground layers.</div>""" + '<h2>Other parts of the forecast</h2>' + tiles('wells'),
        W, r"""
$('#how').textContent=DATA&&DATA.with_rain?"Uses each well's recent levels, the rain that has fallen nearby, and NOAA's rain forecast for the next 10 days.":"Based on each well's own recent levels.";
const G=DATA?DATA.wells:[];$('#g').innerHTML=G.map((g,i)=>`<option value="${i}">${g.name.replace(/^CT- ?\w+ +\d+ +/,'')}</option>`).join('');
function show(i){const g=G[i];lineChart($('#c'),g.dates,[{name:'Depth to water',values:g.depth,color:'var(--accent)'}],{unit:'feet below ground',invert:1,dp:2,label:'Expected depth to water'});
 const ch=g.depth[g.depth.length-1]-g.last;$('#s').innerHTML=`Last reading (${fmtDate(g.last_day)}): water <b>${g.last.toFixed(1)} feet</b> below ground. In 14 days: <b>${g.depth[g.depth.length-1].toFixed(1)} feet</b> &mdash; ${ch>0.05?'water level dropping':ch<-0.05?'water level rising':'about the same'}.`}
if(G.length){$('#g').onchange=e=>show(e.target.value);show(0)}"""))

    # ---------------- fire
    write('fire', page('fire', 'Fire danger', """
<h1>Forest fire danger</h1><p class="lead">Connecticut's statewide forest fire danger for the next 14 days, on the same scale Connecticut DEEP uses.</p>
<div class="card" id="off"></div><h2>Next 14 days</h2><div class="strip" id="strip"></div>
<div class="card"><div class="chart" id="c"></div><p class="small muted">The <b>build-up</b> number tracks how dry forest fuels have become since the last good rain; the <b>spread</b> number reflects wind and dryness that day.</p></div>
<h2>How sure are we?</h2><div class="card" id="sure"></div>
<div class="note small">This is not a burn permit decision. Always check DEEP's official rating and local open-burning rules before burning.</div>""" + '<h2>Other parts of the forecast</h2>' + tiles('fire'),
        F, r"""
const F=DATA;if(F.official)$('#off').innerHTML=`<div class="muted small">Latest official rating from Connecticut DEEP (${fmtDate(F.official.date)})</div><span class="badge" style="background:${FIRE_COLORS[F.official.level]}">${F.official.level}</span> ${F.official.note||''}`;
if(F.dates){$('#strip').innerHTML=F.dates.map((d,i)=>`<div class="day"><div class="dw">${dow(d)}</div><div class="small muted">${md(d)}</div><div class="fire" title="${F.levels[i]}" style="background:${FIRE_COLORS[F.levels[i]]};margin-top:10px">${FIRE_SHORT[F.levels[i]]}</div><div class="small muted">${F.sources[i]=='forecast'?'weather forecast':'past patterns'}</div></div>`).join('');
 const n=F.spread.filter(v=>v!=null).length;lineChart($('#c'),F.dates.slice(0,n),[{name:'Build-up (dryness of fuels)',values:F.buildup.slice(0,n),color:'var(--f3)'},{name:'Spread (wind and dryness)',values:F.spread.slice(0,n),color:'var(--f1)'}],{zero:1,label:'Fire danger indexes'})}
$('#sure').innerHTML=`<p>We recalculate DEEP's method from airport weather. Checked against ${F.match.n} of DEEP's published ratings, it gave the same rating <b>${pct(F.match.exact)}</b> of the time and was within one level <b>${pct(F.match.within_one)}</b> of the time.</p><p class="small muted">Days after NOAA's weather forecast runs out (about 10 days) use past patterns and are less certain.</p>`;"""))

    # ---------------- coast
    write('coast', page('coast', 'Coastal water', """
<h1>Coastal water temperature</h1><p class="lead">Daily average water temperature at NOAA stations along Long Island Sound for the next 14 days.</p>
<div class="picker"><label for="g"><b>Station</b></label><select id="g"></select></div>
<div class="card"><div class="chart" id="c"></div><p id="s"></p></div>
<h2>How sure are we?</h2><div class="card" id="sure"></div><p class="small muted" id="stop"></p>""" + '<h2>Other parts of the forecast</h2>' + tiles('coast'),
        C, r"""
const G=DATA?DATA.stations:[];$('#g').innerHTML=G.map((g,i)=>`<option value="${i}">${g.name.replace(/ \(NOAA.*$/,'')}</option>`).join('');
function show(i){const g=G[i];lineChart($('#c'),g.dates,[{name:'Expected',values:g.temp_f,color:'var(--rain)'}],{unit:'°F',band:{lo:g.lo,hi:g.hi,name:'Likely range'},label:'Water temperature forecast'});
 $('#s').innerHTML=`Yesterday: <b>${g.last_f}°F</b>. In 14 days: about <b>${g.temp_f[g.temp_f.length-1]}°F</b>.`}
if(G.length){$('#g').onchange=e=>show(e.target.value);show(0)}
const t=DATA&&DATA.test;if(t&&t['14'])$('#sure').innerHTML=`<p>Tested on 2022–2025: off by about <b>${t['1'].err_f}°F</b> one day ahead and <b>${t['14'].err_f}°F</b> two weeks ahead (assuming no change: ${t['14'].unchanged_f}°F).</p>`;
if(DATA&&DATA.stopped.length)$('#stop').textContent='No longer reporting, so no forecast: '+DATA.stopped.join('; ')+'.';"""))

    # ---------------- reservoirs
    write('reservoirs', page('reservoirs', 'Reservoirs', """
<h1>Drinking-water reservoirs</h1><p class="lead">How full public water systems' reservoirs were in Connecticut Department of Public Health's latest report we have.</p>
<div class="note" id="age"></div><div class="card tablewrap"><table id="t"></table></div>
<p class="small muted">There is no forecast here yet: the state publishes these readings only occasionally, which is not enough history to forecast from. One row per water system, not per reservoir.</p>""" + '<h2>Other parts of the forecast</h2>' + tiles('reservoirs'),
        RS, r"""
const R=DATA;$('#age').innerHTML=`<b>This report is from ${fmtDate(R.report_date)}.</b> It is old and may not reflect today's levels.`;
$('#t').innerHTML='<thead><tr><th>Water system</th><th>County</th><th class="num">% full</th><th class="num">Normal % full</th><th>Trend</th></tr></thead><tbody>'+R.systems.sort((a,b)=>a.pct_normal-b.pct_normal).map(s=>`<tr><td>${s.name}<div class="small muted">${s.status||''}</div></td><td>${s.county}</td><td class="num">${s.full}</td><td class="num">${s.normal}</td><td>${s.trend=='down'?'falling':s.trend=='up'?'rising':s.trend||''}</td></tr>`).join('')+'</tbody>';"""))

    # ---------------- accuracy
    write('accuracy', page('accuracy', 'How accurate are we?', """
<h1>How accurate are we?</h1><p class="lead">Every forecast is locked (sealed) before the days it predicts. When the real measurements arrive, we compare. We never change a forecast afterwards.</p>
<div class="card tablewrap"><table id="t"></table></div>
<p class="small muted">"Simple guess" means assuming tomorrow will be like today. A good forecast should usually beat it. Comparisons arrive a few days after each forecast, because measurements are published with a delay, so early numbers are based on very few days.</p>
<div class="card"><b>Learning versions.</b> Beside each forecast, a "learning" copy adjusts itself every day using these comparisons. If it proves better over time, it can replace the original.</div>""" + '<h2>Other parts of the forecast</h2>' + tiles('accuracy'),
        A, r"""
$('#t').innerHTML='<thead><tr><th>Forecast</th><th class="num">Checks so far<div class="small" style="text-transform:none">one per place per day</div></th><th>Next-day error vs simple guess</th></tr></thead><tbody>'+DATA.map(r=>`<tr><td><a href="${r.page}">${r.name}</a></td><td class="num">${r.comparisons.toLocaleString()}</td><td>${r.day1?`${r.day1.err} vs ${r.day1.simple} ${r.day1.unit}`:'<span class="muted">waiting for measurements</span>'}</td></tr>`).join('')+'</tbody>';"""))
    # ---------------- daily report (outputs/daily-reports, written after every daily run)
    latest = j('outputs/daily-reports/latest.json'); REP = j(latest['json']) if latest else None
    write('report', page('report', "Today's report", """
<h1>Today's report</h1><p class="lead" id="when"></p><div id="rep"></div>""" + '<h2>Other parts of the forecast</h2>' + tiles('report'),
        REP, r"""
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
if(!DATA){$('#when').textContent='No report yet. One is written after every daily forecast run.';}
else{$('#when').textContent='Written '+DATA.generated_local+' (Connecticut time), after the latest daily run.';
$('#rep').innerHTML=DATA.sections.map(s=>`<h2>${esc(s.title)}</h2><div class="card tablewrap"><table><thead><tr>${s.table.head.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${
 s.table.rows.map(r=>`<tr>${r.map(c=>`<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>${(s.notes||[]).map(n=>`<p class="small muted">${esc(n)}</p>`).join('')}`).join('');}"""))
    return dict(pages=sorted(p.name for p in APP.glob('*.html')))


if __name__ == '__main__':
    print(json.dumps(build()))
