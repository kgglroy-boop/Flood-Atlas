<script setup lang="ts">
import {onMounted,onBeforeUnmount,ref} from 'vue';
import {Map,NavigationControl,ScaleControl,type ImageSourceSpecification} from 'maplibre-gl';
import {PRESENTATION_ROOT,MAP_PAPER} from './presentation-map';

type Layer={id:'sentinel'|'hillshade';file:string;label:string;detail:string;credit:string};
type Corner=[number,number];
type Reference={version:1;corners:[Corner,Corner,Corner,Corner];layers:Layer[]};
const FILES={sentinel:'sentinel.webp',hillshade:'hillshade.png'} as const;
const emit=defineEmits<{close:[]}>();
const dialog=ref<HTMLDialogElement>();
const canvas=ref<HTMLDivElement>();
const layers=ref<Layer[]>([]);
const chosen=ref<Layer>();
const state=ref<'loading'|'ready'|'error'>('loading');
let controller:AbortController|undefined;
let viewer:Map|undefined;
let imageTimer:number|undefined;
let revision=0;
let activeSource='';

function parseReference(value:unknown):Reference {
  const manifest=value as Reference;
  if(manifest?.version!==1||!Array.isArray(manifest.corners)||manifest.corners.length!==4||
     !manifest.corners.every(p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite)&&Math.abs(p[0])<=180&&Math.abs(p[1])<=85)||
     !Array.isArray(manifest.layers)||manifest.layers.length<1||manifest.layers.length>2||
     !manifest.layers.every(layer=>layer&&Object.hasOwn(FILES,layer.id)&&layer.file===FILES[layer.id]&&
       [layer.label,layer.detail,layer.credit].every(text=>typeof text==='string'&&text.length>0))||
     new Set(manifest.layers.map(layer=>layer.id)).size!==manifest.layers.length)throw new Error('Invalid reference');
  const [nw,ne,se,sw]=manifest.corners;
  if(nw[0]!==sw[0]||ne[0]!==se[0]||nw[1]!==ne[1]||sw[1]!==se[1]||nw[0]>=ne[0]||nw[1]<=sw[1])throw new Error('Invalid extent');
  return manifest;
}

function choose(layer:Layer,coordinates:Reference['corners']) {
  if(!viewer)return;
  const map=viewer;
  if(activeSource&&map.getLayer(activeSource))map.removeLayer(activeSource);
  if(activeSource&&map.getSource(activeSource))map.removeSource(activeSource);
  window.clearTimeout(imageTimer);
  chosen.value=layer;
  state.value='loading';
  activeSource='public-reference-'+(++revision);
  const image:ImageSourceSpecification={type:'image',url:PRESENTATION_ROOT+layer.file,coordinates};
  map.addSource(activeSource,image);
  map.addLayer({id:activeSource,type:'raster',source:activeSource,paint:{'raster-fade-duration':0}});
  imageTimer=window.setTimeout(()=>{state.value='error';},10000);
}

let reference:Reference|undefined;
async function openReference() {
  controller?.abort();
  viewer?.remove();viewer=undefined;activeSource='';
  window.clearTimeout(imageTimer);
  const request=new AbortController();controller=request;
  const timeout=window.setTimeout(()=>request.abort(),8000);
  state.value='loading';layers.value=[];chosen.value=undefined;
  try{
    const response=await fetch(PRESENTATION_ROOT+'reference.json',{signal:request.signal});
    if(!response.ok)throw new Error('Reference unavailable');
    const manifest=parseReference(await response.json());
    if(request.signal.aborted||!canvas.value)throw new Error('Reference unavailable');
    reference=manifest;
    const [nw,,se]=manifest.corners;
    const map=new Map({container:canvas.value,bounds:[[nw[0],se[1]],[se[0],nw[1]]],
      fitBoundsOptions:{padding:22},minZoom:12,maxZoom:18,maxPitch:0,dragRotate:false,attributionControl:false,
      style:{version:8,sources:{},layers:[{id:'background',type:'background',paint:{'background-color':MAP_PAPER}}]}});
    viewer=map;
    map.addControl(new NavigationControl({showCompass:false}),'top-right');
    map.addControl(new ScaleControl({unit:'metric'}),'bottom-left');
    map.on('sourcedata',event=>{
      if(event.sourceId!==activeSource||event.sourceDataType!=='metadata')return;
      window.clearTimeout(imageTimer);state.value='ready';
    });
    map.on('error',event=>{
      const id=(event as typeof event & {sourceId?:string}).sourceId;
      if(id===activeSource||(!id&&!activeSource)){window.clearTimeout(imageTimer);state.value='error';}
    });
    imageTimer=window.setTimeout(()=>{state.value='error';},10000);
    map.once('load',()=>{
      layers.value=manifest.layers;
      choose(manifest.layers[0]!,manifest.corners);
    });
  }catch{
    if(controller===request)state.value='error';
  }finally{window.clearTimeout(timeout);}
}

function selectLayer(layer:Layer) {
  if(reference&&layer!==chosen.value)choose(layer,reference.corners);
}
onMounted(()=>{dialog.value?.showModal();void openReference();});
onBeforeUnmount(()=>{const request=controller;controller=undefined;request?.abort();window.clearTimeout(imageTimer);viewer?.remove();});
</script>

<template>
  <dialog ref="dialog" class="reference-dialog" aria-labelledby="reference-title" @close="emit('close')">
    <header class="reference-heading">
      <div><h2 id="reference-title">实景参考</h2><p>同一坐标范围的公开遥感资料</p></div>
      <button type="button" autofocus @click="dialog?.close()">返回教学地图</button>
    </header>
    <div v-if="layers.length" class="reference-options" role="group" aria-label="参考图层">
      <button v-for="layer in layers" :key="layer.id" type="button" :aria-pressed="layer===chosen"
        @click="selectLayer(layer)">{{ layer.label }}</button>
    </div>
    <figure class="reference-figure">
      <div class="reference-canvas" ref="canvas" aria-label="实景参考地图"></div>
      <div v-if="state!=='ready'" class="reference-message">
        <p role="status">{{ state==='loading'?'正在载入本地参考图层…':'参考图层暂时不可用。' }}</p>
        <button v-if="state==='error'" type="button" @click="openReference">重试参考图层</button>
      </div>
      <figcaption v-if="chosen"><strong>{{ chosen.detail }}</strong><span>{{ chosen.credit }}</span></figcaption>
    </figure>
    <p class="reference-foot">实景图仅用于地表对照。水深、建筑和道路影响结果在教学地图中查看。</p>
  </dialog>
</template>
