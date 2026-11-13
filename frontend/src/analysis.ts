export type AnalysisContext={stepId:string;generationId:string};
type Identity={step_id:string;dataset_id:'teaching-v1';generation_id:string;model_type:'synthetic_demo';analysis_srid:32650;threshold_m:0.1};
export type AnalysisSummary=Identity&{flooded_area_m2:number;affected_buildings:number;flooded_road_length_m:number};
export type BuildingFeature={type:'Feature';id:string;properties:{building_id:string;name:string;usage:'demo';affected:boolean};geometry:{type:'Polygon';coordinates:number[][][]}};
export type BuildingCollection={type:'FeatureCollection';features:BuildingFeature[];metadata:Identity&{geometry_srid:4326;limit:number;returned_count:200;total_buildings:200;truncated:false}};
export type AnalysisBundle={summary:AnalysisSummary;buildings:BuildingCollection};

const invalid=():never=>{throw new Error('分析数据暂不可用，请重试');};
function record(v:unknown):Record<string,unknown> {
  if(!v||typeof v!=='object'||Array.isArray(v))return invalid();
  return v as Record<string,unknown>;
}
function exact(v:Record<string,unknown>,keys:string[]) {
  if(Object.keys(v).length!==keys.length||keys.some(k=>!Object.hasOwn(v,k)))invalid();
}
const identityKeys=['step_id','dataset_id','generation_id','model_type','analysis_srid','threshold_m'];
function identity(v:Record<string,unknown>,context:AnalysisContext) {
  if(!/^S0[12]_T(?:00|30|60)$/.test(context.stepId)||!/^[a-f0-9]{20}$/.test(context.generationId)||
    v.step_id!==context.stepId||v.generation_id!==context.generationId||v.dataset_id!=='teaching-v1'||
    v.model_type!=='synthetic_demo'||v.analysis_srid!==32650||v.threshold_m!==.1)invalid();
}
function nonnegative(v:unknown):v is number{return typeof v==='number'&&Number.isFinite(v)&&v>=0;}

export function parseAnalysisBundle(summary:unknown,buildings:unknown,context:AnalysisContext):AnalysisBundle {
  const s=record(summary),b=record(buildings),m=record(b.metadata);
  exact(s,[...identityKeys,'flooded_area_m2','affected_buildings','flooded_road_length_m']);identity(s,context);
  exact(b,['type','features','metadata']);
  exact(m,[...identityKeys,'geometry_srid','limit','returned_count','total_buildings','truncated']);identity(m,context);
  if(!nonnegative(s.flooded_area_m2)||!nonnegative(s.flooded_road_length_m)||
    !nonnegative(s.affected_buildings)||!Number.isInteger(s.affected_buildings)||s.affected_buildings>200||
    b.type!=='FeatureCollection'||!Array.isArray(b.features)||b.features.length!==200||m.geometry_srid!==4326||
    m.limit!==200||m.returned_count!==200||m.total_buildings!==200||m.truncated!==false)return invalid();
  let previous='',affected=0;
  for(const raw of b.features) {
    const f=record(raw),p=record(f.properties),g=record(f.geometry);
    exact(f,['type','id','properties','geometry']);exact(p,['building_id','name','usage','affected']);exact(g,['type','coordinates']);
    if(f.type!=='Feature'||typeof f.id!=='string'||!f.id.trim()||f.id<=previous||p.building_id!==f.id||
      typeof p.name!=='string'||p.usage!=='demo'||typeof p.affected!=='boolean'||g.type!=='Polygon'||
      !Array.isArray(g.coordinates)||!g.coordinates.length)return invalid();
    previous=f.id;if(p.affected)affected++;
    for(const ring of g.coordinates) {
      if(!Array.isArray(ring)||ring.length<4)return invalid();
      for(const point of ring) {
        if(!Array.isArray(point)||point.length!==2||!point.every(v=>typeof v==='number'&&Number.isFinite(v))||
          Math.abs(point[0])>180||Math.abs(point[1])>90)return invalid();
      }
      if(ring[0][0]!==ring.at(-1)[0]||ring[0][1]!==ring.at(-1)[1])return invalid();
    }
  }
  if(affected!==s.affected_buildings)return invalid();
  return {summary:summary as AnalysisSummary,buildings:buildings as BuildingCollection};
}

export async function fetchAnalysis(context:AnalysisContext,signal:AbortSignal):Promise<AnalysisBundle> {
  try {
    const step=encodeURIComponent(context.stepId);
    const read=async(path:string)=>{
      const response=await fetch(`/api/v1/analysis/${path}?step_id=${step}`,{signal,cache:'no-store'});
      if(!response.ok)return invalid();
      return response.json();
    };
    const [summary,buildings]=await Promise.all([read('summary'),read('buildings')]);
    return parseAnalysisBundle(summary,buildings,context);
  } catch {return invalid();}
}
