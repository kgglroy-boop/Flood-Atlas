import type {Map} from 'maplibre-gl';

export const PRESENTATION_ROOT='/maps/presentation/';
export const MAP_PAPER='#eeeee7';
export const STUDY_PAPER='#faf9f2';
export const STUDY_LINE='#6a7f81';

export function addTeachingRoads(map:Map,before:string) {
  const source='teaching-road-display';
  map.addSource(source,{type:'geojson',data:PRESENTATION_ROOT+'roads.geojson',attribution:'教学道路中心线'});
  map.addLayer({id:'road-edge',type:'line',source,paint:{
    'line-color':'#a3a59b','line-width':['interpolate',['linear'],['zoom'],13,.65,17,2.65],
    'line-opacity':.72,
  }},before);
  map.addLayer({id:'road-centre',type:'line',source,paint:{
    'line-color':'#fdfbf4','line-width':['interpolate',['linear'],['zoom'],13,.25,17,1.35],
  }},before);
}

export function quietMap(map:Map) {
  // Optional roads never determine map or analysis readiness.
  map.on('error',event=>{
    if((event as typeof event & {sourceId?:string}).sourceId==='teaching-road-display'){
      for(const layer of ['road-centre','road-edge'])if(map.getLayer(layer))map.removeLayer(layer);
      if(map.getSource('teaching-road-display'))map.removeSource('teaching-road-display');
    }
  });
}
