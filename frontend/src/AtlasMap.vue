<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Map as MapLibre, Marker, MercatorCoordinate, ScaleControl, type SourceSpecification, type MapMouseEvent } from 'maplibre-gl';
import AtlasIcon from './AtlasIcon.vue';
import { depthBins, rectangleCorners, type CaseStep, type CaseVersion, type Point } from './atlas-cases';

const props = withDefaults(defineProps<{
  item: CaseVersion;
  step: CaseStep;
  comparison?: CaseStep;
  online: boolean;
  immersive?: boolean;
  inspectable?: boolean;
  selected?: Point;
  buildingId?: string;
}>(), { inspectable: true });
type Side = 'left' | 'right';
type Fallback = 'missing' | 'unavailable';
type DepthRevision = {
  sourceId: string;
  step: CaseStep;
  side: Side;
  kind: 'wmts' | 'snapshot';
  fallback?: Fallback;
  ready: boolean;
  hasTile: boolean;
  timer?: number;
};
const emit = defineEmits<{ inspect: [point: Point, side: Side, buildingId?: string]; ready: [value: boolean, side: Side] }>();
const root = ref<HTMLDivElement>();
const primaryContainer = ref<HTMLDivElement>();
const secondaryContainer = ref<HTMLDivElement>();
const modeModel = defineModel<'aerial' | 'vector'>('mode');
const mode = computed({
  get: () => props.item.basemap ? modeModel.value ?? 'aerial' : 'vector',
  set: value => { modeModel.value = value; },
});
const swipe = ref(50);
const mapError = ref('');
const comparisonError = ref('');
const depthNotices = ref<Partial<Record<Side, { message: string; retry?: boolean }>>>({});
const showDepth = defineModel<boolean>('showDepth', { default: true });
const bins = computed(() => depthBins(props.item.threshold_m));
const extent = computed(() => rectangleCorners(props.item.bounds));
const angle = ref(0);
const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
let primary: MapLibre | undefined;
let secondary: MapLibre | undefined;
let marker: Marker | undefined;
let observer: ResizeObserver | undefined;
let swipeDrag: { pointer: number; offset: number } | undefined;
let depthGeneration = 0;
const depthRevision = new WeakMap<MapLibre, DepthRevision>();
const depthTimeout = 6000;

function buildMap(container: HTMLDivElement, interactive: boolean): MapLibre {
  const side = interactive ? 'left' : 'right';
  const map = new MapLibre({
    container, interactive, attributionControl: false, renderWorldCopies: false,
    maxPitch: 0, dragRotate: false, touchPitch: false, maxZoom: 20, minZoom: 3,
    bounds: props.item.bounds, fitBoundsOptions: { padding: 28 },
    style: { version: 8, sources: {}, layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#b9c9bf' } },
    ] },
  });
  map.on('load', () => {
    if (props.item.basemap) {
      map.addSource('aerial', { type: 'image', url: props.item.basemap, coordinates: extent.value });
      map.addLayer({ id: 'aerial', type: 'raster', source: 'aerial',
        paint: { 'raster-fade-duration': 0, 'raster-saturation': -0.08, 'raster-contrast': 0.06 } });
    }
    const features = !props.online && props.item.snapshot_features ? props.item.snapshot_features : props.item.features;
    if (features) {
      const vector = features.includes('{z}');
      const source: SourceSpecification = vector
        ? { type: 'vector', tiles: [new URL(features, location.origin).href.replaceAll('%7B', '{').replaceAll('%7D', '}')],
          minzoom: 0, maxzoom: 18 }
        : { type: 'geojson', data: features };
      map.addSource('context', source);
      const sourceLayer = vector ? { 'source-layer': 'features' } : {};
      map.addLayer({ id: 'context-water', type: 'fill', source: 'context', ...sourceLayer,
        filter: ['==', ['get', 'kind'], 'water'],
        paint: { 'fill-color': '#b2c9cc', 'fill-opacity': 0.92 } });
      map.addLayer({ id: 'context-roads-casing', type: 'line', source: 'context', ...sourceLayer,
        filter: ['==', ['get', 'kind'], 'road'],
        paint: { 'line-color': '#c4c1af', 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.85, 15, 2.8, 19, 9] } });
      map.addLayer({ id: 'context-roads', type: 'line', source: 'context', ...sourceLayer,
        filter: ['==', ['get', 'kind'], 'road'],
        paint: { 'line-color': '#fcfaf0', 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.35, 15, 1.8, 19, 7] } });
      map.addLayer({ id: 'context-buildings', type: 'fill', source: 'context', ...sourceLayer,
        filter: ['==', ['get', 'kind'], 'building'],
        paint: { 'fill-color': '#9faea2', 'fill-outline-color': '#8c9b91', 'fill-opacity': 0.85 } });
      map.addLayer({id:'selected-building',type:'line',source:'context',...sourceLayer,
        filter:['all',['==',['get','kind'],'building'],['==',['get','id'],props.buildingId??'']],
        paint:{'line-color':'#ffbd63','line-width':3}});
    }
    applyMode(map);
    if (interactive && mode.value === 'aerial') {
      if (props.immersive) frameAerial(map);
      else if (container.clientWidth > 750) map.jumpTo({ zoom: map.getZoom() + 0.70 });
    }
    const step = interactive ? props.step : props.comparison;
    if (step) applyDepth(map, step, side);
    if (interactive) updateMarker();
    else sync();
  });
  map.on('sourcedata', event => {
    const current = depthRevision.get(map);
    if (!current || current.ready || event.sourceId !== current.sourceId) return;
    if (current.kind === 'snapshot') {
      if (event.sourceDataType === 'metadata') markDepthReady(current);
      return;
    }
    // Raster metadata describes the tile grid. A tile event confirms a decoded tile.
    if (event.tile?.state === 'loaded') current.hasTile = true;
    if (current.hasTile && event.isSourceLoaded) markDepthReady(current);
  });
  map.on('idle', () => {
    const current = depthRevision.get(map);
    if (current?.hasTile && !current.ready && map.isSourceLoaded(current.sourceId)) {
      markDepthReady(current);
    }
  });
  map.on('error', event => {
    const sourceId = (event as typeof event & { sourceId?: string }).sourceId;
    const current = depthRevision.get(map);
    if (current && sourceId === current.sourceId) {
      queueMicrotask(() => failDepth(map, current, true));
    } else if (sourceId === 'aerial' && mode.value === 'aerial') {
      mode.value = 'vector';
      mapError.value = '航拍影像暂不可用，已切换为简图';
    } else if (sourceId === 'context' && mode.value === 'vector') {
      mapError.value = '底图要素暂不可用';
    }
  });
  return map;
}

