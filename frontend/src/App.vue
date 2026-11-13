<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue';
import { Map, Popup, NavigationControl, ScaleControl, setWorkerUrl, type MapSourceDataEvent, type ErrorEvent, type GeoJSONSource } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { probeHealth } from './health';
import { buildDepthTileUrl, STUDY_CORNERS, STUDY_BOUNDS, DEPTH_COLORS,
  DEPTH_SOURCE_ID, DEPTH_LAYER_ID, isDepthContentReady, viewportIntersectsStudy } from './wms';

import {fetchScenarioCatalog,selectStep,type ScenarioCatalog} from './scenarios';
import {startDepthSession,clearDepthSession,reduceDepthSession,shouldStartDepth,shouldRefocusDepth,type DepthSession} from './depth-session';
import {createAnalysisSession,type AnalysisSession} from './analysis-session';
import {visibleAnalysis,formatMetric,createBuildingPopup,buildingDetails} from './analysis-view';
import {createBuildingOverlay} from './building-map';
import type {BuildingFeature} from './analysis';
import {loadModuleRegistry,loadMapModule,type MapDataModule,type ModuleEntry} from './data-modules';
import {searchBuildings} from './building-search';
import {addTeachingRoads,quietMap,MAP_PAPER,STUDY_PAPER,STUDY_LINE} from './presentation-map';
import ReferenceViewer from './ReferenceViewer.vue';

const moduleOptions=ref<ModuleEntry[]>([]);
const moduleId=ref('');
const dataModule=shallowRef<MapDataModule>();
const moduleState=ref<'loading'|'ready'|'error'>('loading');
let moduleEpoch=0,moduleAbort:AbortController|undefined,registryAbort:AbortController|undefined;
const studyBounds=()=>dataModule.value?.bounds??STUDY_BOUNDS;
const mapPadding={top:44,bottom:48,left:42,right:62};

const mapContainer = ref<HTMLDivElement>();
const mapReady = ref(false);
const mapFailed = ref(false);
const catalog = ref<ScenarioCatalog>();
const catalogState = ref<'loading'|'ready'|'error'>('loading');
const scenarioId = ref('S02');
const timeMin = ref<0|30|60>(60);
const selectedStep = computed(() => catalog.value ? selectStep(catalog.value, scenarioId.value, timeMin.value) : undefined);
const session = ref<DepthSession>({attempt:0,stepId:null,state:'idle'});
const wmsState = computed(()=>session.value.state);
let catalogRequest = 0;
let catalogAbort:AbortController|undefined;
const wmsLabel = computed(() => ({idle:'等待情景目录',loading:'正在加载水深图层', ready:'水深图层已加载', error:'水深图层加载失败'})[wmsState.value]);
const legendGradient = `linear-gradient(to right, ${DEPTH_COLORS.map(([v,c]) => `${c} ${(v-.1)/1.9*100}%`).join(', ')})`;
const connection = ref<'checking' | 'ok' | 'error'>('checking');
const checkedAt = ref('');
let map: Map | undefined;
let fittedBounds = '';
let stopDepthListeners: (() => void) | undefined;
const analysis = ref<AnalysisSession>({attempt:0,stepId:null,state:'idle'});
const analysisLoader = createAnalysisSession(state=>{analysis.value=state;},(context,signal)=>{
  const provider=dataModule.value;
  if(!provider)return Promise.reject(new Error('数据模块尚未就绪'));
  return provider.analysis(context,signal);
});
const visible = computed(()=>mapReady.value?visibleAnalysis(selectedStep.value?.step_id??null,analysis.value,session.value):undefined);
const inspectedId = ref('');
const query = ref('');
const results = computed(()=>searchBuildings(visible.value?.buildings.features??[],query.value));
const inspected = computed(()=>visible.value?.buildings.features.find(feature=>feature.id===inspectedId.value));
const showReference = ref(false);
const referenceTrigger = ref<HTMLButtonElement>();
function closeReference(){showReference.value=false;referenceTrigger.value?.focus();}
let buildings:ReturnType<typeof createBuildingOverlay>|undefined;
let popup:Popup|undefined;
const analysisMessage=computed(()=>{
  if(catalogState.value==='error')return '情景目录不可用，分析已清除';
  if(analysis.value.state==='error')return '空间分析加载失败，请重试';
  if(wmsState.value==='error')return '水深图层不可用，分析结果暂不展示';
  if(visible.value)return '当前步骤水深与分析已就绪';
  return analysis.value.state==='ready'?'分析已获取，等待当前水深图层':'正在获取当前步骤分析';
});

