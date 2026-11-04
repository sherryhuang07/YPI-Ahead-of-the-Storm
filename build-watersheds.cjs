// Builds a reproducible catalog and display map from the unmodified CT DEEP download.
const fs = require('node:fs');
const crypto = require('node:crypto');
const raw = fs.readFileSync('data/watersheds.geojson');
const data = JSON.parse(raw);
const expected = JSON.parse(fs.readFileSync('data/watershed-count.json')).count;
if (data.type !== 'FeatureCollection' || data.features.length !== expected || data.exceededTransferLimit) throw Error('Incomplete boundary download');
const groups = new Map();
for (const f of data.features) {
  const p = f.properties;
  const id = String(p.SBAS_NO);
  if (!/^\d{4}$/.test(id) || !['Polygon','MultiPolygon'].includes(f.geometry?.type)) throw Error('Invalid watershed');
  if (id[0] !== String(p.MBAS_NO) || id.slice(0,2) !== String(p.RBAS_NO)) throw Error('Inconsistent hierarchy');
  if (!groups.has(id)) groups.set(id, {id, name:p.SUBREGION, regional_id:String(p.RBAS_NO), regional_name:p.REGIONAL, major_id:String(p.MBAS_NO), major_name:p.MAJOR, source_feature_ids:[], drought_status:null});
  const g = groups.get(id);
  if (g.major_id !== String(p.MBAS_NO) || g.regional_id !== String(p.RBAS_NO)) throw Error('Conflicting basin identifiers');
  g.source_feature_ids.push(p.OBJECTID);
}
const basins = [...groups.values()].sort((a,b)=>a.id.localeCompare(b.id));
const majors = [...new Set(basins.map(b=>b.major_id))].sort().map(id=>({id, name:basins.find(b=>b.major_id===id).major_name, watershed_count:basins.filter(b=>b.major_id===id).length}));
const catalog = {source:'CT DEEP Connecticut Subregional Drainage Basin, polygon layer 1', source_url:'https://services1.arcgis.com/FjPcSmEFuDYlIdKC/ArcGIS/rest/services/Connecticut_Subregional_Drainage_Basin/FeatureServer/1', retrieved_at:fs.statSync('data/watersheds.geojson').mtime.toISOString(), sha256:crypto.createHash('sha256').update(raw).digest('hex'), coordinate_system:'WGS84 longitude, latitude', coverage:'Original source extent, including cross-border portions; not clipped to the Connecticut state line. Not a complete upstream contributing-area network.', feature_count:data.features.length, watershed_count:basins.length, regional_count:new Set(basins.map(b=>b.regional_id)).size, majors, basins};
fs.writeFileSync('data/watershed-catalog.json', JSON.stringify(catalog,null,2));
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const polygons=f=>f.geometry.type==='Polygon'?[f.geometry.coordinates]:f.geometry.coordinates;
let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
const project=([lon,lat])=>[lon*Math.cos(41.6*Math.PI/180),-lat];
for(const f of data.features) for(const poly of polygons(f)) for(const ring of poly) for(const pt of ring){const [x,y]=project(pt);minX=Math.min(minX,x);maxX=Math.max(maxX,x);minY=Math.min(minY,y);maxY=Math.max(maxY,y);}
const scale=Math.min(1000/(maxX-minX),640/(maxY-minY));
const xy=pt=>{const [x,y]=project(pt);return [40+(x-minX)*scale,130+(y-minY)*scale];};
const colors=['#4d8b72','#c8a353','#6687b6','#997fb3','#6ba5a5','#b47e65','#9caa64','#b67996'];
let paths='';
for(const f of data.features){let d='';for(const poly of polygons(f))for(const ring of poly){let prev=null;for(let i=0;i<ring.length;i++){const p=xy(ring[i]);if(prev && i<ring.length-1 && Math.hypot(p[0]-prev[0],p[1]-prev[1])<0.65)continue;d+=(prev?'L':'M')+p.map(n=>n.toFixed(1)).join(',');prev=p;}d+='Z';}paths+=`<path d="${d}" fill="${colors[f.properties.MBAS_NO-1]}" stroke="#ffffff" stroke-width="0.45" fill-rule="evenodd"><title>${esc(f.properties.SUBREGION)} (${f.properties.SBAS_NO})</title></path>`;}
const legend=majors.map((m,i)=>`<rect x="${40+(i%4)*260}" y="${805+Math.floor(i/4)*55}" width="15" height="15" fill="${colors[m.id-1]}"/><text x="${63+(i%4)*260}" y="${818+Math.floor(i/4)*55}" font-size="16">${esc(m.name)}</text><text x="${63+(i%4)*260}" y="${838+Math.floor(i/4)*55}" font-size="13">${m.watershed_count} smaller watershed IDs</text>`).join('');
fs.writeFileSync('watershed-map.svg',`<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="980" viewBox="0 0 1120 980" role="img" aria-labelledby="title desc"><title id="title">Connecticut watershed foundation</title><desc id="desc">Official subregional drainage polygons grouped into eight major basins. Includes source coverage beyond Connecticut. Colors identify geography, not drought risk.</desc><rect width="1120" height="980" fill="#f6f5ef"/><g font-family="Segoe UI, sans-serif" fill="#263c36"><text x="40" y="48" font-size="30" font-weight="bold">Connecticut watershed foundation</text><text x="40" y="80" font-size="17">8 major drainage areas / ${basins.length} smaller watershed IDs / ${data.features.length} polygon records</text><text x="40" y="106" font-size="15">Colors show drainage areas, not drought risk. North is up.</text>${paths}${legend}<text x="40" y="936" font-size="14">Source: CT DEEP. Original coverage includes neighboring-state portions; state line is not shown.</text><text x="40" y="958" font-size="14">Display boundaries simplified. Full-resolution shapes retained for analysis. No drought forecast yet.</text></g></svg>`);
console.log(JSON.stringify({features:catalog.feature_count,watersheds:catalog.watershed_count,regions:catalog.regional_count,majors},null,2));
