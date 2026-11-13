"""Frozen course contract. Changing geography requires a new reviewed version."""

import json
from pathlib import Path

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

EXPECTED = {
    'contract_version': '1.0', 'dataset_id': 'teaching-v1', 'model_type': 'synthetic_demo',
    'analysis_srid': 32650, 'units': 'm',
    'study_bounds': [500000, 3400000, 502000, 3401000],
    'geotransform': [499990, 5, 0, 3401010, 0, -5],
    'width': 404, 'height': 204, 'nodata': -9999, 'threshold_m': .1,
    'valid_pixels': 80000, 'nodata_pixels': 2416,
    'scenarios': [
        {'scenario_id': 'S01', 'name': '教学情景A', 'scale_percent': [0, 50, 100]},
        {'scenario_id': 'S02', 'name': '教学情景B', 'scale_percent': [0, 75, 150]},
    ],
    'steps': [{'step_code': f'T{t:02d}', 'time_min': t} for t in (0, 30, 60)],
}


def load_contract(path: Path) -> dict:
    contract = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if contract != EXPECTED:
        raise ValueError('Data contract differs from approved teaching-v1 contract.')
    return contract


def spatial_reference(srid: int = 32650) -> osr.SpatialReference:
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(srid)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs
