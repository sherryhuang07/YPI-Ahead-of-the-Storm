import sys, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
from statewide_common import *

mode=sys.argv[1] if len(sys.argv)>1 else 'sources'
if mode=='sources':
    for state in ['CT','NY','MA','RI']:
        download(FTW+f'US_{state}.json',DATA/f'ftw-{state.lower()}-item.json')
        item=read(DATA/f'ftw-{state.lower()}-item.json')
        download(urljoin(FTW+f'US_{state}.json',item['assets']['data']['href']),DATA/f'ftw-{state.lower()}.parquet')
    download(TOWNS+'/query?where=1%3D1&outFields=Municipality,MunicipalityNumber&outSR=4326&f=geojson',DATA/'towns.geojson')
    if len(read(DATA/'towns.geojson')['features'])!=169: raise RuntimeError('Expected 169 town shapes')
    # Broad agricultural tags include small urban farms and non-crop farmyards.
    osm_query='''[out:json][timeout:240];area["ISO3166-2"="US-CT"]["boundary"="administrative"]->.ct;(nwr["landuse"~"^(farmland|farmyard|orchard|vineyard|meadow|plant_nursery|greenhouse_horticulture)$"](area.ct);nwr["place"="farm"](area.ct);nwr["leisure"="garden"]["garden:type"="community"](area.ct););out meta geom;'''
    if not (DATA/'osm-agriculture.json').exists():
        log('Requesting public agricultural mapping across Connecticut')
        value=request_json('https://overpass-api.de/api/interpreter',{'data':osm_query},post=True,timeout=300)
        save(DATA/'osm-agriculture.json',value)
        save(DATA/'osm-agriculture.source.json',{'url':'https://overpass-api.de/api/interpreter','query':osm_query,'retrieved_at':datetime.now(timezone.utc).isoformat(),'license':'ODbL; OpenStreetMap contributors'})
    log('Satellite partitions, all 169 towns, and public agricultural mapping downloaded')
elif mode=='directory':
    download('https://www.google.com/maps/d/kml?mid=1Yqd11zrnfJfjZjRKWXR0bkUEd11QCLI&forcekml=1',DATA/'ct-grown-directory.kml')
    log('Downloaded publicly shared CT Grown directory linked by CT Department of Education')
elif mode=='ag-parcels':
    words=['FARM','AGRIC','CROP','PASTURE','ORCHARD','NURSERY','GREENHOUSE','VINEYARD','DAIRY','POULTRY','LIVESTOCK','EQUESTR','HORSE','STABLE','TOBACCO','CHRISTMAS TREE','APIAR','AQUACULT']
    where='('+' OR '.join("UPPER(State_Use_Description) LIKE '%"+w+"%'" for w in words)+") AND UPPER(State_Use_Description) NOT LIKE '%SOLAR%' AND UPPER(State_Use_Description) NOT LIKE '%TANK%'"
    ids=id_query({'where':where});save(DATA/'ag-parcel-ids.json',{'ids':ids,'where':where,'retrieved_at':datetime.now(timezone.utc).isoformat()})
    log(f'Assessor records matching agricultural descriptions: {len(ids):,}; these are candidates, not confirmed farms')
    save(DATA/'ag-parcels.geojson',fetch_records(ids,DATA/'parcel-batches'))
    # Audit all towns, including towns with no candidates or missing descriptions.
    statistics=json.dumps([{'statisticType':'count','onStatisticField':'OBJECTID','outStatisticFieldName':'record_count'}])
    for label,condition in [('all','1=1'),('missing-use',"State_Use_Description IS NULL OR State_Use_Description = ''")]:
        value=query({'f':'json','where':condition,'outStatistics':statistics,'groupByFieldsForStatistics':'Town_Name','returnGeometry':'false'})
        if value.get('exceededTransferLimit'): raise RuntimeError('Town audit truncated')
        save(DATA/('parcel-town-'+label+'.json'),value)
    log('Agricultural parcel screen and statewide attribute-coverage audit saved')
elif mode=='field-parcels':
    batches=read(DATA/'field-query-batches.json')
    folder=DATA/'spatial-queries';folder.mkdir(exist_ok=True)
    ids=set(read(DATA/'ag-parcel-ids.json')['ids'])
    def spatial_batch(b):
        file=folder/(b['key']+'.json')
        if file.exists(): result=read(file)
        else:
            found=id_query({'where':'1=1','geometry':json.dumps(b['geometry'],separators=(',',':')),'geometryType':'esriGeometryPolygon','inSR':'4326','spatialRel':'esriSpatialRelIntersects'})
            result={'candidate_ids':b['candidate_ids'],'parcel_ids':found};save(file,result)
        return result
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(spatial_batch,b) for b in batches]
        for i,future in enumerate(as_completed(futures)):
            ids.update(future.result()['parcel_ids'])
            if i%10==0:log(f'Comparing fields with property records: {i+1} of {len(batches)} area batches')
    ids=sorted(ids); save(DATA/'all-candidate-parcel-ids.json',ids)
    save(DATA/'candidate-parcels.geojson',fetch_records(ids,DATA/'parcel-batches'))
    log(f'Completed property matching: {len(ids):,} unique assessor records retrieved')
else: raise ValueError('Unknown mode')
