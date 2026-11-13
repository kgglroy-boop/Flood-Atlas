import asyncio

import httpx

from app.main import app


def request(method, path, **kwargs):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:5173"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send())


def test_empty_case_catalog_does_not_depend_on_teaching_database(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOOD_CASES_ROOT", str(tmp_path))
    response = request("GET", "/api/v2/cases")
    assert response.status_code == 200
    assert response.json() == {"default": "", "cases": []}


def test_remote_origin_cannot_create_import_even_with_token(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOOD_IMPORT_ROOT", str(tmp_path))
    monkeypatch.setenv("FLOOD_IMPORT_TOKEN", "local-import-test-token-123")
    response = request(
        "POST", "/api/v2/imports",
        headers={"Authorization": "Bearer local-import-test-token-123", "Origin": "https://example.org"},
        files={"metadata": (None, "{}")},
    )
    assert response.status_code == 403
    assert list(tmp_path.iterdir()) == []


def test_invalid_metadata_cannot_queue_upload(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOOD_IMPORT_ROOT", str(tmp_path))
    monkeypatch.setenv("FLOOD_IMPORT_TOKEN", "local-import-test-token-123")
    response = request(
        "POST", "/api/v2/imports",
        headers={"Authorization": "Bearer local-import-test-token-123", "Origin": "http://localhost:5173"},
        files={"metadata": (None, '{"id":"../escape"}'), "depths": ("sample.tif", b"garbage")},
    )
    assert response.status_code == 422
    assert list(tmp_path.iterdir()) == []
