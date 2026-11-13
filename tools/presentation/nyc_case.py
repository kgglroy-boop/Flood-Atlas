"""Build the Jamaica Bay Ida comparison inputs with QGIS Python and SciPy."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import file_digest
import json
import math
from pathlib import Path
import shutil
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
from osgeo import gdal, ogr, osr
from scipy.io import loadmat
from scipy.spatial import cKDTree
from shapely import make_valid, orient_polygons
from shapely.geometry import MultiLineString, MultiPolygon, box, mapping, shape

BBOX = (-73.847, 40.651, -73.801, 40.684)
ANALYSIS_EPSG = 32618
THRESHOLD_M = 0.10
NODATA = -9999.0
MODEL_DATASET = "https://data.mendeley.com/datasets/3tz69prrwv/1"
MODEL_PAPER = "https://doi.org/10.5194/hess-29-2043-2025"
MODEL_FILES = "https://data.mendeley.com/public-files/datasets/3tz69prrwv/files/"
MODEL_URL = MODEL_FILES + "dafaa643-0e63-437a-80fb-032b2f6ec703/file_downloaded"
MODEL_SHA = "cc29bce6bb28fdbb53bf59e934a98eeec73828ad44078df2c3eeab0edf32e5d6"
MODEL_README = MODEL_FILES + "e58b2f60-e28c-404f-8876-09e3b7ce2b17/file_downloaded"
MODEL_RUNS = {
    "depth02": "Historical Ida reconstruction (13 mm/h parameterized drainage)",
    "depth04": "Eastward storm displacement (counterfactual)",
    "depth05": "Northward storm displacement (counterfactual)",
}
NAIP_BASE = "https://coastalimagery.blob.core.windows.net/digitalcoast/NY_NAIP_2021_9664/"
NAIP_TILES = ("m_4007318_sw_18_060_20211105.tif", "m_4007318_se_18_060_20211001.tif")
WATER_CLASSES = {
    2600: "Lake/Reservoir", 2610: "Pond", 2620: "River", 2630: "Stream",
    2640: "Wetland/Marsh", 2650: "Beach/Shoreline", 2660: "Bay/Ocean",
}
PERMANENT_WATER = frozenset((2600, 2610, 2620, 2630, 2660))
VECTOR_SOURCES = {
    "buildings": {
        "url": "https://services2.arcgis.com/IsDCghZ73NgoYoz5/ArcGIS/rest/services/"
               "NYC_Building_Footprint/FeatureServer/0",
        "label": "NYC Building Footprints", "credit": "New York City Office of Technology and Innovation",
        "fields": "FID,NAME,BIN", "geometry": "Polygon", "min_count": 20_000,
    },
    "roads": {
        "url": "https://services9.arcgis.com/1MbK4fp7GOXPpnXP/ArcGIS/rest/services/"
               "SDE_CSCL_Street_Segments/FeatureServer/5",
        "label": "NYC Citywide Street Centerline", "credit": "New York City Department of City Planning",
        "fields": "OBJECTID,FULL_STREE,ST_LABEL,PHYSICALID", "geometry": "LineString", "min_count": 1_500,
    },
    "water": {
        "url": "https://services6.arcgis.com/yG5s3afENB5iO9fj/ArcGIS/rest/services/"
               "Hydrography_2022/FeatureServer/8",
        "label": "NYC Hydrography (2022)", "credit": "New York City Office of Technology and Innovation",
        "fields": "OBJECTID,NAME,FEATURE_CODE", "geometry": "Polygon", "min_count": 10,
    },
}


def utc_now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def write_json(path, value, *, pretty=False):
    temporary = path.with_name(path.name + ".part")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False,
                  indent=2 if pretty else None, separators=None if pretty else (",", ":"))
        stream.write("\n")
    temporary.replace(path)


def fingerprint(path):
    with path.open("rb") as stream:
        return {"bytes": path.stat().st_size, "sha256": file_digest(stream, "sha256").hexdigest()}


def request_json(url, parameters, *, post=False):
    encoded = urlencode(parameters)
    request = Request(url if post else f"{url}?{encoded}", data=encoded.encode() if post else None,
                      headers={"User-Agent": "urban-flood-webgis/nyc-ida"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:
                result = json.load(response)
            if "error" in result:
                raise ValueError(f"{url}: {result['error']}")
            return result
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def download_model(cache):
    model = cache / "Model_output.mat"
    if not model.exists():
        temporary = model.with_name(model.name + ".part")
        with urlopen(MODEL_URL, timeout=90) as response, temporary.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        if fingerprint(temporary)["sha256"] != MODEL_SHA:
            raise ValueError("Downloaded model SHA-256 differs from the published Mendeley checksum")
        temporary.replace(model)
    if fingerprint(model)["sha256"] != MODEL_SHA:
        raise ValueError(f"Remove the invalid cached model and retry: {model}")
    return model


def download_arcgis(name, source, cache):
    snapshot = cache / f"{name}-arcgis.json"
    if snapshot.exists():
        return json.loads(snapshot.read_text(encoding="utf-8")), snapshot

    url = source["url"]
    query = url + "/query"
    metadata = request_json(url, {"f": "json"})
    result = request_json(query, {
        "where": "1=1", "geometry": ",".join(map(str, BBOX)), "geometryType": "esriGeometryEnvelope",
        "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "returnIdsOnly": "true", "f": "json",
    })
    id_field = result["objectIdFieldName"]
    ids = sorted(set(result["objectIds"]))
    if len(ids) < source["min_count"]:
        raise ValueError(f"{name}: expected at least {source['min_count']} AOI IDs, got {len(ids)}")

    def fetch_batch(batch):
        result = request_json(query, {
            "objectIds": ",".join(map(str, batch)), "outFields": source["fields"],
            "outSR": 4326, "returnGeometry": "true", "f": "geojson",
        }, post=True)
        features = result["features"]
        returned = {feature["properties"][id_field] for feature in features}
        if len(features) != len(returned) or returned != set(batch):
            raise ValueError(f"{name}: ArcGIS returned {len(returned)} unique IDs for a batch of {len(batch)}")
        return features

    batch_size = min(400, metadata["maxRecordCount"])
    with ThreadPoolExecutor(max_workers=6) as pool:
        pages = pool.map(fetch_batch, [ids[i:i + batch_size] for i in range(0, len(ids), batch_size)])
        features = sorted((feature for page in pages for feature in page),
                          key=lambda feature: feature["properties"][id_field])
    last_edit_ms = metadata.get("editingInfo", {}).get("dataLastEditDate")
    payload = {
        "url": query, "bbox": BBOX, "accessed": utc_now(), "id_field": id_field, "features": features,
        "data_last_edit": datetime.fromtimestamp(last_edit_ms / 1000, UTC).isoformat() if last_edit_ms else None,
    }
    write_json(snapshot, payload)
    return payload, snapshot


def geometry_parts(geometry, geometry_type):
    if geometry.is_empty:
        return []
    if geometry.geom_type == geometry_type:
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [part for child in geometry.geoms for part in geometry_parts(child, geometry_type)]
    return []


def vector_properties(name, source, object_id):
    properties = {"id": str(object_id)}
    candidate = source.get("FULL_STREE") or source.get("NAME") or source.get("ST_LABEL") or ""
    clean_name = candidate.strip()
    if clean_name and clean_name.lower() != "unset":
        properties["name"] = clean_name
    if name == "buildings":
        properties["bin"] = source["BIN"]
    elif name == "roads":
        properties["physical_id"] = source["PHYSICALID"]
    else:
        code = source["FEATURE_CODE"]
        properties.update(feature_code=code, water_type=WATER_CLASSES[code], permanent_water=code in PERMANENT_WATER)
    return properties


def prepare_vector(name, source, cache, out):
    payload, snapshot = download_arcgis(name, source, cache)
    if payload["url"] != source["url"] + "/query" or tuple(payload["bbox"]) != BBOX:
        raise ValueError(f"{name}: cached source URL or bbox differs from the current configuration")
    features = []
    repaired = 0
    discarded = 0
    bounds = box(*BBOX)
    geometry_type = source["geometry"]
    multi = MultiPolygon if geometry_type == "Polygon" else MultiLineString
    for item in payload["features"]:
        if not item["geometry"]:
            discarded += 1
            continue
        geometry = shape(item["geometry"])
        if not geometry.is_valid:
            geometry = make_valid(geometry)
            repaired += 1
        parts = geometry_parts(geometry.intersection(bounds), geometry_type)
        if not parts:
            discarded += 1
            continue
        clipped = parts[0] if len(parts) == 1 else multi(parts)
        if not clipped.is_valid:
            raise ValueError(f"{name}: clipping generated an invalid {geometry_type}")
        if geometry_type == "Polygon":
            clipped = orient_polygons(clipped)
        properties = vector_properties(name, item["properties"], item["properties"][payload["id_field"]])
        features.append({"type": "Feature", "properties": properties, "geometry": mapping(clipped)})

    if len(features) < source["min_count"] or len({item["properties"]["id"] for item in features}) != len(features):
        raise ValueError(f"{name}: output is missing expected features or has duplicate IDs")
    path = out / f"{name}.geojson"
    write_json(path, {"type": "FeatureCollection", "features": features})
    qa = {
        "queried_features": len(payload["features"]), "output_features": len(features),
        "repaired_source_geometries": repaired, "discarded_at_clip": discarded,
        "id_field": payload["id_field"], "named_features": sum("name" in feature["properties"] for feature in features),
        "raw_snapshot": {"file": snapshot.name, **fingerprint(snapshot)}, "output": fingerprint(path),
    }
    if name == "water":
        qa["classes"] = dict(Counter(feature["properties"]["water_type"] for feature in features))
    provenance = {key: source[key] for key in ("label", "url", "credit")}
    provenance.update(accessed=payload["accessed"], data_last_edit=payload["data_last_edit"])
    print(f"{name}: {len(features):,} features", flush=True)
    return features, provenance, qa


def srs(epsg):
    result = osr.SpatialReference()
    result.ImportFromEPSG(epsg)
    result.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return result


def mem_grid(width, height, transform, data_type):
    dataset = gdal.GetDriverByName("MEM").Create("", width, height, 1, data_type)
    dataset.SetGeoTransform(transform)
    dataset.SetSpatialRef(srs(ANALYSIS_EPSG))
    return dataset


def rasterize_water(features, width, height, transform, project):
    mem = ogr.GetDriverByName("Memory").CreateDataSource("")
    layer = mem.CreateLayer("permanent_water", srs=srs(ANALYSIS_EPSG), geom_type=ogr.wkbMultiPolygon)
    for feature in features:
        if feature["properties"]["permanent_water"]:
            geometry = ogr.CreateGeometryFromJson(json.dumps(feature["geometry"]))
            geometry.Transform(project)
            record = ogr.Feature(layer.GetLayerDefn())
            record.SetGeometry(ogr.ForceToMultiPolygon(geometry))
            layer.CreateFeature(record)
    if not layer.GetFeatureCount():
        raise ValueError("The hydrography extract contains no permanent-water polygons")
    grid = mem_grid(width, height, transform, gdal.GDT_Byte)
    gdal.RasterizeLayer(grid, [1], layer, burn_values=[1])
    return grid.ReadAsArray().astype(bool)


def prepare_depth(model, water, out):
    geographic = srs(4326)
    projected = srs(ANALYSIS_EPSG)
    project = osr.CoordinateTransformation(geographic, projected)
    inverse = osr.CoordinateTransformation(projected, geographic)
    values = loadmat(model, variable_names=[*MODEL_RUNS, "lon_rho", "lat_rho", "mask_rho"])
    lon, lat, mask = (values[key] for key in ("lon_rho", "lat_rho", "mask_rho"))
    if not all(values[key].shape == lon.shape for key in (*MODEL_RUNS, "lat_rho", "mask_rho")):
        raise ValueError("MAT fields must share the same rho-grid shape")

    # Include several source cells past the cutline so the nearest-centre lookup is defined at the AOI edge.
    west, south, east, north = BBOX
    pad = 0.002
    rows, columns = np.where((west - pad <= lon) & (lon <= east + pad)
                             & (south - pad <= lat) & (lat <= north + pad))
    window = np.s_[rows.min():rows.max() + 1, columns.min():columns.max() + 1]
    centres_lonlat = np.column_stack((lon[window].ravel(), lat[window].ravel()))
    centres = np.array(project.TransformPoints(centres_lonlat))[:, :2]
    source_grid = centres.reshape(*lon[window].shape, 2)
    spacing = [float(np.median(np.linalg.norm(np.diff(source_grid, axis=axis), axis=2))) for axis in (0, 1)]
    resolution = round(math.sqrt(spacing[0] * spacing[1]))

    envelope = project.TransformBounds(*BBOX, 21)
    left, bottom, right, top = tuple(
        (math.floor if i < 2 else math.ceil)(value / resolution) * resolution for i, value in enumerate(envelope)
    )
    width = (right - left) // resolution
    height = (top - bottom) // resolution
    transform = (left, resolution, 0, top, 0, -resolution)
    x, y = np.meshgrid(left + (np.arange(width) + .5) * resolution, top - (np.arange(height) + .5) * resolution)
    target_xy = np.column_stack((x.ravel(), y.ravel()))
    lonlat = np.array(inverse.TransformPoints(target_xy))
    inside = ((west <= lonlat[:, 0]) & (lonlat[:, 0] <= east)
              & (south <= lonlat[:, 1]) & (lonlat[:, 1] <= north)).reshape(height, width)
    distance, nearest = cKDTree(centres).query(target_xy)
    if distance.max() > 1.5 * resolution:
        raise ValueError("The selected rho grid fails to cover the projected AOI")
    active = mask[window].ravel()[nearest].reshape(height, width) == 1
    permanent_water = rasterize_water(water, width, height, transform, project)
    eligible = inside & active & ~permanent_water

    qa = {
        "source_array_shape": list(lon.shape), "rho_median_spacing_m_by_axis": spacing,
        "output_spacing_m": resolution, "size": [width, height], "geotransform": transform,
        "projected_bounds": [left, bottom, right, top], "maximum_nearest_rho_center_distance_m": float(distance.max()),
        "nodata_value": NODATA, "outside_bbox_cells": int(np.count_nonzero(~inside)),
        "inactive_model_cells_in_bbox": int(np.count_nonzero(inside & ~active)),
        "permanent_water_cells_removed": int(np.count_nonzero(inside & active & permanent_water)),
        "scenarios": {},
    }
    for variable, scenario in MODEL_RUNS.items():
        depth = values[variable][window].ravel()[nearest].reshape(height, width)
        valid = eligible & np.isfinite(depth) & (depth >= 0)
        data = np.where(valid, depth, NODATA).astype(np.float32)
        inundated = valid & (data > THRESHOLD_M)
        if not np.any(inundated) or not np.any(valid & ~inundated):
            raise ValueError(f"{variable}: expected both above- and below-threshold cells")
        raster = mem_grid(width, height, transform, gdal.GDT_Float32)
        raster.SetMetadata({"AREA_OR_POINT": "Area", "MODEL_VARIABLE": variable, "MODEL_CITATION": MODEL_PAPER})
        band = raster.GetRasterBand(1)
        band.SetNoDataValue(NODATA)
        band.SetUnitType("m")
        band.SetDescription("Peak modeled water depth above ground")
        band.WriteArray(data)
        output = out / f"{variable}.tif"
        gdal.Translate(str(output), raster, creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "PREDICTOR=3"]).Close()
        qa["scenarios"][variable] = {
            "description": scenario, "output": fingerprint(output), "valid_cells": int(valid.sum()),
            "invalid_source_depth_cells": int(np.count_nonzero(eligible & ~valid)),
            "nodata_cells": int(np.count_nonzero(~valid)), "cells_above_threshold": int(inundated.sum()),
            "grid_area_above_threshold_m2": int(inundated.sum()) * resolution ** 2,
            "valid_depth_range_m": [float(data[valid].min()), float(data[valid].max())],
        }
        print(f"{variable}: {width} x {height} at {resolution} m, {inundated.sum():,} cells > {THRESHOLD_M} m", flush=True)
    return (left, bottom, right, top), qa


def prepare_imagery(bounds, out):
    tiles = []
    inputs = []
    for name in NAIP_TILES:
        url = NAIP_BASE + name
        with urlopen(Request(url, method="HEAD"), timeout=45) as response:
            headers = response.headers
        dataset = gdal.Open("/vsicurl/" + url)
        tiles.append({
            "url": url, "tile_date": datetime.strptime(name.removesuffix(".tif").split("_")[-1], "%Y%m%d").date().isoformat(),
            "etag": headers.get("ETag"), "last_modified": headers.get("Last-Modified"),
            "content_length": int(headers["Content-Length"]), "content_md5": headers.get("Content-MD5"),
            "source_epsg": int(dataset.GetSpatialRef().GetAuthorityCode(None)),
            "source_pixel_m": dataset.GetGeoTransform()[1],
        })
        inputs.append(dataset)

    vrt = gdal.BuildVRT("", inputs, bandList=[1, 2, 3], addAlpha=True)
    # 1.4 m divides the 35 m depth cell into 25 imagery pixels on the verified source grid.
    width = round((bounds[2] - bounds[0]) / 1.4)
    height = round((bounds[3] - bounds[1]) / 1.4)
    mosaic = gdal.Warp("", vrt, format="MEM", dstSRS=f"EPSG:{ANALYSIS_EPSG}",
                       outputBounds=bounds, width=width, height=height,
                       srcAlpha=True, dstAlpha=True, resampleAlg="bilinear")
    missing = int(np.count_nonzero(mosaic.GetRasterBand(4).ReadAsArray() != 255))
    if missing:
        raise ValueError(f"NAIP tiles leave {missing} imagery pixels without full coverage")
    path = out / "imagery.tif"
    gdal.Translate(str(path), mosaic, bandList=[1, 2, 3],
                   creationOptions=["TILED=YES", "COMPRESS=DEFLATE", "PREDICTOR=2"]).Close()
    qa = {
        "tiles": tiles, "output": fingerprint(path), "size": [width, height], "bands": "RGB",
        "geotransform": mosaic.GetGeoTransform(), "missing_pixels": missing, "resampling": "bilinear",
        "source_verification": "HTTP source ETag/length/MD5 when provided, plus SHA-256 of the local crop",
    }
    print(f"imagery: {width} x {height}, {missing} missing pixels", flush=True)
    return qa


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("data/raw/nyc-ida"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/cases/nyc-ida"))
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.mkdir(parents=True, exist_ok=True)
    gdal.UseExceptions()
    ogr.UseExceptions()
    osr.UseExceptions()
    for key, value in {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_HTTP_CONNECTTIMEOUT": "15",
        "GDAL_HTTP_TIMEOUT": "90", "GDAL_HTTP_MAX_RETRY": "2", "GDAL_PAM_ENABLED": "NO",
    }.items():
        gdal.SetConfigOption(key, value)

    model = download_model(args.cache)
    qa = {}
    sources = [
        {"label": "Published Ida model outputs", "url": MODEL_DATASET, "credit": "Shima Kasaei and Philip Orton",
         "license": "CC BY 4.0", "published": "2025-02-13", "paper": MODEL_PAPER, "readme": MODEL_README,
         "file": {"name": model.name, "url": MODEL_URL, **fingerprint(model)}},
        {"label": "2021 USDA NAIP imagery, New York", "url": NAIP_BASE + "index.html",
         "credit": "USDA Farm Service Agency / NOAA Digital Coast", "acquisition_year": 2021},
    ]
    for name, source in VECTOR_SOURCES.items():
        features, provenance, qa[name] = prepare_vector(name, source, args.cache, args.out)
        sources.append(provenance)
        if name == "water":
            water = features
    bounds, qa["depth"] = prepare_depth(model, water, args.out)
    qa["imagery"] = prepare_imagery(bounds, args.out)
    write_json(args.out / "source.json", {
        "case_id": "nyc-ida", "prepared": utc_now(), "bbox": BBOX, "analysis_crs": f"EPSG:{ANALYSIS_EPSG}",
        "vector_crs": "EPSG:4326", "depth_unit": "m", "threshold_m": THRESHOLD_M, "threshold_operator": ">",
        "sources": sources,
        "method": {
            "depth": "Nearest native rho-cell centre in projected metre coordinates, without depth interpolation. "
                     "AOI cutline, inactive model cells, nonfinite or negative values and permanent surface water are "
                     "NoData. Valid source depths are retained, including shallow cells near the 0.05 m model minimum.",
            "water": "2022 NYC OTI polygons rasterized by target cell centre. The permanent-water mask includes "
                     "lake/reservoir, pond, river, stream and bay/ocean classes. Wetland/marsh and beach/shoreline "
                     "remain eligible for depth display and analysis.",
            "imagery": "Two 0.6 m NAIP tiles mosaic and bilinear RGB reprojection to the analytical raster extent.",
            "vectors": "ArcGIS queried with the AOI envelope and bounded object-ID batches, then normalized and "
                       "clipped to the WGS84 AOI. IDs are source layer object IDs. Names are the source values when present.",
        },
        "limitations": {
            "depth": "Per-cell model peaks may occur at different times. The study reports about 0.20 m RMSE "
                     "against high-water observations for the calibrated configuration. Sewer effects were parameterized "
                     "as a uniform drainage rate. Parcel and street values represent spatial exposure estimates.",
            "reference_layers": "Imagery and city vector layers have separate source vintages. Buildings and roads "
                                "provide geographic context for exposure estimates.",
        },
        "qa": qa,
    }, pretty=True)


if __name__ == "__main__":
    main()