function closePopup(){popup?.remove();popup=undefined;inspectedId.value='';buildings?.select('');}
function inspectBuilding(feature:BuildingFeature) {
  const data=visible.value;
  if(!map||!data||!data.buildings.features.some(f=>f.id===feature.id))return;
  closePopup();inspectedId.value=feature.id;query.value='';buildings?.select(feature.id);
  const ring=feature.geometry.coordinates[0]!;
  const xs=ring.map(p=>p[0]!),ys=ring.map(p=>p[1]!);
  const current=new Popup({maxWidth:'320px',closeButton:true})
    .setLngLat([(Math.min(...xs)+Math.max(...xs))/2,(Math.min(...ys)+Math.max(...ys))/2])
    .setDOMContent(createBuildingPopup(feature,data.summary.step_id)).addTo(map);
  popup=current;
  current.on('close',()=>{if(popup===current){popup=undefined;inspectedId.value='';buildings?.select('');}});
}
function inspectFirst() {
  const feature=results.value[0];
  if(feature)inspectBuilding(feature);
}
function loadAnalysis() {
  if(catalogState.value!=='ready'||!selectedStep.value||!catalog.value)return;
  void analysisLoader.load({stepId:selectedStep.value.step_id,generationId:catalog.value.generation_id});
}
watch(selectedStep,()=>{analysisLoader.clear();loadAnalysis();},{flush:'sync'});
watch(visible,data=>{
  closePopup();query.value='';buildings?.clear();
  if(data)buildings?.show(data.buildings);
},{flush:'sync'});


function returnToStudy() {
  map?.fitBounds(studyBounds(), {padding:mapPadding, duration:window.matchMedia('(prefers-reduced-motion: reduce)').matches?0:600, maxZoom:17});
}

function applyModuleGeometry(){
  const provider=dataModule.value;
  if(!map||!provider)return;
  const study=map.getSource('study') as GeoJSONSource|undefined;
  if(study?.type==='geojson')study.setData({type:'Feature',properties:{},geometry:{type:'Polygon',coordinates:[[...provider.outline,provider.outline[0]]]}});
  const nextBounds=JSON.stringify(provider.bounds);
  if(nextBounds!==fittedBounds){
    map.fitBounds(provider.bounds,{padding:mapPadding,duration:0,maxZoom:17});
    fittedBounds=nextBounds;
  }
}

async function prepareModules(){
  registryAbort?.abort();const controller=new AbortController();registryAbort=controller;
  const timeout=window.setTimeout(()=>controller.abort(),12000);
  try{
    const registry=await loadModuleRegistry(controller.signal);
    if(controller.signal.aborted)return;
    moduleOptions.value=registry.modules;moduleId.value=registry.default;
  }catch{if(registryAbort===controller){moduleState.value='error';catalogState.value='error';}}
  finally{window.clearTimeout(timeout);}
}
async function activateModule(id:string){
  const entry=moduleOptions.value.find(e=>e.id===id);
  if(!entry){void prepareModules();return;}
  const epoch=++moduleEpoch;
  moduleAbort?.abort();catalogAbort?.abort();++catalogRequest;
  analysisLoader.clear();clearDepth();closePopup();buildings?.clear();
  dataModule.value?.dispose();dataModule.value=undefined;catalog.value=undefined;
  moduleState.value='loading';catalogState.value='loading';
  const controller=new AbortController();moduleAbort=controller;
  const timeout=window.setTimeout(()=>controller.abort(),12000);
  try{
    const provider=await loadMapModule(entry,controller.signal,import.meta.env.VITE_GEOSERVER_URL);
    window.clearTimeout(timeout);
    if(epoch!==moduleEpoch||controller.signal.aborted){provider.dispose();return;}
    dataModule.value=provider;moduleState.value='ready';
    if(mapReady.value)applyModuleGeometry();
    await refreshCatalog();
  }catch{if(epoch===moduleEpoch){controller.abort();moduleState.value='error';catalogState.value='error';}}
  finally{window.clearTimeout(timeout);}
}
watch(moduleId,id=>{void activateModule(id);});

