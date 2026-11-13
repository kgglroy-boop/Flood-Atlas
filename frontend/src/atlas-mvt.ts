import {
  Map as MapLibre, ScaleControl, setWorkerUrl,
  type FilterSpecification, type MapGeoJSONFeature, type PointLike, type StyleSpecification,
} from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { caseEndpoint, chooseRequestedCase, loadCaseCatalog, type CaseVersion } from './atlas-cases';
import 'maplibre-gl/dist/maplibre-gl.css';
import './atlas-mvt.css';

const container = document.querySelector<HTMLDivElement>('#map')!;
const statusCard = document.querySelector<HTMLDivElement>('#tile-status')!;
const status = document.querySelector<HTMLParagraphElement>('#tile-state')!;
const retry = document.querySelector<HTMLButtonElement>('#tile-retry')!;
const controls = document.querySelector<HTMLDivElement>('#tile-controls')!;
const zoomReadout = document.querySelector<HTMLSpanElement>('#tile-zoom')!;
const caseName = document.querySelector<HTMLParagraphElement>('#case-name')!;
const credit = document.querySelector<HTMLParagraphElement>('#tile-credit')!;
const featureMessage = document.querySelector<HTMLParagraphElement>('#tile-feature-message')!;
const featureData = document.querySelector<HTMLDListElement>('#tile-feature-data')!;
const featureKind = document.querySelector<HTMLElement>('#tile-feature-kind')!;
const featureName = document.querySelector<HTMLElement>('#tile-feature-name')!;
const featureId = document.querySelector<HTMLElement>('#tile-feature-id')!;
const inspectCenter = document.querySelector<HTMLButtonElement>('#inspect-center')!;
const clearFeature = document.querySelector<HTMLButtonElement>('#tile-clear')!;

const featureLayers = ['buildings', 'streets', 'water'];
const kindLabels = { building: '建筑', road: '道路', water: '水体' };
const emptySelection: FilterSpecification = ['==', ['get', 'kind'], ''];
let request: AbortController | undefined;
let map: MapLibre | undefined;
let activeCase: CaseVersion | undefined;

setWorkerUrl(workerUrl);

function updateLinks(caseId: string | null, version: string | null) {
  const query = new URLSearchParams();
  if (caseId) query.set('case', caseId);
  if (version) query.set('version', version);
  const suffix = query.size ? `?${query}` : '';
  document.querySelectorAll<HTMLAnchorElement>('[data-case-map]').forEach(link => { link.href = `/${suffix}`; });
  document.querySelector<HTMLAnchorElement>('#tile-current-page')!.href = `/mvt-demo.html${suffix}`;
}

function showStatus(state: 'loading' | 'ready' | 'offline' | 'error' | 'unavailable', message: string, canRetry = false) {
  statusCard.dataset.state = state;
  if (status.textContent !== message) status.textContent = message;
  retry.hidden = !canRetry;
}

function highlightFeature(hit?: MapGeoJSONFeature) {
  if (!map?.getLayer('selection-area')) return;
  const kind = String(hit?.properties.kind ?? '');
  const id = hit?.properties.id;
  const filter: FilterSpecification = id == null ? emptySelection
    : ['all', ['==', ['get', 'kind'], kind], ['==', ['to-string', ['get', 'id']], String(id)]];
  map.setFilter('selection-area', kind === 'road' ? emptySelection : filter);
  map.setFilter('selection-road', kind === 'road' ? filter : emptySelection);
}

function clearSelection(message = '在地图上选择地物') {
  highlightFeature();
  featureData.hidden = true;
  featureMessage.textContent = message;
  featureMessage.hidden = false;
  clearFeature.hidden = true;
}

function showFeature(hit: MapGeoJSONFeature | undefined) {
  if (!hit) {
    clearSelection('这里没有可查询的地物');
    return;
  }
  highlightFeature(hit);
  const kind = hit.properties.kind as keyof typeof kindLabels;
  featureKind.textContent = kindLabels[kind] ?? '地物';
  featureName.textContent = String(hit.properties.name || '未命名');
  featureId.textContent = String(hit.properties.id ?? hit.id ?? '—');
  featureMessage.hidden = true;
  featureData.hidden = false;
  clearFeature.hidden = false;
}

