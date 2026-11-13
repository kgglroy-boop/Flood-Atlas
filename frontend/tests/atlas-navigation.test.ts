import assert from 'node:assert/strict';
import test from 'node:test';
import { sceneChoices, chooseRequestedCase, chooseSceneStep, readyForPlayback } from '../src/atlas-cases.ts';
import type { CaseStep, CaseVersion } from '../src/atlas-cases.ts';

function frame(id: string, scenario: string, time: number | null): CaseStep {
  return {
    id, scenario, time_min: time, label: time === null ? id : time + ' 分钟',
    kind: time === null ? 'peak' : 'time', description: '', depth: '/depth.png',
    summary: { flooded_area_m2: 0, affected_buildings: null, flooded_road_length_m: null },
  };
}

test('the scene dock groups time steps and retains individual peak views', () => {
  const steps = [frame('b60','B',60), frame('a30','A',30), frame('b0','B',0),
    frame('base','B',null), frame('a0','A',0), frame('east','C',null)];
  const choices = sceneChoices(steps);
  assert.deepEqual(choices.map(choice => [choice.label, choice.steps.map(step => step.id)]), [
    ['B', ['b0', 'b60']], ['A', ['a0', 'a30']], ['base', ['base']], ['east', ['east']],
  ]);
  assert.equal(chooseSceneStep(choices[0]!, steps[1]!)?.id, 'b0');
  assert.equal(chooseSceneStep(choices[1]!, steps[2]!)?.id, 'a0');
});

test('playback can advance with hidden water; a visible comparison waits for both frames', () => {
  assert.equal(readyForPlayback(false, false, true, false), true);
  assert.equal(readyForPlayback(true, true, true, false), false);
  assert.equal(readyForPlayback(true, true, false, false), true);
  assert.equal(readyForPlayback(true, false, false, true), false);
});

test('a pinned case does not silently turn into the default when offline', () => {
  const nyc = { id: 'nyc', version: 'new' } as CaseVersion;
  const archived = { id: 'nyc', version: 'old' } as CaseVersion;
  const imported = { id: 'another', version: 'new' } as CaseVersion;
  const catalog = { default: 'nyc', cases: [nyc, archived, imported] };
  assert.equal(chooseRequestedCase(catalog, 'another'), imported);
  assert.equal(chooseRequestedCase(catalog, 'nyc', 'old'), archived);
  assert.equal(chooseRequestedCase(catalog, 'another', 'missing'), undefined);
  assert.equal(chooseRequestedCase({ ...catalog, cases: [nyc] }, 'another', 'new'), undefined);
});

