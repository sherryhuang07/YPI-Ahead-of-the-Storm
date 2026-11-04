"""Check units, missing-data rules, source integrity, coverage and Yale regression."""
import hashlib
import numpy as np
import rasterio
from shapely.geometry import shape
from statewide_common import ROOT,read
from build_precipitation import cumulative,weighted,project

assert cumulative(np.array([[[1.]],[[2.]],[[3.]]]),2)[0,0]==5
assert np.isnan(cumulative(np.array([[[1.]],[[np.nan]]]),2)[0,0])
assert cumulative(np.zeros((7,1,1)),7)[0,0]==0
value,coverage=weighted(np.array([10.,30.]),np.array([.25,.75]));assert value==25 and coverage==1
value,coverage=weighted(np.array([10.,np.nan]),np.array([.25,.75]));assert value is None and coverage==.25
summary=read(ROOT/'outputs/precipitation/summary.json'); folder=ROOT/'data/prism'/summary['snapshot']
for day in summary['dates']:
    metadata=read(folder/f'{day}.json')
    assert hashlib.sha256((folder/f'{day}.tif').read_bytes()).hexdigest()==metadata['crop_sha256']
records=read(ROOT/'outputs/precipitation/records.json');assert len({r['id'] for r in records})==len(records)
assert len([r for r in records if r['kind']=='farm_candidate'])==11759
for r in records:
    previous=0
    for n in summary['windows']:
        t=r['totals'][str(n)];assert -.000001<=t['coverage_fraction']<=1.000001
        if t['mm'] is not None:
            assert t['mm']>=previous-1e-7 and abs(t['inches']*25.4-t['mm'])<1e-8
            previous=t['mm'];assert abs(t['coverage_fraction']-1)<1e-6
# Independent brute-force bounding-cell intersections for the Yale pilot.
from shapely.geometry import box
from rasterio.windows import from_bounds
from pyproj import Transformer
from shapely import transform
g=shape(read(ROOT/'data/yale-farm/farm-outline.geojson')['features'][0]['geometry'])
nad=transform(g,Transformer.from_crs(4326,4269,always_xy=True).transform,interleaved=False)
area=project(g);daily=[]
for day in summary['dates']:
    with rasterio.open(folder/f'{day}.tif') as src:
        window=from_bounds(*nad.bounds,transform=src.transform);arr=src.read(1);total=0;weight=0
        for row in range(int(np.floor(window.row_off)),int(np.ceil(window.row_off+window.height))):
            for col in range(int(np.floor(window.col_off)),int(np.ceil(window.col_off+window.width))):
                x,y=src.transform*(col,row);xx,yy=src.transform*(col+1,row+1)
                fraction=area.intersection(project(box(x,yy,xx,y),4269)).area/area.area
                assert arr[row,col]!=src.nodata
                total+=float(arr[row,col])*fraction;weight+=fraction
        assert abs(weight-1)<1e-6;daily.append(total)
for n in summary['windows']:
    assert abs(sum(daily[-n:])-summary['yale']['totals'][str(n)]['mm'])<1e-7
print('PASS: missing data, dry zero, area weights, units, all 90 crop hashes, candidate IDs, cumulative windows, coverage, and independent Yale calculation.')
