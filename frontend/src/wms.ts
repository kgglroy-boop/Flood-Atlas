export const DEPTH_SOURCE_ID = 'depth-wms';
export const DEPTH_LAYER_ID = 'depth-wms-layer';
export const DEPTH_COLORS = [[.101,'#d6eef0'],[.3,'#a8dce4'],[.6,'#69bfd0'],
  [1,'#3297b5'],[1.5,'#146a91'],[2,'#103f67']] as const;

// OSR: EPSG:32650 -> EPSG:4326, traditional GIS axes, all four study corners.
export const STUDY_CORNERS: readonly [number, number][] = [
  [117,30.73288955997538], [117.0208918467933,30.73288787851833],
  [117.02089379372558,30.74191146968369], [117,30.741913151740533],
];
export const STUDY_BOUNDS: [[number,number],[number,number]] = [
  [Math.min(...STUDY_CORNERS.map(p => p[0])), Math.min(...STUDY_CORNERS.map(p => p[1]))],
  [Math.max(...STUDY_CORNERS.map(p => p[0])), Math.max(...STUDY_CORNERS.map(p => p[1]))],
];

export function buildDepthTileUrl(layerId:string='flood:depth_S02_T60',base:string='http://localhost:8080/geoserver'): string {
  if (!/^flood:depth_S0[12]_T(?:00|30|60)$/.test(layerId)) throw new Error('Unknown depth layer');
  const endpoint=new URL(base);
  if(!['http:','https:'].includes(endpoint.protocol)||!['localhost','127.0.0.1'].includes(endpoint.hostname)||endpoint.username||endpoint.password||endpoint.search||endpoint.hash||!['/geoserver','/geoserver/'].includes(endpoint.pathname)) throw new Error('Invalid local GeoServer address');
  const params = new URLSearchParams({SERVICE:'WMTS',VERSION:'1.0.0',REQUEST:'GetTile',
    LAYER:layerId,STYLE:'flood:depth_teaching',TILEMATRIXSET:'EPSG:900913',
    TILEMATRIX:'EPSG:900913:ZOOM_PLACEHOLDER',TILECOL:'COL_PLACEHOLDER',TILEROW:'ROW_PLACEHOLDER',FORMAT:'image/png'});
  return `${endpoint.origin}/geoserver/gwc/service/wmts?${params}`
    .replace('ZOOM_PLACEHOLDER','{z}').replace('COL_PLACEHOLDER','{x}').replace('ROW_PLACEHOLDER','{y}');
}

export type WmsState = 'loading' | 'ready' | 'error';
export function viewportIntersectsStudy(bounds:[[number,number],[number,number]],study=STUDY_BOUNDS): boolean {
  return bounds[0][0] < study[1][0] && bounds[1][0] > study[0][0] &&
    bounds[0][1] < study[1][1] && bounds[1][1] > study[0][1];
}
export function isDepthContentReady(event: {sourceId?:string;sourceDataType?:string;isSourceLoaded?:boolean}, sourceLoaded:boolean, intersectsStudy=true): boolean {
  return event.sourceId === DEPTH_SOURCE_ID && event.isSourceLoaded === true && sourceLoaded &&
    (event.sourceDataType === undefined || event.sourceDataType === 'content' ||
      (event.sourceDataType === 'idle' && !intersectsStudy));
}
export function nextWmsState(current: WmsState,
  event: {kind:'start'|'content-ready'|'source-error';sourceId?:string}): WmsState {
  if (event.kind === 'start') return 'loading';
  if (event.sourceId !== DEPTH_SOURCE_ID) return current;
  if (event.kind === 'source-error') return 'error';
  return current === 'error' ? 'error' : 'ready';
}
