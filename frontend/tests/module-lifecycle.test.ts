import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import ts from 'typescript';
import {loadMapModule} from '../src/data-modules.ts';
import * as wms from '../src/wms.ts';
import * as scenarios from '../src/scenarios.ts';

const entry={id:'live',label:'在线',manifest:'/maps/live/module.json'};
const bounds=[[114,30],[114.02,30.01]];
const outline=[[114,30.01],[114.02,30.01],[114.02,30],[114,30]];
const manifest={version:1,id:'live',label:'在线',kind:'api',bounds,outline};
const catalog={dataset_id:'teaching-v1',generation_id:'0123456789abcdef0123',model_type:'synthetic_demo',analysis_srid:32650,depth_unit:'m',threshold_m:.1,scenarios:['S01','S02'].map(s=>({scenario_id:s,name:s,steps:[0,30,60].map(t=>({step_id:`${s}_T${String(t).padStart(2,'0')}`,step_code:`T${String(t).padStart(2,'0')}`,time_min:t,layer_id:`flood:depth_${s}_T${String(t).padStart(2,'0')}`}))}))};
function deferred<T>(){let resolve!:(v:T)=>void;const promise=new Promise<T>(r=>{resolve=r;});return {promise,resolve};}
async function until(check:()=>boolean){for(let i=0;i<100;i++){if(check())return;await Promise.resolve();}throw new Error('Expected async stage not reached');}
function harness(reducedMotion=false){
 let now=0,next=0,mount=()=>{};const timers=new Map<number,{due:number;fn:()=>void}>();
 const writes:{bounds:unknown[];outline:unknown[];durations:number[]}={bounds:[],outline:[],durations:[]};
 const maps:FakeMap[]=[];
 class FakeMap {
  events=new Map<string,()=>void>();
  touchZoomRotate={disableRotation(){}};
  constructor(){maps.push(this);}
  addControl(){} remove(){} getLayer(){return undefined;} removeLayer(){} removeSource(){}
  getSource(){return {type:'geojson',setData:(data:unknown)=>writes.outline.push(JSON.parse(JSON.stringify(data))) };}
  fitBounds(value:unknown,options?:{duration?:number}){writes.bounds.push(JSON.parse(JSON.stringify(value)));if(options?.duration!==undefined)writes.durations.push(options.duration);}
  on(name:string,callback:()=>void){this.events.set(name,callback);}
  off(){}
 }
 const noop=()=>{};
 const modules:Record<string,unknown>={
  vue:{ref:(value:unknown)=>({value}),shallowRef:(value:unknown)=>({value}),computed:(fn:()=>unknown)=>({get value(){return fn();}}),watch:noop,onMounted:(fn:()=>void)=>{mount=fn;},onBeforeUnmount:noop},
  'maplibre-gl':{Map:FakeMap,Popup:class{},NavigationControl:class{},ScaleControl:class{},setWorkerUrl:noop},
  'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url':{default:'worker'},
  './health':{probeHealth:async()=>{}},'./wms':wms,'./scenarios':scenarios,
  './depth-session':{clearDepthSession:()=>({attempt:0,stepId:null,state:'idle'})},
  './analysis-session':{createAnalysisSession:()=>({clear:noop,load:noop,dispose:noop})},
  './analysis-view':{},'./building-map':{createBuildingOverlay:()=>({clear:noop,select:noop,dispose:noop})},
  './building-search':{},'./ReferenceViewer.vue':{},'./presentation-map':{addTeachingRoads:noop,quietMap:noop},
  './data-modules':{loadMapModule,loadModuleRegistry:async()=>({default:'live',modules:[entry]})},
 };
 const source=readFileSync(new URL('../src/App.vue',import.meta.url),'utf8').split('<script setup lang="ts">')[1]!.split('</script>')[0]!.replace('import.meta.env.VITE_GEOSERVER_URL','undefined');
 const code=ts.transpileModule(source+'\nglobalThis.__app={activateModule,refreshCatalog,returnToStudy,moduleOptions,dataModule,moduleState,catalogState,mapContainer};',{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true}}).outputText;
 const context:any={exports:{},AbortController,Date,window:{matchMedia:()=>({matches:reducedMotion}),setTimeout:(fn:()=>void,ms:number)=>{const id=++next;timers.set(id,{fn,due:now+ms});return id;},clearTimeout:(id:number)=>timers.delete(id)},require:(name:string)=>{if(!(name in modules))throw new Error('Unexpected dependency '+name);return modules[name];}};
 runInNewContext(code,context);const app=context.__app;app.moduleOptions.value=[entry];
 return {app,writes,maps,mount:()=>mount(),tick:(ms:number)=>{now+=ms;for(const [id,timer] of [...timers])if(timer.due<=now){timers.delete(id);timer.fn();}}};
}

test('return-to-study camera movement respects the system reduced-motion preference',()=>{
 for(const reduced of [false,true]){
  const h=harness(reduced);h.app.mapContainer.value={};h.mount();h.app.returnToStudy();
  assert.equal(h.writes.durations.at(-1),reduced?0:600);
 }
});

test('module preparation deadline cannot poison a ready provider during its separately timed catalog request',async()=>{
 const original=globalThis.fetch;const manifestResponse=deferred<Response>(),catalogResponse=deferred<Response>();let catalogCalled=false;
 try {
  globalThis.fetch=async input=>{if(String(input).includes('module.json'))return manifestResponse.promise;catalogCalled=true;return catalogResponse.promise;};
  const h=harness(),activation=h.app.activateModule('live');h.tick(3000);manifestResponse.resolve(Response.json(manifest));
  await until(()=>catalogCalled);h.tick(9500);catalogResponse.resolve(Response.json(catalog));await activation;
  assert.equal(h.app.moduleState.value,'ready');assert.equal(h.app.catalogState.value,'ready');
  assert.doesNotThrow(()=>h.app.dataModule.value.depth(catalog.scenarios[0]!.steps[0]!));
  globalThis.fetch=async()=>Response.json(catalog);await h.app.refreshCatalog();
  assert.doesNotThrow(()=>h.app.dataModule.value.depth(catalog.scenarios[0]!.steps[0]!));
 }finally{globalThis.fetch=original;}
});

test('module bounds and outline are applied for both map-first and module-first startup',async()=>{
 const original=globalThis.fetch;
 try {
  globalThis.fetch=async input=>Response.json(String(input).includes('module.json')?manifest:catalog);
  for(const mapFirst of [false,true]){
   const h=harness();h.app.mapContainer.value={};h.mount();
   if(mapFirst)h.maps[0]!.events.get('load')!();
   await h.app.activateModule('live');
   if(!mapFirst)h.maps[0]!.events.get('load')!();
   assert.deepEqual(h.writes.bounds.at(-1),bounds,`mapFirst=${mapFirst}`);
   assert.deepEqual((h.writes.outline.at(-1) as any).geometry.coordinates,[[...outline,outline[0]]]);
  }
 }finally{globalThis.fetch=original;}
});