function inspect(point: PointLike) {
  if (inspectCenter.disabled) return;
  showFeature(map?.queryRenderedFeatures(point, { layers: featureLayers })[0]);
}

function inspectAtCenter() {
  inspect([container.clientWidth / 2, container.clientHeight / 2]);
}

function cameraPadding() {
  const width = container.clientWidth;
  const height = container.clientHeight;
  return width <= 650
    ? { left: 20, right: 20, top: Math.round(height * .16), bottom: Math.round(height * .32) }
    : { left: 58, right: 68, top: Math.round(height * .11), bottom: Math.round(height * .12) };
}

function motionDuration() {
  return matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 360;
}

function tileStyle(item: CaseVersion, path: string): StyleSpecification {
  return {
    version: 8,
    sources: {
      features: {
        type: 'vector', tiles: [location.origin + path], bounds: [...item.bounds[0], ...item.bounds[1]],
        minzoom: 0, maxzoom: 19,
      },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#172422' } },
      { id: 'water', type: 'fill', source: 'features', 'source-layer': 'features',
        filter: ['==', ['get', 'kind'], 'water'],
        paint: {
          'fill-color': '#1d4140',
          'fill-outline-color': '#518078',
        } },
      { id: 'streets', type: 'line', source: 'features', 'source-layer': 'features',
        filter: ['==', ['get', 'kind'], 'road'], layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': '#91ab9b',
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, .55, 15, 1.25, 19, 5.4],
        } },
      { id: 'buildings', type: 'fill', source: 'features', 'source-layer': 'features',
        filter: ['==', ['get', 'kind'], 'building'],
        paint: {
          'fill-color': '#527c71',
          'fill-outline-color': '#72998e',
        } },
      { id: 'selection-area', type: 'fill', source: 'features', 'source-layer': 'features', filter: emptySelection,
        paint: { 'fill-color': '#9fdfcc', 'fill-opacity': .62, 'fill-outline-color': '#e4fff5' } },
      { id: 'selection-road', type: 'line', source: 'features', 'source-layer': 'features', filter: emptySelection,
        paint: { 'line-color': '#dcfff0', 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 2, 15, 3, 19, 7] } },
    ],
  };
}

function openMap(item: CaseVersion, path: string) {
  const current = new MapLibre({
    container, bounds: item.bounds, fitBoundsOptions: { padding: cameraPadding() },
    maxPitch: 0, maxZoom: 19, minZoom: 3, dragRotate: false, touchPitch: false,
    renderWorldCopies: false, attributionControl: false, style: tileStyle(item, path),
    locale: {
      'CooperativeGesturesHandler.WindowsHelpText': '按住 Ctrl 并滚动以缩放地图',
      'CooperativeGesturesHandler.MacHelpText': '按住 ⌘ 并滚动以缩放地图',
      'CooperativeGesturesHandler.MobileHelpText': '用双指移动地图',
    },
  });
  map = current;
  controls.hidden = false;
  current.addControl(new ScaleControl({ unit: 'metric', maxWidth: 86 }), 'top-right');
  current.keyboard.disableRotation();
  current.touchZoomRotate.disableRotation();
  const updateGestures = () => {
    if (container.clientHeight > document.documentElement.clientHeight) current.cooperativeGestures.enable();
    else current.cooperativeGestures.disable();
  };
  updateGestures();
  current.on('resize', updateGestures);
  const canvas = current.getCanvas();
  canvas.setAttribute('aria-label', '案例矢量瓦片地图');
  canvas.setAttribute('aria-describedby', 'map-help');
  canvas.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      inspectAtCenter();
    } else if (event.key === 'Escape') {
      clearSelection();
    }
  });

  const updateZoom = () => {
    zoomReadout.textContent = `z ${current.getZoom().toFixed(1)}`;
    zoomReadout.hidden = false;
  };
  updateZoom();
  current.on('moveend', updateZoom);

  let tileAvailable = false;
  const startupTimeout = window.setTimeout(() => {
    if (!tileAvailable) showStatus('error', '暂未收到案例瓦片', true);
  }, 7000);
  current.on('remove', () => window.clearTimeout(startupTimeout));
  current.on('sourcedata', event => {
    if (event.sourceId !== 'features' || event.tile?.state !== 'loaded') return;
    tileAvailable = true;
    window.clearTimeout(startupTimeout);
    showStatus('ready', '在线矢量瓦片已加载');
    inspectCenter.disabled = false;
  });
  current.on('error', () => {
    window.clearTimeout(startupTimeout);
    showStatus('error', '瓦片加载失败', true);
  });
  current.on('click', event => inspect(event.point));
  current.on('mousemove', event => {
    canvas.style.cursor = !inspectCenter.disabled && current.queryRenderedFeatures(event.point, { layers: featureLayers }).length
      ? 'pointer' : '';
  });
  current.on('mouseout', () => { canvas.style.cursor = ''; });
}

