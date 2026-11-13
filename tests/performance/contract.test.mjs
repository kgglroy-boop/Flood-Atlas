import { test } from 'node:test';
import assert from 'node:assert/strict';
import { healthValid, summaryValid, referenceRows, thresholds } from './contract.mjs';
const reference = { status: 'ok', analysis_srid: 32650, steps: Array.from({length:6}, (_,i)=>({step_id:`S0${i<3?1:2}_T${['00','30','60'][i%3]}`,flooded_area_m2:i*100,affected_building_ids:Array.from({length:i},(_,j)=>`B${j}`),flooded_road_length_m:i*20})) };
test('health rejects HTTP failures, invalid JSON and false 200',()=>{
 assert.equal(healthValid(200,'{"status":"ok"}'),true);
 for(const [status,body] of [[503,'{"status":"ok"}'],[200,'{'],[200,'{"status":"down"}'],[200,'{"status":"ok","extra":1}']]) assert.equal(healthValid(status,body),false);
});
test('six independent reference rows and response identities/metrics required',()=>{
 const rows=referenceRows(reference); assert.equal(rows.length,6);
 for(const row of rows){
  const good={...row,generation_id:'74e68b2da680e9680f65',analysis_srid:32650,dataset_id:'teaching-v1',model_type:'synthetic_demo',threshold_m:0.1};
  assert.equal(summaryValid(200,JSON.stringify(good),row,'74e68b2da680e9680f65'),true);
  for(const patch of [{affected_buildings:99},{flooded_area_m2:row.flooded_area_m2+1},{flooded_road_length_m:row.flooded_road_length_m+1},{step_id:'S01_T99'},{generation_id:'wrong'},{analysis_srid:4326}]) assert.equal(summaryValid(200,JSON.stringify({...good,...patch}),row,'74e68b2da680e9680f65'),false);
 }
 assert.throws(()=>referenceRows({...reference,steps:reference.steps.slice(1)}));
 assert.throws(()=>referenceRows({...reference,steps:Array(6).fill(reference.steps[0])}));
 assert.equal(summaryValid(200,'bad',rows[0],'x'),false);
});
test('correctness thresholds are fatal, not a latency SLA',()=>{
 assert.deepEqual(thresholds.http_req_failed,['rate==0']);
 assert.deepEqual(thresholds.checks,['rate==1']);
 assert.equal(Object.keys(thresholds).some(k=>k.includes('duration')),false);
});
