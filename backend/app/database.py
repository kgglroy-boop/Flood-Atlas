"""Small, bounded readiness check; no business spatial queries here."""

import os

import psycopg


def open_database() -> psycopg.Connection:
    """Open a fresh bounded connection without exposing configuration errors."""
    try:
        password = os.environ["POSTGRES_PASSWORD"]
        if not password.strip() or password == "CHANGE_ME":
            raise ValueError("unconfigured password")
        return psycopg.connect(
            host=os.environ.get("PGHOST", "db"),
            port=int(os.environ.get("PGPORT", "5432")),
            dbname=os.environ.get("POSTGRES_DB", "flood"),
            user=os.environ.get("POSTGRES_USER", "flood"),
            password=password,
            connect_timeout=2,
            options="-c statement_timeout=2000",
            application_name="urban-flood-webgis",
        )
    except (psycopg.Error, KeyError, ValueError):
        raise psycopg.OperationalError("database unavailable") from None


def check_database() -> None:
    """Raise a sanitized driver error unless PostgreSQL and PostGIS are ready."""
    try:
        with open_database() as connection:
            row = connection.execute("SELECT 1, PostGIS_Version()").fetchone()
            if not row or row[0] != 1 or not row[1]:
                raise ValueError("PostGIS not ready")
    except (psycopg.Error, KeyError, ValueError):
        raise psycopg.OperationalError("database unavailable") from None
