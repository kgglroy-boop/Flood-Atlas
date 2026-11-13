"""Bounded vector ingestion for user GeoJSON and GeoPackage files."""
import json
import math
from dataclasses import dataclass

from osgeo import ogr, osr

from case_contract import InvalidCase
from .rasters import reference


@dataclass(frozen=True)
class Feature:
    id: str
    name: str
    address: str
    kind: str
    lon: float
    lat: float
    wkb: bytes
    geometry: dict
    permanent_water: bool


def polygon_for(bounds):
    (west, south), (east, north) = bounds
    return ogr.CreateGeometryFromWkt(
        f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    )


def _clean(value, limit):
    return str(value if value is not None else "").strip().replace("\0", "")[:limit]


def _extract_parts(geometry, family):
    flat = ogr.GT_Flatten(geometry.GetGeometryType())
    if flat == family:
        return [geometry]
    if flat not in (ogr.wkbGeometryCollection, ogr.wkbMultiLineString, ogr.wkbMultiPolygon):
        return []
    return [child for part in geometry for child in _extract_parts(part, family)]


def load_vector(path, kind, bounds):
    if path is None:
        return []
    with path.open("rb") as stream:
        header = stream.read(16)
    if path.suffix == ".gpkg" and header != b"SQLite format 3\0":
        raise InvalidCase("Invalid GeoPackage signature.")
    driver = "GPKG" if path.suffix == ".gpkg" else "GeoJSON"
    from osgeo import gdal
    dataset = gdal.OpenEx(str(path), gdal.OF_VECTOR | gdal.OF_READONLY, allowed_drivers=[driver])
    if dataset is None:
        raise InvalidCase("A vector input could not be opened.")
    names = {"building": ("buildings", "building"), "road": ("roads", "road"), "water": ("water",), "area": ("area", "study_area")}
    layer = next((candidate for name in names[kind] if (candidate := dataset.GetLayerByName(name))), None)
    if layer is None:
        if dataset.GetLayerCount() != 1:
            raise InvalidCase("Select a one-layer GeoPackage or name its layers buildings, roads, water or area.")
        layer = dataset.GetLayer(0)
    srs = layer.GetSpatialRef()
    if srs is None or layer.GetFeatureCount() > 100_000:
        raise InvalidCase("Vector data need a CRS and at most 100,000 features per layer.")
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    conversion = osr.CoordinateTransformation(srs, reference(4326))
    family = ogr.wkbLineString if kind == "road" else ogr.wkbPolygon
    container = ogr.wkbMultiLineString if kind == "road" else ogr.wkbMultiPolygon
    aoi = polygon_for(bounds)
    identifiers = set()
    rows = []
    for source in layer:
        fields = {name.lower(): value for name, value in source.items().items()}
        geometry = source.GetGeometryRef()
        if geometry is None or geometry.IsEmpty():
            continue
        geometry = geometry.Clone()
        geometry.FlattenTo2D()
        geometry.Transform(conversion)
        if not geometry.IsValid():
            geometry = geometry.MakeValid()
        if geometry is None or geometry.IsEmpty() or not geometry.Intersects(aoi):
            continue
        geometry = geometry.Intersection(aoi)
        multi = ogr.Geometry(container)
        for part in _extract_parts(geometry, family):
            multi.AddGeometry(part)
        if multi.IsEmpty():
            continue
        native_id = next((fields.get(name) for name in ("id", "building_id", "road_id", "bin", "segmentid", "objectid") if fields.get(name) is not None), None)
        identifier = _clean(native_id, 120)
        if not identifier or not all(c.isalnum() or c in "._-:" for c in identifier):
            identifier = f"{kind}-{source.GetFID()}"
        if identifier in identifiers:
            identifier = f"{identifier}-{source.GetFID()}"
        if identifier in identifiers:
            raise InvalidCase("Vector features must have distinct IDs.")
        identifiers.add(identifier)
        if family == ogr.wkbPolygon:
            center = multi.PointOnSurface()
        else:
            center = multi.Centroid()
        lon, lat = center.GetPoint()[:2]
        if not math.isfinite(lon) or not math.isfinite(lat):
            raise InvalidCase("A feature has invalid coordinates.")
        name = _clean(fields.get("name") or fields.get("streetname") or identifier, 180)
        address = _clean(fields.get("address"), 200)
        permanent = kind == "water" and fields.get("permanent_water") not in (False, 0, "0", "false")
        rows.append(Feature(identifier, name, address, kind, lon, lat,
                            bytes(multi.ExportToWkb()), json.loads(multi.ExportToJson(options=["COORDINATE_PRECISION=7"])),
                            permanent))
    if not rows:
        raise InvalidCase(f"The {kind} layer does not overlap the depth grid.")
    return rows


def snapshot_features(features):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": item.geometry,
         "properties": {"id": item.id, "name": item.name, "address": item.address, "kind": item.kind}}
        for item in features
    ]}
