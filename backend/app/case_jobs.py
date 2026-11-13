"""Filesystem hand-off shared by the local import API and worker."""
import json
import os
import tempfile
from pathlib import Path


def cases_root():
    return Path(os.environ.get("FLOOD_CASES_ROOT", "/cases"))


def import_root():
    return Path(os.environ.get("FLOOD_IMPORT_ROOT", "/case-import"))


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value):
    descriptor, name = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def set_state(job, status, message, **fields):
    state = {"id": job.name, "status": status, "message": message, **fields}
    write_json(job / "state.json", state)
    return state


def read_catalog():
    try:
        catalog = read_json(cases_root() / "catalog.json")
    except FileNotFoundError:
        return {"default": "", "cases": []}
    if not isinstance(catalog.get("default"), str) or not isinstance(catalog.get("cases"), list):
        raise ValueError("Invalid case catalog.")
    return catalog
