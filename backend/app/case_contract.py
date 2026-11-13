"""The upload contract shared by FastAPI, the worker and archived imports."""
import math
import re
from urllib.parse import urlsplit

MAX_STEPS = 20
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
OPTIONAL_INPUTS = {
    "buildings": "buildings.geojson",
    "roads": "roads.geojson",
    "imagery": "imagery.tif",
    "water": "water.geojson",
    "area": "area.geojson",
}
CASE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}\Z")
STEP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z")
VERSION = re.compile(r"[0-9a-f]{20}\Z")
JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
UNIT_FACTORS = {"m": 1.0, "cm": 0.01, "ft": 0.3048}
DEPTH_CLASSES = (
    (0.30, (183, 214, 238, 255)),
    (0.60, (116, 155, 208, 255)),
    (1.00, (73, 104, 170, 255)),
    (1.50, (63, 64, 123, 255)),
    (math.inf, (40, 35, 78, 255)),
)


class InvalidCase(ValueError):
    """An input validation error safe to show to the person who supplied it."""


def _record(value, keys, label):
    if not isinstance(value, dict) or set(value).difference(keys):
        raise InvalidCase(f"{label} has an invalid format or unknown fields.")
    return value


def _text(value, label, limit, required=True):
    if not isinstance(value, str) or len(value) > limit or "\0" in value:
        raise InvalidCase(f"{label} must be text of at most {limit} characters.")
    value = value.strip()
    if required and not value:
        raise InvalidCase(f"{label} is required.")
    return value


def _number(value, label):
    if type(value) not in (int, float) or not 0 <= value <= 1_000_000_000:
        raise InvalidCase(f"{label} must be a finite, nonnegative number.")
    return value


def _step(value):
    step = _record(value, ("id", "label", "scenario", "kind", "time_min", "description"), "Step")
    step_id = _text(step.get("id"), "Step ID", 48)
    if not STEP_ID.fullmatch(step_id):
        raise InvalidCase("Use letters, numbers, hyphens or underscores in step IDs.")
    kind = step.get("kind")
    if kind not in ("peak", "time"):
        raise InvalidCase("Step kind must be peak or time.")
    time_min = step.get("time_min")
    if kind == "time":
        time_min = _number(time_min, "Time in minutes")
    elif time_min is not None:
        raise InvalidCase("Peak steps must omit time in minutes.")
    return {
        "id": step_id,
        "label": _text(step.get("label"), "Step label", 150),
        "description": _text(step.get("description", ""), "Step description", 1600, False),
        "scenario": _text(step.get("scenario"), "Scenario", 150),
        "kind": kind,
        "time_min": time_min,
    }


def _source(value):
    source = _record(value, ("label", "url", "credit"), "Source")
    url = _text(source.get("url"), "Source URL", 1000)
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
            raise ValueError
    except ValueError:
        raise InvalidCase("Source URL must be an HTTP or HTTPS link.") from None
    return {
        "label": _text(source.get("label"), "Source label", 150),
        "url": url,
        "credit": _text(source.get("credit", ""), "Source credit", 600, False),
    }


def validate_metadata(value):
    data = _record(
        value,
        ("id", "title", "subtitle", "description", "threshold_m", "unit", "srid", "sources", "steps"),
        "Metadata",
    )
    case_id = _text(data.get("id"), "Case ID", 48)
    if not CASE_ID.fullmatch(case_id):
        raise InvalidCase("Use lowercase letters, numbers, hyphens or underscores in the case ID.")
    unit = data.get("unit")
    if not isinstance(unit, str) or unit not in UNIT_FACTORS:
        raise InvalidCase("Depth unit must be m, cm or ft.")
    srid = data.get("srid")
    if srid is not None and (type(srid) is not int or not 1 <= srid <= 999999):
        raise InvalidCase("Analysis CRS must be an EPSG number.")
    steps = data.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise InvalidCase(f"Provide between 1 and {MAX_STEPS} steps.")
    steps = [_step(step) for step in steps]
    if len({step["id"].lower() for step in steps}) != len(steps):
        raise InvalidCase("Each step must have a distinct ID.")
    if len({(step["scenario"], step["kind"], step["time_min"]) for step in steps}) != len(steps):
        raise InvalidCase("Each scenario must have distinct times and at most one peak.")
    sources = data.get("sources", [])
    if not isinstance(sources, list) or len(sources) > 20:
        raise InvalidCase("Provide at most 20 source citations.")
    return {
        "id": case_id,
        "title": _text(data.get("title"), "Case title", 150),
        "subtitle": _text(data.get("subtitle", ""), "Case subtitle", 250, False),
        "description": _text(data.get("description", ""), "Case description", 4000, False),
        "threshold_m": _number(data.get("threshold_m"), "Threshold in metres"),
        "unit": unit,
        "srid": srid,
        "sources": [_source(source) for source in sources],
        "steps": steps,
    }


def input_paths(folder, metadata):
    depths = {f'depths/{step["id"]}.tif': folder / "depths" / f'{step["id"]}.tif'
              for step in metadata["steps"]}
    options = {name: folder / name for name in OPTIONAL_INPUTS.values() if (folder / name).is_file()}
    options.update({name.removesuffix(".geojson")+".gpkg": (folder / name).with_suffix(".gpkg")
                    for name in OPTIONAL_INPUTS.values()
                    if name.endswith(".geojson") and (folder / name).with_suffix(".gpkg").is_file()})
    return depths | options


def is_tiff(header):
    return header in (b"II*\0", b"MM\0*", b"II+\0", b"MM\0+")
