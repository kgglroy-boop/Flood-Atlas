"""Prepare the optional, same-origin atlas assets with QGIS GDAL Python."""
import argparse
import hashlib
import json
import math
from datetime import date
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

SENTINEL_ITEM = "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/S2A_50RMV_20251118_0_L2A"
SENTINEL = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/50/R/MV/2025/11/S2A_50RMV_20251118_0_L2A/"
DEM = ("https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/"
       "Copernicus_DSM_COG_10_N30_00_E117_00_DEM/Copernicus_DSM_COG_10_N30_00_E117_00_DEM.tif")
DEM_WEST = DEM.replace("E117", "E116")
DEM_CREDIT = ("produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and "
              "Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved")
SENTINEL_CREDIT = "Contains modified Copernicus Sentinel data [2025]"
PADDED_UTM = (499960, 3399960, 502040, 3401040)
REFERENCE_FILES = ("sentinel.webp", "hillshade.png")
OPTIONS = {"GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_CONNECTTIMEOUT": "12",
           "GDAL_HTTP_TIMEOUT": "45", "GDAL_HTTP_MAX_RETRY": "2", "CPL_VSIL_CURL_USE_HEAD": "NO",
           "GDAL_PAM_ENABLED": "NO"}


def spatial(epsg):
    result = osr.SpatialReference()
    result.ImportFromEPSG(epsg)
    result.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return result


def corners(bounds):
    x0, y0, x1, y1 = bounds
    return [(x0, y1), (x1, y1), (x1, y0), (x0, y0)]


def output_grid():
    project = osr.CoordinateTransformation(spatial(32650), spatial(3857))
    extent = project.TransformBounds(*PADDED_UTM, 21)
    grid = tuple((math.floor if i < 2 else math.ceil)(v / 12) * 12 for i, v in enumerate(extent))
    geographic = osr.CoordinateTransformation(spatial(3857), spatial(4326))
    coordinates = [geographic.TransformPoint(*p)[:2] for p in corners(grid)]
    restored = [project.TransformPoint(*p) for p in corners(PADDED_UTM)]
    assert all(grid[0] <= x <= grid[2] and grid[1] <= y <= grid[3] for x, y, _ in restored)
    return grid, coordinates


def crop(source_url, destination, bounds, spacing, algorithm, *, local_source=None, alpha=False, nodata=None):
    source = (gdal.Open(str(local_source) if local_source else "/vsicurl/" + source_url)
              if isinstance(source_url, str) else gdal.BuildVRT("", [
                  str(path) for path in local_source] if local_source else ["/vsicurl/" + url for url in source_url]))
    original = {"size": [source.RasterXSize, source.RasterYSize],
                "crs": source.GetSpatialRef().GetAuthorityCode(None),
                "pixel_size_native": list(source.GetGeoTransform()[1:6:4])}
    output = gdal.Warp(str(destination), source, format="GTiff", outputBounds=bounds,
                       dstSRS="EPSG:3857", xRes=spacing, yRes=spacing, resampleAlg=algorithm,
                       errorThreshold=0, dstAlpha=alpha, dstNodata=nodata,
                       creationOptions=["COMPRESS=DEFLATE"])
    output.FlushCache()
    return output, original


