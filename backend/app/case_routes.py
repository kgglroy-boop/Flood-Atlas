"""Read-only v2 map catalog, geometry tiles and case-specific analysis."""
import logging
import math
import struct
from typing import Annotated

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.case_contract import CASE_ID, STEP_ID, VERSION
from app.case_jobs import cases_root, read_catalog, read_json
from app.database import open_database
from app.tiles import parse_tile

router = APIRouter(prefix="/api/v2/cases", tags=["cases"])
logger = logging.getLogger("urban_flood.cases")

SEARCH_SQL = """
SELECT id, name, address, lon, lat
FROM case_v2.features
WHERE case_id=%(case_id)s AND version=%(version)s AND kind='building'
  AND (strpos(lower(id), lower(%(query)s)) > 0
       OR strpos(lower(name), lower(%(query)s)) > 0
       OR strpos(lower(coalesce(address, '')), lower(%(query)s)) > 0)
ORDER BY CASE WHEN lower(id)=lower(%(query)s) THEN 0 ELSE 1 END, name, id
LIMIT 20
"""
BUILDING_SQL = """
SELECT f.id, f.name, f.address, f.lon, f.lat, b.affected
FROM case_v2.features f
LEFT JOIN case_v2.building_steps b ON b.case_id=f.case_id AND b.version=f.version
  AND b.building_id=f.id AND b.step_id=%(step)s
WHERE f.case_id=%(case_id)s AND f.version=%(version)s AND f.kind='building' AND f.id=%(bid)s
"""
TILE_SQL = """
WITH bounds AS (
  SELECT ST_TileEnvelope(%(z)s,%(x)s,%(y)s) AS tile,
         ST_TileEnvelope(%(z)s,%(x)s,%(y)s,margin=>64.0/4096) AS buffered
), clipped AS (
  SELECT f.id, f.name, f.kind, ST_AsMVTGeom(f.map_geom,b.tile,4096,64,true) AS geom
  FROM case_v2.features f CROSS JOIN bounds b
  WHERE f.case_id=%(case_id)s AND f.version=%(version)s AND f.map_geom && b.buffered
)
SELECT COALESCE(ST_AsMVT(q,'features',4096,'geom'),''::bytea)
FROM (SELECT id, name, kind, geom FROM clipped WHERE geom IS NOT NULL) q
"""
TRANSFORM_SQL = """
SELECT ST_X(point), ST_Y(point)
FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%s,%s),4326),%s) AS point) transformed
"""


@router.get("")
def list_cases(response: Response):
    response.headers["Cache-Control"] = "no-cache"
    try:
        return read_catalog()
    except (AttributeError, OSError, ValueError):
        raise HTTPException(503, "Case catalog unavailable.") from None


def published_case(case_id, version):
    if not CASE_ID.fullmatch(case_id) or not VERSION.fullmatch(version):
        raise HTTPException(404, "Case version not found.")
    catalog = list_cases(Response())
    for case in catalog["cases"]:
        if case["id"] == case_id and case["version"] == version:
            return case
    raise HTTPException(404, "Case version not found.")


def require_step(case, step_id):
    if not STEP_ID.fullmatch(step_id) or all(step["id"] != step_id for step in case["steps"]):
        raise HTTPException(404, "Step not found.")


def read_rows(query, parameters):
    try:
        with open_database() as connection:
            return connection.execute(query, parameters).fetchall()
    except psycopg.Error:
        logger.warning("Case analysis database read failed")
        raise HTTPException(503, "Case analysis unavailable.") from None


def building(row):
    return dict(zip(("id", "name", "address", "lon", "lat"), row[:5], strict=True))


@router.get("/{case_id}/{version}/buildings")
def buildings(case_id: str, version: str, q: Annotated[str, Query(max_length=120)] = ""):
    case = published_case(case_id, version)
    if not case["features"] or not q.strip():
        return {"items": []}
    rows = read_rows(SEARCH_SQL, {"case_id": case_id, "version": version, "query": q.strip()})
    return {"items": [building(row) for row in rows]}


@router.get("/{case_id}/{version}/buildings/{bid}")
def building_details(case_id: str, version: str, bid: str, step: str):
    case = published_case(case_id, version)
    require_step(case, step)
    if not case["features"] or len(bid) > 160 or "\0" in bid:
        raise HTTPException(404, "Building not found.")
    parameters = {"case_id": case_id, "version": version, "bid": bid, "step": step}
    rows = read_rows(BUILDING_SQL, parameters)
    if not rows:
        raise HTTPException(404, "Building not found.")
    return {**building(rows[0]), "affected": rows[0][5]}


@router.get("/{case_id}/{version}/tiles/{z}/{x}/{y}.pbf", response_class=Response)
def features_tile(case_id: str, version: str, z: str, x: str, y: str, request: Request):
    case = published_case(case_id, version)
    z, x, y = parse_tile(z, x, y, list(request.query_params.multi_items()))
    content = b""
    if case["features"]:
        parameters = {"case_id": case_id, "version": version, "z": z, "x": x, "y": y}
        content = bytes(read_rows(TILE_SQL, parameters)[0][0])
    return Response(
        content,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


def sample_value(case, step, lon, lat):
    bounds = case["bounds"]
    if not bounds[0][0] <= lon <= bounds[1][0] or not bounds[0][1] <= lat <= bounds[1][1]:
        return math.nan
    x, y = read_rows(TRANSFORM_SQL, (lon, lat, case["analysis_srid"]))[0]
    if not math.isfinite(x) or not math.isfinite(y):
        return math.nan
    path = cases_root() / case["id"] / case["version"] / "sampling"
    try:
        grid = read_json(path / "native.json")
        left, pixel_x, _, top, _, pixel_y = grid["transform"]
        column = math.floor((x - left) / pixel_x)
        row = math.floor((y - top) / pixel_y)
        if not 0 <= column < grid["width"] or not 0 <= row < grid["height"]:
            return math.nan
        with (path / f"{step}.f32").open("rb") as stream:
            stream.seek(4 * (row * grid["width"] + column))
            return struct.unpack("<f", stream.read(4))[0]
    except (OSError, ValueError, KeyError, struct.error):
        raise HTTPException(503, "Case sample grid unavailable.") from None


@router.get("/{case_id}/{version}/sample")
def sample_depth(
    case_id: str,
    version: str,
    step: str,
    lon: Annotated[float, Query(ge=-180, le=180, allow_inf_nan=False)],
    lat: Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False)],
):
    case = published_case(case_id, version)
    require_step(case, step)
    depth = sample_value(case, step, lon, lat)
    if depth == -1:
        return {"depth_m": None, "status": "water"}
    if not math.isfinite(depth):
        return {"depth_m": None, "status": "no_coverage"}
    return {"depth_m": round(depth, 6), "status": "covered"}
