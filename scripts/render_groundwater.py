from html import escape
from shapely.geometry import shape
from statewide_common import ROOT,read

out=ROOT/'outputs/groundwater';summary=read(out/'summary.json');records=read(out/'wells.json');coverage={r['town']:r for r in read(out/'town-coverage.json')}
towns=read(ROOT/'data/statewide/towns.geojson')['features'];xmin,ymin,xmax,ymax=-73.74,40.95,-71.78,42.06
sx=1050/(xmax-xmin);sy=500/(ymax-ymin)
def xy(x,y):return 60+(x-xmin)*sx,150+(ymax-y)*sy
def path(g):
 parts=[]
 for polygon in ([g] if g.geom_type=='Polygon' else g.geoms):
  for ring in [polygon.exterior,*polygon.interiors]:
   points=[xy(x,y) for x,y,*rest in ring.coords];parts.append('M'+' L'.join(f'{x:.2f},{y:.2f}' for x,y in points)+' Z')
 return ' '.join(parts)
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="850"><rect width="1200" height="850" fill="#f8faf7"/><g font-family="Segoe UI,Arial" fill="#173d36">',
 '<text x="60" y="55" font-size="30" font-weight="bold">Connecticut | Where groundwater is being observed</text>',
 f'<text x="60" y="90" font-size="18">Readings searched: {summary["window_start"]}–{summary["window_end"]} • Snapshot {summary["snapshot"]}</text>',
 '<text x="60" y="120" font-size="17">Monitoring coverage only. Town shading does not represent groundwater levels or aquifer extent.</text>']
for f in towns:
 name=f['properties']['Municipality'];n=coverage[name]['wells_with_recent_readings'];fill='#c7e4db' if n else '#e2e5e5'
 svg.append(f'<path d="{path(shape(f["geometry"]))}" fill="{fill}" fill-rule="evenodd" stroke="#9ba9a5" stroke-width=".6"><title>{escape(name)}: {n} wells with readings</title></path>')
for r in records:
 if not r['recent_observation_count']:continue
 x,y=xy(*r['coordinates']);fill='#176c98' if r['daily_days'] else '#af681d'
 svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{fill}" stroke="white" stroke-width=".8"><title>{escape(r["name"])}: {r["latest"]["date"]}</title></circle>')
yale=shape(read(ROOT/'data/yale-farm/farm-outline.geojson')['features'][0]['geometry']).representative_point();x,y=xy(yale.x,yale.y)
svg.append(f'<circle cx="{x}" cy="{y}" r="6" fill="#173d36" stroke="white" stroke-width="2"/><text x="{x+10}" y="{y+5}" font-size="18" font-weight="bold" stroke="white" stroke-width="3" paint-order="stroke">Yale Farm</text>')
svg.extend(['<circle cx="70" cy="698" r="5" fill="#176c98"/><text x="85" y="704" font-size="16">Daily records available (9 wells)</text>',
 '<circle cx="420" cy="698" r="5" fill="#af681d"/><text x="435" y="704" font-size="16">Manual readings only (58 wells)</text>',
 '<text x="60" y="745" font-size="17">Green towns: at least one recent well. Gray towns: none in the imported sources (140 towns).</text>',
 '<text x="60" y="777" font-size="16">Some well markers overlap. Missing coverage does not mean dry wells or absent groundwater.</text>',
 '<text x="60" y="813" font-size="14">USGS Water Data APIs • NGWMN membership and non-USGS providers not verified • No farm-level interpolation</text></g></svg>'])
(out/'groundwater-coverage.svg').write_text(''.join(svg),encoding='utf-8')
print('Saved groundwater coverage map.')
