import assert from 'node:assert/strict';
import test from 'node:test';
import { chooseComparison, chooseDefaultCase, loadCaseCatalog, rectangleCorners } from '../src/atlas-cases.ts';
import type { CaseVersion, CaseStep } from '../src/atlas-cases.ts';

const step = (id: string, scenario: string, time_min: number | null): CaseStep => ({
  id, scenario, time_min, label: id, description: '', kind: time_min === null ? 'peak' : 'time',
  depth: '/cases/example/depth.png',
  summary: { flooded_area_m2: 0, affected_buildings: 0, flooded_road_length_m: 0 },
});

const example: CaseVersion = {
  id: 'nyc', version: '2026-11-12', title: 'NYC', subtitle: '', description: '',
  bounds: [[-74, 40], [-73, 41]], threshold_m: 0.1, analysis_srid: 32618,
  sources: [], basemap: null, features: null, steps: [step('a', 'Rain', null)],
};

test('scenario comparison prefers the same minute from another scenario', () => {
  const a = step('a', 'Rain', 30);
  const steps = [a, step('b', 'Rain', 60), step('c', 'Compound', 60), step('d', 'Compound', 30)];
  assert.equal(chooseComparison(steps, a)?.id, 'd');
  assert.equal(chooseComparison(steps.slice(0, 2), a)?.id, 'b');
  assert.equal(chooseComparison([a], a), undefined);
});

test('catalog preference accepts a pinned version and then a latest case ID', () => {
  const newest = { ...example, version: '2' };
  const older = { ...example, version: '1' };
  const other = { ...example, id: 'other' };
  assert.equal(chooseDefaultCase({ default: 'nyc', cases: [other, newest, older] }), newest);
  assert.equal(chooseDefaultCase({ default: 'nyc', cases: [other, newest, older] }, 'nyc/1'), older);
});

test('invalid online catalog falls back to the offline case contract', async () => {
  const request: typeof fetch = async input => new Response(JSON.stringify(
    input === '/api/v2/cases' ? { default: 'nyc', cases: [{}] } : { default: 'nyc', cases: [example] },
  ));
  const result = await loadCaseCatalog(undefined, request);
  assert.equal(result.mode, 'snapshot');
  assert.equal(result.catalog.cases[0]?.id, 'nyc');
});

test('image corners follow MapLibre’s clockwise northwest-first order', () => {
  assert.deepEqual(rectangleCorners(example.bounds), [
    [-74, 41], [-73, 41], [-73, 40], [-74, 40],
  ]);
});
test('offline point sampling uses Web Mercator, north-up rows and explicit water / NoData values', async () => {
  const { sampleDepthGrid } = await import('../src/atlas-cases.ts');
  const grid = { url: '/grid.f32', width: 2, height: 2, extent: [-1000, -1000, 1000, 1000] } as const;
  const bytes = new ArrayBuffer(16);
  const samples = new DataView(bytes);
  [0.125, -1, NaN, 0].forEach((value, index) => samples.setFloat32(index * 4, value, true));
  assert.deepEqual(sampleDepthGrid(grid, bytes, [-0.004, 0.004]), { depth_m: 0.125, status: 'covered' });
  assert.deepEqual(sampleDepthGrid(grid, bytes, [0.004, 0.004]), { depth_m: null, status: 'water' });
  assert.deepEqual(sampleDepthGrid(grid, bytes, [-0.004, -0.004]), { depth_m: null, status: 'no_coverage' });
  assert.deepEqual(sampleDepthGrid(grid, bytes, [0.004, -0.004]), { depth_m: 0, status: 'covered' });
  assert.deepEqual(sampleDepthGrid(grid, bytes, [1, 1]), { depth_m: null, status: 'no_coverage' });
});
