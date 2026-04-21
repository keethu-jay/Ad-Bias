#!/usr/bin/env python3
"""
Apply `sql/postgres/benchmark_schema.sql` to Postgres/Supabase: `ad_impressions`, q1–q13 harness,
and BRIN on `impression_id` (PGM-style path).

Run from repo root:  python -m etl.apply_benchmark_schema

Splits the file on `-- STATEMENT` lines. Uses postgres_config.connect_postgres.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from postgres_config import connect_postgres

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SQL = _REPO_ROOT / "sql" / "postgres" / "benchmark_schema.sql"


def split_statements(sql_text: str) -> list[str]:
    parts = re.split(r"^-- STATEMENT\s*\r?\n", sql_text, flags=re.MULTILINE)
    out: list[str] = []
    for p in parts:
        block = p.strip()
        if not block:
            continue
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if lines and all(ln.startswith("--") for ln in lines):
            continue
        out.append(block)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply ClearBias benchmark DDL to PostgreSQL.")
    parser.add_argument(
        "--sql-file",
        type=Path,
        default=_SQL,
        help=f"Path to benchmark_schema.sql (default: {_SQL})",
    )
    args = parser.parse_args()

    if not args.sql_file.is_file():
        print(f"Missing SQL file: {args.sql_file}", file=sys.stderr)
        return 2

    text = args.sql_file.read_text(encoding="utf-8")
    statements = split_statements(text)
    if not statements:
        print("No SQL statements found (expected -- STATEMENT markers).", file=sys.stderr)
        return 2

    conn = connect_postgres()
    cur = conn.cursor()
    i = 0
    stmt = ""
    try:
        t0 = time.perf_counter()
        for i, stmt in enumerate(statements, start=1):
            cur.execute(stmt)
            conn.commit()
            print(f"  [{i}/{len(statements)}] ok")
        print(f"Done in {(time.perf_counter() - t0) * 1000:.1f} ms")
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"Error on statement {i}: {exc}", file=sys.stderr)
        print("--- statement preview ---", file=sys.stderr)
        print(stmt[:800], file=sys.stderr)
        return 1
    finally:
        cur.close()
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
