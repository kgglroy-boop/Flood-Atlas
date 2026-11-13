"""Decode WMS output and compare visible pixels with the persisted depth grid."""

import argparse
import json
from pathlib import Path

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
osr.UseExceptions()


def projected_bbox():
    source, target = osr.SpatialReference(), osr.SpatialReference()
    source.ImportFromEPSG(32650)
    target.ImportFromEPSG(3857)
    source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(source, target)
    points = [transform.TransformPoint(x, y) for x in (499990, 502010) for y in (3399990, 3401010)]
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def read_png(path: Path):
    try:
        with path.open('rb') as stream:
            if stream.read(8) != b'\x89PNG\r\n\x1a\n':
                raise ValueError('WMS response is not a PNG image.')
        ds = gdal.OpenEx(str(path), allowed_drivers=['PNG'])
        if ds is None:
            raise ValueError('WMS PNG could not be decoded.')
        return ds
    except (RuntimeError, OSError) as error:
        raise ValueError('WMS PNG could not be decoded.') from error


def png_alpha(ds):
    if ds.RasterCount == 4:
        return ds.GetRasterBand(4).ReadAsArray()
    if ds.RasterCount == 1 and ds.GetRasterBand(1).GetColorTable() is not None:
        band = ds.GetRasterBand(1)
        table = band.GetColorTable()
        alpha = np.array([table.GetColorEntry(i)[3] for i in range(table.GetCount())], dtype=np.uint8)
        return alpha[band.ReadAsArray()]
    raise ValueError('WMS PNG has no explicit alpha channel.')


def validate_wms_png(png_path: Path, reference_path: Path) -> dict:
    png = read_png(Path(png_path))
    reference = gdal.Open(str(reference_path))
    try:
        if (png.RasterXSize, png.RasterYSize) != (reference.RasterXSize, reference.RasterYSize):
            raise ValueError('WMS dimensions differ from native grid.')
        values = reference.GetRasterBand(1).ReadAsArray()
        nodata = reference.GetRasterBand(1).GetNoDataValue()
        expected = np.isfinite(values) & (values != nodata) & (values > np.float32(.1))
        alpha = png_alpha(png)
        if not np.array_equal(alpha > 0, expected):
            raise ValueError('WMS alpha differs from native wet-cell footprint.')
        return {'status':'ok', 'width':png.RasterXSize, 'height':png.RasterYSize,
                'wet_pixel_count':int(expected.sum()), 'transparent_pixel_count':int((alpha == 0).sum())}
    finally:
        reference.Close()
        png.Close()


def validate_projected_png(png_path: Path, expected_empty: bool = False) -> dict:
    png = read_png(png_path)
    try:
        visible = int((png_alpha(png) > 0).sum())
        if (visible == 0) != expected_empty:
            raise ValueError('Projected WMS visibility differs from the expected dry/wet step.')
        return {'status': 'ok', 'width': png.RasterXSize, 'height': png.RasterYSize,
                'visible_pixels': visible}
    finally:
        png.Close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--png', type=Path)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--projected-bbox', action='store_true')
    parser.add_argument('--expect-empty', action='store_true')
    args = parser.parse_args()
    if args.projected_bbox:
        result = {'status':'ok', 'bbox':projected_bbox(), 'srs':'EPSG:3857'}
    elif not args.png:
        parser.error('--png or --projected-bbox is required')
    elif args.reference:
        result = validate_wms_png(args.png, args.reference)
    else:
        result = validate_projected_png(args.png, expected_empty=args.expect_empty)
    print(json.dumps(result))
