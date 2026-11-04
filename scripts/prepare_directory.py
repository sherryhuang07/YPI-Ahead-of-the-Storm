import csv,io,re,hashlib,sys
import xml.etree.ElementTree as ET
from statewide_common import *

ns={'k':'http://www.opengis.net/kml/2.2'}
root=ET.parse(DATA/'ct-grown-directory.kml')
entries={}
for folder in root.findall('.//k:Folder',ns):
    category=folder.findtext('k:name',default='',namespaces=ns)
    for place in folder.findall('k:Placemark',ns):
        name=place.findtext('k:name',default='',namespaces=ns)
        details={d.attrib['name'].lower().rstrip(':').strip():d.findtext('k:value',default='',namespaces=ns) for d in place.findall('.//k:Data',ns)}
        street=details.get('street address',details.get('address',details.get('street','')))
        town=details.get('town',details.get('city',''))
        state=details.get('state','CT')
        zipcode=details.get('zip code',details.get('zip',''))
        address=place.findtext('k:address',default='',namespaces=ns)
        key=hashlib.sha256((name.strip().lower()+'|'+re.sub(r'\s+',' ',address.strip().lower())).encode()).hexdigest()[:16]
        if key not in entries:
            entries[key]={'directory_id':'ctgrown-'+key,'name':name,'address':address,'street':street,'town_as_listed':town,'state':state,'zip':zipcode,'categories':[],'source_url':'https://www.google.com/maps/d/viewer?mid=1Yqd11zrnfJfjZjRKWXR0bkUEd11QCLI','source_date':None,'boundary_status':'No operated boundary established','farm_operator_id':None,'farmer_confirmed':False,'recommendations_ready':False}
        if category not in entries[key]['categories']:entries[key]['categories'].append(category)
records=list(entries.values())
payload=io.StringIO(newline='');writer=csv.writer(payload)
sent=[]
for p in records:
    if p['street'] and p['town_as_listed']:
        writer.writerow([p['directory_id'],p['street'],p['town_as_listed'],p['state'],p['zip']]);sent.append(p['directory_id'])
response_path=DATA/'directory-geocodes.csv'
if '--fetch' in sys.argv and not response_path.exists():
    log(f'Locating {len(sent)} public CT Grown directory addresses using the Census geocoder')
    response=SESSION.post('https://geocoding.geo.census.gov/geocoder/locations/addressbatch',data={'benchmark':'Public_AR_Current'},files={'addressFile':('addresses.csv',payload.getvalue().encode(),'text/csv')},timeout=(30,300))
    response.raise_for_status()
    rows=list(csv.reader(io.StringIO(response.text)))
    if {r[0] for r in rows}!=set(sent):raise RuntimeError('Incomplete geocoder batch')
    response_path.write_text(response.text,encoding='utf-8')
    save(DATA/'directory-geocodes.source.json',{'url':response.url,'retrieved_at':datetime.now(timezone.utc).isoformat(),'benchmark':'Public_AR_Current','submitted':len(sent),'meaning':'Approximate street address locations, not farm or parcel boundaries'})
geocodes={r[0]:r for r in csv.reader(response_path.open(encoding='utf-8'))} if response_path.exists() else {}
for p in records:
    r=geocodes.get(p['directory_id'])
    p['geometry']=None;p['geocode_status']='Address not geocoded'
    if r:
        p['geocode_status']=r[2]
        if r[2]=='Match' and len(r)>5:
            lon,lat=map(float,r[5].split(','));p['geometry']={'type':'Point','coordinates':[lon,lat]};p['geocode_match_type']=r[3];p['matched_address']=r[4]
    p['directory_listing_kind']='Sales location may not be production land' if any('Market' in c or 'Stand' in c for c in p['categories']) else 'Farm/producer lead; operating status unverified'
save(DATA/'directory-leads.json',records)
log(f'Preserved {len(records)} distinct directory listings; {sum(p["geometry"] is not None for p in records)} have approximate address locations')
