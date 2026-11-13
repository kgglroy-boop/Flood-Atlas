import assert from 'node:assert/strict';
import {test} from 'node:test';
import {parseAnalysisBundle,fetchAnalysis} from '../src/analysis.ts';
import {fixture,context} from './analysis-fixtures.ts';

test('accepts complete current wet and dry analysis with real zero semantics',()=>{
  for(const stepId of ['S02_T60','S01_T00']) {
    const f=fixture(stepId),bundle=parseAnalysisBundle(f.summary,f.buildings,{...context,stepId});
    assert.equal(bundle.buildings.features.length,200);
    assert.equal(bundle.summary.affected_buildings,stepId.endsWith('T00')?0:1);
  }
});
test('rejects mixed identity invalid numbers and incomplete or corrupt geometry',()=>{
  const mutations:Array<(f:ReturnType<typeof fixture>)=>void>=[
    f=>{f.summary.step_id='S01_T30';},f=>{f.buildings.metadata.generation_id='a'.repeat(20);},
    f=>{f.summary.analysis_srid=4326;},f=>{f.summary.threshold_m=.2;},
    f=>{f.summary.flooded_area_m2=NaN;},f=>{f.summary.flooded_road_length_m=-1;},
    f=>{f.summary.affected_buildings=2;},f=>{f.buildings.metadata.truncated=true;},
    f=>{f.buildings.features.pop();},f=>{f.buildings.features[1]!.id='B001';},
    f=>{f.buildings.features.reverse();},f=>{f.buildings.features[0]!.geometry.coordinates[0]![0]![0]=500000;},
    f=>{f.buildings.features[0]!.geometry.coordinates[0]!.pop();},
    f=>{f.buildings.metadata.geometry_srid=32650;},
  ];
  for(const mutate of mutations) {const f=fixture();mutate(f);assert.throws(()=>parseAnalysisBundle(f.summary,f.buildings,context));}
});
test('HTTP uses relative two endpoint URLs and rejects HTML and503 without raw details',async()=>{
  const original=globalThis.fetch;
  const urls:string[]=[];const f=fixture();
  try {
    globalThis.fetch=async(input,options)=>{urls.push(String(input));assert.equal(options?.cache,'no-store');return Response.json(String(input).includes('/summary')?f.summary:f.buildings);};
    await fetchAnalysis(context,new AbortController().signal);
    assert.deepEqual(urls.sort(),['/api/v1/analysis/buildings?step_id=S02_T60','/api/v1/analysis/summary?step_id=S02_T60']);
    for(const response of [new Response('<html>SECRET</html>'),new Response('SECRET',{status:503})]) {
      globalThis.fetch=async()=>response.clone();
      await assert.rejects(fetchAnalysis(context,new AbortController().signal),error=>error instanceof Error&&!error.message.includes('SECRET'));
    }
  } finally {globalThis.fetch=original;}
});
