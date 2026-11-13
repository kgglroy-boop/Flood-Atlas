// Pure contract shared by Node tests and the local k6 workload.
export const thresholds = { http_req_failed: ['rate==0'], checks: ['rate==1'] };
function parsed(body) { try { return JSON.parse(body); } catch { return null; } }
export function healthValid(status, body) {
 const value=parsed(body);
 return status===200 && value!==null && typeof value==='object' && Object.keys(value).length===1 && value.status==='ok';
}
export function referenceRows(reference) {
 const ids=['S01_T00','S01_T30','S01_T60','S02_T00','S02_T30','S02_T60'];
 if(reference.status!=='ok'||reference.analysis_srid!==32650||!Array.isArray(reference.steps)||reference.steps.length!==6) throw Error('Invalid independent reference');
 return ids.map(id=>{
  const rows=reference.steps.filter(row=>row.step_id===id);
  if(rows.length!==1) throw Error('Missing/duplicate reference step');
  const r=rows[0];
  if(!Number.isFinite(r.flooded_area_m2)||r.flooded_area_m2<0||!Number.isFinite(r.flooded_road_length_m)||r.flooded_road_length_m<0||!Array.isArray(r.affected_building_ids)||new Set(r.affected_building_ids).size!==r.affected_building_ids.length) throw Error('Invalid independent metrics');
  return {step_id:id,flooded_area_m2:r.flooded_area_m2,affected_buildings:r.affected_building_ids.length,flooded_road_length_m:r.flooded_road_length_m};
 });
}
export function summaryValid(status,body,expected,generation) {
 const r=parsed(body);
 return status===200 && r!==null && r.step_id===expected.step_id && r.generation_id===generation && r.analysis_srid===32650 &&
  r.dataset_id==='teaching-v1' && r.model_type==='synthetic_demo' && r.threshold_m===0.1 &&
  r.affected_buildings===expected.affected_buildings &&
  Number.isFinite(r.flooded_area_m2)&&Math.abs(r.flooded_area_m2-expected.flooded_area_m2)<=0.01 &&
  Number.isFinite(r.flooded_road_length_m)&&Math.abs(r.flooded_road_length_m-expected.flooded_road_length_m)<=0.01;
}
