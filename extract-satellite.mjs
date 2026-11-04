import fs from 'node:fs';
import {fromUrl} from 'geotiff';
import proj4 from 'proj4';
import {PNG} from 'pngjs';
const dir='data/yale-farm/';
const scenes=JSON.parse(fs.readFileSync(dir+'sentinel-scenes.json')).features.sort((a,b)=>b.properties.datetime.localeCompare(a.properties.datetime));
const scene=scenes[0];
if(scene.properties['proj:epsg']!==32618)throw Error('Expected UTM zone 18N');
const utm='+proj=utm +zone=18 +datum=WGS84 +units=m +no_defs';
const ex=JSON.parse(fs.readFileSync(dir+'aerial-export.json')).extent;
const bbox=[ex.xmin,ex.ymin,ex.xmax,ex.ymax];
const corners=[[bbox[0],bbox[1]],[bbox[0],bbox[3]],[bbox[2],bbox[1]],[bbox[2],bbox[3]]].map(p=>proj4('EPSG:4326',utm,p));
async function windowFor(asset){const tiff=await fromUrl(asset.href,{allowFullFile:false});const image=await tiff.getImage();const origin=image.getOrigin(),resolution=image.getResolution();const pixels=corners.map(([x,y])=>[(x-origin[0])/resolution[0],(y-origin[1])/resolution[1]]);const win=[Math.floor(Math.min(...pixels.map(p=>p[0]))),Math.floor(Math.min(...pixels.map(p=>p[1]))),Math.ceil(Math.max(...pixels.map(p=>p[0]))),Math.ceil(Math.max(...pixels.map(p=>p[1])))];if(win[0]<0||win[1]<0||win[2]>image.getWidth()||win[3]>image.getHeight())throw Error('Requested area outside image');const bands=await image.readRasters({window:win});return {bands,origin,resolution,win,width:win[2]-win[0]};}
const rgb=await windowFor(scene.assets.visual);
const scl=await windowFor(scene.assets.scl);
const width=600,height=500,png=new PNG({width,height});
function indexFor(r,p){return (Math.floor((p[1]-r.origin[1])/r.resolution[1])-r.win[1])*r.width+Math.floor((p[0]-r.origin[0])/r.resolution[0])-r.win[0];}
for(let y=0;y<height;y++)for(let x=0;x<width;x++){const lon=bbox[0]+(x+0.5)/width*(bbox[2]-bbox[0]),lat=bbox[3]-(y+0.5)/height*(bbox[3]-bbox[1]);const p=proj4('EPSG:4326',utm,[lon,lat]);const idx=indexFor(rgb,p),offset=(y*width+x)*4;for(let b=0;b<3;b++)png.data[offset+b]=rgb.bands[b][idx];png.data[offset+3]=255;}
fs.writeFileSync(dir+'sentinel-2026-10-23.png',PNG.sync.write(png));
const counts={};for(const v of scl.bands[0])counts[v]=(counts[v]||0)+1;
fs.writeFileSync(dir+'satellite-extract.json',JSON.stringify({scene_id:scene.id,date:scene.properties.datetime,bbox,visual_native_pixel_meters:10,classification_native_pixel_meters:20,display:'Nearest-neighbor reprojection; enlarged display does not add detail',classification_counts_in_neighborhood_window:counts,classification_scope:'Neighborhood window, not farm-only; no drought index calculated',source:scene.assets.visual.href,classification_source:scene.assets.scl.href},null,2));
console.log('Satellite crop saved; neighborhood scene-classification counts:',counts);