function clearDepth() {
  session.value=clearDepthSession(session.value);
  stopDepthListeners?.(); stopDepthListeners=undefined;
  if(map?.getLayer(DEPTH_LAYER_ID)) map.removeLayer(DEPTH_LAYER_ID);
  if(map?.getSource(DEPTH_SOURCE_ID)) map.removeSource(DEPTH_SOURCE_ID);
}

async function refreshCatalog() {
  const request=++catalogRequest;
  catalogAbort?.abort();
  const controller=new AbortController(); catalogAbort=controller;
  analysisLoader.clear();closePopup();buildings?.clear();
  clearDepth(); catalog.value=undefined; catalogState.value='loading';
  const timeout=window.setTimeout(()=>controller.abort(),10000);
  try {
    const provider=dataModule.value;
    if(!provider)throw new Error('数据模块不可用');
    const result=await provider.catalog(controller.signal);
    if(request!==catalogRequest) return;
    catalogState.value='ready'; catalog.value=result;
  } catch {
    if(request===catalogRequest) {catalogState.value='error';clearDepth();}
  } finally {window.clearTimeout(timeout);}
}

function loadDepth(isRetry=false) {
  const step=selectedStep.value;
  if (!map || !mapReady.value || !step || !dataModule.value || catalogState.value!=='ready') return;
  const currentMap = map;
  clearDepth();
  if (shouldRefocusDepth(isRetry,viewportIntersectsStudy(currentMap.getBounds().toArray(),studyBounds()))) {
    currentMap.fitBounds(studyBounds(), {padding:mapPadding,duration:0,maxZoom:17});
  }
  session.value=startDepthSession(session.value,step.step_id);
  const run=session.value.attempt;
  const sourceId=`${DEPTH_SOURCE_ID}-${run}`;
  // Each source ID is unique: late error events cannot be attributed to a newer source.
  const source=dataModule.value.depth(step);
  const update=(kind:'ready'|'error'|'timeout')=>{
    session.value=reduceDepthSession(session.value,{attempt:run,stepId:step.step_id,kind});
  };
  const timeout=window.setTimeout(()=>update('timeout'),20000);
  function onContent(event:MapSourceDataEvent) {
    if(run!==session.value.attempt || event.sourceId!==sourceId || !currentMap.getSource(sourceId)) return;
    if(!isDepthContentReady({...event,sourceId:DEPTH_SOURCE_ID},currentMap.isSourceLoaded(sourceId),
      viewportIntersectsStudy(currentMap.getBounds().toArray(),studyBounds()))) return;
    const sameRaster=source.type==='raster'&&event.source.type==='raster'&&event.source.tiles?.[0]===source.tiles?.[0];
    const sameImage=source.type==='image'&&event.source.type==='image'&&event.source.url===source.url;
    if(!sameRaster&&!sameImage)return;
    update('ready');window.clearTimeout(timeout);
  }
  function onSourceError(event:ErrorEvent) {
    if((event as ErrorEvent & {sourceId?:string}).sourceId!==sourceId) return;
    update('error');window.clearTimeout(timeout);
  }
  currentMap.on('sourcedata',onContent);currentMap.on('error',onSourceError);
  stopDepthListeners=()=>{
    currentMap.off('sourcedata',onContent);currentMap.off('error',onSourceError);window.clearTimeout(timeout);
    if(currentMap.getLayer(DEPTH_LAYER_ID)) currentMap.removeLayer(DEPTH_LAYER_ID);
    if(currentMap.getSource(sourceId)) currentMap.removeSource(sourceId);
  };
  currentMap.addSource(sourceId,source);
  currentMap.addLayer({id:DEPTH_LAYER_ID,type:'raster',source:sourceId,
    paint:{'raster-fade-duration':0,'raster-resampling':'nearest'}},'study-outline');
}

