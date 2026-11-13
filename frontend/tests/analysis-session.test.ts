import assert from 'node:assert/strict';
import {test} from 'node:test';
import {setTimeout as delay} from 'node:timers/promises';
import {createAnalysisSession,type AnalysisSession} from '../src/analysis-session.ts';
import {parseAnalysisBundle,type AnalysisBundle} from '../src/analysis.ts';
import {fixture,context} from './analysis-fixtures.ts';
const bundle=(stepId:string)=>{const f=fixture(stepId);return parseAnalysisBundle(f.summary,f.buildings,{...context,stepId});};
function deferred() {let resolve!:(b:AnalysisBundle)=>void;let reject!:(e:Error)=>void;const promise=new Promise<AnalysisBundle>((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
test('A B A ignores first A even when transport ignores abort',async()=>{
  const calls=[deferred(),deferred(),deferred()];let i=0;const states:AnalysisSession[]=[];
  const loader=createAnalysisSession(s=>states.push(s),async()=>calls[i++]!.promise);
  const a=loader.load(context),b=loader.load({...context,stepId:'S01_T30'}),a2=loader.load(context);
  calls[2]!.resolve(bundle('S02_T60'));await a2;
  calls[0]!.resolve(bundle('S02_T60'));calls[1]!.reject(new Error('SECRET'));
  await Promise.all([a,b]);
  assert.equal(states.filter(s=>s.state==='ready').length,1);
  assert.equal(states.at(-1)!.attempt,3);
  assert.equal(states.at(-1)!.state,'ready');loader.dispose();
});
test('retry clears old bundle before success and failure never retains it',async()=>{
  const states:AnalysisSession[]=[];let fail=false;
  const loader=createAnalysisSession(s=>states.push(s),async()=>{if(fail)throw new Error('SECRET');return bundle(context.stepId);});
  await loader.load(context);fail=true;await loader.load(context);
  assert.deepEqual(states.map(s=>s.state),['loading','ready','loading','error']);
  assert.ok(!JSON.stringify(states.at(-1)).includes('SECRET'));
  assert.equal(states.at(-1)!.bundle,undefined);loader.dispose();
});
test('timeout publishes error even if transport ignores cancellation; late result stays hidden',async()=>{
  const d=deferred(),states:AnalysisSession[]=[];
  const loader=createAnalysisSession(s=>states.push(s),async()=>d.promise,10);
  const run=loader.load(context);await delay(30);
  assert.equal(states.at(-1)!.state,'error');
  d.resolve(bundle(context.stepId));await run;
  assert.equal(states.at(-1)!.state,'error');loader.dispose();
});
test('clear and dispose invalidate in-flight requests and abort their signals',async()=>{
  const d=deferred(),states:AnalysisSession[]=[];let signal:AbortSignal|undefined;
  const loader=createAnalysisSession(s=>states.push(s),async(_c,s)=>{signal=s;return d.promise;});
  const run=loader.load(context);loader.clear();assert.equal(signal?.aborted,true);
  loader.dispose();const count=states.length;d.resolve(bundle(context.stepId));await run;
  assert.equal(states.length,count);assert.equal(states.at(-1)!.state,'idle');
});

test('an early HTTP failure aborts the pending sibling before dropping its controller',async()=>{
  const original=globalThis.fetch,states:AnalysisSession[]=[];
  let active=0,signal:AbortSignal|undefined;
  const loader=createAnalysisSession(s=>states.push(s));
  try {
    globalThis.fetch=async(input,options)=>{
      if(String(input).includes('/summary'))return new Response('unavailable',{status:503});
      signal=options?.signal??undefined;active++;
      return new Promise<Response>((_resolve,reject)=>{
        signal!.addEventListener('abort',()=>{active--;reject(new Error('cancelled'));},{once:true});
      });
    };
    await loader.load(context);
    assert.equal(states.at(-1)!.state,'error');
    assert.equal(signal?.aborted,true,'paired request must be cancelled on early failure');
    assert.equal(active,0,'no orphan sibling request may remain after failure');
    loader.clear();loader.dispose();
    assert.equal(active,0);
  } finally {loader.dispose();globalThis.fetch=original;}
});
