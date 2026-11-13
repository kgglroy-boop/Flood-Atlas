import {fetchAnalysis,type AnalysisBundle,type AnalysisContext} from './analysis.ts';
export type AnalysisSession={attempt:number;stepId:string|null;state:'idle'|'loading'|'ready'|'error';bundle?:AnalysisBundle};
export function createAnalysisSession(
  notify:(s:AnalysisSession)=>void,
  fetcher:(context:AnalysisContext,signal:AbortSignal)=>Promise<AnalysisBundle>=fetchAnalysis,
  timeoutMs=10000,
) {
  let attempt=0,disposed=false;
  let controller:AbortController|undefined;
  const publish=(s:AnalysisSession)=>{if(!disposed)notify(s);};
  function clear() {
    ++attempt;controller?.abort();controller=undefined;
    publish({attempt,stepId:null,state:'idle'});
  }
  async function load(context:AnalysisContext) {
    if(disposed)return;
    const run=++attempt;controller?.abort();
    const current=new AbortController();controller=current;
    publish({attempt:run,stepId:context.stepId,state:'loading'});
    let abortListener:()=>void=()=>{};
    const aborted=new Promise<never>((_resolve,reject)=>{abortListener=()=>reject(new Error('cancelled'));current.signal.addEventListener('abort',abortListener,{once:true});});
    const timeout=setTimeout(()=>current.abort(),timeoutMs);
    try {
      const bundle=await Promise.race([fetcher(context,current.signal),aborted]);
      if(run===attempt&&!disposed&&!current.signal.aborted)publish({attempt:run,stepId:context.stepId,state:'ready',bundle});
    } catch {
      if(run===attempt&&!disposed)publish({attempt:run,stepId:context.stepId,state:'error'});
    } finally {
      clearTimeout(timeout);current.signal.removeEventListener('abort',abortListener);
      // A failed sibling must not outlive the pair after its controller is
      // released. Also safe after success: both response bodies are consumed.
      current.abort();
      if(controller===current)controller=undefined;
    }
  }
  return {load,clear,dispose(){disposed=true;clear();}};
}
