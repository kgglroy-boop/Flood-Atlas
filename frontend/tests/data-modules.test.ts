import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parseModuleRegistry,loadMapModule,sha256} from '../src/data-modules.ts';
import {fixture,context} from './analysis-fixtures.ts';
const entry={id:'snapshot',label:'校验包',manifest:'/maps/snapshot/module.json'};
function catalog(){return {dataset_id:'teaching-v1',generation_id:context.generationId,model_type:'synthetic_demo',analysis_srid:32650,depth_unit:'m',threshold_m:.1,scenarios:['S01','S02'].map(s=>({scenario_id:s,name:s,steps:([0,30,60] as const).map(t=>({step_id:`${s}_T${String(t).padStart(2,'0')}`,step_code:`T${String(t).padStart(2,'0')}`,time_min:t,layer_id:`flood:depth_${s}_T${String(t).padStart(2,'0')}`}))}))};}
async function assets(){
 const files:Record<string,Uint8Array>={};const analyses:Record<string,unknown>={};
 for(const s of catalog().scenarios)for(const step of s.steps){analyses[step.step_id]=fixture(step.step_id);files[`depth_${step.step_id}.png`]=new Uint8Array(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==','base64'));}
 files['catalog.json']=new TextEncoder().encode(JSON.stringify(catalog()));files['analysis.json']=new TextEncoder().encode(JSON.stringify(analyses));
 const hashes=Object.fromEntries(await Promise.all(Object.entries(files).map(async([k,v])=>[k,await sha256(v)])));
 const corners:[[number,number],[number,number],[number,number],[number,number]]=[[117,31],[118,31],[118,30],[117,30]];
 return {files,manifest:{version:1,id:'snapshot',label:'校验包',kind:'package',generation_id:context.generationId,bounds:[[117,30],[118,31]],outline:corners,image_coordinates:corners,files:hashes}};
}
test('registry rejects cross-site paths, traversal, duplicate and unknown default modules',()=>{
 assert.equal(parseModuleRegistry({version:1,default:'snapshot',modules:[entry]}).modules.length,1);
 for(const path of ['https://example.org/x','/maps/../secret','/maps/x%2fy','//maps/a.json'])assert.throws(()=>parseModuleRegistry({version:1,default:'snapshot',modules:[{...entry,manifest:path}]}));
 assert.throws(()=>parseModuleRegistry({version:1,default:'unknown',modules:[entry]}));
 assert.throws(()=>parseModuleRegistry({version:1,default:'snapshot',modules:[entry,entry]}));
});
test('live adapter preserves public WMTS and injectable reconstruction origin',async()=>{
 const old=globalThis.fetch;try{
 globalThis.fetch=async()=>Response.json({version:1,id:'snapshot',kind:'api',label:'在线'});
 const module=await loadMapModule(entry,new AbortController().signal,'http://localhost:18080/geoserver');
 const source=module.depth(catalog().scenarios[0]!.steps[0]!);
 assert.equal(source.type,'raster');if(source.type==='raster')assert.ok(source.tiles![0]!.includes(':18080/geoserver/gwc/service/wmts'));
 module.dispose();}finally{globalThis.fetch=old;}
});
test('verified snapshot has six steps, current identities and revocable image assets',async()=>{
 const old=globalThis.fetch;const data=await assets();let reads=0;
 try{
 globalThis.fetch=async(input)=>{reads++;const name=String(input).split('/').at(-1)!;return name==='module.json'?Response.json(data.manifest):new Response(data.files[name] as BodyInit);};
 const module=await loadMapModule(entry,new AbortController().signal);
 const c=await module.catalog(new AbortController().signal);assert.equal(c.scenarios.length,2);
 for(const s of c.scenarios)for(const step of s.steps){const b=await module.analysis({...context,stepId:step.step_id},new AbortController().signal);assert.equal(b.buildings.features.length,200);assert.equal(module.depth(step).type,'image');}
 assert.equal(reads,9);module.dispose();assert.throws(()=>module.depth(c.scenarios[0]!.steps[0]!));
 }finally{globalThis.fetch=old;}
});
test('corruption and mixed generation never become a usable module',async()=>{
 const old=globalThis.fetch;
 try{for(const mutation of ['hash','generation','missing']){
  const data=await assets();if(mutation==='hash')data.manifest.files['analysis.json']='f'.repeat(64);if(mutation==='generation')data.manifest.generation_id='a'.repeat(20);if(mutation==='missing')delete data.manifest.files['depth_S02_T60.png'];
  globalThis.fetch=async(input)=>{const name=String(input).split('/').at(-1)!;return name==='module.json'?Response.json(data.manifest):new Response(data.files[name] as BodyInit);};
  await assert.rejects(loadMapModule(entry,new AbortController().signal));
 }}finally{globalThis.fetch=old;}
});
test('aborted module preparation cannot be installed after a late response',async()=>{
 const old=globalThis.fetch;const controller=new AbortController();try{
 globalThis.fetch=async()=>{controller.abort();return Response.json({version:1,id:'snapshot',kind:'api',label:'late'});};
 await assert.rejects(loadMapModule(entry,controller.signal));
 }finally{globalThis.fetch=old;}
});
