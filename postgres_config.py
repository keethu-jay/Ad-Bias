"""
PostgreSQL / Supabase connection for ClearBias (live queries, benchmark schema, migrations).

Environment (first match wins in get_postgres_dsn):
  CLEARBIAS_POSTGRES_DSN — full libpq URL (preferred for local notes).
  DATABASE_URL — common on hosted platforms.
  SUPABASE_DB_URL — explicit Supabase DB connection string.

Optional: install python-dotenv; a `.env` next to this file is loaded into os.environ.

Example DSN:
  postgresql://postgres:PASSWORD@db.<project-ref>.supabase.co:5432/postgres?sslmode=require
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg2


def _load_dotenv() -> None:
    """Load project-root .env into os.environ if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)


_load_dotenv()


def get_postgres_dsn() -> str:
    dsn = (
        os.environ.get("CLEARBIAS_POSTGRES_DSN")
        or os.environ.get("DATABASE_URL")
        or os.environ.get("SUPABASE_DB_URL")
        or ""
    ).strip()
    if not dsn:
        raise RuntimeError(
            "Set CLEARBIAS_POSTGRES_DSN (or DATABASE_URL / SUPABASE_DB_URL) before running PostgreSQL scripts."
        )
    return dsn


def connect_postgres(*, autocommit: bool = False) -> Any:
    conn = psycopg2.connect(get_postgres_dsn())
    conn.autocommit = autocommit
    return conn
