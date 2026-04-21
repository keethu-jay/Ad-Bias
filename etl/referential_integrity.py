#!/usr/bin/env python3
"""
Audit and repair ad_impressions ↔ interests / demographics alignment (PostgreSQL).

From repo root:
  python -m etl.referential_integrity audit
  python -m etl.referential_integrity align   # runs sql/postgres/fix_ad_impressions_lookup_alignment.sql
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from postgres_config import connect_postgres

_REPO_ROOT = Path(__file__).resolve().parents[1]
FIX_SQL = _REPO_ROOT / "sql" / "postgres" / "fix_ad_impressions_lookup_alignment.sql"


def audit() -> int:
    conn = connect_postgres()
    cur = conn.cursor()
    bad = 0

    cur.execute(
        """
        SELECT COUNT(*) FROM ad_impressions ai
        WHERE TRIM(COALESCE(ai.ad_category, '')) <> ''
          AND NOT EXISTS (
            SELECT 1 FROM interests it
            WHERE it.interest_name = LEFT(TRIM(ai.ad_category), 200)
          )
        """
    )
    n = cur.fetchone()[0]
    print(f"ad_impressions rows with no matching interests.interest_name: {n}")
    bad += n

    cur.execute(
        """
        SELECT COUNT(*) FROM ad_impressions ai
        WHERE TRIM(COALESCE(ai.gender, '')) <> ''
          AND NOT EXISTS (
            SELECT 1 FROM demographics d
            WHERE d.race IS NULL AND LOWER(TRIM(d.gender)) = LOWER(TRIM(ai.gender))
          )
        """
    )
    n = cur.fetchone()[0]
    print(f"ad_impressions rows with no matching demographics (race IS NULL): {n}")
    bad += n

    cur.execute(
        """
        SELECT COUNT(*) FROM ad_impressions ai
        JOIN interests it ON LOWER(TRIM(it.interest_name)) = LOWER(TRIM(ai.ad_category))
        WHERE it.interest_name <> TRIM(ai.ad_category)
          AND TRIM(COALESCE(ai.ad_category, '')) <> ''
        """
    )
    n = cur.fetchone()[0]
    print(f"rows needing category canonicalization (case/spacing vs interests): {n}")
    bad += n

    cur.execute(
        """
        SELECT COUNT(*) FROM ad_impressions ai
        JOIN demographics d ON d.race IS NULL AND LOWER(TRIM(d.gender)) = LOWER(TRIM(ai.gender))
        WHERE d.gender <> TRIM(ai.gender)
          AND TRIM(COALESCE(ai.gender, '')) <> ''
        """
    )
    n = cur.fetchone()[0]
    print(f"rows needing gender canonicalization vs demographics: {n}")
    bad += n

    cur.close()
    conn.close()

    if bad == 0:
        print("OK: no referential drift detected for text dimensions.")
        return 0
    print("Issues found — run: python -m etl.referential_integrity align")
    return 1


def align() -> int:
    if not FIX_SQL.is_file():
        print(f"Missing {FIX_SQL}", file=sys.stderr)
        return 1
    sql = FIX_SQL.read_text(encoding="utf-8")
    conn = connect_postgres()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute(sql)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"align failed: {exc}", file=sys.stderr)
        return 1
    finally:
        cur.close()
        conn.close()
    print("Applied sql/postgres/fix_ad_impressions_lookup_alignment.sql successfully.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Referential integrity for ad_impressions.")
    parser.add_argument("command", choices=["audit", "align"], help="audit (read-only) or align (apply fix SQL)")
    args = parser.parse_args()
    if args.command == "audit":
        return audit()
    return align()


if __name__ == "__main__":
    raise SystemExit(main())
