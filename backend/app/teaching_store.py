"""Explicit, bounded and transaction-safe storage for the single teaching dataset."""

import hashlib
import json
from pathlib import Path

import psycopg
from psycopg import sql

from .teaching_payload import FIELDS, KEYS, EXPECTED_IDS, geometry_bytes, payload_rows, validate_payload

TABLES = tuple(FIELDS)
GEOMETRIES = {'study_area': 'MULTIPOLYGON', 'buildings': 'POLYGON',
              'roads': 'LINESTRING', 'flood_extents': 'MULTIPOLYGON'}


def _fields(table):
    return [field if field != 'geom_wkb_hex' else 'geom' for field in FIELDS[table]]


def _schema_signature(connection):
    # Fix deparser qualification independently of the login role's search_path.
    with connection.transaction():
        connection.execute('SET LOCAL search_path TO pg_catalog,public')
        constraints = connection.execute(
            "SELECT t.relname,c.conname,c.contype,pg_get_constraintdef(c.oid),"
            "c.convalidated,c.condeferrable,c.condeferred FROM pg_constraint c "
            "JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
            "WHERE n.nspname='flood'").fetchall()
        indexes = connection.execute(
            "SELECT x.relname,t.relname,pg_get_indexdef(i.indexrelid),i.indisvalid,i.indisready "
            "FROM pg_index i JOIN pg_class x ON x.oid=i.indexrelid "
            "JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
            "WHERE n.nspname='flood' AND x.relname LIKE '%_geom_gist'").fetchall()
    return {'constraints': {f'{t}.{name}': list(values) for t, name, *values in constraints},
            'indexes': {name: list(values) for name, *values in indexes}}


def _guard_schema_definitions(connection):
    expected = json.loads(Path(__file__).with_name('teaching_schema.json').read_text(encoding='utf-8'))
    migration = Path('/app/migrations/010_teaching_data.sql')
    if hashlib.sha256(migration.read_bytes()).hexdigest() != expected['migration_sha256']:
        raise ValueError('Teaching schema contract and migration differ.')
    actual = _schema_signature(connection)
    for kind in ('constraints', 'indexes'):
        if any(actual[kind].get(name) != definition for name, definition in expected[kind].items()):
            raise ValueError(f'Teaching schema {kind} differ; nothing was replaced.')


