import asyncio
import logging

import httpx
import psycopg

from app import main


def get(path):
    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            return await client.get(path)
    return asyncio.run(request())


def test_health_returns_exact_contract_after_database_probe(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "check_database", lambda: calls.append("checked"), raising=False)
    response = get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == ["checked"]


def test_database_failure_is_503_without_leaking_credentials(monkeypatch, caplog):
    secret = "private-test-password"

    def unavailable():
        raise psycopg.OperationalError(f"password={secret} host=db")

    monkeypatch.setattr(main, "check_database", unavailable, raising=False)
    with caplog.at_level(logging.WARNING):
        response = get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
    assert secret not in response.text
    assert secret not in caplog.text


def test_database_recovery_uses_a_fresh_probe(monkeypatch):
    available = False

    def probe():
        if not available:
            raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(main, "check_database", probe, raising=False)
    assert get("/api/v1/health").status_code == 503
    available = True
    assert get("/api/v1/health").json() == {"status": "ok"}


def test_swagger_available_and_analysis_routes_registered():
    assert get("/docs").status_code == 200
    paths = get('/openapi.json').json()['paths']
    assert '/api/v1/analysis/summary' in paths
    assert '/api/v1/analysis/buildings' in paths