watch([mapReady,selectedStep],()=>{
  if(shouldStartDepth(mapReady.value,selectedStep.value?.step_id??null,session.value)) loadDepth();
},{flush:'sync'});

const connectionLabel = computed(() => dataModule.value?.kind==='package'?'本地快照已校验 · 不依赖后端':({
  checking: '正在检查连接',
  ok: 'API / 数据库连接正常',
  error: '服务暂不可用',
}[connection.value]));

async function refreshConnection() {
  if(dataModule.value?.kind==='package'){
    await activateModule(moduleId.value);
    checkedAt.value = new Date().toLocaleTimeString('zh-CN', {hour12:false});
    return;
  }
  connection.value = 'checking';
  try {
    await probeHealth();
    connection.value = 'ok';
  } catch {
    connection.value = 'error';
  }
  checkedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false });
}

onMounted(() => {
  void refreshConnection();
  void prepareModules();
  if (!mapContainer.value) return;
  try {
    // Let Vite emit the worker URL; dependency prebundling relocates import.meta.url.
    setWorkerUrl(workerUrl);
    map = new Map({
      container: mapContainer.value,
      bounds: STUDY_BOUNDS,
      fitBoundsOptions: {padding:mapPadding},
      maxPitch: 0,
      dragRotate: false,
      pitchWithRotate: false,
      maxZoom: 19,
      attributionControl: false,
      style: {
        version: 8,
        sources: {study:{type:'geojson',data:{type:'Feature',properties:{},geometry:{
          type:'Polygon',coordinates:[[...STUDY_CORNERS,STUDY_CORNERS[0]!]],
        }}}},
        layers: [
          { id:'background',type:'background',paint:{'background-color':MAP_PAPER} },
          { id:'study-fill',type:'fill',source:'study',paint:{'fill-color':STUDY_PAPER} },
          { id:'study-outline',type:'line',source:'study',paint:{'line-color':STUDY_LINE,'line-width':1.15,'line-dasharray':[4,3]} },
        ],
      },
    });
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right');
    map.addControl(new ScaleControl({unit:'metric'}), 'bottom-left');
    map.touchZoomRotate.disableRotation();
    quietMap(map);
    map.on('load', () => {
      if(map)buildings=createBuildingOverlay(map,inspectBuilding);
      applyModuleGeometry();
      mapReady.value = true;
      if(map)addTeachingRoads(map,'study-outline');
    });
    map.on('error', () => { if (!mapReady.value) mapFailed.value = true; });
  } catch {
    mapFailed.value = true;
  }
});

onBeforeUnmount(() => { ++moduleEpoch;registryAbort?.abort();moduleAbort?.abort();++catalogRequest; catalogAbort?.abort(); analysisLoader.dispose();closePopup();buildings?.dispose();clearDepth();dataModule.value?.dispose();map?.remove(); });
</script>