def _guard_existing(connection):
    actual = {r[0] for r in connection.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='flood' AND c.relkind IN ('r','p','v','m','f')").fetchall()}
    if not actual:
        return
    if actual != set(TABLES):
        raise ValueError('Existing flood schema is not the teaching schema; nothing was replaced.')
    for table in TABLES:
        columns = connection.execute(
            "SELECT column_name,udt_name,is_nullable FROM information_schema.columns "
            "WHERE table_schema='flood' AND table_name=%s ORDER BY ordinal_position", (table,)).fetchall()
        expected = []
        for field in _fields(table):
            data_type = ('geometry' if field == 'geom' else 'int4' if field in ('time_min', 'wet_pixel_count', 'analysis_srid')
                         else 'float8' if field in ('area_m2', 'threshold_m') else 'text')
            expected.append((field, data_type, 'NO'))
        if columns != expected:
            raise ValueError('Existing teaching table structure differs; nothing was replaced.')
        keys = connection.execute(sql.SQL('SELECT {} FROM flood.{}').format(
            sql.SQL(',').join(map(sql.Identifier, KEYS[table])), sql.Identifier(table))).fetchall()
        if not set(keys).issubset(EXPECTED_IDS[table]):
            raise ValueError('Unknown records exist in teaching tables; nothing was replaced.')
    metadata = connection.execute('SELECT dataset_id,model_type,contract_version,analysis_srid FROM flood.dataset_info').fetchall()
    if any(tuple(r) != ('teaching-v1', 'synthetic_demo', '1.0', 32650) for r in metadata):
        raise ValueError('Foreign dataset metadata exists; nothing was replaced.')
    _guard_schema_definitions(connection)
    for table, kind in GEOMETRIES.items():
        info = connection.execute(
            "SELECT type,srid FROM public.geometry_columns WHERE f_table_schema='flood' AND f_table_name=%s", (table,)).fetchone()
        if info != (kind, 32650):
            raise ValueError('Teaching geometry column type or CRS differs.')


def _check_geometries(connection, rows):
    for table in GEOMETRIES:
        for row in rows[table]:
            binary = bytes.fromhex(row['geom_wkb_hex'])
            result = connection.execute(
                'WITH g AS (SELECT public.ST_GeomFromWKB(%s,32650) AS v) '
                'SELECT public.ST_IsValid(v),public.ST_IsEmpty(v),public.GeometryType(v),'
                'public.ST_Area(v),public.ST_CoveredBy(v,public.ST_MakeEnvelope(500000,3400000,502000,3401000,32650)) '
                'FROM g', (binary,)).fetchone()
            valid, empty, kind, area, inside = result
            if not valid or kind != GEOMETRIES[table] or (not empty and not inside):
                raise ValueError('Invalid teaching geometry topology or range.')
            expected_area = (2_000_000 if table == 'study_area' else 2400 if table == 'buildings'
                             else row['area_m2'] if table == 'flood_extents' else 0)
            if abs(area - expected_area) > .01 or (empty and table != 'flood_extents'):
                raise ValueError('Teaching asset geometry area differs.')
            if table == 'flood_extents' and empty != (row['wet_pixel_count'] == 0):
                raise ValueError('Empty inundation geometry differs from count.')


def _current_rows(connection, table):
    expressions = [sql.SQL("public.ST_AsBinary(geom,'NDR')") if f == 'geom_wkb_hex' else sql.Identifier(f)
                   for f in FIELDS[table]]
    raw = connection.execute(sql.SQL('SELECT {} FROM flood.{}').format(
        sql.SQL(',').join(expressions), sql.Identifier(table))).fetchall()
    rows = []
    for values in raw:
        row = dict(zip(FIELDS[table], values, strict=True))
        if 'geom_wkb_hex' in row:
            row['geom_wkb_hex'] = bytes(row['geom_wkb_hex']).hex()
        rows.append(row)
    return rows


def verify_database(connection: psycopg.Connection, payload: dict) -> dict:
    validate_payload(payload)
    _guard_existing(connection)
    expected = payload_rows(payload)
    for table in TABLES:
        actual = _current_rows(connection, table)
        key = lambda row: tuple(row[k] for k in KEYS[table])
        if sorted(actual, key=key) != sorted(expected[table], key=key):
            raise ValueError('Stored teaching content differs from validated payload.')
    areas = connection.execute('SELECT scenario_id,time_min,wet_pixel_count,area_m2,public.ST_Area(geom) '
                               'FROM flood.flood_extents ORDER BY scenario_id,time_min').fetchall()
    for scenario, minute, count, area, geometric_area in areas:
        if abs(area - geometric_area) > .01 or area != count * 25:
            raise ValueError('Stored area does not match raster cell area.')
    return {'status': 'ok', 'dataset_id': 'teaching-v1', 'generation_id': payload['generation_id'],
            'counts': {table: len(rows) for table, rows in expected.items()},
            'steps': [dict(zip(['scenario_id', 'time_min', 'wet_pixel_count', 'area_m2', 'geometry_area_m2'], row, strict=True)) for row in areas]}


def import_dataset(connection: psycopg.Connection, payload: dict, migration_path: Path) -> dict:
    validate_payload(payload)
    rows = payload_rows(payload)
    with connection.transaction():
        _guard_existing(connection)
        _check_geometries(connection, rows)
        connection.execute(migration_path.read_text(encoding='utf-8'))
        for table in ('flood_extents', 'scenario_steps', 'buildings', 'roads', 'study_area', 'scenarios', 'dataset_info'):
            if table in ('flood_extents', 'scenario_steps'):
                connection.execute(sql.SQL('DELETE FROM flood.{} WHERE scenario_id IN (%s,%s)').format(sql.Identifier(table)), ('S01', 'S02'))
            else:
                connection.execute(sql.SQL('DELETE FROM flood.{} WHERE dataset_id=%s').format(sql.Identifier(table)), ('teaching-v1',))
        for table in TABLES:
            placeholders = [sql.SQL('public.ST_GeomFromWKB(%s,32650)') if f == 'geom_wkb_hex' else sql.Placeholder()
                            for f in FIELDS[table]]
            statement = sql.SQL('INSERT INTO flood.{} ({}) VALUES ({})').format(
                sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, _fields(table))), sql.SQL(',').join(placeholders))
            with connection.cursor() as cursor:
                cursor.executemany(statement, [tuple(bytes.fromhex(row[f]) if f == 'geom_wkb_hex' else row[f]
                                                     for f in FIELDS[table]) for row in rows[table]])
        return verify_database(connection, payload)
