"""Serve a compiled atlas with local case files on the loopback interface."""
import argparse
import json
import mimetypes
import re
import shutil
import tempfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from backend.app.case_archive import read_snapshot

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}", re.ASCII)


class AtlasHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, web, cases, **kwargs):
        self.web = web.resolve()
        self.cases = cases.resolve()
        super().__init__(*args, directory=str(self.web), **kwargs)

    def translate_path(self, path):
        url = unquote(urlsplit(path).path)
        if url == "/":
            return str(self.web / "index.html")
        base, relative = (self.cases, url[7:]) if url.startswith("/cases/") else (self.web, url.lstrip("/"))
        parts = PurePosixPath(relative).parts
        if not parts or ".." in parts or any("\\" in part or ":" in part or part.startswith(".") for part in parts):
            return str(base / ".__missing__")
        result = base.joinpath(*parts).resolve()
        return str(result) if result.is_relative_to(base) else str(base / ".__missing__")

    def list_directory(self, path):
        self.send_error(404)
        return None

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()


def prepare_archive(archive_path, temporary):
    staging = temporary / "snapshot"
    with archive_path.open("rb") as stream:
        metadata = read_snapshot(stream, staging)
    candidates = [staging / "case.json", staging / "manifest.json"]
    manifest = next((p for p in candidates if p.is_file()), None)
    if not manifest:
        raise ValueError("Offline snapshot has no case descriptor")
    case = json.loads(manifest.read_text(encoding="utf-8"))
    case_id, version = case.get("id"), case.get("version")
    if not (isinstance(case_id, str) and isinstance(version, str)
            and NAME.fullmatch(case_id) and NAME.fullmatch(version)
            and case_id == metadata.get("id")):
        raise ValueError("Invalid offline case identity")
    root = temporary / "cases"
    target = root / case_id / version
    target.parent.mkdir(parents=True)
    shutil.move(staging, target)
    (root / "catalog.json").write_text(json.dumps({"default": case_id, "cases": [case]}, ensure_ascii=False),
                                       encoding="utf-8")
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--cases", type=Path)
    group.add_argument("--archive", type=Path)
    parser.add_argument("--port", type=int, default=5174)
    args = parser.parse_args()
    if not (args.web / "index.html").is_file():
        parser.error("Compile or extract the atlas web assets first")
    for suffix in (".pbf", ".f32", ".bin", ".pmtiles"):
        mimetypes.add_type("application/octet-stream", suffix)
    with tempfile.TemporaryDirectory(prefix="flood-atlas-") as path:
        cases = prepare_archive(args.archive, Path(path)) if args.archive else args.cases
        if not (cases / "catalog.json").is_file():
            parser.error("Offline case catalog is unavailable")
        handler = partial(AtlasHandler, web=args.web, cases=cases)
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
            print(f"Flood Atlas offline: http://127.0.0.1:{args.port}/", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
