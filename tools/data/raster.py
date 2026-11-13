"""GeoTIFF persistence and exact cell-boundary inundation polygons."""

from pathlib import Path

import numpy as np
from osgeo import gdal, ogr

from .contract import spatial_reference
from .generation import wet_mask


def write_depth(path: Path, depth: np.ndarray, contract: dict) -> None:
    ds = gdal.GetDriverByName('GTiff').Create(str(path), contract['width'], contract['height'], 1,
                                           gdal.GDT_Float32,
                                           ['TILED=YES', 'COMPRESS=DEFLATE', 'PREDICTOR=3'])
    ds.SetGeoTransform(contract['geotransform'])
    ds.SetProjection(spatial_reference().ExportToWkt())
    ds.SetMetadata({'model_type': 'synthetic_demo', 'dataset_id': 'teaching-v1',
                    'provenance': 'Deterministic project script; no real flood observations',
                    'threshold_m': str(contract['threshold_m']),
                    'threshold_stored_float32': repr(float(np.float32(contract['threshold_m'])))})
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(contract['nodata'])
    band.SetUnitType('m')
    band.WriteArray(depth)
    band.FlushCache()
    band = None
    ds.Close()


def polygonize_wet(depth: np.ndarray, contract: dict) -> ogr.Geometry:
    mask = wet_mask(depth, contract['nodata'], contract['threshold_m']).astype(np.uint8)
    multi = ogr.Geometry(ogr.wkbMultiPolygon)
    multi.AssignSpatialReference(spatial_reference())
    if not mask.any():
        return multi
    raster = gdal.GetDriverByName('MEM').Create('', mask.shape[1], mask.shape[0], 1, gdal.GDT_Byte)
    raster.SetGeoTransform(contract['geotransform'])
    raster.SetProjection(spatial_reference().ExportToWkt())
    raster.GetRasterBand(1).WriteArray(mask)
    vector = ogr.GetDriverByName('MEM').CreateDataSource('')
    layer = vector.CreateLayer('wet', spatial_reference(), ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn('wet', ogr.OFTInteger))
    # The wet band is also the validity mask, so zeros never become polygons.
    gdal.Polygonize(raster.GetRasterBand(1), raster.GetRasterBand(1), layer, 0, [])
    for feature in layer:
        multi.AddGeometry(feature.GetGeometryRef())
    merged = multi.UnionCascaded()
    result = ogr.ForceToMultiPolygon(merged)
    result.AssignSpatialReference(spatial_reference())
    if not result.IsValid():
        raise ValueError('Polygonized inundation geometry is invalid.')
    layer, vector = None, None
    raster.Close()
    return result.Normalize()
