import assert from 'node:assert/strict';
import {test} from 'node:test';
import {visibleAnalysis,formatMetric,buildingDetails,createBuildingPopup} from '../src/analysis-view.ts';
import {parseAnalysisBundle} from '../src/analysis.ts';
import {fixture,context} from './analysis-fixtures.ts';

test('display waits for both current WMS and analysis; hides errors retries and old steps',()=>{
  const f=fixture(),bundle=parseAnalysisBundle(f.summary,f.buildings,context);
  const a={attempt:2,stepId:context.stepId,state:'ready' as const,bundle};
  const d={attempt:3,stepId:context.stepId,state:'ready' as const};
  assert.equal(visibleAnalysis(context.stepId,a,d),bundle);
  for(const state of ['idle','loading','error'] as const) {
    assert.equal(visibleAnalysis(context.stepId,{...a,state},d),undefined);
    assert.equal(visibleAnalysis(context.stepId,a,{...d,state}),undefined);
  }
  assert.equal(visibleAnalysis('S01_T30',a,d),undefined);
  assert.equal(visibleAnalysis(context.stepId,a,{...d,stepId:'S01_T30'}),undefined);
  assert.equal(visibleAnalysis(null,a,d),undefined);
});
test('dry0 is displayed as zero not an error; popup states geometry intersection not depth',()=>{
  const f=fixture('S01_T00'),bundle=parseAnalysisBundle(f.summary,f.buildings,{...context,stepId:'S01_T00'});
  assert.equal(formatMetric(bundle.summary.flooded_area_m2),'0');
  assert.equal(formatMetric(738775),'738,775');
  const details=buildingDetails(bundle.buildings.features[0]!,'S01_T00');
  assert.ok(details.some(([,v])=>v==='未与淹没范围相交'));
  assert.ok(!details.some(([k])=>k.includes('水深')));
});
test('popup uses text DOM even when a building name contains active HTML',()=>{
  class Element {
    className='';textContent='';children:Element[]=[];
    append(...nodes:Element[]){this.children.push(...nodes);}
    set innerHTML(_v:string){throw new Error('Unsafe HTML assignment');}
  }
  const f=fixture(),feature=parseAnalysisBundle(f.summary,f.buildings,context).buildings.features[0]!;
  feature.properties.name='<img src=x onerror=alert(1)>';
  const root=createBuildingPopup(feature,context.stepId,{createElement:()=>new Element()} as unknown as Document) as unknown as Element;
  const flatten=(node:Element):string=>node.textContent+node.children.map(flatten).join('');
  assert.ok(flatten(root).includes(feature.properties.name));assert.ok(flatten(root).includes(context.stepId));
});
