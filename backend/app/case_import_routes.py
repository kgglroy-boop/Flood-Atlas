"""Local, authenticated submission and publication of case import jobs."""
import hmac
import json
import os
import shutil
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.case_archive import read_archive
from app.case_contract import (
    JOB_ID, MAX_METADATA_BYTES, MAX_STEPS, MAX_UPLOAD_BYTES, OPTIONAL_INPUTS,
    InvalidCase, is_tiff, validate_metadata,
)
from app.case_jobs import import_root, read_json, set_state, write_json
from app.case_routes import published_case

router = APIRouter(prefix="/api/v2", tags=["local case imports"])
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
DEFAULT_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,http://[::1]:5173,"
    "http://localhost:8000,http://127.0.0.1:8000,http://[::1]:8000"
)
UPLOAD_SLOTS = threading.BoundedSemaphore(2)
CHUNK_SIZE = 1024 * 1024
MAX_PENDING_JOBS = 12
PENDING_STATES = {"queued", "processing", "preview", "publishing"}


def authorize(request):
    expected = os.environ.get("FLOOD_IMPORT_TOKEN", "")
    if not expected or expected == "CHANGE_ME":
        raise HTTPException(503, "Local case imports are disabled.")
    origin = request.headers.get("origin")
    host = request.url.hostname
    fetch_site = request.headers.get("sec-fetch-site")
    if origin is not None:
        origins = {item.strip() for item in os.environ.get("FLOOD_IMPORT_ORIGINS", DEFAULT_ORIGINS).split(",")}
        try:
            parsed = urlsplit(origin)
            allowed = (
                origin in origins and parsed.scheme in ("http", "https") and parsed.hostname in LOOPBACK
                and not (parsed.username or parsed.path or parsed.query or parsed.fragment)
            )
        except ValueError:
            allowed = False
        if not allowed:
            raise HTTPException(403, "Imports are available only from the local WebGIS origin.")
    elif host not in LOOPBACK and not (host == "backend" and fetch_site == "same-origin"):
        raise HTTPException(403, "Imports are available only from the local WebGIS origin.")
    if fetch_site == "cross-site":
        raise HTTPException(403, "Cross-site import requests are forbidden.")
    supplied = request.headers.get("authorization", "").encode("utf-8")
    if not hmac.compare_digest(supplied, f"Bearer {expected}".encode("utf-8")):
        raise HTTPException(401, "A valid local import token is required.", {"WWW-Authenticate": "Bearer"})


class UploadTooLarge(MultiPartException):
    pass


async def bounded_stream(request):
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise UploadTooLarge("Upload exceeds 512 MiB.")
        yield chunk


async def parse_form(request):
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdecimal() or len(length) > 12:
            raise HTTPException(400, "Invalid upload length.")
        if int(length) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Upload exceeds 512 MiB.")
    if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "multipart/form-data":
        raise HTTPException(415, "Use multipart form data.")
    parser = MultiPartParser(
        request.headers, bounded_stream(request),
        max_files=MAX_STEPS + len(OPTIONAL_INPUTS), max_fields=1, max_part_size=MAX_METADATA_BYTES,
    )
    try:
        return await parser.parse()
    except UploadTooLarge:
        raise HTTPException(413, "Upload exceeds 512 MiB.") from None
    except (MultiPartException, ValueError):
        raise HTTPException(400, "Invalid multipart upload.") from None


def copy_upload(upload, path):
    if not isinstance(upload, UploadFile) or not upload.size:
        raise InvalidCase("Expected a nonempty uploaded file.")
    suffix = Path(upload.filename or "").suffix.lower()
    allowed = {".tif", ".tiff"} if path.suffix == ".tif" else {".geojson", ".json", ".gpkg"}
    if suffix not in allowed:
        raise InvalidCase("Use GeoTIFF for rasters, and GeoJSON or GeoPackage for vectors.")
    if path.suffix == ".tif":
        if not is_tiff(upload.file.read(4)):
            raise InvalidCase("A raster has an invalid GeoTIFF signature.")
        upload.file.seek(0)
    with path.open("xb") as destination:
        shutil.copyfileobj(upload.file, destination, length=CHUNK_SIZE)


