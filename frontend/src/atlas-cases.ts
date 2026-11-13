export type Point = [number, number];
export type Bounds = [Point, Point];
export type CaseStep = {
  id: string;
  label: string;
  description: string;
  kind: 'peak' | 'time';
  time_min: number | null;
  scenario: string;
  depth: string;
  wmts?: string;
  coverage?: string;
  grid?: DepthGrid;
  summary: {
    flooded_area_m2: number;
    affected_buildings: number | null;
    flooded_road_length_m: number | null;
  };
};

export type CaseVersion = {
  id: string;
  version: string;
  title: string;
  subtitle: string;
  description: string;
  bounds: Bounds;
  analysis_srid: number;
  threshold_m: number;
  sources: { label: string; url: string; credit: string }[];
  basemap: string | null;
  features: string | null;
  snapshot_features?: string;
  steps: CaseStep[];
};

export type Catalog = { default: string; cases: CaseVersion[] };
export type CatalogMode = 'online' | 'snapshot';
export type Building = {
  id: string;
  name: string;
  address?: string;
  lon: number;
  lat: number;
  affected?: boolean | null;
};
export type DepthSample = { depth_m: number | null; status: 'covered' | 'no_coverage' | 'water' };
export type ImportJob = {
  id: string;
  status: 'queued' | 'processing' | 'preview' | 'publishing' | 'ready' | 'error';
  message: string;
  case?: CaseVersion;
  preview?: { warnings: string[]; steps: CaseStep[] };
};

export function caseKey(item: CaseVersion): string {
  return `${item.id}/${item.version}`;
}

export function chooseDefaultCase(catalog: Catalog, pinned?: string): CaseVersion | undefined {
  return catalog.cases.find(item => caseKey(item) === pinned)
    ?? catalog.cases.find(item => item.id === catalog.default)
    ?? catalog.cases[0];
}

export function chooseRequestedCase(catalog: Catalog, id?: string | null, version?: string | null): CaseVersion | undefined {
  if (!id && !version) return chooseDefaultCase(catalog);
  return catalog.cases.find(item => item.id === (id || catalog.default) && (!version || item.version === version));
}

export function chooseComparison(steps: CaseStep[], primary: CaseStep): CaseStep | undefined {
  const alternatives = steps.filter(step => step.id !== primary.id);
  return alternatives.find(step => step.scenario !== primary.scenario
      && step.kind === primary.kind && step.time_min === primary.time_min)
    ?? alternatives.find(step => step.scenario !== primary.scenario)
    ?? alternatives[0];
}

export type SceneChoice = { id: string; label: string; steps: CaseStep[] };

export function sceneChoices(steps: CaseStep[]): SceneChoice[] {
  const choices = new Map<string, SceneChoice>();
  for (const step of steps) {
    const id = step.kind === 'time' ? `time:${step.scenario}` : `peak:${step.id}`;
    const choice = choices.get(id) ?? { id, label: step.kind === 'time' ? step.scenario : step.label, steps: [] };
    choice.steps.push(step);
    choices.set(id, choice);
  }
  for (const choice of choices.values()) {
    choice.steps.sort((a, b) => (a.time_min ?? 0) - (b.time_min ?? 0));
  }
  return [...choices.values()];
}

export function chooseSceneStep(choice: SceneChoice, current: CaseStep): CaseStep | undefined {
  return choice.steps.find(step => step.kind === current.kind && step.time_min === current.time_min)
    ?? choice.steps[0];
}

export function readyForPlayback(depthVisible: boolean, primaryReady: boolean, comparing: boolean, comparisonReady: boolean) {
  return !depthVisible || (primaryReady && (!comparing || comparisonReady));
}

export function rectangleCorners([[west, south], [east, north]]: Bounds): [Point, Point, Point, Point] {
  return [[west, north], [east, north], [east, south], [west, south]];
}

export async function requestJson<T>(path: string, init?: RequestInit, request = fetch): Promise<T> {
  const response = await request(path, init);
  if (!response.ok) {
    const problem = await response.json().catch(() => null) as { detail?: unknown; message?: unknown } | null;
    const detail = problem?.detail ?? problem?.message;
    const message = typeof detail === 'string' ? detail : `请求失败（HTTP ${response.status}）`;
    throw new Error(message);
  }
  return await response.json() as T;
}

