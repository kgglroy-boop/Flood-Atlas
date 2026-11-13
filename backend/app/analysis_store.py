"""Consistent, read-only flood-impact queries over the frozen teaching dataset."""
import math
from contextlib import contextmanager

import psycopg

from app.analysis_sql import INPUTS_SQL, WET_SQL, SUMMARY_SQL, BUILDINGS_SQL
from app.scenarios import read_catalog_snapshot, ScenarioCatalogUnavailable


class AnalysisDataUnavailable(ValueError):
    pass


class AnalysisStepNotFound(ValueError):
    pass


STEPS = {f'{scenario}_T{minute:02}': (scenario, minute)
         for scenario in ('S01', 'S02') for minute in (0, 30, 60)}


def resolve_step_id(step_id: str) -> tuple[str, int]:
    if step_id not in STEPS:
        raise AnalysisStepNotFound('step not found')
    return STEPS[step_id]


def _invalid_geometry(expected_type: str, allow_empty: bool = False) -> str:
    # Every identifier/type here is internal. Values in actual queries are bound.
    empty = '' if allow_empty else 'OR ST_IsEmpty(geom)'
    return f"""geom IS NULL OR ST_SRID(geom)<>32650 OR GeometryType(geom)<>'{expected_type}'
      OR ST_NDims(geom)<>2 OR NOT ST_IsValid(geom) {empty}
      OR EXISTS (SELECT 1 FROM ST_DumpPoints(geom) p
        WHERE ST_X(p.geom)::text IN ('Infinity','-Infinity','NaN')
           OR ST_Y(p.geom)::text IN ('Infinity','-Infinity','NaN'))"""


def _validate_sources(connection, params):
    for table, shape, count in (('buildings', 'POLYGON', 200), ('roads', 'LINESTRING', 32)):
        row = connection.execute(
            f'SELECT count(*),bool_or({_invalid_geometry(shape)}) FROM flood.{table} WHERE dataset_id=%(dataset_id)s', params
        ).fetchone()
        if row[0] != count or row[1]:
            raise AnalysisDataUnavailable('analysis data unavailable')
    row = connection.execute(
        f"""SELECT count(*),bool_or({_invalid_geometry('MULTIPOLYGON', allow_empty=True)} OR threshold_m IS NULL OR threshold_m<>0.1)
        FROM flood.flood_extents WHERE scenario_id=%(scenario_id)s AND time_min=%(time_min)s""", params
    ).fetchone()
    if row[0] != 1 or row[1]:
        raise AnalysisDataUnavailable('analysis data unavailable')


@contextmanager
def analysis_snapshot(connection: psycopg.Connection, step_id: str):
    scenario_id, minute = resolve_step_id(step_id)
    params = dict(scenario_id=scenario_id, time_min=minute, dataset_id='teaching-v1')
    try:
        with connection.transaction():
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            catalog = read_catalog_snapshot(connection)
            _validate_sources(connection, params)
            identity = {key: catalog[key] for key in ('dataset_id', 'generation_id', 'model_type', 'analysis_srid', 'threshold_m')}
            yield dict(step_id=step_id, **identity), params
    except (ScenarioCatalogUnavailable, psycopg.errors.UndefinedTable,
            psycopg.errors.UndefinedColumn, psycopg.errors.InvalidSchemaName):
        raise AnalysisDataUnavailable('analysis data unavailable') from None


def read_summary(connection: psycopg.Connection, step_id: str) -> dict:
    with analysis_snapshot(connection, step_id) as (identity, params):
        area, buildings, length = connection.execute(INPUTS_SQL + WET_SQL + SUMMARY_SQL, params).fetchone()
        if any(value is None or not math.isfinite(value) or value < 0 for value in (area, buildings, length)):
            raise AnalysisDataUnavailable('analysis data unavailable')
        return dict(**identity, flooded_area_m2=float(area), affected_buildings=int(buildings), flooded_road_length_m=float(length))


def read_buildings(connection: psycopg.Connection, step_id: str, limit: int = 200) -> dict:
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('invalid limit')
    with analysis_snapshot(connection, step_id) as (identity, params):
        rows = connection.execute(INPUTS_SQL + WET_SQL + BUILDINGS_SQL, dict(**params, limit=limit)).fetchall()
        if not rows or any(row[5] != 200 or type(row[3]) is not bool for row in rows):
            raise AnalysisDataUnavailable('analysis data unavailable')
        features = [dict(type='Feature', id=row[0], properties=dict(building_id=row[0], name=row[1], usage=row[2], affected=row[3]), geometry=row[4]) for row in rows]
        metadata = dict(**identity, geometry_srid=4326, limit=limit, returned_count=len(features), total_buildings=rows[0][5], truncated=len(features) < rows[0][5])
        return dict(type='FeatureCollection', features=features, metadata=metadata)
