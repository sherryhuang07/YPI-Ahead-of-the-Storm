"""Regional scientific overview: connected gauges and selected river geometry."""
import html
import pyogrio
from shapely import from_wkb
from shapely.geometry import shape
from statewide_common import ROOT,read
O=ROOT/'outputs/regional-streamflow'
def main():
    gauges=read(O/'relevant-gauges.json');svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="1100" viewBox="0 0 1100 1100"><rect width="1100" height="1100" fill="#f7f8f3"/>']
    def text(x,y,s,size=16):svg.append(f'<text x="{x}" y="{y}" font-size="{size}" font-family="Arial" fill="#193b36">{html.escape(s)}</text>')
    text(35,40,'Streamflow context beyond Connecticut',28);text(35,68,'Connected gauges in neighboring states and the upper Connecticut River basin')
    def xy(x,y):return 50+(x+75)/5*1000,95+(45.4-y)/4.7*850
    svg.append('<defs><clipPath id="map"><rect x="30" y="85" width="1040" height="870"/></clipPath></defs><g clip-path="url(#map)">')
    def draw(g,fill,stroke,width):
        if hasattr(g,'geoms'):
            for part in g.geoms:draw(part,fill,stroke,width)
        elif g.geom_type=='Polygon':
            d=' '.join('M'+' L'.join(f'{x:.1f},{y:.1f}' for x,y in [xy(*c[:2]) for c in ring.coords])+' Z' for ring in [g.exterior,*g.interiors]);svg.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" fill-rule="evenodd"/>')
        elif g.geom_type=='LineString':
            pts=' '.join(f'{x:.1f},{y:.1f}' for x,y in [xy(*c[:2]) for c in g.coords]);svg.append(f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="{width}"/>')
    for f in read(ROOT/'data/statewide/connecticut-mask.geojson')['features']:draw(shape(f['geometry']),'#dcebcf','#5c7c4f',1.2)
    names=['Connecticut River','Housatonic River','Farmington River','West Branch Farmington River','Quinebaug River','Pawcatuck River','Byram River','Deerfield River','Westfield River','White River','Ashuelot River']
    where='gnis_name IN ('+','.join("'"+n+"'" for n in names)+')'
    for folder in sorted((ROOT/'data/hydrography/bulk').glob('*_GDB')):
        gdb=next(folder.rglob('*.gdb'));meta,table=pyogrio.read_arrow(gdb,layer='NHDFlowline',columns=['gnis_name'],where=where)
        for r in table.to_pylist():draw(from_wkb(r[meta['geometry_name']]),'none','#4b8fa9',1)
    colors={'Massachusetts':'#2a8055','New York':'#3664aa','Rhode Island':'#bb4d50','Vermont':'#8654a5','New Hampshire':'#bd791d'}
    for g in gauges:
        x,y=xy(*g['coordinates']);svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{colors[g["state"]]}" stroke="white" stroke-width=".8"><title>{html.escape(g["name"]+" | "+g["gauge_id"])}</title></circle>')
    svg.append('</g>')
    text(450,870,'CONNECTICUT',18);text(200,450,'NEW YORK');text(400,260,'VERMONT');text(710,260,'NEW HAMPSHIRE');text(650,675,'MASSACHUSETTS');text(800,850,'RHODE ISLAND')
    for i,(state,color) in enumerate(colors.items()):
        x=35+i*210;svg.append(f'<circle cx="{x}" cy="990" r="5" fill="{color}"/>');text(x+12,996,state,14)
    text(35,1030,'Dots mark connected gauges. Available forecasts apply at the gauge; travel time and tides are not simulated.',15)
    text(35,1060,'Sources: USGS daily discharge and regional NHDPlus HR. State names indicate general locations.',15)
    svg.append('</svg>');(O/'neighboring-gauge-map.svg').write_text(''.join(svg),encoding='utf-8')
if __name__=='__main__':main()