def submit(form):
    if "archive" in form:
        if len(form.multi_items()) != 1 or not isinstance(form["archive"], UploadFile):
            raise InvalidCase("Supply a single case archive without additional form fields.")
        metadata = None
    else:
        allowed = {"metadata", "depths", *OPTIONAL_INPUTS}
        if set(form.keys()).difference(allowed):
            raise InvalidCase("Unknown case upload field.")
        raw = form.get("metadata")
        if not isinstance(raw, str):
            raise InvalidCase("A JSON metadata field is required.")
        incoming = json.loads(raw)
        reuse_version = incoming.pop("reuse_version", None) if isinstance(incoming, dict) else None
        metadata = validate_metadata(incoming)
        previous = None
        if reuse_version is not None:
            if not isinstance(reuse_version, str):
                raise InvalidCase("Choose a published version of the same case.")
            previous = published_case(metadata["id"], reuse_version)
        if len(form.getlist("depths")) != len(metadata["steps"]):
            raise InvalidCase("Provide one GeoTIFF per step, in metadata order.")
        if any(len(form.getlist(key)) > 1 for key in OPTIONAL_INPUTS):
            raise InvalidCase("Optional inputs may appear only once.")

    root = import_root()
    root.mkdir(parents=True, exist_ok=True)
    pending = 0
    for folder in root.iterdir():
        if not JOB_ID.fullmatch(folder.name):
            continue
        try:
            pending += read_json(folder / "state.json")["status"] in PENDING_STATES
        except FileNotFoundError:
            continue
    if pending >= MAX_PENDING_JOBS:
        raise HTTPException(429, "The case import queue is full.")

    job = root / uuid4().hex
    stage = root / f".upload-{job.name}"
    stage.mkdir(mode=0o750)
    try:
        inputs = stage / "inputs"
        inputs.mkdir()
        if metadata is None:
            metadata = validate_metadata(read_archive(form["archive"].file, inputs))
        else:
            (inputs / "depths").mkdir()
            for step, upload in zip(metadata["steps"], form.getlist("depths"), strict=True):
                copy_upload(upload, inputs / "depths" / f'{step["id"]}.tif')
            for key, name in OPTIONAL_INPUTS.items():
                if key in form:
                    upload = form[key]
                    target = inputs / name
                    if isinstance(upload, UploadFile) and target.suffix == ".geojson" and Path(upload.filename or "").suffix.lower() == ".gpkg":
                        target = target.with_suffix(".gpkg")
                    copy_upload(upload, target)
            if previous is not None:
                previous_archive = root / "exports" / previous["id"] / (previous["version"] + ".zip")
                if not previous_archive.is_file():
                    raise InvalidCase("The previous version has no reusable source archive.")
                inherited = stage / "inherited"
                with previous_archive.open("rb") as stream:
                    read_archive(stream, inherited)
                for key, name in OPTIONAL_INPUTS.items():
                    if key in form:
                        continue
                    for candidate in (inherited / name, (inherited / name).with_suffix(".gpkg")):
                        if candidate.is_file():
                            candidate.rename(inputs / candidate.name)
                            break
                shutil.rmtree(inherited)
                write_json(stage / "reuse.json", previous["bounds"])
        write_json(stage / "metadata.json", metadata)
        state = {"id": job.name, "status": "queued", "message": "Waiting for local preflight."}
        write_json(stage / "state.json", state)
        stage.rename(job)
        return state
    finally:
        if stage.exists():
            shutil.rmtree(stage)


@router.post("/imports", status_code=202)
async def create_import(request: Request):
    authorize(request)
    if not UPLOAD_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Other case uploads are in progress.")
    try:
        form = await parse_form(request)
        try:
            # Copying a spooled upload can take time and must leave the API event loop free.
            from starlette.concurrency import run_in_threadpool

            return await run_in_threadpool(submit, form)
        except InvalidCase as error:
            raise HTTPException(422, str(error)) from None
        except (ValueError, zipfile.BadZipFile, RuntimeError):
            raise HTTPException(422, "Invalid case upload or metadata.") from None
        finally:
            await form.close()
    finally:
        UPLOAD_SLOTS.release()


def get_job(job_id):
    if not JOB_ID.fullmatch(job_id):
        raise HTTPException(404, "Import job not found.")
    job = import_root() / job_id
    try:
        state = read_json(job / "state.json")
    except FileNotFoundError:
        raise HTTPException(404, "Import job not found.") from None
    return job, state


@router.get("/imports/{job_id}")
def import_status(job_id: str, request: Request):
    authorize(request)
    _, state = get_job(job_id)
    return state


@router.post("/imports/{job_id}/publish", status_code=202)
def publish_import(job_id: str, request: Request):
    authorize(request)
    job, state = get_job(job_id)
    if state["status"] in {"publishing", "ready"}:
        return state
    if state["status"] != "preview":
        raise HTTPException(409, "The import needs a successful preview before publishing.")
    # The worker owns persisted state transitions. A durable exclusive marker
    # queues publication without racing with worker or duplicate requests.
    try:
        descriptor = os.open(job / "publish", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        pass
    else:
        os.close(descriptor)
    return {**state, "status": "publishing", "message": "Publication queued."}


@router.get("/cases/{case_id}/{version}/export")
def export_case(case_id: str, version: str, request: Request):
    authorize(request)
    published_case(case_id, version)
    path = import_root() / "exports" / case_id / f"{version}.zip"
    if not path.is_file():
        raise HTTPException(404, "Archive not available for this case version.")
    return FileResponse(
        path, media_type="application/zip", filename=f"{case_id}-{version}.zip",
        headers={"Cache-Control": "private, no-store"},
    )
