export type ScenarioStep={step_id:string;step_code:string;time_min:0|30|60;layer_id:string};
export type Scenario={scenario_id:'S01'|'S02';name:string;steps:ScenarioStep[]};
export type ScenarioCatalog={dataset_id:'teaching-v1';generation_id:string;model_type:'synthetic_demo';analysis_srid:32650;depth_unit:'m';threshold_m:0.1;scenarios:Scenario[]};

export function parseScenarioCatalog(value:unknown):ScenarioCatalog {
  const fail=():never=>{throw new Error('情景目录格式不符');};
  if(!value || typeof value!=='object') return fail();
  const v=value as Record<string,unknown>;
  if(v.dataset_id!=='teaching-v1' || typeof v.generation_id!=='string' || !/^[0-9a-f]{20}$/.test(v.generation_id) ||
    v.model_type!=='synthetic_demo' || v.analysis_srid!==32650 || v.depth_unit!=='m' || v.threshold_m!==.1 ||
    !Array.isArray(v.scenarios) || v.scenarios.length!==2) return fail();
  const scenarios:Scenario[]=[];
  for(const id of ['S01','S02'] as const) {
    const matches=v.scenarios.filter(s=>s && s.scenario_id===id);
    if(matches.length!==1) return fail();
    const s=matches[0];
    if(typeof s.name!=='string' || !s.name.trim() || !Array.isArray(s.steps) || s.steps.length!==3) return fail();
    const steps:ScenarioStep[]=[];
    for(const t of [0,30,60] as const) {
      const code=`T${String(t).padStart(2,'0')}`, stepId=`${id}_${code}`;
      const found=s.steps.filter((step:unknown)=>!!step && typeof step==='object' && (step as ScenarioStep).time_min===t);
      if(found.length!==1) return fail();
      const step=found[0];
      if(step.step_id!==stepId || step.step_code!==code || step.layer_id!==`flood:depth_${stepId}`) return fail();
      steps.push({step_id:stepId,step_code:code,time_min:t,layer_id:step.layer_id});
    }
    scenarios.push({scenario_id:id,name:s.name,steps});
  }
  return {dataset_id:'teaching-v1',generation_id:v.generation_id,model_type:'synthetic_demo',analysis_srid:32650,depth_unit:'m',threshold_m:.1,scenarios};
}

export async function fetchScenarioCatalog(signal?:AbortSignal):Promise<ScenarioCatalog> {
  const response=await fetch('/api/v1/scenarios',{signal,cache:'no-store'});
  if(!response.ok) throw new Error('情景目录暂不可用');
  return parseScenarioCatalog(await response.json());
}

export function selectStep(catalog:ScenarioCatalog,scenarioId:string,timeMin:number):ScenarioStep {
  const step=catalog.scenarios.find(s=>s.scenario_id===scenarioId)?.steps.find(s=>s.time_min===timeMin);
  if(!step) throw new Error('未知情景步骤');
  return step;
}
