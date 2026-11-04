import html
from shapely.geometry import shape
from shapely.ops import transform
from pyproj import Transformer
from statewide_common import *
OUT=ROOT/'outputs'/'statewide'
project=Transformer.from_crs(4326,5070,always_xy=True).transform
towns=read(DATA/'towns.geojson')['features']
features=read(OUT/'field-candidates.geojson')['features']
summary=read(OUT/'summary.json')
tg=[transform(project,shape(f['geometry'])) for f in towns]
fg=[transform(project,shape(f['geometry'])) for f in features]
def paths(g,xy):
    if g.geom_type=='Point':
        x,y=xy(g.x,g.y);return f'M{x:.1f},{y:.1f}h1'
    polys=[g] if g.geom_type=='Polygon' else [p for p in g.geoms if p.geom_type=='Polygon']
    out=[]
    for p in polys:
        for ring in [p.exterior,*p.interiors]:
            out.append(''.join(('M' if i==0 else 'L')+','.join(f'{v:.1f}' for v in xy(x,y)) for i,(x,y) in enumerate(ring.coords))+'Z')
    return ''.join(out)
def render(title,bounds,indices,destination,subtitle):
    x0,y0,x1,y1=bounds
    scale=min(1260/(x1-x0),750/(y1-y0))
    left=45+(1260-(x1-x0)*scale)/2;top=140+(750-(y1-y0)*scale)/2
    xy=lambda x,y:(left+(x-x0)*scale,top+(y1-y)*scale)
    parts=[]
    for geom,town in zip(tg,towns):
        if geom.bounds[2]<x0 or geom.bounds[0]>x1 or geom.bounds[3]<y0 or geom.bounds[1]>y1:continue
        parts.append(f'<path d="{paths(geom.simplify(25),xy)}" fill="#e7eae3" stroke="#aeb7ab" stroke-width="0.7"><title>{html.escape(town["properties"]["Municipality"])}</title></path>')
    for i in indices:
        f=features[i];p=f['properties'];color='#26795e' if p['source'].startswith('FTW') else '#7855a0'
        parts.append(f'<path d="{paths(fg[i].simplify(max(1,0.25/scale)),xy)}" fill="{color}" fill-opacity="0.65" stroke="{color}" stroke-width="0.65" fill-rule="evenodd"><title>{html.escape((p.get("name") or p["candidate_id"])+" | Unreviewed")}</title></path>')
        if 'boundary review' in title and fg[i].area*scale*scale<25:
            center=fg[i].representative_point();cx,cy=xy(center.x,center.y)
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3" fill="none" stroke="{color}" stroke-width="1.2"><title>Locator ring, not land area: {html.escape(p.get("name") or p["candidate_id"])}</title></circle>')
    # Map is a display product; full geometry and all evidence are retained separately.
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="1350" height="1040" viewBox="0 0 1350 1040" role="img" aria-labelledby="title desc"><title id="title">{html.escape(title)}</title><desc id="desc">Candidate agricultural outlines from satellite modeling and public mapping, not confirmed farm operating boundaries. Municipal boundaries shown for orientation.</desc><rect width="1350" height="1040" fill="#f7f6ef"/><g font-family="Segoe UI,sans-serif" fill="#253c33"><text x="45" y="52" font-size="32" font-weight="bold">{html.escape(title)}</text><text x="45" y="89" font-size="19">{html.escape(subtitle)}</text><text x="45" y="118" font-size="16">Candidate outlines, not confirmed farms. Overlapping source records may describe the same land.</text><clipPath id="map"><rect x="40" y="135" width="1270" height="765"/></clipPath><g clip-path="url(#map)">{''.join(parts)}</g><rect x="45" y="929" width="16" height="16" fill="#26795e"/><text x="72" y="943" font-size="17">2025 satellite field candidates</text><rect x="440" y="929" width="16" height="16" fill="#7855a0"/><text x="467" y="943" font-size="17">Public mapped agricultural outlines / locations</text><text x="45" y="980" font-size="15">Sources: Fields of the World / Taylor Geospatial (CC-BY-4.0); © OpenStreetMap contributors (ODbL); CT DOT towns.</text><text x="45" y="1007" font-size="15">Property records and directory leads are separate layers. Colors do not indicate drought, ownership, or verification.</text></g></svg>'''
    destination.write_text(svg,encoding='utf-8')
bounds=(min(g.bounds[0] for g in tg),min(g.bounds[1] for g in tg),max(g.bounds[2] for g in tg),max(g.bounds[3] for g in tg))
render('Connecticut farm-boundary candidates',bounds,range(len(features)),OUT/'statewide-map.svg',f'169 towns processed | {summary["candidate_records"]:,} mapped candidates | 0 farmer-confirmed boundaries')
for i,town in enumerate(towns):
    name=town['properties']['Municipality'];number=town['properties']['MunicipalityNumber']
    indices=[j for j,f in enumerate(features) if name in f['properties']['towns']]
    render(name+' — boundary review',tg[i].bounds,indices,OUT/'towns'/f'{number:03d}-map.svg',f'{len(indices):,} source records touching this town; farm-business count unknown')
log('Statewide overview and 169 town maps saved')
