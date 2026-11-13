import type {SourceSpecification} from 'maplibre-gl';
import {fetchScenarioCatalog,parseScenarioCatalog,type ScenarioCatalog,type ScenarioStep} from './scenarios.ts';
import {fetchAnalysis,parseAnalysisBundle,type AnalysisBundle,type AnalysisContext} from './analysis.ts';
import {buildDepthTileUrl,STUDY_BOUNDS,STUDY_CORNERS} from './wms.ts';

export type ModuleEntry={id:string;label:string;manifest:string};
export type Bounds=[[number,number],[number,number]];
export type Corners=[[number,number],[number,number],[number,number],[number,number]];
export type MapDataModule={id:string;label:string;kind:'api'|'package';bounds:Bounds;outline:Corners;catalog:(signal:AbortSignal)=>Promise<ScenarioCatalog>;analysis:(context:AnalysisContext,signal:AbortSignal)=>Promise<AnalysisBundle>;depth:(step:ScenarioStep)=>SourceSpecification;dispose:()=>void};
const fail=():never=>{throw new Error('地图数据模块不可用，请检查配置或数据包');};
function path(value:unknown):string{
 if(typeof value!=='string'||!/^\/maps\/[A-Za-z0-9_./-]+$/.test(value)||value.includes('//')||value.split('/').some(x=>x==='.'||x==='..'))return fail();
 return value;
}
export function parseModuleRegistry(value:unknown):{default:string;modules:ModuleEntry[]}{
 const v=value as {version?:number;default?:string;modules?:ModuleEntry[]};
 if(!v||v.version!==1||!Array.isArray(v.modules)||v.modules.length<1||v.modules.length>12)return fail();
 const seen=new Set<string>();const modules=v.modules.map(e=>{
  if(!e||typeof e.id!=='string'||!/^[a-z0-9][a-z0-9-]{0,47}$/.test(e.id)||seen.has(e.id)||typeof e.label!=='string'||!e.label.trim()||e.label.length>48)return fail();
  seen.add(e.id);return {id:e.id,label:e.label,manifest:path(e.manifest)};
 });
 if(typeof v.default!=='string'||!seen.has(v.default))return fail();return {default:v.default,modules};
}
async function bytes(url:string,signal:AbortSignal):Promise<Uint8Array>{
 const r=await fetch(url,{signal,cache:'no-store',redirect:'error'});if(!r.ok)return fail();
 const value=new Uint8Array(await r.arrayBuffer());signal.throwIfAborted();if(value.length>4*1024*1024)return fail();return value;
}
function json(value:Uint8Array):any{try{return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(value));}catch{return fail();}}
export async function sha256(value:Uint8Array):Promise<string>{
 const digest=await crypto.subtle.digest('SHA-256',new Uint8Array(value).buffer);
 return Array.from(new Uint8Array(digest),v=>v.toString(16).padStart(2,'0')).join('');
}
export async function loadModuleRegistry(signal:AbortSignal){return parseModuleRegistry(json(await bytes('/maps/registry.json',signal)));}
function point(v:any):v is [number,number]{return Array.isArray(v)&&v.length===2&&v.every(Number.isFinite)&&Math.abs(v[0])<=180&&Math.abs(v[1])<=90;}
function view(m:any):{bounds:Bounds;outline:Corners}{
 const bounds=m.bounds??STUDY_BOUNDS,outline=m.outline??STUDY_CORNERS;
 if(!Array.isArray(bounds)||bounds.length!==2||!bounds.every(point)||bounds[0][0]>=bounds[1][0]||bounds[0][1]>=bounds[1][1]||!Array.isArray(outline)||outline.length!==4||!outline.every(point))return fail();
 if(outline.some((p:[number,number])=>p[0]<bounds[0][0]-1e-7||p[0]>bounds[1][0]+1e-7||p[1]<bounds[0][1]-1e-7||p[1]>bounds[1][1]+1e-7))return fail();
 return {bounds:bounds as Bounds,outline:outline as Corners};
}
export async function loadMapModule(entry:ModuleEntry,signal:AbortSignal,geoBase?:string):Promise<MapDataModule>{
 const blobs:string[]=[];let disposed=false;
 try{
  const manifestPath=path(entry.manifest);const m=json(await bytes(manifestPath,signal));
  if(m.version!==1||m.id!==entry.id||typeof m.label!=='string'||m.label.length>48||!['api','package'].includes(m.kind))return fail();
  const geometry=view(m);const guard=()=>{signal.throwIfAborted();if(disposed)return fail();};
  const dispose=()=>{disposed=true;for(const url of blobs)URL.revokeObjectURL(url);blobs.length=0;};
  if(m.kind==='api'){
   buildDepthTileUrl(undefined,geoBase??m.geoserver);
   return {id:entry.id,label:m.label,kind:'api',...geometry,
    catalog:fetchScenarioCatalog,analysis:fetchAnalysis,
    depth:step=>{guard();return {type:'raster',tiles:[buildDepthTileUrl(step.layer_id,geoBase??m.geoserver)],tileSize:256,bounds:[...geometry.bounds[0],...geometry.bounds[1]],minzoom:0,maxzoom:19};},dispose};
  }
  const steps=['S01_T00','S01_T30','S01_T60','S02_T00','S02_T30','S02_T60'];
  const names=['catalog.json','analysis.json',...steps.map(s=>`depth_${s}.png`)];
  if(!m.files||Object.keys(m.files).length!==8||!names.every(n=>typeof m.files[n]==='string'&&/^[0-9a-f]{64}$/.test(m.files[n]))||!Array.isArray(m.image_coordinates)||m.image_coordinates.length!==4||!m.image_coordinates.every(point))return fail();
  const base=manifestPath.slice(0,manifestPath.lastIndexOf('/')+1);
  const entries=await Promise.all(names.map(async name=>{const value=await bytes(base+name,signal);if(await sha256(value)!==m.files[name])return fail();return [name,value] as const;}));
  guard();const assets=Object.fromEntries(entries);const catalog=parseScenarioCatalog(json(assets['catalog.json']!));
  if(catalog.generation_id!==m.generation_id)return fail();
  const raw=json(assets['analysis.json']!);if(!raw||Object.keys(raw).length!==6)return fail();
  const analyses:Record<string,AnalysisBundle>={},images:Record<string,string>={};
  for(const step of steps){
   analyses[step]=parseAnalysisBundle(raw[step]?.summary,raw[step]?.buildings,{stepId:step,generationId:catalog.generation_id});
   const png=assets[`depth_${step}.png`]!;
   if(png.length<24||png.slice(0,8).join(',')!=='137,80,78,71,13,10,26,10')return fail();
  }
  for(const step of steps){const url=URL.createObjectURL(new Blob([new Uint8Array(assets[`depth_${step}.png`]!).buffer],{type:'image/png'}));images[step]=url;blobs.push(url);}
  guard();return {id:entry.id,label:m.label,kind:'package',...geometry,
   catalog:async request=>{request.throwIfAborted();guard();return structuredClone(catalog);},
   analysis:async(context,request)=>{request.throwIfAborted();guard();const b=analyses[context.stepId];if(!b)return fail();return structuredClone(parseAnalysisBundle(b.summary,b.buildings,context));},
   depth:step=>{guard();const url=images[step.step_id];if(!url)return fail();return {type:'image',url,coordinates:m.image_coordinates};},dispose};
 }catch(error){for(const url of blobs)URL.revokeObjectURL(url);if(signal.aborted)signal.throwIfAborted();return fail();}
}
