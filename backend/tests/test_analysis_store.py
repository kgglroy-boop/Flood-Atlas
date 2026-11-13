import json
import os

import psycopg
import pytest

from analysis_fixtures import isolated_database, MICRO_INPUTS_SQL
from app.analysis_sql import WET_SQL, SUMMARY_SQL, BUILDINGS_SQL
from app.analysis_store import read_summary, read_buildings, resolve_step_id, AnalysisDataUnavailable, AnalysisStepNotFound

pytestmark = pytest.mark.skipif(os.environ.get('RUN_POSTGIS_INTEGRATION') != '1', reason='Explicit PostGIS integration opt-in required')


@pytest.fixture
def database():
    with isolated_database() as connection:
        yield connection


def test_hand_calculated_union_building_contacts_and_road_parts(database):
    row = database.execute(MICRO_INPUTS_SQL + WET_SQL + SUMMARY_SQL).fetchone()
    assert tuple(row) == (150.0, 3, 30.0)
    buildings = database.execute(MICRO_INPUTS_SQL + WET_SQL + BUILDINGS_SQL, {'limit': 500}).fetchall()
    assert [(r[0], r[3]) for r in buildings] == [('B001', True), ('B002', True), ('B003', True), ('B004', False)]
    assert all(r[5] == 4 for r in buildings)
    # B002 touches the edge, but must retain its full polygon in longitude/latitude.
    geometry = buildings[1][4]
    if isinstance(geometry, str): geometry = json.loads(geometry)
    assert geometry['type'] == 'Polygon' and len(geometry['coordinates'][0]) == 5
    reference = database.execute("SELECT ST_AsGeoJSON(ST_Transform(ST_MakeEnvelope(500015,3400002,500017,3400004,32650),4326),9)::jsonb").fetchone()[0]
    assert geometry == reference


def test_six_steps_empty_and_limit_do_not_change_summary(database):
    for scenario in ('S01', 'S02'):
        for minute in (0, 30, 60):
            step_id = f'{scenario}_T{minute:02}'
            summary = read_summary(database, step_id)
            assert summary['step_id'] == step_id and summary['generation_id'] == 'a' * 20
            assert summary['analysis_srid'] == 32650
            collection = read_buildings(database, step_id)
            small = read_buildings(database, step_id, 1)
            assert len(collection['features']) == 200
            assert small['features'] == collection['features'][:1]
            assert small['metadata']['total_buildings'] == 200
            assert small['metadata']['returned_count'] == 1 and small['metadata']['truncated'] is True
            assert collection['metadata']['truncated'] is False
            assert sum(f['properties']['affected'] for f in collection['features']) == summary['affected_buildings']
            assert read_summary(database, step_id) == summary
            if minute == 0:
                assert [summary[k] for k in ('flooded_area_m2','affected_buildings','flooded_road_length_m')] == [0,0,0]
            else:
                assert summary['flooded_area_m2'] == 10000


def test_unknown_step(database):
    with pytest.raises(AnalysisStepNotFound): resolve_step_id('S03_T30')
    with pytest.raises(AnalysisStepNotFound): read_summary(database, 'S03_T30')


@pytest.mark.parametrize('change', ['extent', 'generation', 'table', 'building_count', 'road_count'])
def test_missing_or_mixed_data_is_not_zero(database, change):
    if change == 'extent': database.execute("DELETE FROM flood.flood_extents WHERE scenario_id='S01' AND time_min=0")
    elif change == 'generation': database.execute("UPDATE flood.scenario_steps SET generation_id=%s WHERE scenario_id='S01' AND time_min=0", ('b'*20,))
    elif change == 'table': database.execute('ALTER TABLE flood.roads RENAME TO unavailable_roads')
    elif change == 'building_count': database.execute("DELETE FROM flood.buildings WHERE building_id='B001'")
    else: database.execute("DELETE FROM flood.roads WHERE road_id='RH00'")
    with pytest.raises(AnalysisDataUnavailable): read_summary(database, 'S01_T00')
    with pytest.raises(AnalysisDataUnavailable): read_buildings(database, 'S01_T00')


@pytest.mark.parametrize('change', ['null', 'empty', 'crs', 'invalid', 'infinite'])
def test_bad_building_in_disposable_relation_is_rejected(database, change):
    # Only this disposable DB: preserve migrated relation, make an unconstrained test copy.
    database.execute('ALTER TABLE flood.buildings RENAME TO original_buildings')
    database.execute('CREATE TABLE flood.buildings AS SELECT * FROM flood.original_buildings')
    database.execute('ALTER TABLE flood.buildings ALTER COLUMN geom TYPE geometry USING geom::geometry')
    values = {'null':'NULL', 'empty':"ST_GeomFromText('POLYGON EMPTY',32650)",
              'crs':'ST_SetSRID(geom,4326)',
              'invalid':"ST_GeomFromText('POLYGON((500000 3400000,500010 3400010,500000 3400010,500010 3400000,500000 3400000))',32650)",
              'infinite':"ST_Scale(geom,'Infinity'::double precision,1)"}
    database.execute("UPDATE flood.buildings SET geom=" + values[change] + " WHERE building_id='B001'")
    with pytest.raises(AnalysisDataUnavailable): read_summary(database, 'S01_T30')


def test_extent_null_or_wrong_threshold_is_rejected(database):
    database.execute('ALTER TABLE flood.flood_extents RENAME TO original_extents')
    database.execute('CREATE TABLE flood.flood_extents AS SELECT * FROM flood.original_extents')
    database.execute("UPDATE flood.flood_extents SET geom=NULL WHERE scenario_id='S01' AND time_min=0")
    with pytest.raises(AnalysisDataUnavailable): read_summary(database,'S01_T00')
    database.execute("UPDATE flood.flood_extents SET threshold_m=0.2 WHERE scenario_id='S02' AND time_min=0")
    with pytest.raises(AnalysisDataUnavailable): read_summary(database,'S02_T00')


def test_real_transaction_is_read_only_and_set_once(database):
    class Probe:
        sets = 0
        def transaction(self): return database.transaction()
        def execute(self, query, params=None):
            result = database.execute(query, params)
            if query.startswith('SET TRANSACTION'):
                self.sets += 1
                assert database.execute('SHOW transaction_isolation').fetchone()[0] == 'repeatable read'
                assert database.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
                with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                    with database.transaction(): database.execute('CREATE TABLE forbidden(id int)')
            return result
    probe = Probe()
    read_summary(probe,'S01_T00')
    assert probe.sets == 1
    probe.sets = 0
    read_buildings(probe,'S01_T00')
    assert probe.sets == 1
