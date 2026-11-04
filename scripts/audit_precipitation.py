"""Reproduce map statistics and limited source/station checks using saved evidence."""
import zipfile
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from shapely.geometry import shape,mapping
from shapely.ops import unary_union
from shapely import transform
from pyproj import Transformer
from statewide_common import ROOT,read,save

folder=ROOT/'data/prism/2026-11-02';audit=ROOT/'data/prism/audit'
mask=unary_union([shape(f['geometry']) for f in read(ROOT/'data/statewide/connecticut-mask.geojson')['features']])
mask=transform(mask,Transformer.from_crs(4326,4269,always_xy=True).transform,interleaved=False)
with rasterio.open(ROOT/'outputs/precipitation/cumulative-30-days.tif') as src:
    a=src.read(1);inside=geometry_mask([mapping(mask)],a.shape,src.transform,invert=True)
    values=a[inside]/25.4; total=np.zeros(a.shape);daily=[]
    for day in read(folder/'manifest.json')['dates'][-30:]:
        with rasterio.open(folder/f'{day}.tif') as s:d=s.read(1)
        total+=d;daily.append(dict(date=day,mean_mm=float(d[inside].mean()),max_mm=float(d[inside].max())))
    error=float(np.max(abs(total[inside]-a[inside])));assert error<1e-8
    result=dict(statistic_scope='Equal weighting of grid cells whose centers lie within Connecticut; not an area-weighted state mean',
        percentiles_inches=dict(zip(['min','p05','p25','median','p75','p95','max'],np.percentile(values,[0,5,25,50,75,95,100]).tolist())),
        mean_inches=float(values.mean()),std_inches=float(values.std()),independent_sum_max_error_mm=error,daily=daily)
for day,archive in [('2026-10-12',audit/'20261012.zip'),('2026-11-01',ROOT/'data/prism/20261101.zip')]:
    with zipfile.ZipFile(archive) as z:name=next(n for n in z.namelist() if n.endswith('.tif'))
    with rasterio.open('/vsizip/'+archive.as_posix()+'/'+name) as original,rasterio.open(folder/f'{day}.tif') as crop:
        w=from_bounds(*crop.bounds,original.transform).round_offsets().round_lengths()
        match=np.array_equal(original.read(1,window=w),crop.read(1));assert match
        result.setdefault('source_grid_checks',[]).append(dict(date=day,entire_crop_matches_original=bool(match)))
rows=read(audit/'noaa-stations.json'); comparisons=[]
for station,name,xy in [('USW00014740','Bradley Airport',(-72.68202,41.93742)),('USW00094702','Sikorsky Memorial Airport',(-73.12664,41.16424))]:
    entries=[r for r in rows if r['STATION']==station and r.get('PRCP') is not None and not r.get('PRCP_ATTRIBUTES',',,').split(',')[1]]
    modeled=0
    for entry in entries:
        with rasterio.open(folder/(entry['DATE']+'.tif')) as s:modeled+=float(next(s.sample([xy]))[0])
    gauge=sum(float(r['PRCP']) for r in entries)
    comparisons.append(dict(station=station,name=name,available_days=len(entries),start=min(r['DATE'] for r in entries),end=max(r['DATE'] for r in entries),
        gauge_inches=gauge/25.4,prism_same_date_labels_inches=modeled/25.4,trace_dates=[r['DATE'] for r in entries if r.get('PRCP_ATTRIBUTES','').startswith('T')]))
result['station_checks']=comparisons
result['station_limitations']='Only 28 available daily reports per station. Station day ends at 2400; PRISM ends at 12 UTC, so date-label comparisons are approximate, not aligned-interval validation. Trace precipitation is retained in flags but numerically zero. Stations may be inputs to PRISM: this is not independent model validation.'
result['noaa_query']='https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries&stations=USW00014740,USW00094702&startDate=2026-10-03&endDate=2026-11-01&dataTypes=PRCP&units=metric&format=json&includeAttributes=true'
save(ROOT/'outputs/precipitation/audit.json',result)
print(result['percentiles_inches']);print(comparisons);print('PASS: daily accumulation and both original-source crop comparisons.')
