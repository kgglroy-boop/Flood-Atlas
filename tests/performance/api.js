import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend, Counter, Rate } from 'k6/metrics';
import { healthValid, summaryValid, referenceRows, thresholds } from './contract.mjs';
const base='http://backend:8000';
const reference=JSON.parse(open('/results/reference.json'));
const rows=referenceRows(reference);
if(!/^[0-9a-f]{20}$/.test(reference.generation_id)) throw Error('Missing generation');
const vus=Number(__ENV.AUDIT_VUS), duration=__ENV.AUDIT_DURATION;
if(![1,5,10,20].includes(vus)||duration!==(vus===1?'10s':'30s')) throw Error('Unapproved load profile');
export const options={vus,duration,gracefulStop:'5s',summaryTrendStats:['count','p(50)','p(95)','max'],thresholds:{...thresholds,health_requests:['count>0'],summary_requests:['count>0']}};
const metrics={health:{duration:new Trend('health_duration',true),requests:new Counter('health_requests'),errors:new Rate('health_errors')},summary:{duration:new Trend('summary_duration',true),requests:new Counter('summary_requests'),errors:new Rate('summary_errors')}};
function request(endpoint,path,valid){
 const r=http.get(base+path,{timeout:'10s',tags:{endpoint,name:endpoint},redirects:0});
 const passed=check(r,{[endpoint+' status and contract']:response=>valid(response.status,response.body)});
 metrics[endpoint].duration.add(r.timings.duration);metrics[endpoint].requests.add(1);metrics[endpoint].errors.add(!passed);
 if(!passed) console.warn(JSON.stringify({endpoint,status:r.status,step:valid.step||null,error:'response contract failed'}));
}
export default function(){
 request('health','/api/v1/health',healthValid);
 const row=rows[(__ITER+__VU-1)%6];
 const valid=(status,body)=>summaryValid(status,body,row,reference.generation_id); valid.step=row.step_id;
 request('summary','/api/v1/analysis/summary?step_id='+row.step_id,valid);
 sleep(1);
}
export function handleSummary(data){return {'/results/summary.json':JSON.stringify(data,null,2),stdout:JSON.stringify({status:'recorded',vus,duration,metrics:data.metrics})+'\n'};}
