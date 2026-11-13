"""Validate depth grids and derive same-origin map images, samples and masks."""
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

from case_contract import DEPTH_CLASSES, InvalidCase, UNIT_FACTORS, is_tiff

MAX_RASTER_CELLS = 16_000_000
MAX_IMAGE_CELLS = 64_000_000
DISPLAY_SIZE = 1280
DISPLAY_LIMIT = 20037508.342789244

gdal.UseExceptions()
ogr.UseExceptions()
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
gdal.SetConfigOption("GDAL_PAM_ENABLED", "NO")
gdal.SetConfigOption("GDAL_CACHEMAX", "128")
gdal.SetConfigOption("GDAL_NUM_THREADS", "1")
osr.SetPROJEnableNetwork(False)


@dataclass(frozen=True)
class Grid:
    width: int
    height: int
    transform: tuple
    srid: int

    @property
    def extent(self):
        x, dx, _, y, _, dy = self.transform
        return x, y + self.height * dy, x + self.width * dx, y

    def memory(self, bands=1, data_type=gdal.GDT_Byte):
        dataset = gdal.GetDriverByName("MEM").Create("", self.width, self.height, bands, data_type)
        dataset.SetGeoTransform(self.transform)
        dataset.SetSpatialRef(reference(self.srid))
        return dataset


def reference(srid):
    spatial = osr.SpatialReference()
    try:
        spatial.ImportFromEPSG(srid)
    except RuntimeError:
        raise InvalidCase("The analysis EPSG code could not be resolved.") from None
    spatial.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return spatial


def tiff(path: Path, max_cells):
    if not path.is_file():
        raise InvalidCase("A required raster is missing.")
    with path.open("rb") as stream:
        if not is_tiff(stream.read(4)):
            raise InvalidCase("Only local GeoTIFF raster files are accepted.")
    try:
        dataset = gdal.OpenEx(str(path), gdal.OF_RASTER | gdal.OF_READONLY, allowed_drivers=["GTiff"])
    except RuntimeError:
        raise InvalidCase("A GeoTIFF could not be read.") from None
    if dataset is None:
        raise InvalidCase("A GeoTIFF could not be read.")
    if not 0 < dataset.RasterXSize * dataset.RasterYSize <= max_cells:
        raise InvalidCase(f"Raster exceeds the {max_cells:,}-cell limit.")
    if dataset.GetSpatialRef() is None or dataset.GetGeoTransform(can_return_null=True) is None:
        raise InvalidCase("A raster is missing its CRS or affine transform.")
    return dataset


def analysis_grid(dataset, requested_srid):
    spatial = dataset.GetSpatialRef()
    spatial.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    spatial.AutoIdentifyEPSG()
    identifier = spatial.GetAuthorityCode(None)
    if not identifier or not identifier.isdecimal():
        raise InvalidCase("Depth GeoTIFFs must declare a projected EPSG CRS in metres.")
    srid = int(identifier)
    if (not spatial.IsProjected() or srid in {3857, 3395} or not math.isclose(spatial.GetLinearUnits(), 1.0)):
        raise InvalidCase("Depth must use a local projected CRS with metre units.")
    if not spatial.IsSame(reference(srid)) or (requested_srid is not None and srid != requested_srid):
        raise InvalidCase("Depth CRS does not match the requested analysis EPSG code.")
    transform = dataset.GetGeoTransform()
    _, dx, skew_x, _, skew_y, dy = transform
    if not all(math.isfinite(value) for value in transform) or not (dx > 0 > dy) or skew_x or skew_y:
        raise InvalidCase("Depth GeoTIFFs must have a north-up, unrotated grid.")
    if dataset.RasterCount != 1:
        raise InvalidCase("Each depth GeoTIFF must have one numeric band.")
    return Grid(dataset.RasterXSize, dataset.RasterYSize, transform, srid)


def display_grid(native):
    source = native.memory()
    try:
        view = gdal.AutoCreateWarpedVRT(source, None, reference(3857).ExportToWkt(), gdal.GRA_NearestNeighbour)
    except RuntimeError:
        raise InvalidCase("Depth bounds cannot be displayed in Web Mercator.") from None
    if view is None:
        raise InvalidCase("Depth bounds cannot be displayed in Web Mercator.")
    grid = Grid(view.RasterXSize, view.RasterYSize, view.GetGeoTransform(), 3857)
    left, bottom, right, top = grid.extent
    if not all(math.isfinite(value) and abs(value) <= DISPLAY_LIMIT for value in grid.extent):
        raise InvalidCase("Depth bounds must fit inside Web Mercator.")
    span_x, span_y = right - left, top - bottom
    if span_x <= 0 or span_y <= 0 or max(span_x, span_y) > 1_000_000:
        raise InvalidCase("Import a local study area no wider than 1,000 km.")
    resolution = max(span_x, span_y) / DISPLAY_SIZE
    width = max(1, round(span_x / resolution))
    height = max(1, round(span_y / resolution))
    return Grid(width, height, (left, span_x / width, 0, top, 0, -span_y / height), 3857)


def geographic_bounds(view):
    convert = osr.CoordinateTransformation(reference(3857), reference(4326))
    left, bottom, right, top = view.extent
    return [list(convert.TransformPoint(left, bottom)[:2]), list(convert.TransformPoint(right, top)[:2])]