function closeMap() {
  clearSelection();
  map?.remove();
  map = undefined;
  controls.hidden = true;
  zoomReadout.hidden = true;
  inspectCenter.disabled = true;
}

async function start() {
  request?.abort();
  const controller = new AbortController();
  request = controller;
  closeMap();
  showStatus('loading', '正在连接案例服务…');
  const query = new URLSearchParams(location.search);
  const requestedCase = query.get('case');
  const requestedVersion = query.get('version');
  updateLinks(requestedCase, requestedVersion);

  try {
    const { catalog, mode } = await loadCaseCatalog(controller.signal);
    controller.signal.throwIfAborted();
    activeCase = chooseRequestedCase(catalog, requestedCase, requestedVersion);
    caseName.textContent = activeCase?.title ?? '';
    caseName.hidden = !activeCase;
    credit.textContent = activeCase?.sources.map(source => source.label).join(' · ') ?? '';
    credit.hidden = !credit.textContent;
    if (activeCase) updateLinks(activeCase.id, activeCase.version);
    if (mode === 'snapshot') {
      showStatus('offline', activeCase ? '离线案例快照 · 在线矢量瓦片暂不可用' : '离线目录中没有所选案例或版本', true);
      return;
    }
    if (!activeCase) {
      showStatus('unavailable', '找不到所选案例或版本');
      return;
    }
    const path = `${caseEndpoint(activeCase)}/tiles/{z}/{x}/{y}.pbf`;
    if (activeCase.features !== path) {
      showStatus('unavailable', '该案例未提供在线矢量瓦片');
      return;
    }
    showStatus('loading', '正在加载矢量瓦片…');
    try {
      openMap(activeCase, path);
    } catch {
      closeMap();
      showStatus('error', '无法启动地图', true);
    }
  } catch {
    if (controller.signal.aborted) return;
    if (navigator.onLine) showStatus('error', '无法连接案例服务', true);
    else showStatus('offline', '设备离线 · 在线矢量瓦片暂不可用', true);
  }
}

retry.addEventListener('click', () => {
  status.tabIndex = -1;
  status.focus();
  void start();
});
inspectCenter.addEventListener('click', inspectAtCenter);
clearFeature.addEventListener('click', () => {
  inspectCenter.focus();
  clearSelection();
});
document.querySelector('.lab-skip')!.addEventListener('click', event => {
  event.preventDefault();
  (map?.getCanvas() ?? container).focus();
});
document.querySelector('#tile-zoom-in')!.addEventListener('click', () => map?.zoomIn({ duration: motionDuration() }));
document.querySelector('#tile-zoom-out')!.addEventListener('click', () => map?.zoomOut({ duration: motionDuration() }));
document.querySelector('#tile-fit')!.addEventListener('click', () => {
  if (activeCase) map?.fitBounds(activeCase.bounds, { padding: cameraPadding(), duration: motionDuration() });
});
window.addEventListener('pagehide', event => {
  if (!event.persisted) {
    request?.abort();
    closeMap();
  }
});
window.addEventListener('pageshow', event => {
  if (event.persisted) map?.resize();
});
void start();
