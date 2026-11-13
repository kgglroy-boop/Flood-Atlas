<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AtlasIcon from './AtlasIcon.vue';
import AtlasImport from './AtlasImport.vue';
import AtlasMap from './AtlasMap.vue';
import AtlasScene from './AtlasScene.vue';
import {
  caseEndpoint, caseKey, chooseComparison, chooseRequestedCase, chooseSceneStep, depthBins,
  loadCaseCatalog, loadSnapshotBuildings, readyForPlayback, requestJson, sampleDepthGrid, sceneChoices,
  type Building, type CaseVersion, type Catalog, type DepthSample, type Point,
} from './atlas-cases';

type Overlay = 'library' | 'search' | 'layers' | 'sources';
type Side = 'left' | 'right';

const catalog = ref<Catalog>({ default: '', cases: [] });
const item = ref<CaseVersion>();
const stepId = ref('');
const comparisonId = ref('');
const online = ref(true);
const loadError = ref('');
const caseUnavailable = ref(false);
const loaded = ref(false);
const map = ref<InstanceType<typeof AtlasMap>>();
const wizard = ref<InstanceType<typeof AtlasImport>>();
const dialog = ref<HTMLDialogElement>();
const searchField = ref<HTMLInputElement>();
const impactButton = ref<HTMLButtonElement>();
const overlay = ref<Overlay>();
const panel = ref<'impact' | 'inspection'>();
const quiet = ref(false);
const mode = ref<'aerial' | 'vector'>('aerial');
const showDepth = ref(true);
const accessKey = ref('');
const query = ref('');
const searchResults = ref<Building[]>([]);
const searchMessage = ref('');
const mapReady = ref(false);
const comparisonReady = ref(false);
const selected = ref<Point>();
const inspection = ref<{ building?: Building; depth?: DepthSample; label: string; pending: boolean }>();
const inspectionError = ref('');
const playing = ref(false);
const exporting = ref(false);
const exportError = ref('');
let searchAbort: AbortController | undefined;
let pointAbort: AbortController | undefined;
let catalogAbort: AbortController | undefined;
let timer: number | undefined;
let frames: number | undefined;
let localBuildingCache: { url: string; items: Building[] } | undefined;
let inspectedTarget: { point: Point; side: Side; id?: string; building?: Building } | undefined;
let overlayTrigger: HTMLElement | undefined;
let returnToMapAfterDialog = false;

const number = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 });
const step = computed(() => item.value?.steps.find(value => value.id === stepId.value));
const comparison = computed(() => item.value?.steps.find(value => value.id === comparisonId.value));
const alternatives = computed(() => item.value?.steps.filter(value => value.id !== stepId.value) ?? []);
const choices = computed(() => sceneChoices(item.value?.steps ?? []));
const choice = computed(() => choices.value.find(entry => entry.steps.some(value => value.id === stepId.value)));
const series = computed(() => step.value?.kind === 'time' ? choice.value?.steps ?? [] : []);
const usableDelta = computed(() => !!step.value?.coverage && step.value.coverage === comparison.value?.coverage);
const canSearch = computed(() => online.value ? !!item.value?.features : !!item.value?.snapshot_features);
const hrefMvt = computed(() => item.value ? '/mvt-demo.html?' + new URLSearchParams({ case: item.value.id, version: item.value.version }) : '/mvt-demo.html');
const titleParts = computed(() => {
  const [first, ...rest] = item.value?.title.split(/\s+·\s+/) ?? [];
  return [first, rest.join(' · ')] as const;
});
const bins = computed(() => depthBins(item.value?.threshold_m ?? .1));
const panelTitle = { library: '案例库', search: '查找建筑', layers: '图层与视图', sources: '案例来源' };
const metrics = [
  { key: 'flooded_area_m2', label: '淹没面积', unit: 'm²', icon: 'drop' },
  { key: 'affected_buildings', label: '相交建筑', unit: '栋', icon: 'building' },
  { key: 'flooded_road_length_m', label: '道路交集长度', unit: 'm', icon: 'road' },
] as const;
const metric = (value: number | null | undefined) => value == null ? '—' : number.format(value);

function selectCase(next: CaseVersion, pin = true) {
  if (item.value && caseKey(item.value) === caseKey(next)) return;
  playing.value = false;
  comparisonId.value = '';
  item.value = next;
  stepId.value = next.steps[0]?.id ?? '';
  mode.value = next.basemap ? 'aerial' : 'vector';
  mapReady.value = false;
  query.value = '';
  searchResults.value = [];
  clearPoint();
  if (pin) {
    const url = new URL(location.href);
    url.searchParams.set('case', next.id);
    url.searchParams.set('version', next.version);
    history.replaceState(null, '', url);
  }
}

