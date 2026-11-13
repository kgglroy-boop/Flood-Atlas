import copy
from contextlib import nullcontext

import psycopg
import pytest

from app import main
from app.scenarios import assemble_catalog, ScenarioCatalogUnavailable
from test_health import get

GENERATION = '74e68b2da680e9680f65'


def rows():
    return ([('teaching-v1', GENERATION, 'synthetic_demo', '1.0', 32650)],
            [(s, 'teaching-v1', name, 'synthetic_demo') for s, name in [('S02', '教学情景B'), ('S01', '教学情景A')]],
            [(s, t, f'T{t:02}', GENERATION) for s in ['S02', 'S01'] for t in [60, 0, 30]])


def test_complete_sorted_catalog_has_only_public_fields():
    catalog = assemble_catalog(*rows())
    assert set(catalog) == {'dataset_id', 'generation_id', 'model_type', 'analysis_srid', 'depth_unit', 'threshold_m', 'scenarios'}
    assert catalog['generation_id'] == GENERATION
    assert catalog['depth_unit'] == 'm' and catalog['threshold_m'] == .1
    assert [s['scenario_id'] for s in catalog['scenarios']] == ['S01', 'S02']
    for scenario in catalog['scenarios']:
        assert set(scenario) == {'scenario_id', 'name', 'steps'}
        assert [s['time_min'] for s in scenario['steps']] == [0, 30, 60]
        for step in scenario['steps']:
            assert set(step) == {'step_id', 'step_code', 'time_min', 'layer_id'}
            assert step['layer_id'] == 'flood:depth_' + step['step_id']


@pytest.mark.parametrize('change', ['missing', 'generation', 'model', 'crs', 'duplicate', 'foreign', 'step_code'])
def test_invalid_catalog_is_not_partial_success(change):
    datasets, scenarios, steps = copy.deepcopy(rows())
    if change == 'missing': steps.pop()
    elif change == 'generation': steps[0] = (*steps[0][:3], '0' * 20)
    elif change == 'model': datasets[0] = ('teaching-v1', GENERATION, 'real', '1.0', 32650)
    elif change == 'crs': datasets[0] = (*datasets[0][:4], 4326)
    elif change == 'duplicate': steps.append(steps[0])
    elif change == 'foreign': scenarios[0] = ('S99', *scenarios[0][1:])
    else: steps[0] = (steps[0][0], steps[0][1], 'T99', GENERATION)
    with pytest.raises(ScenarioCatalogUnavailable): assemble_catalog(datasets, scenarios, steps)


def test_endpoint_exact_catalog(monkeypatch):
    expected = assemble_catalog(*rows())
    monkeypatch.setattr(main, 'open_database', lambda: nullcontext(object()))
    monkeypatch.setattr(main, 'read_scenario_catalog', lambda _: expected)
    response = get('/api/v1/scenarios')
    assert response.status_code == 200 and response.json() == expected


@pytest.mark.parametrize('error,detail', [(psycopg.OperationalError, 'database unavailable'), (ScenarioCatalogUnavailable, 'scenario catalog unavailable')])
def test_endpoint_failures_are_sanitized(monkeypatch, caplog, error, detail):
    def fail(): raise error('secret-password /private/path')
    monkeypatch.setattr(main, 'open_database', fail)
    response = get('/api/v1/scenarios')
    assert response.status_code == 503 and response.json() == {'detail': detail}
    assert 'secret-password' not in response.text + caplog.text
