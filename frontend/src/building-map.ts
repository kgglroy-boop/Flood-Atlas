import type {Map,MapLayerMouseEvent} from 'maplibre-gl';
import type {BuildingCollection,BuildingFeature} from './analysis.ts';

const SOURCE='analysis-buildings',FILL='analysis-buildings-fill',LINE='analysis-buildings-line',SELECTED='analysis-building-selected';
export function createBuildingOverlay(map:Map,onInspect:(feature:BuildingFeature)=>void) {
  let current:BuildingCollection|undefined;
  const click=(event:MapLayerMouseEvent)=>{
    // The rendered tile may coerce GeoJSON string IDs; application identity
    // remains a property. Resolve back to our validated full feature.
    const id=event.features?.[0]?.properties?.building_id;
    const feature=current?.features.find(f=>f.id===id);
    if(feature)onInspect(feature);
  };
  const enter=()=>{if(current)map.getCanvas().style.cursor='pointer';};
  const leave=()=>{map.getCanvas().style.cursor='';};
  map.on('click',FILL,click);map.on('mouseenter',FILL,enter);map.on('mouseleave',FILL,leave);
  function clear() {
    current=undefined;leave();
    for(const id of [SELECTED,LINE,FILL])if(map.getLayer(id))map.removeLayer(id);
    if(map.getSource(SOURCE))map.removeSource(SOURCE);
  }
  function show(collection:BuildingCollection) {
    clear();current=collection;
    map.addSource(SOURCE,{type:'geojson',data:collection});
    map.addLayer({id:FILL,type:'fill',source:SOURCE,paint:{
      'fill-color':['case',['get','affected'],'#385e70','#f8f5e9'],'fill-opacity':.87,
    }});
    map.addLayer({id:LINE,type:'line',source:SOURCE,paint:{
      'line-color':['case',['get','affected'],'#143346','#686e64'],'line-width':.85,
    }});
  }
  function select(id:string) {
    if(map.getLayer(SELECTED))map.removeLayer(SELECTED);
    if(id&&current)map.addLayer({id:SELECTED,type:'line',source:SOURCE,
      filter:['==',['get','building_id'],id],paint:{'line-color':'#a64418','line-width':2.8}});
  }
  return {show,clear,select,dispose(){clear();map.off('click',FILL,click);map.off('mouseenter',FILL,enter);map.off('mouseleave',FILL,leave);}};
}