async function refresh(pinned?: string) {
  catalogAbort?.abort();
  const request = new AbortController();
  catalogAbort = request;
  loaded.value = false;
  loadError.value = '';
  caseUnavailable.value = false;
  try {
    const result = await loadCaseCatalog(request.signal);
    if (request.signal.aborted) return;
    catalog.value = result.catalog;
    online.value = result.mode === 'online';
    const params = new URLSearchParams(location.search);
    const [id, version] = pinned ? pinned.split('/') : [params.get('case'), params.get('version')];
    const target = chooseRequestedCase(result.catalog, id, version);
    if (!target && (id || version)) {
      item.value = undefined;
      caseUnavailable.value = true;
      loadError.value = '此案例或版本当前不可用。';
      return;
    }
    if (!target) throw new Error('暂无可用案例');
    selectCase(target, !!pinned);
  } catch {
    if (!request.signal.aborted) loadError.value = '案例暂未就绪，请重新加载。';
  } finally {
    if (!request.signal.aborted) loaded.value = true;
  }
}
function showDefaultCase() {
  const url = new URL(location.href);
  url.searchParams.delete('case');
  url.searchParams.delete('version');
  history.replaceState(null, '', url);
  void refresh();
}

function toggleComparison() {
  comparisonId.value = comparison.value || !item.value || !step.value
    ? '' : chooseComparison(item.value.steps, step.value)?.id ?? '';
}
function setStep(id: string) {
  if (id === comparisonId.value) comparisonId.value = stepId.value;
  stepId.value = id;
}
function setScene(id: string) {
  const target = choices.value.find(entry => entry.id === id);
  if (!target || !step.value || id === choice.value?.id) return;
  playing.value = false;
  const frame = chooseSceneStep(target, step.value);
  if (frame) setStep(frame.id);
}
function clearPoint() {
  pointAbort?.abort();
  inspectedTarget = undefined;
  selected.value = undefined;
  inspection.value = undefined;
  inspectionError.value = '';
  if (panel.value === 'inspection') panel.value = undefined;
}
function layerReady(value: boolean, side: Side) {
  if (side === 'left') mapReady.value = value;
  else comparisonReady.value = value;
}

watch(stepId, () => { mapReady.value = false; });
watch(comparisonId, () => { comparisonReady.value = false; });
watch([stepId, comparisonId], ([left, right], [oldLeft, oldRight]) => {
  const target = inspectedTarget;
  if (!target) return;
  if (target.side === 'right' && !comparison.value) clearPoint();
  else if (target.side === 'left' ? left !== oldLeft : right !== oldRight) {
    void inspect(target.point, target.side, target.id, target.building);
  }
});
watch(playing, value => {
  window.clearInterval(frames);
  if (value && series.value.length > 1) frames = window.setInterval(() => {
    if (document.hidden || !readyForPlayback(showDepth.value, mapReady.value, !!comparison.value, comparisonReady.value)) return;
    const index = series.value.findIndex(value => value.id === stepId.value);
    const next = series.value[(index + 1) % series.value.length];
    if (next) setStep(next.id);
  }, 1500);
});
watch(query, () => {
  window.clearTimeout(timer);
  searchAbort?.abort();
  searchResults.value = [];
  searchMessage.value = '';
  if (query.value.trim()) timer = window.setTimeout(runSearch, 230);
});

async function runSearch() {
  window.clearTimeout(timer);
  const value = query.value.trim();
  const active = item.value;
  if (!value || !active) return;
  searchAbort?.abort();
  const request = new AbortController();
  searchAbort = request;
  searchMessage.value = '搜索中…';
  try {
    let results: Building[];
    if (online.value) {
      results = (await requestJson<{ items: Building[] }>(caseEndpoint(active) + '/buildings?' + new URLSearchParams({ q: value }), { signal: request.signal })).items;
    } else if (active.snapshot_features) {
      const url = active.snapshot_features;
      if (localBuildingCache?.url !== url) localBuildingCache = { url, items: await loadSnapshotBuildings(url, request.signal) };
      const lower = value.toLowerCase();
      results = localBuildingCache.items.filter(record => [record.id, record.name, record.address].some(text => text?.toLowerCase().includes(lower))).slice(0, 20);
    } else results = [];
    if (!request.signal.aborted) {
      searchResults.value = results;
      searchMessage.value = results.length ? '' : '没有匹配的建筑';
    }
  } catch {
    if (!request.signal.aborted) searchMessage.value = '建筑搜索暂不可用';
  }
}

