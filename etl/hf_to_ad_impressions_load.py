#!/usr/bin/env python3
"""
Stream Hugging Face Criteo-style rows into public.ad_impressions (Postgres/Supabase).

Run from repo root:  python -m etl.hf_to_ad_impressions_load  (see --help)

Demographics are synthesized so Databricks notebook literals (25-34, F, Housing, Northeast,
2023 H1 time range, spend > 5) return rows. Default dataset: reczoo/Criteo_x4.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg2.extras import execute_values

from postgres_config import connect_postgres


def _h(seed: str) -> int:
    return int(hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest(), 16)


def _norm_click(rec: dict[str, Any]) -> int:
    if "label" not in rec and "Label" in rec:
        rec = {**rec, "label": rec.get("Label")}
    raw = rec.get("label", rec.get("Label", 0))
    try:
        return 1 if float(raw) >= 1.0 else 0
    except (TypeError, ValueError):
        return 0


def _row_to_impression(idx: int, rec: dict[str, Any]) -> tuple[Any, ...]:
    """Returns tuple for INSERT columns (no impression_id)."""
    click_flag = _norm_click(rec)

    # Align with Databricks notebook filter literals on a periodic slice of rows.
    if idx % 50 == 0:
        age_group = "25-34"
        gender = "F"
        ad_category = "Housing"
        region = "Northeast"
    else:
        h = _h(f"{idx}|{rec.get('C1')}|{rec.get('C2')}|{rec.get('label')}")
        age_groups = ["18-24", "25-34", "35-44", "45-54", "55+"]
        age_group = age_groups[h % 5]
        gender = "F" if (h // 5) % 2 == 0 else "M"
        ad_category = ["Housing", "Finance", "Health", "Retail", "Auto", "News"][h % 6]
        region = ["Northeast", "Southeast", "Midwest", "West", "South"][h % 5]

    platform = ["Web", "Mobile", "Tablet"][_h(f"p|{idx}") % 3]

    hh = _h(f"s|{idx}|{rec.get('I1')}")
    spend_usd = round(0.5 + (hh % 10_000) / 800.0, 4)
    if idx % 3 == 0 or idx % 50 == 0:
        spend_usd = round(5.5 + (hh % 500) / 50.0, 4)

    # Q10 notebook range: 2023-01-01 .. 2023-06-30
    start = datetime(2023, 1, 1, tzinfo=UTC)
    day_off = hh % 180
    hour = hh % 24
    minute = (hh // 7) % 60
    impression_time = start + timedelta(days=day_off, hours=hour, minutes=minute)

    return (age_group, gender, ad_category, platform, region, click_flag, spend_usd, impression_time)


def stream_hf(
    dataset_id: str,
    split: str,
    max_rows: int,
    chunk_size: int,
) -> int:
    from datasets import load_dataset

    conn = connect_postgres()
    cur = conn.cursor()
    try:
        ds = load_dataset(dataset_id, split=split, streaming=True)
        inserted = 0
        t0 = time.perf_counter()
        chunk: list[tuple[Any, ...]] = []
        base_idx = 0

        for rec in ds:
            if inserted >= max_rows:
                break
            chunk.append(_row_to_impression(base_idx, rec))
            base_idx += 1
            if len(chunk) >= chunk_size:
                take = min(len(chunk), max_rows - inserted)
                if take <= 0:
                    break
                execute_values(
                    cur,
                    """
                    INSERT INTO ad_impressions (
                      age_group, gender, ad_category, platform, region,
                      click_flag, spend_usd, impression_time
                    ) VALUES %s
                    """,
                    chunk[:take],
                    template="(%s, %s, %s, %s, %s, %s, %s, %s)",
                    page_size=take,
                )
                conn.commit()
                inserted += take
                chunk = chunk[take:]
                print(f"  loaded {inserted} rows...", flush=True)
                if inserted >= max_rows:
                    break

        if chunk and inserted < max_rows:
            take = min(len(chunk), max_rows - inserted)
            execute_values(
                cur,
                """
                INSERT INTO ad_impressions (
                  age_group, gender, ad_category, platform, region,
                  click_flag, spend_usd, impression_time
                ) VALUES %s
                """,
                chunk[:take],
                template="(%s, %s, %s, %s, %s, %s, %s, %s)",
                page_size=take,
            )
            conn.commit()
            inserted += take

        elapsed = time.perf_counter() - t0
        print(f"Done. Inserted {inserted} rows in {elapsed:.1f}s (~{inserted / max(elapsed, 1e-6):.0f} rows/s).")
        return inserted
    finally:
        cur.close()
        conn.close()


def truncate_table() -> None:
    conn = connect_postgres(autocommit=True)
    cur = conn.cursor()
    try:
        cur.execute("TRUNCATE ad_impressions RESTART IDENTITY CASCADE")
    finally:
        cur.close()
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Load HF Criteo data into ad_impressions.")
    parser.add_argument("--dataset", default="reczoo/Criteo_x4", help="Hugging Face dataset id.")
    parser.add_argument("--split", default="train", help="Split name.")
    parser.add_argument("--max-rows", type=int, default=1_000_000, help="Max rows to ingest.")
    parser.add_argument("--chunk-size", type=int, default=5000, help="Batch size.")
    parser.add_argument(
        "--truncate-first",
        action="store_true",
        help="TRUNCATE ad_impressions before loading (destructive).",
    )
    args = parser.parse_args()

    if args.truncate_first:
        print("Truncating ad_impressions...", flush=True)
        truncate_table()

    cs = max(500, args.chunk_size)
    try:
        inserted = stream_hf(
            dataset_id=args.dataset,
            split=args.split,
            max_rows=args.max_rows,
            chunk_size=cs,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Load failed: {exc}", file=sys.stderr)
        return 1

    print(f"Final inserted rows: {inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
