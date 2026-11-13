import io
import json
import zipfile

import pytest

from app.case_archive import read_archive, read_snapshot, write_archive


def test_case_archive_roundtrip(tmp_path):
    meta = {"id": "sample", "steps": [{"id": "a"}]}
    original = tmp_path / "a.tif"
    original.write_bytes(b"GeoTIFF test content")
    snap = tmp_path / "display"
    snap.mkdir()
    (snap / "depth.png").write_bytes(b"display bytes")
    archive = tmp_path / "case.zip"
    write_archive(archive, meta, {"depths/a.tif": original}, snap)
    with archive.open("rb") as stream:
        assert read_archive(stream, tmp_path / "imported") == meta
    with archive.open("rb") as stream:
        assert read_snapshot(stream, tmp_path / "offline") == meta
    assert (tmp_path / "imported/depths/a.tif").read_bytes() == original.read_bytes()
    assert (tmp_path / "offline/depth.png").read_bytes() == b"display bytes"
    assert not (tmp_path / "offline/depths/a.tif").exists()


@pytest.mark.parametrize("name", ["source/../../outside.tif", "snapshot/../outside.png", "snapshot/x.html",
                                  "snapshot/C:\\escape.png", "snapshot//broken.png"])
def test_case_archive_rejects_unsafe_names(tmp_path, name):
    archive = io.BytesIO()
    meta = {"format": "flood-case", "version": 2, "metadata": {"steps": [{"id": "a"}]},
            "sha256": {"source/depths/a.tif": "", name: ""}}
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("manifest.json", json.dumps(meta))
        file.writestr("source/depths/a.tif", b"a")
        file.writestr(name, b"b")
    archive.seek(0)
    with pytest.raises(ValueError):
        read_archive(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()
