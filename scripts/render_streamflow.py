"""Daily discharge against official USGS seasonal percentiles; gaps are never joined."""
import math
from datetime import date,timedelta
from statewide_common import ROOT,read

O=ROOT/'outputs/streamflow';s=read(O/'summary.json');r=next(r for r in read(O/'gauges.json') if r['gauge_id']=='USGS-01196620')
start=date.fromisoformat(s['start']);end=date.fromisoformat(s['end']);days=[start+timedelta(days=i) for i in range((end-start).days+1)]
actual={v['date']:v['flow_cfs'] for v in r['history']};normals={}
for f in read(ROOT/'data/streamflow/percentiles.json')['features']:
 for group in f['properties']['data']:
  if group['parent_time_series_id']!=r['series_id']:continue
  for v in group['values']:
   if v['time_of_year_type']!='day_of_year' or v['computation']!='percentile' or v['sample_count']<10:continue
   thresholds=dict(zip(v['percentiles'],map(float,v['values'])))
   if all(math.isfinite(thresholds[str(p)]) for p in [25,50,75]):normals[v['time_of_year']]=thresholds
ymax=math.ceil(max([0,*actual.values(),*[v['75'] for v in normals.values()]])/25)*25
left,top,width,height=95,185,1040,390
def xy(i,value):return left+i/(len(days)-1)*width,top+height-value/ymax*height
def coords(points):return ' '.join(f'{x:.2f},{y:.2f}' for x,y in points)
def runs(predicate):
 current=[]
 for i,d in enumerate(days):
  if predicate(d):current.append((i,d))
  elif current:yield current;current=[]
 if current:yield current
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="850"><rect width="1200" height="850" fill="#f8faf7"/><g font-family="Segoe UI,Arial" fill="#173d36">',
 '<text x="60" y="50" font-size="29" font-weight="bold">Mill River near Hamden | Streamflow in seasonal context</text>',
 f'<text x="60" y="85" font-size="18">{s["start"]}–{s["end"]} • USGS 01196620 • Daily mean discharge</text>',
 '<text x="60" y="118" font-size="17">A nearby gauge in Yale Farm’s mapped watershed; the farm’s river connection is not established.</text>',
 '<text x="60" y="150" font-size="16">Cubic feet per second</text>']
for tick in range(6):
 value=ymax*tick/5;_,y=xy(0,value);svg.append(f'<line x1="{left}" x2="{left+width}" y1="{y}" y2="{y}" stroke="#d9e2de"/><text x="{left-12}" y="{y+5}" text-anchor="end" font-size="15">{value:g}</text>')
for run in runs(lambda d:d.strftime('%m-%d') in normals):
 upper=[xy(i,normals[d.strftime('%m-%d')]['75']) for i,d in run];lower=[xy(i,normals[d.strftime('%m-%d')]['25']) for i,d in reversed(run)]
 svg.append(f'<polygon points="{coords(upper+lower)}" fill="#c9e2d7"/>')
 median=[xy(i,normals[d.strftime('%m-%d')]['50']) for i,d in run];svg.append(f'<polyline points="{coords(median)}" fill="none" stroke="#587766" stroke-width="2" stroke-dasharray="6,4"/>')
for run in runs(lambda d:str(d) in actual):
 points=[xy(i,actual[str(d)]) for i,d in run];svg.append(f'<polyline points="{coords(points)}" fill="none" stroke="#126f9e" stroke-width="2.5"/>')
for i,d in enumerate(days):
 if i in [0,len(days)-1] or d.day==1:
  x,y=xy(i,0);svg.append(f'<text x="{x}" y="{y+27}" text-anchor="middle" font-size="15">{d:%b %d}</text>')
svg.extend(['<rect x="70" y="640" width="30" height="15" fill="#c9e2d7"/><text x="110" y="654" font-size="16">Historical middle half (25th–75th percentiles)</text>',
 '<line x1="650" x2="690" y1="647" y2="647" stroke="#126f9e" stroke-width="3"/><text x="700" y="654" font-size="16">Observed daily mean (recent values provisional)</text>',
 '<line x1="70" x2="100" y1="680" y2="680" stroke="#587766" stroke-width="2" stroke-dasharray="6,4"/><text x="110" y="686" font-size="16">Historical median for each day of year</text>',
 f'<text x="60" y="729" font-size="19" font-weight="bold">November 1: {r["latest"]["flow_cfs"]:.1f} cubic feet/second • Historical median: {r["seasonal_context"]["thresholds_cfs"]["50"]:.2f}</text>',
 '<text x="60" y="763" font-size="16">Seasonal thresholds use approved historical USGS data. This is not an irrigation allocation or drought forecast.</text>',
 '<text x="60" y="810" font-size="14">USGS Water Data APIs and Statistics API • Snapshot November 2, 2026 • api.waterdata.usgs.gov</text></g></svg>'])
(O/'mill-river-streamflow.svg').write_text(''.join(svg),encoding='utf-8');print('Saved Mill River streamflow and seasonal-percentile chart.')
