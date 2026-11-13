import psycopg
import pytest

from app import database


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only-secret")
    monkeypatch.setenv("POSTGRES_DB", "flood")
    monkeypatch.setenv("POSTGRES_USER", "flood")
    monkeypatch.setenv("PGHOST", "db")
    monkeypatch.setenv("PGPORT", "5432")


class ProbeConnection:
    def __init__(self, row):
        self.row = row
        self.sql = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql):
        self.sql = sql
        return self

    def fetchone(self):
        return self.row


def probe():
    function = getattr(database, "check_database", None)
    assert callable(function), "database readiness probe has not been implemented"
    return function()


def test_probe_checks_postgis_and_sets_connection_and_query_timeouts(monkeypatch):
    connection = ProbeConnection((1, "3.5 USE_GEOS=1"))
    arguments = {}

    def connect(**kwargs):
        arguments.update(kwargs)
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)
    assert probe() is None
    assert connection.sql == "SELECT 1, PostGIS_Version()"
    assert arguments["connect_timeout"] == 2
    assert arguments["options"] == "-c statement_timeout=2000"
    assert arguments["host"] == "db"
    assert arguments["password"] == "test-only-secret"


@pytest.mark.parametrize("row", [None, (1, None), (1, "")])
def test_missing_postgis_readiness_is_failure(monkeypatch, row):
    monkeypatch.setattr(psycopg, "connect", lambda **_: ProbeConnection(row))
    with pytest.raises(psycopg.OperationalError, match="database unavailable"):
        probe()


@pytest.mark.parametrize("password", ["", "CHANGE_ME"])
def test_unconfigured_password_fails_before_connection(monkeypatch, password):
    monkeypatch.setenv("POSTGRES_PASSWORD", password)

    def forbidden(**_):
        pytest.fail("unconfigured credentials must not open a connection")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    with pytest.raises(psycopg.OperationalError, match="database unavailable"):
        probe()