async function inspect(point: Point, side: Side, id?: string, base?: Building) {
  const active = item.value;
  const frame = side === 'right' ? comparison.value : step.value;
  if (!active || !frame) return;
  pointAbort?.abort();
  const request = new AbortController();
  pointAbort = request;
  inspectedTarget = { point, side, id, building: base };
  selected.value = point;
  panel.value = 'inspection';
  inspectionError.value = '';
  inspection.value = { building: base, label: frame.label, pending: true };
  const params = new URLSearchParams({ step: frame.id, lon: String(point[0]), lat: String(point[1]) });
  const depth = online.value
    ? requestJson<DepthSample>(caseEndpoint(active) + '/sample?' + params, { signal: request.signal })
    : frame.grid ? fetch(frame.grid.url, { signal: request.signal }).then(response => {
      if (!response.ok) throw new Error('网格读取失败');
      return response.arrayBuffer();
    }).then(bytes => sampleDepthGrid(frame.grid!, bytes, point)) : Promise.resolve(undefined);
  const building = id && online.value
    ? requestJson<Building>(caseEndpoint(active) + '/buildings/' + encodeURIComponent(id) + '?step=' + encodeURIComponent(frame.id), { signal: request.signal })
    : Promise.resolve(base ?? (id ? { id, name: id, lon: point[0], lat: point[1] } : undefined));
  const [d, b] = await Promise.allSettled([depth, building]);
  if (request.signal.aborted) return;
  const record = b.status === 'fulfilled' ? b.value : base;
  inspectedTarget = { point, side, id, building: record ? { ...record, affected: undefined } : undefined };
  inspection.value = { label: frame.label, pending: false, depth: d.status === 'fulfilled' ? d.value : undefined, building: record };
  if (d.status === 'rejected' || b.status === 'rejected') inspectionError.value = '部分查询结果暂不可用';
}
function chooseBuilding(result: Building) {
  query.value = '';
  searchResults.value = [];
  closeOverlay();
  const point: Point = [result.lon, result.lat];
  map.value?.focusPoint(point);
  void inspect(point, 'left', result.id, result);
}
function hidePanel() {
  if (panel.value === 'inspection') clearPoint();
  else panel.value = undefined;
  impactButton.value?.focus({ preventScroll: true });
}
function toggleImpact() {
  if (panel.value === 'impact') hidePanel();
  else {
    clearPoint();
    panel.value = 'impact';
  }
}
async function openOverlay(value: Overlay) {
  overlayTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
  overlay.value = value;
  exportError.value = '';
  await nextTick();
  if (!dialog.value?.open) dialog.value?.showModal();
  if (value === 'search') searchField.value?.focus();
}
function closeOverlay() { dialog.value?.close(); }
function overlayClosed() {
  overlay.value = undefined;
  if (!returnToMapAfterDialog) overlayTrigger?.focus({ preventScroll: true });
  returnToMapAfterDialog = false;
  overlayTrigger = undefined;
}
function goToCase(entry: CaseVersion) { selectCase(entry); closeOverlay(); }
function openWizard() {
  returnToMapAfterDialog = true;
  closeOverlay();
  wizard.value?.open();
}
function sampleView() {
  closeOverlay();
  map.value?.sampleCenter();
}
async function exportCase() {
  if (!item.value || exporting.value) return;
  const current = item.value;
  exporting.value = true;
  exportError.value = '';
  try {
    const response = await fetch(caseEndpoint(current) + '/export', {
      headers: { Authorization: 'Bearer ' + accessKey.value.trim() },
      signal: AbortSignal.timeout(45000),
    });
    if (response.status === 401) throw new Error('本地访问密钥无效，请检查后重试。');
    if (!response.ok) throw new Error('案例包暂不可用，请稍后重试。');
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = current.id + '-' + current.version + '.zip';
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    exportError.value = error instanceof Error && error.name === 'Error' ? error.message : '下载失败，请稍后重试。';
  } finally { exporting.value = false; }
}
function keyboard(event: KeyboardEvent) {
  if (event.key !== 'Escape' || dialog.value?.open || document.querySelector('dialog[open]')) return;
  if (quiet.value) quiet.value = false;
  else if (panel.value) hidePanel();
}
onMounted(() => {
  void refresh();
  window.addEventListener('keydown', keyboard);
});
onBeforeUnmount(() => {
  searchAbort?.abort();
  pointAbort?.abort();
  catalogAbort?.abort();
  window.clearTimeout(timer);
  window.clearInterval(frames);
  window.removeEventListener('keydown', keyboard);
});
</script>