function verifyCatalog(value: Catalog): Catalog {
  if (typeof value?.default !== 'string' || !Array.isArray(value.cases)
      || value.cases.some(item => typeof item?.id !== 'string'
        || typeof item.version !== 'string' || typeof item.title !== 'string'
        || !Number.isFinite(item.threshold_m) || !Array.isArray(item.sources)
        || !Array.isArray(item.bounds) || item.bounds.length !== 2
        || !item.bounds.every(point => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite))
        || item.bounds[0][0] >= item.bounds[1][0] || item.bounds[0][1] >= item.bounds[1][1]
        || !Array.isArray(item.steps) || !item.steps.length
        || item.steps.some(step => typeof step?.id !== 'string' || typeof step.depth !== 'string'
          || !Number.isFinite(step.summary?.flooded_area_m2)))) {
    throw new Error('案例目录格式无效');
  }
  return value;
}

export async function loadCaseCatalog(signal?: AbortSignal, request = fetch): Promise<{
  catalog: Catalog;
  mode: CatalogMode;
}> {
  try {
    const timeout = AbortSignal.timeout(3000);
    const apiSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
    const online = verifyCatalog(await requestJson<Catalog>('/api/v2/cases', { signal: apiSignal }, request));
    if (online.cases.length) return { catalog: online, mode: 'online' };
  } catch {
    signal?.throwIfAborted();
  }
  const snapshot = verifyCatalog(await requestJson<Catalog>('/cases/catalog.json', { signal }, request));
  return { catalog: snapshot, mode: 'snapshot' };
}

export function caseEndpoint(item: CaseVersion): string {
  return `/api/v2/cases/${encodeURIComponent(item.id)}/${encodeURIComponent(item.version)}`;
}

const colors = ['#b7d6ee', '#749bd0', '#4968aa', '#3f407b', '#28234e'];
const caps = [0.3, 0.6, 1, 1.5, Infinity];
const number = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 3 });

export function depthBins(threshold: number) {
  return caps.flatMap((cap, index) => {
    if (cap <= threshold) return [];
    const lower = Math.max(threshold, caps[index - 1] ?? 0);
    return [{
      color: colors[index],
      label: Number.isFinite(cap) ? `${number.format(lower)}–${number.format(cap)}` : `>${number.format(lower)}`,
    }];
  });
}

type SnapshotFeature = {
  geometry?: { coordinates?: unknown };
  properties?: { id?: unknown; name?: unknown; address?: unknown; kind?: unknown };
};

export async function loadSnapshotBuildings(url: string, signal: AbortSignal): Promise<Building[]> {
  const data = await requestJson<{ features: SnapshotFeature[] }>(url, { signal });
  return data.features.flatMap(feature => {
    const props = feature.properties;
    if (props?.kind !== 'building' || props.id == null) return [];
    const extent = [Infinity, Infinity, -Infinity, -Infinity];
    function extend(coords: unknown) {
      if (!Array.isArray(coords)) return;
      const [x, y] = coords;
      if (typeof x === 'number' && typeof y === 'number') {
        extent[0] = Math.min(x, extent[0]);
        extent[1] = Math.min(y, extent[1]);
        extent[2] = Math.max(x, extent[2]);
        extent[3] = Math.max(y, extent[3]);
      } else coords.forEach(extend);
    }
    extend(feature.geometry?.coordinates);
    if (!extent.every(Number.isFinite)) return [];
    const id = String(props.id);
    return [{
      id,
      name: String(props.name || id),
      address: typeof props.address === 'string' ? props.address : undefined,
      lon: (extent[0] + extent[2]) / 2,
      lat: (extent[1] + extent[3]) / 2,
    }];
  });
}

export type DepthGrid = {
  url: string;
  width: number;
  height: number;
  extent: readonly [number, number, number, number];
};

export function sampleDepthGrid(grid: DepthGrid, bytes: ArrayBuffer, [lon, lat]: Point): DepthSample {
  const [west, south, east, north] = grid.extent;
  if (!Number.isInteger(grid.width) || !Number.isInteger(grid.height) || grid.width < 1 || grid.height < 1
    || bytes.byteLength !== grid.width * grid.height * 4 || !(east > west) || !(north > south)) {
    throw new Error('水深查询网格格式无效');
  }
  const radius = 6378137;
  const x = radius * lon * Math.PI / 180;
  const y = radius * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
  const column = Math.floor((x - west) * grid.width / (east - west));
  const row = Math.floor((north - y) * grid.height / (north - south));
  if (!Number.isFinite(column) || !Number.isFinite(row) || column < 0 || row < 0 || column >= grid.width || row >= grid.height) {
    return { depth_m: null, status: 'no_coverage' };
  }
  const value = new DataView(bytes).getFloat32((row * grid.width + column) * 4, true);
  if (value === -1) return { depth_m: null, status: 'water' };
  if (!Number.isFinite(value) || value < 0) return { depth_m: null, status: 'no_coverage' };
  return { depth_m: value, status: 'covered' };
}
