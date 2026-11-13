import os
from contextlib import nullcontext
import psycopg
import pytest
from test_health import get
from analysis_fixtures import isolated_database
from app import tiles

@pytest.mark.parametrize('path',['20/0/0','-1/0/0','15/32768/0','15/0/32768','abc/1/1','15/1.0/1','15/1/1?CQL_FILTER=x'])
def test_invalid_tiles_are_rejected_before_database(monkeypatch,path):
    monkeypatch.setattr(tiles,'open_database',lambda:pytest.fail('invalid tile opened DB'))
    # Query belongs after the suffix, not within the y coordinate.
    uri='/api/v1/tiles/buildings/'+(path.replace('?CQL_FILTER=x','.pbf?CQL_FILTER=x') if '?' in path else path+'.pbf')
    assert get(uri).status_code==422

def test_tile_binary_mime_no_store_and_sanitized_errors(monkeypatch):
    monkeypatch.setattr(tiles,'open_database',lambda:nullcontext(object()))
    monkeypatch.setattr(tiles,'read_tile',lambda *_:b'\x1a\x03abc')
    response=get('/api/v1/tiles/buildings/15/27034/13441.pbf')
    assert response.status_code==200 and response.content==b'\x1a\x03abc'
    assert response.headers['content-type']=='application/vnd.mapbox-vector-tile'
    assert response.headers['cache-control']=='no-store'
    for error,detail in [(psycopg.OperationalError('SECRET postgresql://secret'),'database unavailable'),(tiles.TileDataUnavailable('SECRET'),'tile data unavailable')]:
        def fail(*_):raise error
        monkeypatch.setattr(tiles,'read_tile',fail)
        r=get('/api/v1/tiles/buildings/15/27034/13441.pbf')
        assert r.status_code==503 and r.json()=={'detail':detail}

@pytest.mark.skipif(os.environ.get('RUN_POSTGIS_INTEGRATION')!='1',reason='PostGIS opt-in')
def test_actual_postgis_tiles_world_empty_geometry_and_bad_source():
    with isolated_database() as db:
        lon,lat=db.execute("SELECT ST_X(g),ST_Y(g) FROM (SELECT ST_Transform(ST_Centroid(geom),4326) g FROM flood.buildings ORDER BY building_id LIMIT 1) q").fetchone()
        import math
        z=15;x=int((lon+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)
        content=tiles.read_tile(db,z,x,y)
        assert isinstance(content,bytes) and len(content)>0 and not content.startswith(b'{')
        assert isinstance(tiles.read_tile(db,0,0,0),bytes)
        assert tiles.read_tile(db,15,0,0)==b''
        db.execute("DELETE FROM flood.buildings WHERE building_id='B200'")
        with pytest.raises(tiles.TileDataUnavailable):tiles.read_tile(db,15,0,0)