def metadata(dataset, path):
    return {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": [dataset.RasterXSize, dataset.RasterYSize], "geotransform": list(dataset.GetGeoTransform())}


def export_roads(gpkg, out):
    source = ogr.Open(str(gpkg), 0)
    if not source:
        raise ValueError("教学 GeoPackage 无法读取")
    roads = source.GetLayerByName("roads")
    if not roads or roads.GetFeatureCount() != 32:
        raise ValueError("预期原始图层有 32 条教学道路")
    native = roads.GetSpatialRef()
    native.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(native, spatial(4326))
    features = []
    for row in roads:
        geom = row.GetGeometryRef().Clone()
        geom.Transform(transform)
        geom.FlattenTo2D()
        line = json.loads(geom.ExportToJson())
        if line["type"] != "LineString":
            raise ValueError("预期单条教学道路中心线")
        features.append({"type": "Feature", "properties": {"road_id": row["road_id"]}, "geometry": line})
    features.sort(key=lambda feature: feature["properties"]["road_id"])
    assert len({feature["properties"]["road_id"] for feature in features}) == 32
    write_json(out / "roads.geojson", {"type": "FeatureCollection", "features": features})


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_reference(cache, out, local_sources):
    grid, coordinates = output_grid()
    sources = lambda name: local_sources / name if local_sources else None
    layers, checks = [], {}
    try:
        tci, tci_native = crop(SENTINEL + "TCI.tif", cache / "sentinel-crop.tif", grid, 12, "bilinear",
                               alpha=True, local_source=sources("TCI.tif"))
        scl, scl_native = crop(SENTINEL + "SCL.tif", cache / "scl-crop.tif", grid, 24, "near",
                               nodata=0, local_source=sources("SCL.tif"))
        values, counts = np.unique(scl.ReadAsArray(), return_counts=True)
        histogram = dict(zip(map(int, values), map(int, counts)))
        obstructed = sum(histogram.get(k, 0) for k in (0, 1, 3, 8, 9, 10, 11))
        alpha_missing = int(np.count_nonzero(tci.GetRasterBand(4).ReadAsArray() != 255))
        checks["sentinel"] = {"item": SENTINEL_ITEM, "observed_utc": "2025-11-18T02:59:32Z",
            "url": SENTINEL + "TCI.tif", "source": tci_native, "scl_url": SENTINEL + "SCL.tif",
            "scl_source": scl_native, "scl_histogram": histogram, "obstructed_pixels": obstructed,
            "alpha_missing_pixels": alpha_missing, "crop": metadata(tci, cache / "sentinel-crop.tif"),
            "scl_crop": metadata(scl, cache / "scl-crop.tif"), "credit": SENTINEL_CREDIT}
        # Exclude cloudy or missing scenes for this small teaching extent.
        if alpha_missing or obstructed / int(counts.sum()) > .05:
            raise ValueError("真彩色裁片缺值或云、阴影、雪等受阻像元超过 5%")
        # Drop the verified opaque alpha, retaining the source colour balance.
        rgb = gdal.Translate("", tci, format="MEM", bandList=[1, 2, 3])
        gdal.Translate(str(out / REFERENCE_FILES[0]), rgb, format="WEBP",
                       creationOptions=["QUALITY=91"]).FlushCache()
        layers.append({"id": "sentinel", "file": REFERENCE_FILES[0], "label": "卫星真彩色",
                       "detail": "Sentinel‑2 L2A · 2025-11-18 · 原始 10 m", "credit": SENTINEL_CREDIT})
    except (RuntimeError, ValueError) as error:
        checks.setdefault("sentinel", {})["rejected"] = str(error)

    try:
        dem, dem_native = crop((DEM_WEST, DEM), cache / "dsm-crop.tif", grid, 24, "bilinear", nodata=-9999,
                               local_source=[sources("DSM-west.tif"), sources("DSM.tif")] if local_sources else None)
        surface = dem.ReadAsArray()
        missing = int(np.count_nonzero((surface == -9999) | ~np.isfinite(surface)))
        checks["hillshade"] = {"urls": [DEM_WEST, DEM], "source_mosaic": dem_native, "release": 2021, "nodata_pixels": missing,
            "crop": metadata(dem, cache / "dsm-crop.tif"), "credit": DEM_CREDIT}
        if missing:
            raise ValueError("地表模型裁片含缺值")
        checks["hillshade"]["elevation_range_m"] = [float(surface.min()), float(surface.max())]
        # Correct the Mercator scale at the small AOI's centre latitude.
        latitude = sum(p[1] for p in coordinates) / 4
        scale = math.cos(math.radians(latitude))
        shade = gdal.DEMProcessing("", dem, "hillshade", format="MEM", azimuth=315, altitude=45,
                                   scale=scale, computeEdges=True)
        tone = np.rint(183 + shade.ReadAsArray().astype(float) * .265).astype("uint8")
        shade.GetRasterBand(1).DeleteNoDataValue()
        shade.GetRasterBand(1).WriteArray(tone)
        gdal.Translate(str(out / REFERENCE_FILES[1]), shade, format="PNG").FlushCache()
        layers.append({"id": "hillshade", "file": REFERENCE_FILES[1], "label": "地表阴影",
                       "detail": "Copernicus GLO‑30 · 约 30 m · 地表高程", "credit": DEM_CREDIT})
    except (RuntimeError, ValueError) as error:
        checks.setdefault("hillshade", {})["rejected"] = str(error)

    # No rejected or stale layer is advertised by the presentation index.
    total = sum((out / layer["file"]).stat().st_size for layer in layers)
    if total > 1_000_000:
        raise ValueError(f"Reference assets exceed 1 MB: {total}")
    write_json(out / "reference.json", {"version": 1, "corners": coordinates, "layers": layers})
    for layer in layers:
        path = out / layer["file"]
        checks[layer["id"]]["display"] = {"bytes": path.stat().st_size,
                                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    write_json(cache / "reference-qa.json", {"accessed": date.today().isoformat(), "gdal": gdal.VersionInfo("RELEASE_NAME"),
        "utm_extent": PADDED_UTM, "web_mercator_extent": grid, "corners_4326": coordinates,
        "display_total_bytes": total, "resampling": {"sentinel": "bilinear, 12 m in EPSG:3857",
        "scl": "nearest, 24 m in EPSG:3857", "dsm": "bilinear, 24 m in EPSG:3857"},
        "hillshade": {"azimuth_deg": 315, "altitude_deg": 45, "mercator_scale": round(math.cos(math.radians(
            sum(p[1] for p in coordinates) / 4)), 8), "tone": "round(183 + 0.265 × hillshade)"},
        "checks": checks})
    print(f"{len(layers)} reference layers, {total} display bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpkg", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("frontend/public/maps/presentation"))
    parser.add_argument("--cache", type=Path, default=Path("data/raw/hydro-reference"))
    parser.add_argument("--local-sources", type=Path, help="Directory containing TCI.tif, SCL.tif, DSM.tif and DSM-west.tif")
    parser.add_argument("--roads-only", action="store_true")
    args = parser.parse_args()
    gdal.UseExceptions()
    ogr.UseExceptions()
    for key, value in OPTIONS.items():
        gdal.SetConfigOption(key, value)
    args.out.mkdir(parents=True, exist_ok=True)
    export_roads(args.gpkg, args.out)
    if not args.roads_only:
        args.cache.mkdir(parents=True, exist_ok=True)
        prepare_reference(args.cache, args.out, args.local_sources)
