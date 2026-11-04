"""Portable map and forecast figure, using the saved data only."""
import html
from shapely.geometry import shape
from statewide_common import ROOT,read

O=ROOT/'outputs/river-network';O.mkdir(parents=True,exist_ok=True)
def main():
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="850" viewBox="0 0 1200 850"><rect width="1200" height="850" fill="#f5f7f2"/>']
    def text(x,y,s,size=16):svg.append(f'<text x="{x}" y="{y}" font-family="Arial" font-size="{size}" fill="#18352f">{html.escape(s)}</text>')
    text(40,42,'Connecticut: fields, upstream drainage areas and stream gauges',25)
    text(40,70,'Saved public-data research map | drainage relationships do not establish water access')
    svg.append('<defs><clipPath id="map"><rect x="30" y="90" width="1140" height="620"/></clipPath></defs><g clip-path="url(#map)">')
    def xy(x,y):return 50+(x+73.8)/2.1*1100,100+(42.1-y)/1.2*600
    def draw(g,fill,stroke,width=.4):
        if g.geom_type.startswith('Multi') or g.geom_type=='GeometryCollection':
            for part in g.geoms:draw(part,fill,stroke,width)
        elif g.geom_type=='Polygon':
            rings=[g.exterior,*g.interiors];d=' '.join('M'+' L'.join(f'{a:.1f},{b:.1f}' for a,b in [xy(*c[:2]) for c in ring.coords])+' Z' for ring in rings)
            svg.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" fill-rule="evenodd"/>')
        elif g.geom_type=='LineString':
            pts=' '.join(f'{a:.1f},{b:.1f}' for a,b in [xy(*c[:2]) for c in g.coords]);svg.append(f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="{width}"/>')
    for f in read(ROOT/'data/statewide/connecticut-mask.geojson')['features']:draw(shape(f['geometry']),'#e1e7db','#6a7966',1)
    # Boundaries are displayed, including cross-border contributions inside the map viewport.
    for p in (ROOT/'data/hydrography/nldi').glob('*-basin.geojson'):
        for f in read(p)['features']:draw(shape(f['geometry']).simplify(.001),'none','#97b5b2',.5)
    p=ROOT/'data/hydrography/hr-flowlines.geojson'
    if p.exists():
        for f in read(p)['features']:
            if (f['properties'].get('streamorde') or 0)>=3 and f['properties'].get('ftype')==460:draw(shape(f['geometry']).simplify(.0003),'none','#367fa0',.6)
    for f in read(ROOT/'outputs/statewide/field-candidates.geojson')['features']:
        p=shape(f['geometry']).representative_point();x,y=xy(p.x,p.y);svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r=".7" fill="#76a243"/>')
    for r in read(ROOT/'outputs/streamflow-trained/results.json'):
        x,y=xy(*r['coordinates']) if 'coordinates' in r else (0,0)
        if not x:continue
        color='#193c81' if 'forecast' in r else '#be6634'
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{color}" stroke="white" stroke-width="1"><title>{html.escape(r["name"])}</title></circle>')
    svg.append('</g>')
    text(40,755,'Green dots: candidate fields | blue dots: trained gauges | orange dots: insufficient clean history')
    text(40,785,'Pale outlines: gauge drainage basins (NLDI). Blue: larger mapped streams; artificial paths omitted here.')
    text(40,815,'Sources: USGS NLDI / NHDPlus HR, Connecticut public mapping, FTW and OpenStreetMap.')
    svg.append('</svg>');(O/'connected-water-map.svg').write_text(''.join(svg),encoding='utf-8')

if __name__=='__main__':main()
