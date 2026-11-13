"""Public teaching catalog, read from a single consistent database snapshot."""
import re
from typing import Literal

import psycopg
from pydantic import BaseModel


class ScenarioCatalogUnavailable(ValueError):
    pass


class ScenarioStep(BaseModel):
    step_id: str
    step_code: Literal['T00', 'T30', 'T60']
    time_min: Literal[0, 30, 60]
    layer_id: str


class Scenario(BaseModel):
    scenario_id: Literal['S01', 'S02']
    name: str
    steps: list[ScenarioStep]


class ScenarioCatalog(BaseModel):
    dataset_id: Literal['teaching-v1']
    generation_id: str
    model_type: Literal['synthetic_demo']
    analysis_srid: Literal[32650]
    depth_unit: Literal['m']
    threshold_m: Literal[0.1]
    scenarios: list[Scenario]


def assemble_catalog(datasets: list, scenarios: list, steps: list) -> dict:
    def unavailable():
        raise ScenarioCatalogUnavailable('scenario catalog unavailable')

    if len(datasets) != 1:
        unavailable()
    dataset_id, generation, model, version, srid = datasets[0]
    if (dataset_id, model, version, srid) != ('teaching-v1', 'synthetic_demo', '1.0', 32650) or not re.fullmatch(r'[0-9a-f]{20}', generation):
        unavailable()
    if len(scenarios) != 2 or {row[0] for row in scenarios} != {'S01', 'S02'}:
        unavailable()
    expected = {(s, t) for s in ('S01', 'S02') for t in (0, 30, 60)}
    if len(steps) != 6 or {(row[0], row[1]) for row in steps} != expected:
        unavailable()
    for scenario_id, time_min, code, step_generation in steps:
        if code != f'T{time_min:02}' or step_generation != generation:
            unavailable()
    public_scenarios = []
    for scenario_id, source_dataset, name, scenario_model in sorted(scenarios):
        if source_dataset != dataset_id or scenario_model != model or not isinstance(name, str) or not name.strip():
            unavailable()
        public_steps = []
        for _, time_min, code, _ in sorted(row for row in steps if row[0] == scenario_id):
            step_id = f'{scenario_id}_{code}'
            public_steps.append(dict(step_id=step_id, step_code=code, time_min=time_min, layer_id=f'flood:depth_{step_id}'))
        public_scenarios.append(dict(scenario_id=scenario_id, name=name, steps=public_steps))
    return dict(dataset_id=dataset_id, generation_id=generation, model_type=model, analysis_srid=srid,
                depth_unit='m', threshold_m=0.1, scenarios=public_scenarios)


def read_catalog_snapshot(connection: psycopg.Connection) -> dict:
    """Read inside the caller's existing consistent transaction; never issue SET."""
    datasets = connection.execute('SELECT dataset_id,generation_id,model_type,contract_version,analysis_srid FROM flood.dataset_info').fetchall()
    scenarios = connection.execute('SELECT scenario_id,dataset_id,name,model_type FROM flood.scenarios').fetchall()
    steps = connection.execute('SELECT scenario_id,time_min,step_code,generation_id FROM flood.scenario_steps').fetchall()
    return assemble_catalog(datasets, scenarios, steps)


def read_scenario_catalog(connection: psycopg.Connection) -> dict:
    try:
        with connection.transaction():
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            return read_catalog_snapshot(connection)
    except (psycopg.errors.UndefinedTable, psycopg.errors.UndefinedColumn, psycopg.errors.InvalidSchemaName):
        raise ScenarioCatalogUnavailable('scenario catalog unavailable') from None
