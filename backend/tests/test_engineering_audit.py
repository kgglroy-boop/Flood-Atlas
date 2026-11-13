import os
import pytest
from analysis_fixtures import isolated_database
from app.engineering_audit import inventory, gist_experiment, validate_owned_database

pytestmark=pytest.mark.skipif(os.environ.get('RUN_POSTGIS_INTEGRATION')!='1',reason='PostGIS integration opt-in')

def test_inventory_reads_actual_crs_empty_extents_and_three_areas():
    with isolated_database() as db:
        result=inventory(db)
        assert result['status']=='ok'
        assert {k:v['count'] for k,v in result['tables'].items()}=={'study_area':1,'buildings':200,'roads':32,'flood_extents':6}
        assert all(v['srid']==32650 and v['invalid']==0 for v in result['tables'].values())
        assert set(result['building_areas_m2'])=={'B001','B108','B200'}
        assert all(a>0 for a in result['building_areas_m2'].values())
        assert len(result['spatial_indexes'])==4

def test_inventory_does_not_accept_missing_building_as_a_smaller_valid_dataset():
    with isolated_database() as db:
        db.execute("DELETE FROM flood.buildings WHERE building_id='B200'")
        with pytest.raises(ValueError):inventory(db)

def test_owned_database_guard_rejects_prod_and_another_experiment():
    own='test_phase7_'+'a'*32
    assert validate_owned_database(own,own)==own
    for name in ['flood','postgres','test_phase7_'+'b'*32,own+'suffix']:
        with pytest.raises(ValueError):validate_owned_database(name,own)

def test_gist_experiment_preserves_source_index_and_cleans_owned_clone():
    with isolated_database() as db:
        before=db.execute("SELECT indexdef FROM pg_indexes WHERE schemaname='flood' AND indexname='buildings_geom_gist'").fetchone()
        report=gist_experiment(db)
        assert report['owned_database_removed'] is True
        assert len(report['without_index']['measurements'])==5
        assert len(report['with_index']['measurements'])==5
        assert report['without_index']['building_count']==report['with_index']['building_count']
        assert report['without_index']['building_count']>=0
        assert db.execute("SELECT indexdef FROM pg_indexes WHERE schemaname='flood' AND indexname='buildings_geom_gist'").fetchone()==before
        assert db.execute('SELECT count(*) FROM pg_database WHERE datname=%s',(report['temporary_database'],)).fetchone()[0]==0