def masks_to_wkb(grid, masks):
    """Polygonize covered cells in analysis CRS, including diagonal edge contacts."""
    raster = grid.memory()
    memory = ogr.GetDriverByName("Memory").CreateDataSource("")
    layer = memory.CreateLayer("coverage", srs=reference(grid.srid), geom_type=ogr.wkbPolygon)
    band = raster.GetRasterBand(1)
    results = []
    for mask in masks:
        band.WriteArray(mask.astype(np.uint8))
        gdal.Polygonize(band, band, layer, -1, [], callback=None)
        results.append([bytes(feature.GetGeometryRef().ExportToWkb()) for feature in layer])
        for feature in layer:
            layer.DeleteFeature(feature.GetFID())
    return results


def rasterize_water(grid, geometries):
    mask = grid.memory()
    if not geometries:
        return np.zeros((grid.height, grid.width), dtype=bool)
    spatial = reference(grid.srid)
    convert = osr.CoordinateTransformation(reference(4326), spatial)
    memory = ogr.GetDriverByName("Memory").CreateDataSource("")
    layer = memory.CreateLayer("water", srs=spatial, geom_type=ogr.wkbUnknown)
    for wkb in geometries:
        geometry = ogr.CreateGeometryFromWkb(wkb, reference(4326))
        geometry.Transform(convert)
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(geometry)
        layer.CreateFeature(feature)
    gdal.RasterizeLayer(mask, [1], layer, burn_values=[1])
    return mask.ReadAsArray().astype(bool)


def read_depth(dataset, unit, water):
    band = dataset.GetRasterBand(1)
    if gdal.DataTypeIsComplex(band.DataType):
        raise InvalidCase("Depth pixels must be real numeric values.")
    raw = band.ReadAsArray()
    covered = (band.GetMaskBand().ReadAsArray() != 0) & np.isfinite(raw)
    if np.any(raw[covered] < 0):
        raise InvalidCase("Depth contains negative covered values. Set a NoData value in the GeoTIFF.")
    with np.errstate(over="ignore", invalid="ignore"):
        depth = np.where(covered, raw, np.nan).astype(np.float32) * np.float32(UNIT_FACTORS[unit])
    if np.any(~np.isfinite(depth[covered])):
        raise InvalidCase("Depth contains values beyond the supported float32 range.")
    covered &= ~water
    depth[water] = -1
    if not covered.any():
        raise InvalidCase("A depth step has no covered land cells.")
    return depth, covered


def warp_to_view(source, view, **kwargs):
    return gdal.Warp(
        "", source, format="MEM", dstSRS="EPSG:3857", outputBounds=view.extent,
        width=view.width, height=view.height, multithread=False, warpMemoryLimit=96, **kwargs,
    )


def render_depth(depth, native, view, threshold, path):
    source = native.memory(data_type=gdal.GDT_Float32)
    source.GetRasterBand(1).WriteArray(depth)
    source.GetRasterBand(1).SetNoDataValue(float("nan"))
    warped = warp_to_view(source, view, resampleAlg="near", dstNodata=float("nan"))
    display = warped.ReadAsArray()
    display.astype("<f4", copy=False).tofile(path.with_suffix(".f32"))
    rgba = np.zeros((4, view.height, view.width), dtype=np.uint8)
    lower = np.float32(threshold)
    for upper, color in DEPTH_CLASSES:
        if upper > lower:
            cells = (display > lower) & (display <= np.float32(upper)) & np.isfinite(display)
            rgba[:, cells] = np.asarray(color, dtype=np.uint8)[:, None]
            lower = np.float32(upper)
    dataset = view.memory(bands=4)
    colors = (gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand, gdal.GCI_AlphaBand)
    for index, (channel, color) in enumerate(zip(rgba, colors, strict=True), 1):
        band = dataset.GetRasterBand(index)
        band.SetColorInterpretation(color)
        band.WriteArray(channel)
    gdal.GetDriverByName("PNG").CreateCopy(str(path.with_suffix(".png")), dataset)
    gdal.GetDriverByName("GTiff").CreateCopy(
        str(path.with_suffix(".tif")), dataset, options=["COMPRESS=DEFLATE", "TILED=YES", "ALPHA=YES"],
    )


def render_basemap(path, view, destination):
    source = tiff(path, MAX_IMAGE_CELLS)
    if source.RasterCount not in (1, 3, 4):
        raise InvalidCase("Imagery must be grayscale, RGB, or RGBA GeoTIFF.")
    if any(source.GetRasterBand(i).DataType != gdal.GDT_Byte for i in range(1, source.RasterCount + 1)):
        raise InvalidCase("Imagery GeoTIFF must use 8-bit color bands.")
    # Keep an alpha band for partial source coverage. Opaque gray images can
    # keep their own rendering and use the same footprint as the depth image.
    rgba = warp_to_view(source, view, resampleAlg="bilinear", dstAlpha=True)
    if rgba.RasterCount == 2:
        bands = rgba.ReadAsArray()
        expanded = view.memory(bands=4)
        for index, values in enumerate([bands[0], bands[0], bands[0], bands[1]], 1):
            expanded.GetRasterBand(index).WriteArray(values)
        rgba = expanded
    gdal.GetDriverByName("WEBP").CreateCopy(str(destination), rgba, options=["QUALITY=85"])
