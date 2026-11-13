export type DepthSession={attempt:number;stepId:string|null;state:'idle'|'loading'|'ready'|'error'};
export function startDepthSession(previous:DepthSession,stepId:string):DepthSession {
  return {attempt:previous.attempt+1,stepId,state:'loading'};
}
export function clearDepthSession(previous:DepthSession):DepthSession {
  return {attempt:previous.attempt+1,stepId:null,state:'idle'};
}
export function shouldStartDepth(mapReady:boolean,stepId:string|null,current:DepthSession):boolean {
  return mapReady && stepId!==null && (current.state==='idle' || current.stepId!==stepId);
}
export function shouldRefocusDepth(isRetry:boolean,intersectsStudy:boolean):boolean {
  return isRetry && !intersectsStudy;
}
export function reduceDepthSession(current:DepthSession,event:{attempt:number;stepId:string;kind:'ready'|'error'|'timeout'}):DepthSession {
  if(current.attempt!==event.attempt || current.stepId!==event.stepId || current.state==='idle') return current;
  if(event.kind==='ready' && current.state==='error') return current;
  return {...current,state:event.kind==='ready'?'ready':'error'};
}
