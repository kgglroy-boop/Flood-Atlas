"""Reopen persisted files; independently compare pixels, geometry and transport."""

import hashlib
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr

from .contract import spatial_reference
from .generation import build_depths, wet_mask
from .integrity import canonical, file_sha, read_json, safe_child
from .vector import read_geopackage, transport_rows, TYPES


def _rasterize_geometry(geom, contract):
    ds = gdal.GetDriverByName('MEM').Create('', contract['width'], contract['height'], 1, gdal.GDT_Byte)
    ds.SetGeoTransform(contract['geotransform'])
    ds.SetProjection(spatial_reference().ExportToWkt())
    source = ogr.GetDriverByName('MEM').CreateDataSource('')
    layer = source.CreateLayer('wet', spatial_reference(), ogr.wkbMultiPolygon)
    if not geom.IsEmpty():
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(geom)
        layer.CreateFeature(feature)
        feature = None
        gdal.RasterizeLayer(ds, [1], layer, burn_values=[1])
    result = ds.ReadAsArray().astype(bool)
    layer, source = None, None
    ds.Close()
    return result


def inspect_dataset(dataset_dir: Path, contract: dict) -> dict:
    assets = read_geopackage(dataset_dir / 'teaching.gpkg')
    counts = {key: len(rows) for key, rows in assets.items()}
    if counts != {'study_area': 1, 'buildings': 200, 'roads': 32, 'flood_extents': 6}:
        raise ValueError('Unexpected vector counts.')
    required_ids = {
        'study_area': ('area_id', {'A01'}),
        'buildings': ('building_id', {f'B{i:03d}' for i in range(1, 201)}),
        'roads': ('road_id', {f'RV{i:02d}' for i in range(21)} | {f'RH{i:02d}' for i in range(11)}),
    }
    for layer, rows in assets.items():
        for row in rows:
            g = row['geom']
            if ogr.GT_Flatten(g.GetGeometryType()) != TYPES[layer] or not g.IsValid():
                raise ValueError(f'Invalid geometry in {layer}')
            if layer != 'flood_extents' and (g.IsEmpty() or row['dataset_id'] != 'teaching-v1'):
                raise ValueError('Empty or foreign teaching asset.')
        if layer in required_ids:
            field, expected = required_ids[layer]
            if {r[field] for r in rows} != expected:
                raise ValueError(f'Duplicate or unknown IDs in {layer}')
    if abs(assets['study_area'][0]['geom'].GetArea() - 2_000_000) > .01:
        raise ValueError('Wrong study area.')
    expected_keys = {(s, t) for s in ('S01', 'S02') for t in (0, 30, 60)}
    extents = {(r['scenario_id'], r['time_min']): r for r in assets['flood_extents']}
    if set(extents) != expected_keys:
        raise ValueError('Missing or duplicate inundation step.')
    digest = hashlib.sha256(canonical({'srid': 32650, 'grid': contract['geotransform']}))
    expected_arrays = build_depths(contract)
    reports = []
    raster_paths = {f'depth_{s}_T{t:02d}.tif' for s, t in expected_keys}
    if {p.name for p in (dataset_dir / 'rasters').glob('*.tif')} != raster_paths:
        raise ValueError('Missing or unexpected raster file.')
    for s, t in sorted(expected_keys):
        path = dataset_dir / f'rasters/depth_{s}_T{t:02d}.tif'
        ds = gdal.Open(str(path))
        if ds.RasterCount != 1 or (ds.RasterXSize, ds.RasterYSize) != (404, 204):
            raise ValueError('Wrong raster dimensions or bands.')
        if ds.GetGeoTransform() != tuple(contract['geotransform']):
            raise ValueError('Raster is not on the common grid.')
        if ds.GetSpatialRef().GetAuthorityCode(None) != '32650':
            raise ValueError('Wrong raster CRS.')
        band = ds.GetRasterBand(1)
        if band.DataType != gdal.GDT_Float32 or band.GetUnitType() != 'm' or band.GetNoDataValue() != -9999:
            raise ValueError('Wrong raster type, units, or NoData.')
        structure = ds.GetMetadata('IMAGE_STRUCTURE')
        if structure.get('COMPRESSION') != 'DEFLATE' or structure.get('PREDICTOR') != '3' or band.GetBlockSize()[1] <= 1:
            raise ValueError('Expected tiled compressed floating point GeoTIFF.')
        if ds.GetMetadataItem('model_type') != 'synthetic_demo' or ds.GetMetadataItem('dataset_id') != 'teaching-v1':
            raise ValueError('Raster provenance missing.')
        array = band.ReadAsArray()
        wet = wet_mask(array, -9999, .1)
        if int((array != -9999).sum()) != 80000 or not np.array_equal(array, expected_arrays[(s, t)]):
            raise ValueError('Raster values or validity mask differ from contract.')
        row = extents[(s, t)]
        count = int(wet.sum())
        if (row['wet_pixel_count'] != count or row['area_m2'] != count * 25 or row['threshold_m'] != .1
                or abs(row['geom'].GetArea() - count * 25) > .01):
            raise ValueError('Wet cell area and polygon area disagree.')
        if not np.array_equal(_rasterize_geometry(row['geom'], contract), wet):
            raise ValueError('Polygon footprint does not match persisted depth cells.')
        reports.append({'scenario_id': s, 'time_min': t, 'wet_pixel_count': count,
                        'area_m2': count * 25, 'valid_pixels': 80000, 'nodata_pixels': 2416,
                        'max_depth_m': float(array[array != -9999].max())})
        digest.update(array.astype('<f4').tobytes())
        band = None
        ds.Close()
    for name, rows in assets.items():
        digest.update(canonical({name: sorted(transport_rows(rows), key=canonical)}))
    payload = read_json(dataset_dir / 'import.json')
    for key in ('study_area', 'buildings', 'roads', 'flood_extents'):
        if canonical(sorted(payload[key], key=canonical)) != canonical(sorted(transport_rows(assets[key]), key=canonical)):
            raise ValueError('Transport payload differs from GeoPackage.')
    if (payload['dataset_id'], payload['model_type'], payload['analysis_srid'], payload['contract_version']) != ('teaching-v1', 'synthetic_demo', 32650, '1.0'):
        raise ValueError('Transport contract metadata mismatch.')
    if {(r['scenario_id'], r['time_min']) for r in payload['steps']} != expected_keys or len(payload['steps']) != 6:
        raise ValueError('Transport step combinations mismatch.')
    for row in payload['steps']:
        relative = f"teaching-v1/{payload['generation_id']}/rasters/depth_{row['scenario_id']}_{row['step_code']}.tif"
        if row['raster_relative_path'] != relative or row['step_code'] != f"T{row['time_min']:02d}":
            raise ValueError('Invalid raster relative path or step code.')
    digest.update(canonical({k: payload[k] for k in ('scenarios', 'steps')}))
    return {'status': 'ok', 'counts': counts, 'rasters': reports,
            'analysis_srid': 32650, 'threshold_stored_float32': float(np.float32(.1)),
            'semantic_sha256': digest.hexdigest()}


