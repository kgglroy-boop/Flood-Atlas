import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildDepthTileUrl, STUDY_CORNERS, STUDY_BOUNDS, DEPTH_COLORS,
  DEPTH_SOURCE_ID, nextWmsState, isDepthContentReady, viewportIntersectsStudy } from '../src/wms.ts';

test('uses public GWC WMTS with the existing Web Mercator grid and XYZ placeholders', () => {
  const value = buildDepthTileUrl();
  assert.ok(value.includes('{z}')&&value.includes('{x}')&&value.includes('{y}'));
  const url = new URL(value);
  assert.equal(url.origin, 'http://localhost:8080');
  assert.equal(url.pathname, '/geoserver/gwc/service/wmts');
  for (const [key, expected] of Object.entries({LAYER:'flood:depth_S02_T60',VERSION:'1.0.0',
    TILEMATRIXSET:'EPSG:900913',TILEMATRIX:'EPSG:900913:{z}',TILECOL:'{x}',TILEROW:'{y}',FORMAT:'image/png',REQUEST:'GetTile'})) {
    assert.equal(url.searchParams.get(key), expected);
  }
  assert.equal(url.username, '');
  assert.equal(url.password, '');
  assert.doesNotMatch(value, /CQL_FILTER|backend:|geoserver:|password|token|_attempt/i);
  for(const id of ['S01','S02'])for(const t of ['00','30','60'])assert.equal(new URL(buildDepthTileUrl(`flood:depth_${id}_T${t}`)).searchParams.get('LAYER'),`flood:depth_${id}_T${t}`);
  assert.throws(()=>buildDepthTileUrl('other:layer'));
});

test('uses all four projected study corners in longitude latitude order', () => {
  assert.equal(STUDY_CORNERS.length, 4);
  assert.deepEqual(STUDY_CORNERS[0], [117,30.73288955997538]);
  assert.deepEqual(STUDY_CORNERS[2], [117.02089379372558,30.74191146968369]);
  assert.deepEqual(STUDY_BOUNDS, [[117,30.73288787851833],[117.02089379372558,30.741913151740533]]);
});

test('legend matches the frozen wet-depth ramp checked by the SLD contract test', () => {
  assert.deepEqual(DEPTH_COLORS, [[.101,'#d6eef0'],[.3,'#a8dce4'],[.6,'#69bfd0'],[1,'#3297b5'],[1.5,'#146a91'],[2,'#103f67']]);
});

test('WMS load state only accepts its source and requires a fresh retry after error', () => {
  assert.equal(nextWmsState('loading', {kind:'content-ready',sourceId:'other'}), 'loading');
  assert.equal(nextWmsState('ready', {kind:'source-error',sourceId:'other'}), 'ready');
  assert.equal(nextWmsState('loading', {kind:'content-ready',sourceId:DEPTH_SOURCE_ID}), 'ready');
  assert.equal(nextWmsState('ready', {kind:'source-error',sourceId:DEPTH_SOURCE_ID}), 'error');
  assert.equal(nextWmsState('error', {kind:'content-ready',sourceId:DEPTH_SOURCE_ID}), 'error');
  assert.equal(nextWmsState('error', {kind:'start'}), 'loading');
  assert.equal(nextWmsState('loading', {kind:'content-ready',sourceId:DEPTH_SOURCE_ID}), 'ready');
});

test('actual final raster tile event can omit sourceDataType', () => {
  assert.equal(isDepthContentReady({sourceId:DEPTH_SOURCE_ID,isSourceLoaded:true}, true), true);
  assert.equal(isDepthContentReady({sourceId:DEPTH_SOURCE_ID,isSourceLoaded:false}, false), false);
  assert.equal(isDepthContentReady({sourceId:'other',isSourceLoaded:true}, true), false);
  assert.equal(isDepthContentReady({sourceId:DEPTH_SOURCE_ID,sourceDataType:'metadata',isSourceLoaded:true}, true), false);
  assert.equal(isDepthContentReady({sourceId:DEPTH_SOURCE_ID,sourceDataType:'content',isSourceLoaded:true}, true), true);
});

test('outside-study idle is not a service failure and retry can detect outside bounds', () => {
  assert.equal(viewportIntersectsStudy([[116,30],[118,32]]), true);
  assert.equal(viewportIntersectsStudy([[118,30],[119,32]]), false);
  assert.equal(viewportIntersectsStudy([[116,32],[118,33]]), false);
  assert.equal(isDepthContentReady({sourceId:DEPTH_SOURCE_ID,sourceDataType:'idle',isSourceLoaded:true}, true, false), true);
  assert.equal(isDepthContentReady({sourceId:DEPTH_SOURCE_ID,sourceDataType:'idle',isSourceLoaded:true}, true, true), false);
});
