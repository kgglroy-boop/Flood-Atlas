import {Map,NavigationControl,ScaleControl,setWorkerUrl} from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';
import {STUDY_BOUNDS} from './wms';
import {MAP_PAPER} from './presentation-map';

const status=document.getElementById('mvt-state')!;
const retry=document.getElementById('mvt-retry')!;
const label=document.getElementById('mvt-feature')!;
let failed=false;
function fail(){failed=true;status.textContent='建筑瓦片加载失败，请确认后端和数据库后重试';retry.hidden=false;}
retry.addEventListener('click',()=>location.reload());
setWorkerUrl(workerUrl);
try{
  const map=new Map({container:'mvt-map',bounds:STUDY_BOUNDS,fitBoundsOptions:{padding:70},maxPitch:0,maxZoom:19,attributionControl:false,
    style:{version:8,sources:{buildings:{type:'vector',tiles:[`${location.origin}/api/v1/tiles/buildings/{z}/{x}/{y}.pbf`],minzoom:0,maxzoom:19,
      bounds:[...STUDY_BOUNDS[0],...STUDY_BOUNDS[1]]}},layers:[
      {id:'background',type:'background',paint:{'background-color':MAP_PAPER}},
      {id:'building-fill',type:'fill',source:'buildings','source-layer':'buildings',paint:{'fill-color':'#bdcdd0','fill-opacity':.9}},
      {id:'building-outline',type:'line',source:'buildings','source-layer':'buildings',paint:{'line-color':'#16465b','line-width':1}},
    ]}});
  map.addControl(new NavigationControl({showCompass:false}),'top-right');map.addControl(new ScaleControl({unit:'metric'}));
  map.on('sourcedata',event=>{if(event.sourceId==='buildings'&&event.isSourceLoaded&&!failed)status.textContent='建筑矢量瓦片已加载';});
  map.on('error',fail);
  map.on('click','building-fill',event=>{
    const p=event.features?.[0]?.properties;
    if(p)label.textContent=`${String(p.building_id)} · ${String(p.name)} · 教学用途`;
  });
  window.addEventListener('pagehide',()=>map.remove(),{once:true});
}catch{fail();}
