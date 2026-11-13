"""Portable case source and display snapshot, with bounded extraction."""
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_MEMBERS = 25_000
INPUT_OPTIONAL = {"imagery.tif", "buildings.geojson", "roads.geojson", "water.geojson",
                  "buildings.gpkg", "roads.gpkg", "water.gpkg", "area.geojson", "area.gpkg"}
SNAPSHOT_EXTENSIONS = {".json", ".geojson", ".png", ".webp", ".f32", ".bin", ".pbf", ".tif", ".pmtiles"}
SAFE_PART = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", re.ASCII)
STEP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", re.ASCII)


def _json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _depth_names(metadata):
    if not isinstance(metadata, dict):
        raise ValueError("invalid case metadata")
    steps = metadata.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 20:
        raise ValueError("invalid case steps")
    names = set()
    for step in steps:
        value = step.get("id") if isinstance(step, dict) else None
        if not isinstance(value, str) or not STEP_ID.fullmatch(value):
            raise ValueError("invalid step identifier")
        names.add(f"depths/{value}.tif")
    if len(names) != len(steps):
        raise ValueError("duplicate step")
    return names


def _valid_inputs(metadata, names):
    depths = _depth_names(metadata)
    if not depths <= names or names - depths - INPUT_OPTIONAL:
        raise ValueError("unexpected case input names")


def _snapshot_name(name):
    parts = name.split("/")
    return (len(parts) <= 12 and all(SAFE_PART.fullmatch(part) for part in parts)
            and PurePosixPath(name).suffix in SNAPSHOT_EXTENSIONS)


def _digest(stream, dest=None):
    sha = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        sha.update(block)
        if dest is not None:
            dest.write(block)
    return sha.hexdigest()


def write_archive(destination: Path, metadata: dict, inputs: dict[str, Path], snapshot: Path | None = None):
    """Write on the caller's private staging directory and atomically expose the archive."""
    _valid_inputs(metadata, set(inputs))
    sources = {f"source/{name}": path for name, path in inputs.items()}
    assets = {}
    if snapshot is not None:
        for path in snapshot.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(snapshot).as_posix()
            if _snapshot_name(rel):
                assets[f"snapshot/{rel}"] = path
    if (len(sources) + len(assets) > MAX_MEMBERS
        or sum(path.stat().st_size for path in sources.values()) > MAX_SOURCE_BYTES
        or sum(path.stat().st_size for path in (*sources.values(), *assets.values())) > MAX_TOTAL_BYTES):
        raise ValueError("case archive exceeds size limit")
    temp = destination.with_suffix(".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED, compresslevel=5) as archive:
            records = {}
            for name, path in sorted({**sources, **assets}.items()):
                with path.open("rb") as stream, archive.open(name, "w") as target:
                    records[name] = _digest(stream, target)
            archive.writestr("manifest.json", _json({
                "format": "flood-case", "version": 2, "metadata": metadata, "sha256": records,
            }))
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)


def _check_members(archive):
    members = archive.infolist()
    if len(members) > MAX_MEMBERS + 1:
        raise ValueError("too many case archive members")
    names = {}
    for entry in members:
        name = entry.filename
        kind = stat.S_IFMT(entry.external_attr >> 16)
        if name in names or entry.is_dir() or kind not in {0, stat.S_IFREG} or entry.flag_bits & 1:
            raise ValueError("invalid case archive member")
        names[name] = entry
    manifest = names.pop("manifest.json", None)
    if manifest is None or manifest.file_size > 2 * 1024 * 1024:
        raise ValueError("invalid case archive manifest")
    if (sum(item.file_size for item in names.values()) > MAX_TOTAL_BYTES
        or sum(item.file_size for key, item in names.items() if key.startswith("source/")) > MAX_SOURCE_BYTES):
        raise ValueError("case archive exceeds size limit")
    return names, manifest


def _read(archive_stream, output_dir: Path, *, snapshot_only=False):
    with zipfile.ZipFile(archive_stream) as archive:
        members, manifest_file = _check_members(archive)
        manifest = json.loads(archive.read(manifest_file))
        if not isinstance(manifest, dict) or manifest.get("format") != "flood-case" or manifest.get("version") != 2:
            raise ValueError("unsupported case archive")
        metadata = manifest.get("metadata")
        expected = manifest.get("sha256")
        if not isinstance(expected, dict) or set(expected) != set(members):
            raise ValueError("incomplete case archive")
        _valid_inputs(metadata, {name[7:] for name in members if name.startswith("source/")})
        if any(not (name.startswith("source/") or name.startswith("snapshot/") and _snapshot_name(name[9:]))
               for name in members):
            raise ValueError("unexpected case archive member")
        if snapshot_only and not any(name.startswith("snapshot/") for name in members):
            raise ValueError("case archive has no offline snapshot")
        for name, info in members.items():
            relative = name[9:] if snapshot_only and name.startswith("snapshot/") else None
            if not snapshot_only and name.startswith("source/"):
                relative = name[7:]
            with archive.open(info) as stream:
                if relative is None:
                    sha = _digest(stream)
                else:
                    target = output_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as dest:
                        sha = _digest(stream, dest)
                if sha != expected[name]:
                    raise ValueError("case archive checksum mismatch")
    return metadata


def read_archive(archive: BinaryIO, output_dir: Path) -> dict:
    """Recover sources only; the importer independently reprocesses published assets."""
    return _read(archive, output_dir)


def read_snapshot(archive: BinaryIO, output_dir: Path) -> dict:
    """Extract a verified display snapshot into a fresh private directory."""
    return _read(archive, output_dir, snapshot_only=True)
