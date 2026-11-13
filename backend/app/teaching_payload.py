"""Validate a bounded teaching data transport without GIS Python dependencies."""

import math
import re
import struct

FIELDS = {
    'dataset_info': ['dataset_id', 'generation_id', 'model_type', 'contract_version', 'analysis_srid'],
    'study_area': ['area_id', 'dataset_id', 'name', 'geom_wkb_hex'],
    'scenarios': ['scenario_id', 'dataset_id', 'name', 'model_type'],
    'scenario_steps': ['scenario_id', 'time_min', 'step_code', 'raster_relative_path', 'generation_id'],
    'buildings': ['building_id', 'dataset_id', 'name', 'usage', 'geom_wkb_hex'],
    'roads': ['road_id', 'dataset_id', 'name', 'direction', 'geom_wkb_hex'],
    'flood_extents': ['scenario_id', 'time_min', 'wet_pixel_count', 'area_m2', 'threshold_m', 'geom_wkb_hex'],
}
KEYS = {'dataset_info': ['dataset_id'], 'study_area': ['area_id'], 'scenarios': ['scenario_id'],
        'scenario_steps': ['scenario_id', 'time_min'], 'buildings': ['building_id'],
        'roads': ['road_id'], 'flood_extents': ['scenario_id', 'time_min']}
EXPECTED_IDS = {
    'dataset_info': {('teaching-v1',)}, 'study_area': {('A01',)},
    'scenarios': {('S01',), ('S02',)},
    'scenario_steps': {(s, t) for s in ('S01', 'S02') for t in (0, 30, 60)},
    'flood_extents': {(s, t) for s in ('S01', 'S02') for t in (0, 30, 60)},
    'buildings': {(f'B{i:03d}',) for i in range(1, 201)},
    'roads': {(f'RV{i:02d}',) for i in range(21)} | {(f'RH{i:02d}',) for i in range(11)},
}


def geometry_bytes(value: str, expected_type: int, allow_empty: bool = False) -> bytes:
    """Parse ordinary 2D WKB; PostGIS later checks topology and exact asset shape."""
    if not isinstance(value, str) or not 18 <= len(value) <= 2_000_000:
        raise ValueError('Invalid geometry encoding.')
    try:
        data = bytes.fromhex(value)
        position = 0
        def read(fmt, order):
            nonlocal position
            size = struct.calcsize(order + fmt)
            values = struct.unpack_from(order + fmt, data, position)
            position += size
            return values[0] if len(values) == 1 else values
        def walk(required):
            order_flag = read('B', '<')
            if order_flag not in (0, 1):
                raise ValueError('Invalid WKB byte order.')
            order = '<' if order_flag else '>'
            if read('I', order) != required:
                raise ValueError('Unexpected geometry type.')
            count = read('I', order)
            if count > 100000:
                raise ValueError('Geometry is too large.')
            if required == 6:
                return sum(walk(3) for _ in range(count))
            total = 0
            for _ in range(1 if required == 2 else count):
                n = read('I', order) if required == 3 else count
                if n < (4 if required == 3 else 2) or n > 100000:
                    raise ValueError('Invalid geometry vertex count.')
                points = []
                for _ in range(n):
                    x, y = read('dd', order)
                    if not math.isfinite(x) or not math.isfinite(y) or not (500000 <= x <= 502000 and 3400000 <= y <= 3401000):
                        raise ValueError('Geometry lies outside the teaching study area.')
                    points.append((x, y))
                if required == 3 and points[0] != points[-1]:
                    raise ValueError('Polygon ring is not closed.')
                total += n
            return total
        points = walk(expected_type)
        if position != len(data) or (not allow_empty and not points):
            raise ValueError('Empty or trailing geometry content.')
        return data
    except (ValueError, struct.error, OverflowError, IndexError, RecursionError) as error:
        raise ValueError('Invalid teaching geometry.') from error


def payload_rows(payload: dict) -> dict[str, list[dict]]:
    return {'dataset_info': [{key: payload[key] for key in FIELDS['dataset_info']}],
            **{key: payload['steps' if key == 'scenario_steps' else key]
               for key in FIELDS if key != 'dataset_info'}}


def validate_payload(payload: dict) -> dict:
    required = {'contract_version', 'dataset_id', 'generation_id', 'model_type', 'analysis_srid',
                'study_area', 'scenarios', 'steps', 'buildings', 'roads', 'flood_extents'}
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError('Unexpected teaching payload fields.')
    if (payload['dataset_id'], payload['model_type'], payload['contract_version']) != ('teaching-v1', 'synthetic_demo', '1.0'):
        raise ValueError('Unsupported dataset identity.')
    if type(payload['analysis_srid']) is not int or payload['analysis_srid'] != 32650:
        raise ValueError('Teaching data requires metre CRS 32650.')
    if not isinstance(payload['generation_id'], str) or not re.fullmatch('[0-9a-f]{20}', payload['generation_id']):
        raise ValueError('Invalid generation identifier.')
    for table, rows in payload_rows(payload).items():
        if not isinstance(rows, list) or len(rows) != len(EXPECTED_IDS[table]):
            raise ValueError('Unexpected teaching record count.')
        keys = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(FIELDS[table]):
                raise ValueError('Unexpected teaching record fields.')
            for name, value in row.items():
                if name in ('time_min', 'wet_pixel_count', 'analysis_srid'):
                    if type(value) is not int:
                        raise ValueError('Integer data field required.')
                elif name in ('area_m2', 'threshold_m'):
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ValueError('Finite numeric data field required.')
                elif not isinstance(value, str) or not value or len(value) > (2_000_000 if name == 'geom_wkb_hex' else 512):
                    raise ValueError('Invalid text data field.')
            if 'dataset_id' in row and row['dataset_id'] != 'teaching-v1':
                raise ValueError('Foreign dataset record.')
            if 'model_type' in row and row['model_type'] != 'synthetic_demo':
                raise ValueError('Foreign model type.')
            if table == 'scenario_steps':
                if row['generation_id'] != payload['generation_id'] or row['step_code'] != f"T{row['time_min']:02d}":
                    raise ValueError('Invalid step identifiers.')
                expected = f"teaching-v1/{payload['generation_id']}/rasters/depth_{row['scenario_id']}_{row['step_code']}.tif"
                if row['raster_relative_path'] != expected:
                    raise ValueError('Invalid raster relative path.')
            if table == 'roads' and row['direction'] != ('vertical' if row['road_id'].startswith('RV') else 'horizontal'):
                raise ValueError('Road direction mismatch.')
            if table == 'buildings' and row['usage'] != 'demo':
                raise ValueError('Unsupported building use.')
            if table == 'flood_extents':
                if not 0 <= row['wet_pixel_count'] <= 80000 or row['area_m2'] != row['wet_pixel_count'] * 25 or row['threshold_m'] != .1:
                    raise ValueError('Invalid inundation area or threshold.')
                if row['time_min'] == 0 and row['wet_pixel_count'] != 0:
                    raise ValueError('Initial teaching step must be dry.')
            if 'geom_wkb_hex' in row:
                geometry_bytes(row['geom_wkb_hex'], {'study_area': 6, 'buildings': 3, 'roads': 2, 'flood_extents': 6}[table], table == 'flood_extents')
            keys.append(tuple(row[k] for k in KEYS[table]))
        if len(set(keys)) != len(keys) or set(keys) != EXPECTED_IDS[table]:
            raise ValueError('Duplicate or unknown teaching record identifiers.')
    return payload