<template>
  <a class="atlas-skip" href="#atlas-main">跳到地图</a>
  <main id="atlas-main" class="atlas-stage" :class="{ 'is-quiet': quiet }" tabindex="-1">
    <template v-if="item && step">
      <AtlasMap ref="map" class="atlas-stage-map" immersive :key="caseKey(item) + '/' + online" :item="item"
        :step="step" :comparison="comparison" :selected="selected" :building-id="inspection?.building?.id" :online="online"
        v-model:mode="mode" v-model:show-depth="showDepth" @ready="layerReady" @inspect="inspect" />
      <div class="atlas-vignette" aria-hidden="true"></div>

      <header class="atlas-top">
        <button class="atlas-glass atlas-library-button" type="button" aria-label="打开案例库" aria-haspopup="dialog" @click="openOverlay('library')">
          <AtlasIcon name="mark" :size="22" /><b>Flood Atlas</b><AtlasIcon name="chevron" :size="14" />
        </button>
        <div class="atlas-glass atlas-quick" role="group" aria-label="地图工具">
          <button v-if="canSearch" type="button" aria-label="查找建筑" title="查找建筑" aria-haspopup="dialog" @click="openOverlay('search')"><AtlasIcon name="search" /></button>
          <button type="button" aria-label="图层与视图" title="图层与视图" aria-haspopup="dialog" @click="openOverlay('layers')"><AtlasIcon name="layers" /></button>
          <button type="button" aria-label="沉浸浏览" title="沉浸浏览" :aria-pressed="quiet" @click="quiet = !quiet"><AtlasIcon :name="quiet ? 'collapse' : 'expand'" :size="19" /></button>
        </div>
      </header>

      <div class="atlas-map-controls" role="group" aria-label="地图缩放">
        <div class="atlas-glass atlas-zoom-stack">
          <button type="button" aria-label="放大" title="放大" @click="map?.changeZoom(1)"><AtlasIcon name="plus" :size="19" /></button>
          <button type="button" aria-label="缩小" title="缩小" @click="map?.changeZoom(-1)"><AtlasIcon name="minus" :size="19" /></button>
        </div>
        <button class="atlas-glass atlas-round" type="button" aria-label="显示完整研究区" title="显示完整研究区" @click="map?.reset()"><AtlasIcon name="target" :size="20" /></button>
      </div>

      <div class="atlas-place" :class="{ 'is-long': (item.title.length > 28) }" :inert="quiet">
        <p v-if="item.subtitle" class="atlas-place-meta">{{ item.subtitle }}</p>
        <h1 :title="item.title"><span>{{ titleParts[0] }}</span><span v-if="titleParts[1]" class="atlas-place-name">{{ titleParts[1] }}</span></h1>
        <p class="atlas-place-context"><span class="atlas-live-dot" aria-hidden="true"></span>{{ step.kind === 'peak' ? '模型峰值' : step.label }}</p>
        <AtlasScene :choices="choices" :choice="choice" :step="step" :comparison="comparison"
          :alternatives="alternatives" :series="series" :playing="playing" @scene="setScene" @frame="setStep"
          @compare="toggleComparison" @reference="comparisonId = $event" @play="playing = !playing" />
      </div>

      <div class="atlas-analysis" :inert="quiet">
        <Transition name="atlas-reveal">
          <aside v-if="panel" id="atlas-detail" class="atlas-reading atlas-detail" :aria-label="panel === 'impact' ? '空间影响' : '地图查询'">
            <header class="atlas-detail-heading">
              <div><p>{{ panel === 'impact' ? step.label : inspection?.label }}</p>
                <h2>{{ panel === 'impact' ? '空间影响' : inspection?.building?.name || '地图点查询' }}</h2>
              </div>
              <button class="atlas-icon-button" type="button" aria-label="关闭详情" @click="hidePanel"><AtlasIcon name="close" :size="18" /></button>
            </header>
            <template v-if="panel === 'impact'">
              <dl class="atlas-metrics" aria-live="polite">
                <div v-for="spec in metrics" :key="spec.key" class="atlas-metric">
                  <dt><AtlasIcon :name="spec.icon" :size="15" />{{ spec.label }}</dt>
                  <dd><strong>{{ metric(step.summary[spec.key]) }}</strong><span>{{ step.summary[spec.key] == null ? '缺少数据' : spec.unit }}</span></dd>
                  <small v-if="comparison">对照 {{ metric(comparison.summary[spec.key]) }}{{ comparison.summary[spec.key] == null ? '（缺少数据）' : ' ' + spec.unit }}
                    <template v-if="usableDelta && step.summary[spec.key] != null && comparison.summary[spec.key] != null">
                      · 差值 {{ number.format(comparison.summary[spec.key]! - step.summary[spec.key]!) }} {{ spec.unit }}
                    </template>
                  </small>
                </div>
              </dl>
              <p v-if="comparison && !usableDelta" class="atlas-small">两图有效覆盖不同，分别显示统计。</p>
              <p class="atlas-small">统计阈值 &gt; {{ item.threshold_m }} m</p>
            </template>
            <div v-else-if="inspection" class="atlas-inspection" aria-live="polite">
              <p v-if="inspection.building?.address">{{ inspection.building.address }}</p>
              <p v-if="inspection.building">建筑编号 {{ inspection.building.id }}</p>
              <p v-if="inspection.pending" role="status">正在查询水深…</p>
              <p v-else-if="inspection.depth" class="atlas-sample">{{ inspection.depth.status === 'water' ? '常年水体' : inspection.depth.status === 'no_coverage' ? '模型无覆盖' : '网格水深 ' + metric(inspection.depth.depth_m) + ' m' }}</p>
              <p v-else-if="!inspectionError">该情景未提供点位水深。</p>
              <p v-if="inspection.building?.affected != null">{{ inspection.building.affected ? '与超阈值区域相交' : '未与超阈值区域相交' }}</p>
              <p v-if="inspectionError" role="status">{{ inspectionError }}</p>
            </div>
          </aside>
        </Transition>
        <button ref="impactButton" class="atlas-glass atlas-impact" type="button" :aria-expanded="panel === 'impact'"
          :aria-controls="panel === 'impact' ? 'atlas-detail' : undefined" @click="toggleImpact">
          <AtlasIcon name="stats" :size="21" /><span>空间影响</span><AtlasIcon name="chevron" class="impact-chevron" :size="16" />
        </button>
      </div>

      <div v-if="showDepth" class="atlas-legend" :inert="quiet" aria-label="积水深度图例">
        <div class="atlas-legend-title"><AtlasIcon name="drop" :size="14" />积水深度 <span>m</span></div>
        <div class="atlas-depth-bins" :style="{ '--bins': bins.length }">
          <div v-for="bin in bins" :key="bin.color"><i :style="{ background: bin.color }"></i><span>{{ bin.label }}</span></div>
        </div>
      </div>

      <footer class="atlas-credits">
        <button class="atlas-credit-button" type="button" aria-haspopup="dialog" @click="openOverlay('sources')">
          <AtlasIcon name="info" :size="15" /><span>数据来源</span>
        </button><span class="atlas-credit-context">{{ online ? '在线' : '本地快照' }} · EPSG:{{ item.analysis_srid }}</span>
      </footer>
    </template>
    <section v-else class="atlas-empty" role="status">
      <AtlasIcon name="mark" :size="38" /><h1>Flood Atlas</h1><p>{{ loaded ? loadError : '正在载入案例…' }}</p>
      <button v-if="loaded" class="atlas-glass atlas-neutral" type="button" @click="refresh()">重新加载</button>
      <button v-if="caseUnavailable" class="atlas-neutral" type="button" @click="showDefaultCase">查看默认案例</button>
      <a class="atlas-empty-archive" href="/legacy.html">教学档案</a>
    </section>
  </main>

  <dialog ref="dialog" class="atlas-dialog atlas-tool-dialog" :class="overlay && 'atlas-dialog-' + overlay" aria-labelledby="atlas-tool-title" @close="overlayClosed">
    <header class="atlas-dialog-head">
      <h2 id="atlas-tool-title">{{ overlay && panelTitle[overlay] }}</h2>
      <button class="atlas-icon-button atlas-neutral" type="button" aria-label="关闭面板" @click="closeOverlay"><AtlasIcon name="close" :size="18" /></button>
    </header>
    <div v-if="overlay === 'library'" class="atlas-dialog-body">
      <div class="atlas-case-list">
        <button v-for="entry in catalog.cases" :key="caseKey(entry)" class="atlas-case-card" type="button"
          :aria-current="item && caseKey(item) === caseKey(entry) ? 'true' : undefined" @click="goToCase(entry)">
          <img v-if="entry.basemap" :src="entry.basemap" alt="" loading="lazy" decoding="async" />
          <div v-else class="atlas-case-symbol"><AtlasIcon name="layers" :size="26" /></div>
          <span><b>{{ entry.title }}</b><small>{{ catalog.cases.some(other => other.id === entry.id && other.version !== entry.version) ? entry.version.slice(0, 8) : entry.subtitle }}</small></span>
          <AtlasIcon :name="item && caseKey(item) === caseKey(entry) ? 'check' : 'arrow'" :size="18" />
        </button>
      </div>
      <div class="atlas-library-actions">
        <button v-if="online" class="atlas-primary" type="button" @click="openWizard"><AtlasIcon name="upload" :size="18" />导入案例</button>
        <a v-if="online && item?.features" class="atlas-neutral" :href="hrefMvt"><AtlasIcon name="grid" :size="17" />矢量瓦片</a>
        <a class="atlas-neutral" href="/legacy.html"><AtlasIcon name="book" :size="17" />教学档案</a>
      </div>
    </div>

    <div v-else-if="overlay === 'search'" class="atlas-dialog-body atlas-search">
      <form role="search" @submit.prevent="searchResults.length ? chooseBuilding(searchResults[0]!) : runSearch()">
        <AtlasIcon name="search" :size="20" />
        <input ref="searchField" v-model="query" type="search" aria-label="建筑编号、名称或地址" placeholder="编号、名称或地址" autocomplete="off" />
      </form>
      <p v-if="searchMessage" role="status" class="atlas-small">{{ searchMessage }}</p>
      <ul v-if="searchResults.length" class="atlas-results">
        <li v-for="result in searchResults" :key="result.id"><button type="button" @click="chooseBuilding(result)">
          <span>{{ result.name }}<small>{{ result.address || result.id }}</small></span><AtlasIcon name="arrow" :size="17" />
        </button></li>
      </ul>
    </div>

    <div v-else-if="overlay === 'layers'" class="atlas-dialog-body atlas-layers">
      <div v-if="item?.basemap" class="atlas-mode" role="group" aria-label="底图">
        <button type="button" :aria-pressed="mode === 'aerial'" @click="mode = 'aerial'"><AtlasIcon name="image" />航拍</button>
        <button type="button" :aria-pressed="mode === 'vector'" @click="mode = 'vector'"><AtlasIcon name="layers" />简图</button>
      </div>
      <button class="atlas-layer-row" type="button" role="switch" :aria-checked="showDepth" @click="showDepth = !showDepth">
        <AtlasIcon name="drop" /><span>显示水深</span><i aria-hidden="true"></i>
      </button>
      <button class="atlas-layer-row" type="button" @click="sampleView"><AtlasIcon name="target" /><span>查询地图中心水深</span><AtlasIcon name="arrow" :size="17" /></button>
    </div>

    <div v-else-if="overlay === 'sources'" class="atlas-dialog-body">
      <p>{{ item?.description }}</p>
      <ul v-if="item?.sources.length" class="atlas-sources">
        <li v-for="source in item.sources" :key="source.url"><a :href="source.url" rel="noopener noreferrer" target="_blank">{{ source.label }} <AtlasIcon name="external" :size="15" /></a><p>{{ source.credit }}</p></li>
      </ul>
      <form v-if="online" class="atlas-export" @submit.prevent="exportCase">
        <label class="atlas-field">本地访问密钥<input v-model="accessKey" type="password" required autocomplete="off" spellcheck="false" /></label>
        <p v-if="exportError" class="atlas-error" role="alert">{{ exportError }}</p>
        <button class="atlas-primary" type="submit" :disabled="exporting"><AtlasIcon name="download" :size="18" />{{ exporting ? '正在生成下载…' : '导出案例 ZIP' }}</button>
      </form>
    </div>
  </dialog>

  <AtlasImport ref="wizard" v-model:access-key="accessKey" :current="item" @published="entry => refresh(entry ? caseKey(entry) : undefined)" />
</template>

