"""Official regional FileGDB fallback; excludes enormous national packages."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath
import zipfile,hashlib
from statewide_common import ROOT,read,save,download,log
D=ROOT/'data/hydrography';B=D/'bulk';B.mkdir(exist_ok=True)
def fetch(item):
    url=item['downloadURL'];path=B/url.rsplit('/',1)[-1];download(url,path)
    folder=B/path.stem
    if not folder.exists():
        folder.mkdir()
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                p=PurePosixPath(n)
                if p.is_absolute() or '..' in p.parts:raise ValueError('Unsafe archive path')
            z.extractall(folder)
    return folder
def main():
    items=[i for i in read(D/'bulk-catalog.json')['items'] if '/GDB/' in i['downloadURL'] and i.get('sizeInBytes',0)<1_000_000_000]
    with ThreadPoolExecutor(max_workers=2) as pool:folders=list(pool.map(fetch,items))
    import pyogrio
    from shapely import from_wkb,to_geojson
    from shapely.ops import transform
    from pyproj import Transformer
    import json
    for out,layer in [('hr-catchments','NHDPlusCatchment'),('hr-waterbodies','NHDWaterbody')]:
        existing=D/(out+'.geojson')
        if existing.exists() and existing.with_suffix('.source.json').exists() and read(existing.with_suffix('.source.json')).get('sources'):
            continue
        features=[];sources=[]
        for folder in folders:
            gdb=next(folder.rglob('*.gdb'));layers=pyogrio.list_layers(gdb);names=[x[0] for x in layers]
            if layer not in names:raise ValueError(str(gdb)+' missing '+layer)
            info=pyogrio.read_info(gdb,layer=layer)
            tolocal=Transformer.from_crs(4326,info['crs'],always_xy=True)
            bbox=tolocal.transform_bounds(-73.8,40.9,-71.7,42.1)
            meta,table=pyogrio.read_arrow(gdb,layer=layer,bbox=bbox,return_fids=True)
            records=table.to_pylist();gc=meta['geometry_name'];project=Transformer.from_crs(info['crs'],4326,always_xy=True).transform
            for n,r in enumerate(records):
                raw=r.pop(gc);g=transform(project,from_wkb(raw))
                props={k.lower():(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in r.items()};props['OBJECTID']=props.pop('objectid',n)
                features.append(dict(type='Feature',id=folder.name+':'+str(props['OBJECTID']),properties=props,geometry=json.loads(to_geojson(g))))
            sources.append(dict(archive=folder.name,features=len(records),crs=info['crs']))
            log(out+': read '+str(len(records))+' features from '+folder.name)
        dest=D/(out+'.geojson');save(dest,dict(type='FeatureCollection',features=features,sources=sources,selection='Connecticut plus border buffer; regional FileGDB fallback'))
        save(dest.with_suffix('.source.json'),dict(sources=sources,count=len(features),sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))
    save(D/'bulk-download-status.json',dict(complete=True,regional_archives=len(folders)))
if __name__=='__main__':main()