function frameAerial(map: MapLibre) {
  const bounds = props.item.bounds;
  const camera = map.cameraForBounds(bounds, { padding: 0 });
  if (!camera) return;
  const [southwest, northeast] = bounds.map(point => MercatorCoordinate.fromLngLat(point));
  const container = map.getContainer();
  const fillScale = Math.max(
    container.clientWidth / (northeast.x - southwest.x),
    container.clientHeight / (southwest.y - northeast.y),
  );
  const zoom = Math.log2(fillScale / 512);
  if (Number.isFinite(zoom)) map.jumpTo({ ...camera, zoom: Math.min(zoom, map.getMaxZoom()) });
}

function applyMode(map: MapLibre) {
  if (!map.getLayer('background')) return;
  const aerial = mode.value === 'aerial';
  map.setPaintProperty('background', 'background-color', aerial ? '#34453d' : '#e4e8de');
  if (map.getLayer('aerial')) map.setLayoutProperty('aerial', 'visibility', aerial ? 'visible' : 'none');
  for (const id of ['context-water', 'context-roads', 'context-roads-casing']) {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', aerial ? 'none' : 'visible');
  }
  if (map.getLayer('context-buildings')) map.setPaintProperty('context-buildings', 'fill-opacity', aerial ? 0.12 : 0.85);
}

function applyDepth(map: MapLibre, step: CaseStep, side: Side, fallback?: Fallback) {
  if (!map.getLayer('background')) return;
  const previous = depthRevision.get(map);
  if (previous) stopDepthTimer(previous);
  if (map.getLayer('depth')) map.removeLayer('depth');
  if (previous && map.getSource(previous.sourceId)) map.removeSource(previous.sourceId);

  const tiles = !fallback && props.online && step.wmts;
  const current: DepthRevision = {
    sourceId: `atlas-depth-${++depthGeneration}`,
    step, side, kind: tiles ? 'wmts' : 'snapshot',
    fallback: fallback ?? (props.online && !step.wmts ? 'missing' : undefined),
    ready: false, hasTile: false,
  };
  depthRevision.set(map, current);
  emit('ready', false, side);
  depthNotices.value[side] = current.fallback ? { message: `${fallbackMessage(current.fallback)}，正在加载水深快照` } : undefined;

  try {
    const source: SourceSpecification = tiles
      ? { type: 'raster', tiles: [new URL(tiles, location.origin).href.replaceAll('%7B', '{').replaceAll('%7D', '}')],
        tileSize: 256, bounds: [...props.item.bounds[0], ...props.item.bounds[1]], maxzoom: 19 }
      : { type: 'image', url: step.depth, coordinates: extent.value };
    map.addSource(current.sourceId, source);
    map.addLayer({ id: 'depth', type: 'raster', source: current.sourceId,
      layout: { visibility: showDepth.value ? 'visible' : 'none' },
      paint: { 'raster-opacity': 0.86, 'raster-fade-duration': 0, 'raster-resampling': 'nearest' },
    }, map.getLayer('selected-building') ? 'selected-building' : undefined);
    startDepthTimer(map, current);
  } catch {
    failDepth(map, current);
  }
}

