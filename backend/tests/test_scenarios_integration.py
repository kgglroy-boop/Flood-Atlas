import os
import uuid

import psycopg
from psycopg import sql
import pytest

from app.scenarios import read_scenario_catalog, ScenarioCatalogUnavailable
from app.teaching_store import import_dataset
from teaching_fixtures import valid_payload
from test_teaching_import import MIGRATION

pytestmark = pytest.mark.skipif(os.environ.get('RUN_POSTGIS_INTEGRATION') != '1', reason='Explicit PostGIS integration opt-in required')


@pytest.fixture
def database():
    settings = dict(host=os.environ.get('PGHOST', 'db'), user=os.environ['POSTGRES_USER'], password=os.environ['POSTGRES_PASSWORD'])
    name = 'test_phase4_' + uuid.uuid4().hex
    with psycopg.connect(**settings, dbname='postgres', autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with psycopg.connect(**settings, dbname=name, autocommit=True) as conn:
            conn.execute('CREATE EXTENSION postgis')
            yield conn
    finally:
        assert name.startswith('test_phase4_') and len(name) == 44
        with psycopg.connect(**settings, dbname='postgres', autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


def test_missing_tables_are_catalog_unavailable(database):
    with pytest.raises(ScenarioCatalogUnavailable): read_scenario_catalog(database)


def test_real_catalog_and_read_only_transaction(database):
    import_dataset(database, valid_payload(), MIGRATION)
    result = read_scenario_catalog(database)
    assert len(result['scenarios']) == 2
    assert [x['time_min'] for x in result['scenarios'][0]['steps']] == [0, 30, 60]
    # Capture the settings during the actual read, not a separate test transaction.
    class ReadOnlyProbe:
        def transaction(self): return database.transaction()
        def execute(self, query, params=None):
            result = database.execute(query, params)
            if query.startswith('SET TRANSACTION'):
                assert database.execute('SHOW transaction_isolation').fetchone()[0] == 'repeatable read'
                assert database.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
                with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                    with database.transaction(): database.execute('CREATE TABLE forbidden(id int)')
            return result
    assert read_scenario_catalog(ReadOnlyProbe()) == result


@pytest.mark.parametrize('change', ['missing', 'generation'])
def test_incomplete_real_catalog_returns_no_partial_data(database, change):
    import_dataset(database, valid_payload(), MIGRATION)
    if change == 'missing':
        database.execute("DELETE FROM flood.flood_extents WHERE scenario_id='S01' AND time_min=0")
        database.execute("DELETE FROM flood.scenario_steps WHERE scenario_id='S01' AND time_min=0")
    else:
        database.execute("UPDATE flood.scenario_steps SET generation_id=%s WHERE scenario_id=%s AND time_min=%s", ('0' * 20, 'S01', 0))
    with pytest.raises(ScenarioCatalogUnavailable): read_scenario_catalog(database)
