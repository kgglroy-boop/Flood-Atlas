import assert from 'node:assert/strict';
import {test} from 'node:test';
import {startDepthSession,reduceDepthSession,clearDepthSession,shouldStartDepth,shouldRefocusDepth,type DepthSession} from '../src/depth-session.ts';

const idle:DepthSession={attempt:0,stepId:null,state:'idle'};
test('A B A rejects first A success error and timeout',()=>{
  const a=startDepthSession(idle,'S02_T60');
  const b=startDepthSession(a,'S01_T30');
  const finalA=startDepthSession(b,'S02_T60');
  for(const kind of ['ready','error','timeout'] as const) {
    assert.deepEqual(reduceDepthSession(finalA,{attempt:a.attempt,stepId:a.stepId!,kind}),finalA);
  }
  const failed=reduceDepthSession(finalA,{attempt:finalA.attempt,stepId:finalA.stepId!,kind:'timeout'});
  assert.equal(failed.state,'error');
  assert.equal(reduceDepthSession(failed,{attempt:failed.attempt,stepId:failed.stepId!,kind:'ready'}).state,'error');
  const retry=startDepthSession(failed,failed.stepId!);
  assert.equal(reduceDepthSession(retry,{attempt:retry.attempt,stepId:retry.stepId!,kind:'ready'}).state,'ready');
});
test('map and catalog can finish in either order without duplicate start',()=>{
  assert.equal(shouldStartDepth(false,'S02_T60',idle),false);
  assert.equal(shouldStartDepth(true,null,idle),false);
  assert.equal(shouldStartDepth(true,'S02_T60',idle),true);
  const started=startDepthSession(idle,'S02_T60');
  assert.equal(shouldStartDepth(true,'S02_T60',started),false);
  const cleared=clearDepthSession(started);
  assert.equal(cleared.state,'idle');
  assert.equal(reduceDepthSession(cleared,{attempt:started.attempt,stepId:started.stepId!,kind:'ready'}).state,'idle');
});
test('zero-minute content readiness is independent of visible pixels',()=>{
  const dry=startDepthSession(idle,'S01_T00');
  assert.equal(reduceDepthSession(dry,{attempt:dry.attempt,stepId:dry.stepId!,kind:'ready'}).state,'ready');
});
test('selection preserves outside viewport and only explicit retry recenters',()=>{
  assert.equal(shouldRefocusDepth(false,false),false);
  assert.equal(shouldRefocusDepth(false,true),false);
  assert.equal(shouldRefocusDepth(true,false),true);
  assert.equal(shouldRefocusDepth(true,true),false);
});