function fallbackMessage(reason: Fallback) {
  return reason === 'missing' ? '在线水深瓦片未配置' : '在线水深瓦片暂不可用';
}

function startDepthTimer(map: MapLibre, current: DepthRevision) {
  if (showDepth.value && !current.ready && current.timer === undefined) {
    current.timer = window.setTimeout(() => failDepth(map, current), depthTimeout);
  }
}

function stopDepthTimer(current: DepthRevision) {
  window.clearTimeout(current.timer);
  current.timer = undefined;
}

function markDepthReady(current: DepthRevision) {
  stopDepthTimer(current);
  current.ready = true;
  depthNotices.value[current.side] = current.fallback ? {
    message: `${fallbackMessage(current.fallback)}，正在显示水深快照`,
    retry: current.fallback === 'unavailable',
  } : undefined;
  emit('ready', true, current.side);
}

function failDepth(map: MapLibre, current: DepthRevision, tileError = false) {
  if (depthRevision.get(map) !== current || (current.ready && !(tileError && current.kind === 'wmts'))) return;
  stopDepthTimer(current);
  if (current.kind === 'wmts') {
    applyDepth(map, current.step, current.side, 'unavailable');
    return;
  }
  depthNotices.value[current.side] = {
    message: current.fallback ? `${fallbackMessage(current.fallback)}，水深快照也暂不可用` : '水深快照暂不可用',
    retry: true,
  };
}

function retryDepth(side: Side) {
  const map = side === 'left' ? primary : secondary;
  const step = side === 'left' ? props.step : props.comparison;
  if (map && step) applyDepth(map, step, side);
}

function removeMap(map: MapLibre | undefined) {
  if (!map) return;
  const current = depthRevision.get(map);
  if (current) stopDepthTimer(current);
  depthRevision.delete(map);
  map.remove();
}

function sync() {
  if (!primary || !secondary) return;
  secondary.jumpTo({ center: primary.getCenter(), zoom: primary.getZoom(),
    bearing: primary.getBearing(), pitch: primary.getPitch() });
}

function sideAt(x: number) {
  return secondary && root.value && x / root.value.clientWidth > swipe.value / 100 ? 'right' : 'left';
}

function startSwipe(event: PointerEvent) {
  if (!event.isPrimary || event.button !== 0 || !root.value) return;
  const { left, width } = root.value.getBoundingClientRect();
  swipeDrag = { pointer: event.pointerId, offset: event.clientX - left - width * swipe.value / 100 };
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  event.preventDefault();
}

function moveSwipe(event: PointerEvent) {
  if (swipeDrag?.pointer !== event.pointerId || !root.value) return;
  const { left, width } = root.value.getBoundingClientRect();
  if (width) swipe.value = Math.round(Math.min(100, Math.max(0, (event.clientX - left - swipeDrag.offset) * 100 / width)));
}

function stopSwipe(event: PointerEvent) {
  if (swipeDrag?.pointer === event.pointerId) swipeDrag = undefined;
}

function inspect(event: MapMouseEvent) {
  if (!props.inspectable) return;
  const side = sideAt(event.point.x);
  const map = side === 'right' ? secondary : primary;
  const layers = ['context-buildings'].filter(layer => map?.getLayer(layer));
  const feature = layers.length ? map?.queryRenderedFeatures(event.point, { layers })[0] : undefined;
  const id = feature?.properties?.id ?? feature?.id;
  emit('inspect', [event.lngLat.lng, event.lngLat.lat], side, id == null ? undefined : String(id));
}

function sampleCenter() {
  if (!props.inspectable) return;
  const point = primary?.getCenter();
  if (point) emit('inspect', [point.lng, point.lat], sideAt((root.value?.clientWidth ?? 0) / 2));
}

function reset() {
  primary?.fitBounds(props.item.bounds, { padding: 28, bearing: 0, duration: reduceMotion() ? 0 : 450 });
}