def validate_dataset(dataset_dir: Path, contract: dict) -> dict:
    dataset_dir = Path(dataset_dir).resolve()
    try:
        manifest = read_json(dataset_dir / 'manifest.json')
        if manifest['contract'] != contract or manifest['generation_id'] != read_json(dataset_dir / 'import.json')['generation_id']:
            raise ValueError('Artifact manifest contract mismatch.')
        expected = {'teaching.gpkg', 'import.json', 'validation-report.json', 'teaching-review.qgz', 'teaching-atlas.png'}
        expected |= {f'rasters/depth_{s}_T{t:02d}.tif' for s in ('S01', 'S02') for t in (0, 30, 60)}
        if set(manifest['files']) != expected:
            raise ValueError('Artifact manifest is incomplete.')
        for relative, sha in manifest['files'].items():
            path = safe_child(dataset_dir, relative)
            if not path.is_file() or file_sha(path) != sha:
                raise ValueError(f'Artifact missing or changed: {relative}')
        report = inspect_dataset(dataset_dir, contract)
        if report['semantic_sha256'] != manifest['semantic_sha256']:
            raise ValueError('Semantic dataset digest mismatch.')
        return report
    except (KeyError, TypeError, FileNotFoundError) as error:
        raise ValueError('Incomplete teaching dataset; existing files were retained.') from error
