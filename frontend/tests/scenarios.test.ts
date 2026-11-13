import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parseScenarioCatalog, selectStep, fetchScenarioCatalog} from '../src/scenarios.ts';
import {buildDepthTileUrl} from '../src/wms.ts';

export function catalogValue() {
  return {dataset_id:'teaching-v1',generation_id:'74e68b2da680e9680f65',model_type:'synthetic_demo',analysis_srid:32650,depth_unit:'m',threshold_m:.1,
    scenarios:['S02','S01'].map(id => ({scenario_id:id,name:`教学${id}`,steps:[60,0,30].map(t => ({
      step_id:`${id}_T${String(t).padStart(2,'0')}`,step_code:`T${String(t).padStart(2,'0')}`,time_min:t,layer_id:`flood:depth_${id}_T${String(t).padStart(2,'0')}`,
    }))}))};
}
test('catalog sorts all six steps and changing scenario preserves minutes', () => {
  const catalog=parseScenarioCatalog(catalogValue());
  assert.deepEqual(catalog.scenarios.map(s=>s.scenario_id),['S01','S02']);
  assert.equal(selectStep(catalog,'S02',60).step_id,'S02_T60');
  assert.equal(selectStep(catalog,'S01',30).time_min,30);
  for(const scenario of catalog.scenarios) for(const step of scenario.steps) {
    assert.equal(new URL(buildDepthTileUrl(step.layer_id)).searchParams.get('LAYER'),step.layer_id);
  }
  assert.throws(()=>selectStep(catalog,'S99',60));
  assert.throws(()=>buildDepthTileUrl('flood:owner'));
});
test('catalog rejects malformed incomplete and foreign responses',()=>{
  for(const mutate of [
    (v:any)=>{v.scenarios[0].steps.pop();}, (v:any)=>{v.scenarios[0].steps[0].layer_id='flood:owner';},
    (v:any)=>{v.generation_id='../owner';}, (v:any)=>{v.analysis_srid=4326;}, (v:any)=>{v.scenarios[0].steps[0].time_min=99;},
  ]) {const value=catalogValue();mutate(value);assert.throws(()=>parseScenarioCatalog(value));}
  assert.throws(()=>parseScenarioCatalog(null));
});
test('fetch uses relative API and rejects HTTP and JSON errors',async()=>{
  const original=globalThis.fetch;
  try {
    globalThis.fetch=async(input)=>{assert.equal(input,'/api/v1/scenarios');return Response.json(catalogValue());};
    assert.equal((await fetchScenarioCatalog()).scenarios.length,2);
    globalThis.fetch=async()=>new Response('unavailable',{status:503});
    await assert.rejects(fetchScenarioCatalog());
    globalThis.fetch=async()=>new Response('bad json');
    await assert.rejects(fetchScenarioCatalog());
  } finally {globalThis.fetch=original;}
});