function changeZoom(amount: number) {
  if (primary) primary.zoomTo(primary.getZoom() + amount, { duration: reduceMotion() ? 0 : 240 });
}

function updateMarker() {
  marker?.remove();
  marker = undefined;
  if (!primary || !props.selected) return;
  const node = document.createElement('span');
  node.className = 'atlas-map-pin';
  node.setAttribute('aria-hidden', 'true');
  marker = new Marker({ element: node, anchor: 'center' }).setLngLat(props.selected).addTo(primary);
}

function focusPoint(point: Point) {
  if (!primary) return;
  primary.easeTo({ center: point, zoom: Math.max(primary.getZoom(), 16), duration: reduceMotion() ? 0 : 520 });
}
defineExpose({ focusPoint, reset, changeZoom, sampleCenter });

function onMapKey(event: KeyboardEvent) {
  if (props.inspectable && event.key === 'Enter' && event.target === primary?.getCanvas()) {
    event.preventDefault();
    sampleCenter();
  }
}

onMounted(() => {
  if (!primaryContainer.value || !root.value) return;
  try {
    primary = buildMap(primaryContainer.value, true);
    primary.getCanvas().setAttribute('aria-label', props.inspectable
      ? '案例地图。用方向键移动，按回车查询中心点。' : '案例地图。用方向键移动。');
    primary.addControl(new ScaleControl({ maxWidth: 100, unit: 'metric' }), 'bottom-right');
    primary.on('move', () => {
      angle.value = primary?.getBearing() ?? 0;
      sync();
    });
    primary.on('click', inspect);
    observer = new ResizeObserver(() => {
      primary?.resize();
      secondary?.resize();
      sync();
    });
    observer.observe(root.value);
  } catch {
    mapError.value = '地图暂不可用。请确认浏览器支持 WebGL 后重新加载。';
    emit('ready', false, 'left');
  }
});

watch(() => props.step, step => {
  if (primary && depthRevision.has(primary)) applyDepth(primary, step, 'left');
});

watch(() => props.comparison, async (step, _previous, onCleanup) => {
  let active = true;
  onCleanup(() => { active = false; });
  comparisonError.value = '';
  if (!step) {
    removeMap(secondary);
    secondary = undefined;
    swipe.value = 50;
    swipeDrag = undefined;
    depthNotices.value.right = undefined;
    return;
  }
  await nextTick();
  if (!active || !secondaryContainer.value || !primary) return;
  if (secondary) {
    if (depthRevision.has(secondary)) applyDepth(secondary, step, 'right');
    return;
  }
  try {
    secondary = buildMap(secondaryContainer.value, false);
    sync();
  } catch {
    comparisonError.value = '对比地图暂不可用';
    emit('ready', false, 'right');
  }
}, { immediate: true });

watch(mode, () => {
  for (const map of [primary, secondary]) if (map) applyMode(map);
});
watch(showDepth, (visible) => {
  for (const map of [primary, secondary]) {
    if (!map) continue;
    if (map.getLayer('depth')) map.setLayoutProperty('depth', 'visibility', visible ? 'visible' : 'none');
    const current = depthRevision.get(map);
    if (current) {
      if (visible) startDepthTimer(map, current);
      else stopDepthTimer(current);
    }
  }
});
watch(() => props.selected, updateMarker);
watch(()=>props.buildingId,id=>{
  for(const map of [primary,secondary])if(map?.getLayer('selected-building')) {
    map.setFilter('selected-building',['all',['==',['get','kind'],'building'],['==',['get','id'],id??'']]);
  }
});
onBeforeUnmount(() => {
  observer?.disconnect();
  marker?.remove();
  removeMap(secondary);
  removeMap(primary);
  secondary = undefined;
  primary = undefined;
});
</script>

