import assert from 'node:assert/strict';
import {test} from 'node:test';
import {searchBuildings} from '../src/building-search.ts';
import type {BuildingFeature} from '../src/analysis.ts';

function feature(id:string,name:string):BuildingFeature {
  return {id,type:'Feature',properties:{building_id:id,name,usage:'demo',affected:false},
    geometry:{type:'Polygon',coordinates:[]}};
}
const rows=[feature('B001','东侧教学楼'),feature('B002','教学楼'),feature('B003','操场配套')];

test('building search ranks exact ID/name and normalizes user input',()=>{
  assert.deepEqual(searchBuildings(rows,' ｂ００２ '),[rows[1]]);
  assert.deepEqual(searchBuildings(rows,'教学楼'),[rows[1],rows[0]]);
  assert.deepEqual(searchBuildings(rows,'操场'),[rows[2]]);
});

test('building search is bounded and leaves empty/no-match results empty',()=>{
  assert.deepEqual(searchBuildings(rows,'   '),[]);
  assert.deepEqual(searchBuildings(rows,'不存在'),[]);
  assert.equal(searchBuildings(Array.from({length:200},(_,i)=>feature(String(i),'教学楼')),'教学楼').length,8);
});
