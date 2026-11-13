"""Disposable phase5 DB and independent, hand-computable geometry inputs."""
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql

from app.teaching_store import import_dataset
from teaching_fixtures import valid_payload


@contextmanager
def isolated_database():
    settings = dict(host=os.environ.get('PGHOST', 'db'), port=int(os.environ.get('PGPORT', '5432')),
                    user=os.environ['POSTGRES_USER'], password=os.environ['POSTGRES_PASSWORD'])
    name = 'test_phase5_' + uuid.uuid4().hex
    with psycopg.connect(**settings, dbname='postgres', autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with psycopg.connect(**settings, dbname=name, autocommit=True) as connection:
            connection.execute('CREATE EXTENSION postgis')
            import_dataset(connection, valid_payload(), Path('/app/migrations/010_teaching_data.sql'))
            yield connection
    finally:
        assert name.startswith('test_phase5_') and len(name) == 44
        with psycopg.connect(**settings, dbname='postgres', autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


MICRO_INPUTS_SQL = """
WITH extent_parts(geom) AS (
 SELECT ST_Translate(ST_GeomFromText(wkt,32650),500000,3400000) FROM (VALUES
 ('POLYGON((0 0,10 0,10 10,0 10,0 0))'),
 ('POLYGON((5 0,15 0,15 10,5 10,5 0))'),
 ('POLYGON((0 0,10 0,10 10,0 10,0 0))')) AS v(wkt)
), selected_buildings(building_id,name,usage,geom) AS (
 SELECT id,id,'demo',ST_Translate(ST_MakeEnvelope(x0,y0,x1,y1,32650),500000,3400000)
 FROM (VALUES ('B001',4,2,11,4),('B002',15,2,17,4),('B003',15,10,17,12),('B004',20,20,22,22)) AS v(id,x0,y0,x1,y1)
), selected_roads(road_id,geom) AS (
 SELECT id,ST_Translate(ST_GeomFromText(wkt,32650),500000,3400000) FROM (VALUES
 ('R1','LINESTRING(-5 5,20 5)'),('R2','LINESTRING(-5 0,20 0)'),('R3','LINESTRING(15 10,20 15)')) AS v(id,wkt)
)
"""
