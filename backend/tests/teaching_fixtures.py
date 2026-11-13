"""Runtime-only WKB fixture, independent of GDAL and the production generator."""

import struct


def polygon(x0, y0, x1, y1):
    points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return struct.pack('<BIII', 1, 3, 1, len(points)) + b''.join(struct.pack('<dd', *p) for p in points)


def multi(poly=None):
    return struct.pack('<BII', 1, 6, int(poly is not None)) + (poly or b'')


def valid_payload():
    dataset, generation = 'teaching-v1', 'a' * 20
    p = {'contract_version': '1.0', 'dataset_id': dataset, 'generation_id': generation,
         'model_type': 'synthetic_demo', 'analysis_srid': 32650,
         'study_area': [{'area_id': 'A01', 'dataset_id': dataset, 'name': '教学研究区',
                         'geom_wkb_hex': multi(polygon(500000, 3400000, 502000, 3401000)).hex()}],
         'scenarios': [], 'steps': [], 'buildings': [], 'roads': [], 'flood_extents': []}
    for j in range(10):
        for i in range(20):
            n = j * 20 + i + 1
            x, y = 500050 + i * 100, 3400050 + j * 100
            p['buildings'].append({'building_id': f'B{n:03d}', 'dataset_id': dataset,
                'name': f'教学建筑{n:03d}', 'usage': 'demo',
                'geom_wkb_hex': polygon(x - 30, y - 20, x + 30, y + 20).hex()})
    for prefix, count in [('RV', 21), ('RH', 11)]:
        for i in range(count):
            points = ((500000 + i * 100, 3400000), (500000 + i * 100, 3401000)) if prefix == 'RV' else (
                (500000, 3400000 + i * 100), (502000, 3400000 + i * 100))
            wkb = struct.pack('<BII', 1, 2, 2) + b''.join(struct.pack('<dd', *point) for point in points)
            p['roads'].append({'road_id': f'{prefix}{i:02d}', 'dataset_id': dataset,
                'name': f'教学道路{prefix}{i:02d}', 'direction': 'vertical' if prefix == 'RV' else 'horizontal',
                'geom_wkb_hex': wkb.hex()})
    for scenario in ['S01', 'S02']:
        p['scenarios'].append({'scenario_id': scenario, 'dataset_id': dataset,
                              'name': f'教学情景{scenario}', 'model_type': 'synthetic_demo'})
        for minute in [0, 30, 60]:
            p['steps'].append({'scenario_id': scenario, 'time_min': minute, 'step_code': f'T{minute:02d}',
                              'generation_id': generation,
                              'raster_relative_path': f'teaching-v1/{generation}/rasters/depth_{scenario}_T{minute:02d}.tif'})
            p['flood_extents'].append({'scenario_id': scenario, 'time_min': minute,
                'wet_pixel_count': 0 if minute == 0 else 400,
                'area_m2': 0.0 if minute == 0 else 10000.0, 'threshold_m': .1,
                'geom_wkb_hex': multi(None if minute == 0 else polygon(500000, 3400000, 500100, 3400100)).hex()})
    return p
