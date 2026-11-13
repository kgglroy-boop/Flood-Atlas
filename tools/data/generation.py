"""Pure synthetic geometry and depth functions, with no file or DB writes."""

import numpy as np
from osgeo import ogr

from .contract import spatial_reference


def rectangle(x0: float, y0: float, x1: float, y1: float) -> ogr.Geometry:
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]:
        ring.AddPoint_2D(x, y)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    poly.AssignSpatialReference(spatial_reference())
    return poly


def build_assets(contract: dict) -> dict[str, list[dict]]:
    x0, y0, x1, y1 = contract['study_bounds']
    area = ogr.Geometry(ogr.wkbMultiPolygon)
    area.AddGeometry(rectangle(x0, y0, x1, y1))
    area.AssignSpatialReference(spatial_reference())
    dataset = contract['dataset_id']
    buildings = []
    for j in range(10):
        for i in range(20):
            n = j * 20 + i + 1
            cx, cy = x0 + 50 + 100 * i, y0 + 50 + 100 * j
            buildings.append({'building_id': f'B{n:03d}', 'dataset_id': dataset,
                              'name': f'教学建筑{n:03d}', 'usage': 'demo',
                              'geom': rectangle(cx - 30, cy - 20, cx + 30, cy + 20)})
    roads = []
    for direction, count in [('vertical', 21), ('horizontal', 11)]:
        for i in range(count):
            line = ogr.Geometry(ogr.wkbLineString)
            if direction == 'vertical':
                points, prefix = [(x0 + i * 100, y0), (x0 + i * 100, y1)], 'RV'
            else:
                points, prefix = [(x0, y0 + i * 100), (x1, y0 + i * 100)], 'RH'
            for point in points:
                line.AddPoint_2D(*point)
            line.AssignSpatialReference(spatial_reference())
            roads.append({'road_id': f'{prefix}{i:02d}', 'dataset_id': dataset,
                          'name': f'教学道路{prefix}{i:02d}', 'direction': direction, 'geom': line})
    return {'study_area': [{'area_id': 'A01', 'dataset_id': dataset, 'name': '虚构教学街区', 'geom': area}],
            'buildings': buildings, 'roads': roads}


def wet_mask(depth: np.ndarray, nodata: float, threshold: float) -> np.ndarray:
    depth = np.asarray(depth, dtype=np.float32)
    valid = depth != np.float32(nodata)
    values = depth[valid]
    if not np.all(np.isfinite(values)) or np.any(values < 0) or np.any(values > 2):
        raise ValueError('Valid depth must be finite and within 0..2 metres.')
    return valid & (depth > np.float32(threshold))


def build_depths(contract: dict) -> dict[tuple[str, int], np.ndarray]:
    # Integer millimetres at the centres of the 400x200 valid study pixels.
    x, y = np.meshgrid(2500 + np.arange(400, dtype=np.int64) * 5000,
                       997500 - np.arange(200, dtype=np.int64) * 5000)
    p1 = np.maximum(0, 1200 - np.abs(x - 650000) // 500 - np.abs(y - 450000) // 400)
    p2 = np.maximum(0, 800 - np.abs(x - 1400000) // 600 - np.abs(y - 650000) // 350)
    base = np.maximum(p1, p2)
    result = {}
    for scenario in contract['scenarios']:
        for step, scale in zip(contract['steps'], scenario['scale_percent'], strict=True):
            depth = np.full((contract['height'], contract['width']), contract['nodata'], dtype=np.float32)
            depth[2:-2, 2:-2] = np.minimum(2000, base * scale // 100).astype(np.float32) / np.float32(1000)
            wet_mask(depth, contract['nodata'], contract['threshold_m'])
            result[(scenario['scenario_id'], step['time_min'])] = depth
    return result
