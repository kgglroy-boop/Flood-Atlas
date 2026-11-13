// Expected nonzero k6 exit: verifies checks are fatal for plausible HTTP 200s.
import { check } from 'k6';
import { healthValid, summaryValid } from './contract.mjs';
export const options={iterations:1,thresholds:{checks:['rate==1']}};
export default function(){
 check(null,{'bad JSON rejected as failed check':()=>healthValid(200,'{')});
 check(null,{'false healthy rejected as failed check':()=>healthValid(200,'{"status":"down"}')});
 const expected={step_id:'S01_T00',flooded_area_m2:0,affected_buildings:0,flooded_road_length_m:0};
 check(null,{'wrong statistics rejected as failed check':()=>summaryValid(200,JSON.stringify({...expected,affected_buildings:99}),expected,'x')});
}
