import type {AnalysisBundle,BuildingFeature} from './analysis.ts';
import type {AnalysisSession} from './analysis-session.ts';
import type {DepthSession} from './depth-session.ts';

export function visibleAnalysis(stepId:string|null,analysis:AnalysisSession,depth:DepthSession):AnalysisBundle|undefined {
  return stepId&&analysis.stepId===stepId&&depth.stepId===stepId&&analysis.state==='ready'&&depth.state==='ready'
    ?analysis.bundle:undefined;
}
export function formatMetric(value:number):string {
  return new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(value);
}
export function buildingDetails(feature:BuildingFeature,stepId:string):Array<[string,string]> {
  return [['建筑编号',feature.id],['名称',feature.properties.name],['用途','教学建筑'],['当前步骤',stepId],
    ['相交状态',feature.properties.affected?'与淹没范围相交（含边界）':'未与淹没范围相交']];
}
export function createBuildingPopup(feature:BuildingFeature,stepId:string,doc:Document=document):HTMLElement {
  const root=doc.createElement('section');root.className='building-popup';
  const title=doc.createElement('h3');title.textContent='建筑详情';root.append(title);
  const list=doc.createElement('dl');
  for(const [label,value] of buildingDetails(feature,stepId)) {
    const term=doc.createElement('dt'),description=doc.createElement('dd');
    term.textContent=label;description.textContent=value;list.append(term,description);
  }
  root.append(list);return root;
}
