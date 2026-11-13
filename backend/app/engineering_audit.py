"""Read-only inventory and explicitly isolated engineering experiments."""
import argparse
import json
import os
import re
import uuid
from pathlib import Path
import psycopg
from psycopg import sql
from app.database import open_database
from app.scenarios import read_catalog_snapshot
from app.analysis_store import _invalid_geometry

TABLES=(('study_area','MULTIPOLYGON',1),('buildings','POLYGON',200),('roads','LINESTRING',32),('flood_extents','MULTIPOLYGON',6))

GIST_QUERY="""WITH wet AS(SELECT ST_UnaryUnion(ST_Collect(geom)) geom FROM flood.flood_extents
 WHERE scenario_id=%s AND time_min=%s)
 SELECT count(DISTINCT b.building_id) FROM flood.buildings b CROSS JOIN wet w
 WHERE b.dataset_id=%s AND ST_Intersects(b.geom,w.geom)"""

def validate_owned_database(name,expected):
    if name!=expected or re.fullmatch(r'test_phase7_[a-f0-9]{32}',name) is None:
        raise ValueError('Refusing non-owned database operation')
    return name

def _settings(dbname):
    return dict(host=os.environ.get('PGHOST','db'),port=int(os.environ.get('PGPORT','5432')),
                user=os.environ['POSTGRES_USER'],password=os.environ['POSTGRES_PASSWORD'],dbname=dbname,
                connect_timeout=2,options='-c statement_timeout=2000')

def gist_experiment(source):
    name='test_phase7_'+uuid.uuid4().hex
    created=False
    try:
        with psycopg.connect(**_settings('postgres'),autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)));created=True
        with psycopg.connect(**_settings(name),autocommit=True) as clone:
            clone.execute('CREATE EXTENSION postgis')
            clone.execute(Path('/app/migrations/010_teaching_data.sql').read_text(),prepare=False)
            with source.transaction():
                source.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                generation=read_catalog_snapshot(source)['generation_id']
                for table in ('dataset_info','study_area','scenarios','scenario_steps','buildings','roads','flood_extents'):
                    rows=source.execute(sql.SQL('SELECT * FROM flood.{}').format(sql.Identifier(table))).fetchall()
                    if not rows:raise ValueError('Missing source table')
                    statement=sql.SQL('INSERT INTO flood.{} VALUES ({})').format(sql.Identifier(table),sql.SQL(',').join(sql.Placeholder() for _ in rows[0]))
                    with clone.cursor() as cursor:cursor.executemany(statement,rows)
            clone.execute('ANALYZE flood.buildings');clone.execute('ANALYZE flood.flood_extents')
            def measure():
                with clone.transaction():
                    clone.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    count=clone.execute(GIST_QUERY,('S02',60,'teaching-v1')).fetchone()[0]
                    plans=[clone.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+GIST_QUERY,('S02',60,'teaching-v1')).fetchone()[0] for _ in range(5)]
                return dict(building_count=count,measurements=plans,execution_times_ms=[p[0]['Execution Time'] for p in plans])
            clone.execute('DROP INDEX flood.buildings_geom_gist')
            without=measure()
            clone.execute('CREATE INDEX buildings_geom_gist ON flood.buildings USING gist(geom)')
            with_index=measure()
            if without['building_count']!=with_index['building_count']:raise ValueError('Index changed results')
            result=dict(status='ok',temporary_database=name,generation_id=generation,buildings=200,
                        query='Bound S02_T60 merged-extent building intersection; optimizer defaults unchanged.',
                        without_index=without,with_index=with_index)
    finally:
        if created:
            validate_owned_database(name,name)
            with psycopg.connect(**_settings('postgres'),autocommit=True) as admin:
                admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
    result['owned_database_removed']=True
    return result

def inventory(connection):
    with connection.transaction():
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        catalog=read_catalog_snapshot(connection)
        tables={}
        for name,shape,expected in TABLES:
            row=connection.execute(sql.SQL('SELECT count(*),min(ST_SRID(geom)),ST_Extent(geom)::text,count(*) FILTER(WHERE '+_invalid_geometry(shape,name=='flood_extents')+') FROM flood.{}').format(sql.Identifier(name))).fetchone()
            if row[0]!=expected or row[1]!=32650 or row[3]:raise ValueError('spatial inventory unavailable')
            tables[name]=dict(count=row[0],srid=row[1],extent=row[2],invalid=row[3])
        areas=dict(connection.execute("SELECT building_id,ST_Area(geom) FROM flood.buildings WHERE building_id=ANY(%s) ORDER BY building_id",(['B001','B108','B200'],)).fetchall())
        if len(areas)!=3:raise ValueError('building samples unavailable')
        indexes=connection.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='flood' AND indexdef LIKE '%%USING gist%%' ORDER BY indexname").fetchall()
        role=connection.execute('SELECT rolname,rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user').fetchone()
        return dict(status='ok',generation_id=catalog['generation_id'],analysis_srid=32650,tables=tables,
                    building_areas_m2=areas,spatial_indexes=[dict(table=r[0],name=r[1],definition=r[2]) for r in indexes],
                    database_role=dict(name=role[0],superuser=role[1],create_database=role[2],create_role=role[3]),
                    limitation='Local teaching only; runtime role is not separated from administrative maintenance.')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--gist-experiment',action='store_true');args=parser.parse_args()
    try:
        with open_database() as connection:print(json.dumps(gist_experiment(connection) if args.gist_experiment else inventory(connection),ensure_ascii=False))
    except Exception:
        raise SystemExit('Engineering inventory unavailable; no raw diagnostic emitted.') from None

if __name__=='__main__':main()
