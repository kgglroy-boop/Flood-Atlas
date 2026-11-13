"""Store immutable case versions and calculate their exposure in a metric CRS."""
import os

import psycopg2
from psycopg2.extras import execute_values

DDL = """
CREATE SCHEMA IF NOT EXISTS case_v2;
CREATE TABLE IF NOT EXISTS case_v2.features (
    case_id text NOT NULL, version text NOT NULL, kind text NOT NULL,
    id text NOT NULL, name text NOT NULL, address text, lon double precision, lat double precision,
    map_geom geometry(Geometry,3857) NOT NULL,
    PRIMARY KEY (case_id,version,kind,id)
);
CREATE INDEX IF NOT EXISTS case_v2_features_map_gist ON case_v2.features USING gist(map_geom);
CREATE TABLE IF NOT EXISTS case_v2.building_steps (
    case_id text NOT NULL, version text NOT NULL, step_id text NOT NULL, building_id text NOT NULL,
    affected boolean, PRIMARY KEY (case_id,version,step_id,building_id)
);
"""
NATIVE_FEATURES = """
CREATE TEMP TABLE native_features (
    id text, name text, address text, kind text, lon double precision, lat double precision, geom geometry
) ON COMMIT DROP;
CREATE INDEX ON native_features USING gist(geom);
CREATE TEMP TABLE wet_cells (geom geometry) ON COMMIT DROP;
CREATE INDEX ON wet_cells USING gist(geom);
CREATE TEMP TABLE covered_cells (geom geometry) ON COMMIT DROP;
CREATE INDEX ON covered_cells USING gist(geom);
"""
BUILDINGS = """
SELECT f.id, CASE
    WHEN EXISTS (SELECT 1 FROM wet_cells w WHERE w.geom && f.geom AND ST_Relate(w.geom,f.geom,'2********'))
    THEN true
    WHEN EXISTS (SELECT 1 FROM covered_cells c WHERE c.geom && f.geom AND ST_Relate(c.geom,f.geom,'2********'))
    THEN false
    ELSE NULL END
FROM native_features f WHERE f.kind='building'
"""
ROAD_LENGTH = """
SELECT COALESCE(ST_Length(ST_UnaryUnion(ST_Collect(ST_Intersection(f.geom,w.geom)))),0)
FROM native_features f JOIN wet_cells w ON f.geom && w.geom AND ST_Intersects(f.geom,w.geom)
WHERE f.kind='road'
"""


def connect():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "db"), port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "flood"), user=os.environ.get("POSTGRES_USER", "flood"),
        password=os.environ.get("POSTGRES_PASSWORD"), connect_timeout=5, options="-c statement_timeout=120000",
    )


def summaries(features, steps, srid, case_id, version, *, publish, buildings, roads):
    connection = connect()
    try:
        with connection, connection.cursor() as cursor:
            if publish:
                cursor.execute("SELECT pg_advisory_xact_lock(293461)")
                cursor.execute(DDL)
            cursor.execute(NATIVE_FEATURES)
            execute_values(
                cursor, "INSERT INTO native_features VALUES %s",
                [(row.id, row.name, row.address or None, row.kind, row.lon, row.lat, row.wkb, srid) for row in features],
                template="(%s,%s,%s,%s,%s,%s,ST_Transform(ST_GeomFromWKB(%s,4326),%s))", page_size=400,
            )
            cursor.execute("ANALYZE native_features")
            if publish:
                cursor.execute("DELETE FROM case_v2.features WHERE case_id=%s AND version=%s", (case_id, version))
                cursor.execute("DELETE FROM case_v2.building_steps WHERE case_id=%s AND version=%s", (case_id, version))
                cursor.execute("""INSERT INTO case_v2.features
                    SELECT %s,%s,kind,id,name,address,lon,lat,ST_Transform(geom,3857) FROM native_features""",
                    (case_id, version))
            result = []
            for step, area, wet, covered in steps:
                cursor.execute("TRUNCATE wet_cells,covered_cells")
                execute_values(cursor, "INSERT INTO wet_cells VALUES %s", [(shape, srid) for shape in wet],
                               template="(ST_MakeValid(ST_GeomFromWKB(%s,%s)))")
                execute_values(cursor, "INSERT INTO covered_cells VALUES %s", [(shape, srid) for shape in covered],
                               template="(ST_MakeValid(ST_GeomFromWKB(%s,%s)))")
                cursor.execute("ANALYZE wet_cells; ANALYZE covered_cells")
                impacted = []
                if buildings:
                    cursor.execute(BUILDINGS)
                    impacted = cursor.fetchall()
                    if publish:
                        execute_values(cursor, "INSERT INTO case_v2.building_steps VALUES %s",
                                       [(case_id,version,step,bid,hit) for bid,hit in impacted])
                length = None
                if roads:
                    cursor.execute(ROAD_LENGTH)
                    length = round(cursor.fetchone()[0], 2)
                result.append({
                    "flooded_area_m2": round(area, 2),
                    "affected_buildings": sum(hit is True for _, hit in impacted) if buildings else None,
                    "flooded_road_length_m": length,
                })
            return result
    finally:
        connection.close()
