"""Register versioned image stores and verify a real GWC tile before exposure."""
import base64
import json
import math
import os
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WORKSPACE = "caseatlas"
PUBLIC_PATH = "/geoserver/gwc/service/wmts"


def _request(path, method="GET", content=None, content_type="application/json"):
    base = os.environ["GEOSERVER_URL"].rstrip("/")
    auth = base64.b64encode(
        f'{os.environ["GEOSERVER_ADMIN_USER"]}:{os.environ["GEOSERVER_ADMIN_PASSWORD"]}'.encode()
    ).decode("ascii")
    request = Request(base + path, data=content, method=method,
                      headers={"Authorization": "Basic " + auth, "Content-Type": content_type})
    with urlopen(request, timeout=35) as response:
        return response.read()


def _ensure_workspace():
    try:
        _request(f"/rest/workspaces/{WORKSPACE}.json")
    except HTTPError as error:
        if error.code != 404:
            raise
        _request("/rest/workspaces", "POST", json.dumps({"workspace": {"name": WORKSPACE}}).encode())


def _xyz(lon, lat, zoom):
    scale = 2 ** zoom
    return int((lon + 180) / 360 * scale), int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * scale)


def _tile_query(layer, zoom, x, y):
    return urlencode({
        "SERVICE":"WMTS", "REQUEST":"GetTile", "VERSION":"1.0.0", "LAYER":f"{WORKSPACE}:{layer}",
        "STYLE":"raster", "TILEMATRIXSET":"EPSG:900913", "TILEMATRIX":"EPSG:900913:"+str(zoom),
        "TILECOL":x, "TILEROW":y, "FORMAT":"image/png",
    })


def register(case, folder):
    _ensure_workspace()
    (west,south),(east,north) = case["bounds"]
    zoom = max(3, min(18, int(math.log2(360 / (east - west))) + 2))
    tile_x, tile_y = _xyz((west + east) / 2, (south + north) / 2, zoom)
    for index, step in enumerate(case["steps"]):
        layer = f'v{case["version"]}_{index}'
        try:
            _request(f"/rest/workspaces/{WORKSPACE}/coveragestores/{layer}.json")
        except HTTPError as error:
            if error.code != 404:
                raise
            _request(f"/rest/workspaces/{WORKSPACE}/coveragestores/{layer}/external.geotiff?configure=first&coverageName={layer}",
                     "PUT", str(folder / f'{step["id"]}.tif').encode(), "text/plain")
        test = _request("/gwc/service/wmts?" + _tile_query(layer, zoom, tile_x, tile_y))
        if not test.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("GeoServer did not return a PNG tile")
        step["wmts"] = PUBLIC_PATH + "?" + _tile_query(layer, "Z_VALUE", "X_VALUE", "Y_VALUE").replace(
            "Z_VALUE", "{z}").replace("X_VALUE", "{x}").replace("Y_VALUE", "{y}")
