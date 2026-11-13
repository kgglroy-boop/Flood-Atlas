import copy
import os
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
import pytest

from teaching_fixtures import valid_payload, polygon
from app.teaching_store import import_dataset, verify_database

pytestmark = pytest.mark.skipif(os.environ.get('RUN_POSTGIS_INTEGRATION') != '1',
                                reason='Explicit PostGIS integration opt-in required')
MIGRATION = Path('/app/migrations/010_teaching_data.sql')


@pytest.fixture
def database():
    settings = dict(host=os.environ.get('PGHOST', 'db'), port=int(os.environ.get('PGPORT', 5432)),
                    user=os.environ['POSTGRES_USER'], password=os.environ['POSTGRES_PASSWORD'])
    name = 'test_phase2_' + uuid.uuid4().hex
    with psycopg.connect(**settings, dbname='postgres', autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with psycopg.connect(**settings, dbname=name, autocommit=True) as conn:
            conn.execute('CREATE EXTENSION postgis')
            yield conn
    finally:
        assert name.startswith('test_phase2_') and len(name) == len('test_phase2_') + 32
        with psycopg.connect(**settings, dbname='postgres', autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


def test_real_import_repeat_empty_gist_and_unicode(database):
    payload = valid_payload()
    payload['buildings'][0]['name'] = "教学建筑 O'Brien"
    first = import_dataset(database, payload, MIGRATION)
    assert first['counts'] == {'dataset_info': 1, 'study_area': 1, 'scenarios': 2,
                               'scenario_steps': 6, 'buildings': 200, 'roads': 32, 'flood_extents': 6}
    assert import_dataset(database, payload, MIGRATION) == first
    assert verify_database(database, payload) == first
    assert database.execute('SELECT count(*) FROM flood.flood_extents WHERE public.ST_IsEmpty(geom)').fetchone()[0] == 2
    assert database.execute("SELECT count(*) FROM pg_indexes WHERE schemaname='flood' AND indexdef LIKE '%USING gist%'").fetchone()[0] == 4
    assert database.execute("SELECT name FROM flood.buildings WHERE building_id='B001'").fetchone()[0] == "教学建筑 O'Brien"


def test_unknown_row_and_unknown_structure_survive(database):
    payload = valid_payload()
    import_dataset(database, payload, MIGRATION)
    database.execute("INSERT INTO flood.buildings SELECT 'OWNER_EXTRA', dataset_id, name, usage, geom FROM flood.buildings LIMIT 1")
    with pytest.raises(ValueError):
        import_dataset(database, payload, MIGRATION)
    assert database.execute('SELECT count(*) FROM flood.buildings').fetchone()[0] == 201
    database.execute('ALTER TABLE flood.roads ADD COLUMN owner_note text')
    with pytest.raises(ValueError):
        import_dataset(database, payload, MIGRATION)
    assert database.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='flood' AND column_name='owner_note'").fetchone()[0] == 1


def test_mid_insert_failure_rolls_back_previous_dataset(database):
    payload = valid_payload()
    import_dataset(database, payload, MIGRATION)
    database.execute("ALTER TABLE flood.buildings ADD CONSTRAINT test_mid_insert CHECK (name <> 'force-failure')")
    changed = copy.deepcopy(payload)
    changed['buildings'][-1]['name'] = 'force-failure'
    with pytest.raises(psycopg.Error):
        import_dataset(database, changed, MIGRATION)
    assert verify_database(database, payload)['counts']['buildings'] == 200


def test_invalid_geometry_cannot_replace_data(database):
    payload = valid_payload()
    import_dataset(database, payload, MIGRATION)
    wrong = copy.deepcopy(payload)
    wrong['buildings'][0]['geom_wkb_hex'] = polygon(500000, 3400000, 500001, 3400001).hex()
    with pytest.raises(ValueError):
        import_dataset(database, wrong, MIGRATION)
    assert verify_database(database, payload)['counts']['buildings'] == 200


@pytest.mark.parametrize('change', [
    'ALTER TABLE flood.buildings DROP CONSTRAINT buildings_valid; '
    'ALTER TABLE flood.buildings ADD CONSTRAINT buildings_valid CHECK (true)',
    'DROP INDEX flood.roads_geom_gist; '
    'CREATE INDEX roads_geom_gist ON flood.buildings USING gist(geom)',
])
def test_same_name_changed_schema_is_refused_without_replacing_data(database, change):
    payload = valid_payload()
    import_dataset(database, payload, MIGRATION)
    database.execute(change)
    for operation in (verify_database, lambda conn, data: import_dataset(conn, data, MIGRATION)):
        with pytest.raises(ValueError, match='constraints|indexes'):
            operation(database, payload)
    assert database.execute('SELECT count(*) FROM flood.buildings').fetchone()[0] == 200