<template>
  <section ref="root" class="atlas-map" :class="{ 'atlas-map--immersive': immersive }" aria-label="内涝地图" @keydown="onMapKey">
    <div ref="primaryContainer" class="atlas-map-canvas"></div>
    <div v-if="comparison" ref="secondaryContainer" class="atlas-map-canvas atlas-map-compare"
      :style="{ clipPath: 'inset(0 0 0 ' + swipe + '%)' }" aria-hidden="true"></div>
    <div v-if="comparison" class="atlas-swipe" :style="{ '--swipe': swipe + '%' }">
      <div class="atlas-swipe-rule" aria-hidden="true"></div>
      <div class="atlas-swipe-handle" aria-hidden="true" @pointerdown="startSwipe" @pointermove="moveSwipe"
        @pointerup="stopSwipe" @pointercancel="stopSwipe" @lostpointercapture="stopSwipe">
        <AtlasIcon name="swipe" :size="24" />
      </div>
      <input v-model.number="swipe" type="range" min="0" max="100" step="1" aria-label="情景卷帘位置"
        :aria-valuetext="'左侧情景占 ' + swipe + '%'" />
    </div>

    <div v-if="!immersive" class="atlas-map-tools">
      <div class="atlas-glass atlas-map-switch" role="group" aria-label="底图">
        <button type="button" :disabled="!item.basemap" :aria-pressed="mode === 'aerial'" @click="mode = 'aerial'">
          <AtlasIcon name="image" :size="17" /> 航拍
        </button>
        <button type="button" :aria-pressed="mode === 'vector'" @click="mode = 'vector'">
          <AtlasIcon name="layers" :size="17" /> 简图
        </button>
      </div>
      <button class="atlas-glass atlas-map-toggle" type="button" :aria-pressed="showDepth" @click="showDepth = !showDepth">
        <AtlasIcon name="drop" :size="17" /> 水深
      </button>
    </div>

    <div v-if="comparison" class="atlas-map-compare-labels">
      <span class="atlas-glass">左 <b>{{ step.label }}</b></span>
      <span class="atlas-glass">右 <b>{{ comparison.label }}</b></span>
    </div>

    <div v-if="!immersive" class="atlas-map-nav" aria-label="地图操作">
      <button type="button" class="atlas-glass atlas-icon-button" aria-label="恢复案例视野" title="恢复案例视野" @click="reset">
        <AtlasIcon name="compass" :size="19" :style="{ transform: 'rotate(' + -angle + 'deg)' }" />
      </button>
      <div class="atlas-glass atlas-zoom">
        <button type="button" class="atlas-icon-button" aria-label="放大" title="放大" @click="changeZoom(1)"><AtlasIcon name="plus" /></button>
        <button type="button" class="atlas-icon-button" aria-label="缩小" title="缩小" @click="changeZoom(-1)"><AtlasIcon name="minus" /></button>
      </div>
      <button v-if="inspectable" type="button" class="atlas-glass atlas-icon-button" aria-label="查询视图中心点水深" title="查询视图中心点水深" @click="sampleCenter">
        <AtlasIcon name="target" :size="20" />
      </button>
    </div>

    <div v-if="showDepth && !immersive" class="atlas-depth-key">
      <header>积水深度 <span>m</span></header>
      <div class="atlas-depth-bins" :style="{ '--bins': bins.length }">
        <div v-for="bin in bins" :key="bin.color"><i :style="{ background: bin.color }"></i><span>{{ bin.label }}</span></div>
      </div>
    </div>
    <div v-if="mapError || comparisonError || (showDepth && (depthNotices.left || depthNotices.right))" class="atlas-map-alert">
      <div v-if="mapError" role="status">{{ mapError }}</div>
      <div v-if="comparisonError" role="status">{{ comparisonError }}</div>
      <template v-for="(notice, side) in depthNotices" :key="side">
        <div v-if="showDepth && notice" class="atlas-map-alert-row">
          <span role="status">{{ comparison ? (side === 'left' ? '左侧 · ' : '右侧 · ') : '' }}{{ notice.message }}</span>
          <button v-if="notice.retry" type="button" @click="retryDepth(side)">重试</button>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.atlas-map-canvas {
  position: absolute;
  inset: 0;
}

.atlas-map-compare {
  pointer-events: none;
}

.atlas-swipe {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.atlas-swipe-rule {
  position: absolute;
  top: 0;
  bottom: 0;
  left: var(--swipe);
  width: 2px;
  transform: translateX(-50%);
  background: #f9fdf5;
  box-shadow: 0 0 12px #0009;
}

.atlas-swipe-handle {
  position: absolute;
  top: 50%;
  left: clamp(22px, var(--swipe), calc(100% - 22px));
  display: grid;
  width: 44px;
  height: 44px;
  place-items: center;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  background: #f8fcf5;
  color: #245449;
  box-shadow: 0 4px 15px #0008;
  cursor: ew-resize;
  pointer-events: auto;
  touch-action: none;
  user-select: none;
}

.atlas-swipe input {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: 0;
  opacity: 0;
  pointer-events: none;
}

.atlas-swipe:focus-within .atlas-swipe-handle {
  outline: 3px solid #158670;
  outline-offset: 3px;
}

.atlas-map-alert-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.atlas-map-alert-row button {
  min-width: 44px;
  min-height: 44px;
  padding: 0 6px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  font-weight: 650;
  text-decoration: underline;
}
</style>
