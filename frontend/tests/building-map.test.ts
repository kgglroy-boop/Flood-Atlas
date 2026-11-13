import assert from 'node:assert/strict';
import {test} from 'node:test';
import type {Map as MapLibreMap} from 'maplibre-gl';
import {createBuildingOverlay} from '../src/building-map.ts';
import {fixture,context} from './analysis-fixtures.ts';
import {parseAnalysisBundle,type BuildingFeature} from '../src/analysis.ts';

test('renders full current geometry with affected styles and clears click handlers on disposal',()=>{
  const sources=new Map<string,unknown>(),layers=new Map<string,any>(),handlers=new Map<string,(e:any)=>void>();
  const cursor={cursor:''};
  const map={
    on(name:string,_layer:string,fn:(e:any)=>void){handlers.set(name,fn);},
    off(name:string){handlers.delete(name);},getCanvas:()=>({style:cursor}),
    getLayer:(id:string)=>layers.get(id),getSource:(id:string)=>sources.get(id),
    addSource:(id:string,s:unknown)=>sources.set(id,s),addLayer:(l:any)=>layers.set(l.id,l),
    removeLayer:(id:string)=>layers.delete(id),removeSource:(id:string)=>sources.delete(id),
  };
  const picked:BuildingFeature[]=[];
  const overlay=createBuildingOverlay(map as unknown as MapLibreMap,f=>picked.push(f));
  const f=fixture(),collection=parseAnalysisBundle(f.summary,f.buildings,context).buildings;
  overlay.show(collection);
  assert.equal(sources.size,1);assert.equal(layers.size,2);
  assert.equal((sources.values().next().value as any).data.features.length,200);
  assert.ok(JSON.stringify([...layers.values()]).includes('affected'));
  // MapLibre's tile conversion parses nonnumeric GeoJSON IDs as NaN;
  // stable application identity survives in properties.building_id.
  handlers.get('click')!({features:[{id:NaN,properties:{building_id:'B001',name:'untrusted tile value'}}]});assert.equal(picked[0],collection.features[0]);
  overlay.clear();assert.equal(sources.size,0);assert.equal(layers.size,0);
  handlers.get('click')!({features:[{id:NaN,properties:{building_id:'B001'}}]});assert.equal(picked.length,1);
  overlay.show(collection);overlay.dispose();assert.equal(handlers.size,0);assert.equal(layers.size,0);assert.equal(cursor.cursor,'');
});
