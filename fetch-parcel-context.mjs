// Reusable statewide parcel connector: node fetch-parcel-context.mjs west south east north output.geojson
import fs from 'node:fs';
import path from 'node:path';
const args=process.argv.slice(2), bbox=args.slice(0,4).map(Number), output=args[4];
if(args.length!==5||!bbox.every(Number.isFinite)||bbox[0]>=bbox[2]||bbox[1]>=bbox[3]||bbox[0]<-74||bbox[2]>-71||bbox[1]<40||bbox[3]>43)throw Error('Supply a Connecticut-area longitude/latitude bounding box and output file.');
const resolved=path.resolve(output), relative=path.relative(process.cwd(),resolved);
if(relative.startsWith('..')||path.isAbsolute(relative))throw Error('Output must stay within this project');
const base='https://services3.arcgis.com/3FL1kr7L4LvwA2Kb/arcgis/rest/services/Connecticut_CAMA_and_Parcel_Layer/FeatureServer/0/query';
async function query(params){const response=await fetch(base+'?'+new URLSearchParams(params),{signal:AbortSignal.timeout(60000)});if(!response.ok)throw Error(`Parcel service returned ${response.status}`);const data=await response.json();if(data.error)throw Error(JSON.stringify(data.error));return data;}
const ids=await query({f:'json',where:'1=1',geometry:bbox.join(','),geometryType:'esriGeometryEnvelope',inSR:'4326',spatialRel:'esriSpatialRelIntersects',returnIdsOnly:'true'});
if(!Array.isArray(ids.objectIds))throw Error('Service did not return parcel IDs');
const unique=[...new Set(ids.objectIds)], features=[];
for(let i=0;i<unique.length;i+=200){const batch=await query({f:'geojson',objectIds:unique.slice(i,i+200).join(','),outSR:'4326',outFields:'OBJECTID,Town_Name,Location,Parcel_ID,State_Use,State_Use_Description,Land_Acres,Parcel_Collection_Year'});if(batch.exceededTransferLimit||!batch.features)throw Error('Incomplete parcel response');features.push(...batch.features);}
if(new Set(features.map(f=>f.properties.OBJECTID)).size!==unique.length)throw Error('Parcel retrieval count mismatch');
fs.mkdirSync(path.dirname(resolved),{recursive:true});
fs.writeFileSync(resolved,JSON.stringify({type:'FeatureCollection',features}));
fs.writeFileSync(resolved+'.source.json',JSON.stringify({source:base,query_bbox:bbox,coordinate_system:'EPSG:4326',retrieved_at:new Date().toISOString(),record_count:features.length,scope:'All nearby property parcels; not a farm classification'},null,2));
console.log(`Saved ${features.length} nearby property records. These are not automatically classified as farms.`);