<template>
  <div class="workspace">
    <a class="skip-link" href="#map-workspace">跳到地图</a>
    <header class="header">
      <a class="brand" href="/" aria-label="Flood Atlas 情景地图首页">
        <svg class="brand-symbol" viewBox="0 0 36 36" fill="none" aria-hidden="true"><path d="M4 12c8-10 15 12 28 0M4 20c8-10 15 12 28 0M9 28c7-6 13 7 21-1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        <span>Flood Atlas</span>
      </a>
      <nav class="primary-nav" aria-label="主导航">
        <a href="/legacy.html" aria-current="page">情景地图</a><a href="/legacy-mvt.html">矢量瓦片</a>
      </nav>
      <button class="reference-trigger" ref="referenceTrigger" type="button" aria-haspopup="dialog" @click="showReference=true">
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><rect x="2.5" y="3.5" width="15" height="13" rx="2" stroke="currentColor"/><path d="m3 14 4.6-5 3.2 3.2 2.1-2 4 4M13.3 7h.1" stroke="currentColor" stroke-linecap="round"/></svg>
        实景参考
      </button>
    </header>

    <main class="atlas-shell">
      <section class="control-strip" aria-label="情景与时间选择">
        <div class="study-title"><h1>城市内涝图谱</h1><p>预计算教学街区 · 2 km × 1 km</p></div>
        <fieldset class="scenario-controls">
          <legend>教学情景</legend>
          <div class="scenario-buttons">
            <button v-for="(scenario,index) in ['S01','S02']" :key="scenario" type="button"
              :disabled="catalogState!=='ready'" :aria-pressed="scenarioId===scenario"
              @click="scenarioId=scenario">{{ index===0?'情景 A':'情景 B' }}</button>
          </div>
        </fieldset>
        <fieldset class="time-controls">
          <legend>情景时间</legend>
          <div class="time-buttons">
            <button v-for="minute in [0,30,60] as const" :key="minute" type="button"
              :disabled="catalogState!=='ready'" :aria-pressed="timeMin===minute" @click="timeMin=minute">
              <span class="time-node" aria-hidden="true"></span>{{ minute }} <span>分钟</span>
            </button>
          </div>
        </fieldset>
        <div class="module-controls">
          <label for="module-select">数据模块</label>
          <select id="module-select" v-model="moduleId" :disabled="!moduleOptions.length">
            <option v-for="entry in moduleOptions" :key="entry.id" :value="entry.id">{{ entry.label }}</option>
          </select>
        </div>
      </section>

      <div class="atlas-grid">
        <section class="map-panel" id="map-workspace" aria-label="教学地图" tabindex="-1">
          <div class="map-surface">
            <div ref="mapContainer" class="map-canvas"></div>
            <div class="map-index"><strong>教学街区</strong><span>30.74°N / 117.01°E</span></div>
            <div class="north-marker" aria-hidden="true"><span>N</span><svg viewBox="0 0 20 25" fill="none"><path d="M10 2 16 20l-6-4-6 4 6-18Z" stroke="currentColor"/><path d="M10 2v14l-6 4L10 2Z" fill="currentColor"/></svg></div>
            <div v-if="mapFailed || !mapReady" class="map-caption" role="status">
              <h2>{{ mapFailed?'地图初始化失败':'正在初始化地图' }}</h2>
              <p>{{ mapFailed?'请检查浏览器 WebGL 支持。':'正在准备教学街区地图。' }}</p>
            </div>
            <section class="depth-legend" aria-label="水深图例">
              <h2>水深 <span>m</span></h2>
              <div class="legend-ramp" :style="{background:legendGradient}"></div>
              <div class="legend-ticks"><span v-for="value in [.1,.6,1,2]" :key="value" :style="{left:`${(value-.1)/1.9*100}%`}">{{ value.toFixed(2) }}</span></div>
              <p>≤ 0.10 m 与 NoData 透明</p>
            </section>
            <button class="return-to-study" type="button" :disabled="!mapReady" @click="returnToStudy">
              <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M3 8V3h5M12 3h5v5M17 12v5h-5M8 17H3v-5M7 10h6M10 7v6" stroke="currentColor" stroke-width="1.2"/></svg>
              回到研究区
            </button>
          </div>
          <div class="map-statusbar">
            <p class="impact-state" role="status"><span class="status-dot" :data-ready="!!visible" aria-hidden="true"></span>{{ analysisMessage }}</p>
            <button v-if="moduleState==='error'" class="text-button" type="button" @click="activateModule(moduleId)">重新加载数据模块</button>
            <button v-else-if="catalogState==='error'" class="text-button" type="button" @click="refreshCatalog">重试情景目录</button>
            <button v-if="analysis.state==='error' && catalogState==='ready'" class="text-button" type="button" @click="loadAnalysis">重试空间分析</button>
            <button v-if="wmsState==='error'" class="text-button" type="button" @click="loadDepth(true)">重试水深图层</button>
            <span class="map-label">{{ dataModule?.kind==='package'?'本地校验图层':'GWC 缓存图层' }}</span>
          </div>
        </section>

        <aside class="results-panel" aria-label="情景结果">
          <section class="impact-overview" aria-label="当前步骤空间统计" :aria-busy="analysis.state==='loading'||wmsState==='loading'">
            <div class="impact-context"><h2>空间影响</h2><strong>{{ selectedStep?.step_id ?? '等待目录' }}</strong></div>
            <div class="impact-cards">
              <article class="impact-card"><h3>淹没面积</h3><p><strong>{{ visible?formatMetric(visible.summary.flooded_area_m2):'—' }}</strong><span>m²</span></p></article>
              <article class="impact-card"><h3>受影响建筑</h3><p><strong>{{ visible?formatMetric(visible.summary.affected_buildings):'—' }}</strong><span>栋</span></p></article>
              <article class="impact-card"><h3>道路交集长度</h3><p><strong>{{ visible?formatMetric(visible.summary.flooded_road_length_m):'—' }}</strong><span>m</span></p></article>
            </div>
            <p v-if="visible && timeMin===0" class="zero-note">0 分钟没有超过 0.10 米的积水。</p>
          </section>
          <section class="building-panel" aria-labelledby="building-title">
            <h2 id="building-title">建筑详情</h2>
            <form class="building-search" role="search" @submit.prevent="inspectFirst">
              <label class="sr-only" for="building-query">按编号或名称搜索建筑</label>
              <input id="building-query" v-model="query" type="search" :disabled="!visible" placeholder="按编号或名称搜索" autocomplete="off" />
              <button type="submit" :disabled="!results.length" aria-label="查看第一个匹配建筑">
                <svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.6" cy="8.6" r="4.4" stroke="currentColor" stroke-width="1.5"/><path d="m12 12 4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
              </button>
            </form>
            <ul v-if="results.length" class="search-results" aria-label="匹配建筑">
              <li v-for="feature in results" :key="feature.id"><button type="button" @click="inspectBuilding(feature)"><strong>{{ feature.id }}</strong><span>{{ feature.properties.name }}</span></button></li>
            </ul>
            <p v-else-if="query.trim()" class="building-hint" role="status">未找到匹配建筑。</p>
            <dl v-if="inspected && visible" class="inspected-building" aria-live="polite">
              <div v-for="[label,value] in buildingDetails(inspected,visible.summary.step_id)" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></div>
            </dl>
            <p v-else-if="!query" class="building-hint">也可点选地图中的建筑。</p>
            <div class="building-key"><span><i class="building-swatch normal"></i>普通</span><span><i class="building-swatch affected"></i>受影响</span><span><i class="building-swatch selected"></i>已选中</span></div>
          </section>

          <details class="technical-details">
            <summary>数据与服务</summary>
            <p>{{ dataModule?.kind==='package'?'固定发布快照 · SHA256 完整性校验':'GeoServer 地图 · PostGIS 空间分析' }}</p>
            <p>与淹没范围相交的建筑包含触边。分析使用 EPSG:32650 和 5 米网格。</p>
            <p class="connection-status" role="status">{{ wmsLabel }} · {{ connectionLabel }}</p>
            <button type="button" :disabled="connection==='checking' && dataModule?.kind!=='package'" @click="refreshConnection">{{ dataModule?.kind==='package'?'重新校验数据包':connection==='checking'?'检查中…':'重新检查连接' }}</button>
            <button class="text-button" type="button" :disabled="catalogState==='loading'||moduleState!=='ready'" @click="refreshCatalog">刷新情景目录</button>
            <p v-if="checkedAt">上次检查 {{ checkedAt }}</p>
          </details>
        </aside>
      </div>
    </main>
    <footer class="footer"><span>教学模拟 · 不代表真实灾情</span><span>MapLibre · GeoServer · PostGIS</span></footer>
    <ReferenceViewer v-if="showReference" @close="closeReference" />
  </div>
</template>
