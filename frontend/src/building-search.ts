import type {BuildingFeature} from './analysis.ts';

const normalize=(text:string)=>text.normalize('NFKC').trim().toLowerCase();

export function searchBuildings(features:BuildingFeature[],input:string):BuildingFeature[] {
  const query=normalize(input);
  if(!query)return [];
  const exact:BuildingFeature[]=[],partial:BuildingFeature[]=[];
  for(const feature of features) {
    const id=normalize(feature.id),name=normalize(feature.properties.name);
    if(id===query||name===query)exact.push(feature);
    else if(id.includes(query)||name.includes(query))partial.push(feature);
  }
  return [...exact,...partial].slice(0,8);
}
