import assert from 'node:assert/strict';
import {test} from 'node:test';
import {buildDepthTileUrl} from '../src/wms.ts';
test('isolated reconstruction uses its own loopback GeoServer without changing default',()=>{
 assert.equal(new URL(buildDepthTileUrl()).origin,'http://localhost:8080');
 for(const base of ['http://localhost:18080/geoserver','http://127.0.0.1:18080/geoserver/']){
  const url=new URL(buildDepthTileUrl('flood:depth_S01_T30',base));
  assert.equal(url.port,'18080');assert.equal(url.pathname,'/geoserver/gwc/service/wmts');
  assert.equal(url.searchParams.get('LAYER'),'flood:depth_S01_T30');
 }
});
test('runtime GeoServer address rejects remote origins, credentials and extra parameters',()=>{
 for(const base of ['http://example.org/geoserver','http://user:secret@localhost:18080/geoserver','http://localhost/geoserver?token=x','http://localhost/geoserver#x','file:///geoserver','http://backend:8080/geoserver','http://localhost/other']) assert.throws(()=>buildDepthTileUrl('flood:depth_S02_T60',base));
});
