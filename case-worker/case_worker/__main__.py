"""Local process for previewing and publishing flood cases."""
import argparse
import fcntl
import hashlib
import json
import shutil
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
from osgeo import gdal

from case_archive import write_archive
from case_contract import InvalidCase, JOB_ID, input_paths, validate_metadata
from case_jobs import cases_root, import_root, read_catalog, read_json, set_state, write_json
from .analysis import summaries
from .geoserver import register
from .rasters import (
    MAX_RASTER_CELLS, analysis_grid, display_grid, geographic_bounds, masks_to_wkb, rasterize_water,
    read_depth, reference, render_basemap, render_depth, tiff,
)
from .vectors import load_vector, snapshot_features


def version_of(metadata, files):
    digest = hashlib.sha256(b"flood-case-v2.2\0")
    digest.update(json.dumps(metadata, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())
    for name, path in sorted(files.items()):
        digest.update(name.encode() + b"\0")
        with path.open("rb") as stream:
            digest.update(hashlib.file_digest(stream, "sha256").digest())
    return digest.hexdigest()[:20]


def project_depths(files, steps, requested):
    rasters = [tiff(files[f'depths/{step["id"]}.tif'], MAX_RASTER_CELLS) for step in steps]
    base = rasters[0]
    transform = base.GetGeoTransform()
    for raster in rasters[1:]:
        if (raster.RasterXSize != base.RasterXSize or raster.RasterYSize != base.RasterYSize
            or raster.GetGeoTransform() != transform or not raster.GetSpatialRef().IsSame(base.GetSpatialRef())):
            raise InvalidCase("Depth files must share a grid, extent and source CRS before import.")
    try:
        native = analysis_grid(base, requested)
        return rasters, native
    except InvalidCase:
        if any(raster.RasterCount != 1 for raster in rasters):
            raise InvalidCase("Each depth file must have a single band.") from None
        if requested is None:
            geographic = gdal.AutoCreateWarpedVRT(base, None, reference(4326).ExportToWkt(), gdal.GRA_NearestNeighbour)
            if geographic is None:
                raise InvalidCase("Cannot resolve the study area. Supply a suitable projected metric EPSG code.") from None
            left, dx, _, top, _, dy = geographic.GetGeoTransform()
            right, bottom = left + dx * geographic.RasterXSize, top + dy * geographic.RasterYSize
            zone = lambda lon: min(60, max(1, int((lon + 180) // 6) + 1))
            if not (-80 <= bottom <= top <= 84) or zone(left) != zone(right) or bottom * top < 0:
                raise InvalidCase("The study area crosses a UTM boundary. Supply a suitable projected metric EPSG code.") from None
            requested = (32600 if bottom >= 0 else 32700) + zone(left)
        projected = reference(requested)
        if not projected.IsProjected() or requested in {3857, 3395} or abs(projected.GetLinearUnits()-1)>1e-8:
            raise InvalidCase("Use a local projected CRS with metre units.") from None
        vrt = gdal.AutoCreateWarpedVRT(base, None, projected.ExportToWkt(), gdal.GRA_NearestNeighbour)
        if vrt is None or vrt.RasterXSize * vrt.RasterYSize > MAX_RASTER_CELLS:
            raise InvalidCase("The reprojected depth raster exceeds the supported grid size.") from None
        provisional = analysis_grid(vrt, requested)
        converted = [gdal.Warp("", src, format="MEM", dstSRS=f"EPSG:{requested}",
                               outputBounds=provisional.extent, width=provisional.width, height=provisional.height,
                               resampleAlg="near", outputType=gdal.GDT_Float32, dstNodata=float("nan"))
                     for src in rasters]
        return converted, analysis_grid(converted[0], requested)


def prepare(job, metadata, prefix, folder, *, publishing):
    files = input_paths(job / "inputs", metadata)
    version = version_of(metadata, files)
    rasters, native = project_depths(files, metadata["steps"], metadata["srid"])
    view = display_grid(native)
    bounds = geographic_bounds(view)
    if (job / "reuse.json").exists():
        old = read_json(job / "reuse.json")
        (x0,y0),(x1,y1) = bounds
        (a0,b0),(a1,b1) = old
        shared = max(0,min(x1,a1)-max(x0,a0))*max(0,min(y1,b1)-max(y0,b0))
        if shared < .90*max((x1-x0)*(y1-y0),(a1-a0)*(b1-b0)):
            raise InvalidCase("复用上一版本的地物时，新旧研究范围需基本一致。")
    layers = {}
    for kind, stem in (("building","buildings"),("road","roads"),("water","water"),("area","area")):
        path = files.get(stem + ".geojson") or files.get(stem + ".gpkg")
        layers[kind] = load_vector(path, kind, bounds)
    features = layers["building"] + layers["road"] + layers["water"]
    mask = rasterize_water(native, [feature.wkb for feature in layers["water"] if feature.permanent_water])
    area_mask = rasterize_water(native, [feature.wkb for feature in layers["area"]]) if layers["area"] else None
    folder.mkdir(parents=True, exist_ok=True)
    sampling = folder / "sampling"
    sampling.mkdir(exist_ok=True)
    write_json(sampling / "native.json", {"width": native.width, "height": native.height, "transform": native.transform})
    case = {key:metadata[key] for key in ("id","title","subtitle","description","threshold_m","sources")}
    case.update(version=version, bounds=bounds, analysis_srid=native.srid, basemap=None,
                features=None, snapshot_features=None, steps=[])
    if features:
        write_json(folder / "features.geojson", snapshot_features(features))
        case["snapshot_features"] = prefix + "/features.geojson"
        case["features"] = (
            f'/api/v2/cases/{case["id"]}/{version}/tiles/{{z}}/{{x}}/{{y}}.pbf'
            if publishing else case["snapshot_features"]
        )
    if "imagery.tif" in files:
        render_basemap(files["imagery.tif"], view, folder / "aerial.webp")
        case["basemap"] = prefix + "/aerial.webp"
    metrics = []
    coverage_reports = []
    for dataset, metadata_step in zip(rasters, metadata["steps"], strict=True):
        step_id = metadata_step["id"]
        depth, covered = read_depth(dataset, metadata["unit"], mask)
        if area_mask is not None:
            depth[~area_mask] = np.nan
            covered &= area_mask
        if not covered.any():
            raise InvalidCase("A step has no valid land cells inside the analysis boundary.")
        wet = covered & (depth > np.float32(metadata["threshold_m"]))
        wet_shapes, valid_shapes = masks_to_wkb(native, [wet, covered])
        area = int(wet.sum()) * native.transform[1] * abs(native.transform[5])
        metrics.append((step_id, area, wet_shapes, valid_shapes))
        depth.astype("<f4", copy=False).tofile(sampling / f"{step_id}.f32")
        render_depth(depth, native, view, metadata["threshold_m"], folder / step_id)
        coverage = hashlib.sha256(covered.tobytes()).hexdigest()[:16]
        coverage_reports.append({"id":step_id,"valid_cells":int(covered.sum()),"wet_cells":int(wet.sum())})
        case["steps"].append({**metadata_step,"depth":prefix+f"/{step_id}.png","coverage":coverage,
                              "grid":{"url":prefix+f"/{step_id}.f32","width":view.width,"height":view.height,"extent":view.extent}})
    result = summaries(features, metrics, native.srid, case["id"], version, publish=publishing,
                       buildings=bool(layers["building"]), roads=bool(layers["road"]))
    for step, values in zip(case["steps"], result, strict=True):
        step["summary"] = values
    reports = {"width":native.width,"height":native.height,"analysis_srid":native.srid,
               "cell_size_m":[native.transform[1],abs(native.transform[5])],
               "buildings":len(layers["building"]),"roads":len(layers["road"]),"coverage":coverage_reports,
               "warnings":[name for name,kind in (("缺少建筑图层","building"),("缺少道路图层","road")) if not layers[kind]]}
    return case, files, reports


def preview(job, metadata):
    folder = cases_root() / "previews" / job.name
    case, _, report = prepare(job, metadata, f"/cases/previews/{job.name}", folder, publishing=False)
    set_state(job, "preview", "预检完成，可以核对图层后发布。", case=case, preview=report)


def publish(job, metadata, default=False):
    files = input_paths(job / "inputs", metadata)
    case_id, version = metadata["id"], version_of(metadata, files)
    destination = cases_root() / case_id / version
    set_state(job, "publishing", "正在生成数据库、地图瓦片和案例包。")
    catalog = read_catalog()
    old = next((item for item in catalog["cases"] if item["id"]==case_id and item["version"]==version), None)
    if old and not default:
        set_state(job, "ready", "此版本已经发布。", case=old)
        return old
    stage = destination if not old else destination.with_name(f"refresh-{job.name}")
    stage.mkdir(parents=True, exist_ok=True)
    case, _, report = prepare(job, metadata, f"/cases/{case_id}/{version}", stage, publishing=True)
    if stage != destination:
        for asset in stage.iterdir():
            target = destination / asset.name
            if not target.exists():
                asset.rename(target)
    register(case, destination)
    write_json(destination / "manifest.json", case)
    archive = import_root() / "exports" / case_id / (version + ".zip")
    write_archive(archive, metadata, files, destination)
    catalog["cases"] = [case] + [item for item in catalog["cases"]
                                 if (item["id"],item["version"]) != (case_id,version)]
    if default or not catalog["default"]:
        catalog["default"] = case_id
    write_json(cases_root() / "catalog.json", catalog)
    set_state(job, "ready", "案例已发布。", case=case, preview=report)
    return case


def run():
    while True:
        for job in sorted(import_root().iterdir()):
            if not JOB_ID.fullmatch(job.name):
                continue
            with (import_root() / ".worker.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    state = read_json(job / "state.json")["status"]
                    if state in {"queued","processing"}:
                        set_state(job, "processing", "正在检查坐标、覆盖和空间统计。")
                        preview(job, validate_metadata(read_json(job / "metadata.json")))
                    elif state in {"preview","publishing"} and (job / "publish").is_file():
                        publish(job, validate_metadata(read_json(job / "metadata.json")))
                except InvalidCase as error:
                    set_state(job, "error", str(error))
                except Exception as error:
                    print(f"Case job {job.name}: {type(error).__name__}", flush=True)
                    set_state(job, "error", "无法处理案例。请检查源文件和本机地图服务。")
        time.sleep(0.8)


def bootstrap(args):
    metadata = validate_metadata(read_json(args.metadata))
    if len(args.depth) != len(metadata["steps"]):
        raise InvalidCase("Provide one depth file per step.")
    with (import_root() / ".worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        job = import_root() / ("bootstrap-" + uuid4().hex)
        target = job / "inputs"
        (target / "depths").mkdir(parents=True)
        for step, source in zip(metadata["steps"], args.depth, strict=True):
            shutil.copyfile(source, target / "depths" / (step["id"] + ".tif"))
        for field, stem in (("buildings","buildings"),("roads","roads"),("water","water"),("imagery","imagery")):
            source = getattr(args, field)
            if source:
                shutil.copyfile(source, target / (stem + source.suffix.lower()))
        case = publish(job, metadata, args.default)
        print(json.dumps({"id":case["id"],"version":case["version"],"steps":[s["summary"] for s in case["steps"]]},
                         ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    boot = sub.add_parser("bootstrap")
    boot.add_argument("--metadata", required=True, type=Path)
    boot.add_argument("--depth", action="append", required=True, type=Path)
    for name in ("buildings","roads","water","imagery"):
        boot.add_argument("--"+name, type=Path)
    boot.add_argument("--default", action="store_true")
    args = parser.parse_args()
    cases_root().mkdir(exist_ok=True, parents=True)
    import_root().mkdir(exist_ok=True, parents=True)
    if args.command == "run":
        run()
    else:
        bootstrap(args)


if __name__ == "__main__":
    main()
