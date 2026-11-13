export const context = {stepId:'S02_T60',generationId:'74e68b2da680e9680f65'};
export function fixture(stepId=context.stepId) {
  const identity={step_id:stepId,dataset_id:'teaching-v1',generation_id:context.generationId,model_type:'synthetic_demo',analysis_srid:32650,threshold_m:.1};
  const wet=!stepId.endsWith('T00');
  return {
    summary:{...identity,flooded_area_m2:wet?150:0,affected_buildings:wet?1:0,flooded_road_length_m:wet?30:0},
    buildings:{type:'FeatureCollection',metadata:{...identity,geometry_srid:4326,limit:200,returned_count:200,total_buildings:200,truncated:false},features:Array.from({length:200},(_,i)=>{
      const id=`B${String(i+1).padStart(3,'0')}`;
      return {type:'Feature',id,properties:{building_id:id,name:`教学建筑${i+1}`,usage:'demo',affected:wet&&i===0},geometry:{type:'Polygon',coordinates:[[[117,30],[117.001,30],[117.001,30.001],[117,30]]]}};
    })},
  };
}
