"""Standalone precipitation map; source resolution remains visible."""
from html import escape
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import shape,mapping
from shapely.ops import unary_union
from shapely import transform
from pyproj import Transformer
from statewide_common import ROOT,read

out=ROOT/'outputs/precipitation';summary=read(out/'summary.json')
with rasterio.open(out/'cumulative-30-days.tif') as src:
    data=src.read(1,masked=True).filled(np.nan)/25.4; affine=src.transform
    features=read(ROOT/'data/statewide/connecticut-mask.geojson')['features']
    boundary=unary_union([shape(f['geometry']) for f in features])
    boundary=transform(boundary,Transformer.from_crs(4326,4269,always_xy=True).transform,interleaved=False)
    inside=geometry_mask([mapping(boundary)],data.shape,affine,invert=True)
    h,w=data.shape
    scale=min(1000/w,510/h); left=70;top=150
    maximum=float(np.nanmax(data[inside])); minimum=float(np.nanmin(data[inside]))
    low=np.floor(minimum*4)/4; high=np.ceil(maximum*4)/4
    if high==low: high=low+.25
    def color(v):
        t=max(0,min(1,(v-low)/(high-low)));return f'rgb({int(239-222*t)},{int(249-158*t)},{int(232-78*t)})'
    parts=['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="850" viewBox="0 0 1200 850">',
        '<rect width="1200" height="850" fill="#f8faf7"/>',
        '<g font-family="Segoe UI,Arial" fill="#173d36">',
        '<text x="60" y="55" font-size="30" font-weight="bold">Connecticut | Precipitation over the past 30 days</text>',
        f'<text x="60" y="90" font-size="19">Through {summary["end"]} at 12:00 UTC • PRISM nominal 800-meter grid • inches</text>',
        '<text x="60" y="120" font-size="17">Provisional historical estimates. This is not a drought classification or a forecast.</text>']
    for row,col in zip(*np.where(inside)):
        v=data[row,col];fill=color(v) if np.isfinite(v) else '#999999'
        parts.append(f'<rect shape-rendering="crispEdges" x="{left+col*scale:.4f}" y="{top+row*scale:.4f}" width="{scale:.4f}" height="{scale:.4f}" fill="{fill}"/>')
    sites={'Stamford':(-73.5387,41.0534),'Hartford':(-72.6851,41.7637),'Norwich':(-72.0759,41.5243),'Salisbury':(-73.4212,41.9834),'Putnam':(-71.9076,41.9151),'New Haven':(-72.9279,41.3083)}
    for name,(lon,lat) in sites.items():
        col,row=(~affine)*(lon,lat); px=left+col*scale;py=top+row*scale; value=data[int(row),int(col)]
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="#173d36" stroke="white" stroke-width="1.5"/><text x="{px+7:.1f}" y="{py-8:.1f}" font-size="16" font-weight="bold" stroke="#f8faf7" stroke-width="3" paint-order="stroke">{name} {value:.2f}</text>')
    for i in range(200):parts.append(f'<rect shape-rendering="crispEdges" x="{70+i*2.25}" y="690" width="2.3" height="20" fill="{color(low+(high-low)*i/199)}"/>')
    for tick in np.arange(low,high+.001,.25):
        px=70+(tick-low)/(high-low)*450
        parts.append(f'<text x="{px:.1f}" y="733" text-anchor="middle" font-size="15">{tick:.2f}</text>')
    parts.extend([
        '<rect x="650" y="690" width="20" height="20" fill="#999999"/><text x="680" y="707" font-size="16">Missing data</text>',
        f'<text x="70" y="761" font-size="16">Inches • Scale starts at {low:.2f}, not zero, to show regional differences. Point labels are grid estimates.</text>',
        f'<text x="70" y="788" font-size="16">Actual range: {minimum:.2f}–{maximum:.2f} inches. Colors show precipitation totals, not drought severity.</text>',
        f'<text x="70" y="815" font-size="14">{escape(summary["attribution"])}</text>','</g></svg>'])
    (out/'precipitation-30-days.svg').write_text(''.join(parts),encoding='utf-8')
print('Saved the 30-day Connecticut precipitation map.')
