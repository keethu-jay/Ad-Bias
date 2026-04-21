#!/usr/bin/env python3
"""
Stream up to 1M rows from Hugging Face Criteo into PostgreSQL using psycopg2.execute_values.

Run from repo root:  python -m etl.hf_to_postgres_load  (see --help)

Source default: reczoo/Criteo_x4 (Parquet; streaming works).
Note: criteo/CriteoClickLogs is not loadable via ``datasets`` without custom parsing; use ``python -m etl.download_criteo_data`` + raw path if you need that corpus.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from typing import Any, Iterator

from psycopg2.extras import execute_values

from postgres_config import connect_postgres


def norm_label(val: Any) -> float:
    try:
        return 1.0 if float(val) >= 1.0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def to_bigint_with_fallback(val: Any) -> int:
    if val is None:
        return 0
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if val != val:  # NaN
            return 0
        return int(val)
    s = str(val).strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        digits = "".join(ch for ch in s if ch.isdigit() or ch == "-")
        if not digits or digits == "-":
            return 0
        try:
            return int(digits)
        except ValueError:
            return 0


def normalize_time_metrics(rec: dict[str, Any]) -> dict[str, int]:
    """
    Cast all Criteo time-ish columns to BIGINT with fallback to 0.
    """
    out: dict[str, int] = {}
    for k, v in rec.items():
        lk = k.lower()
        if "time" in lk or "timestamp" in lk or lk in {"day", "hour"}:
            out[k] = to_bigint_with_fallback(v)
    if "day" not in out:
        out["day"] = to_bigint_with_fallback(rec.get("day") or rec.get("Day"))
    return out


def posted_at_from_time_metrics(metrics: dict[str, int]) -> datetime:
    ts = 0
    for key in ("timestamp", "Timestamp", "time", "Time", "hour", "day"):
        if key in metrics and metrics[key] > 0:
            ts = metrics[key]
            break
    if ts <= 0:
        return datetime.now(UTC)
    if ts < 10_000_000_000:
        return datetime.fromtimestamp(ts, tz=UTC)
    return datetime.fromtimestamp(ts / 1000.0, tz=UTC)


def fetch_or_create_id(cur, select_sql: str, insert_sql: str, params: tuple[Any, ...]) -> int:
    cur.execute(select_sql, params)
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute(insert_sql, params)
    return int(cur.fetchone()[0])


def ensure_seed_rows(cur) -> tuple[int, int]:
    industry_id = fetch_or_create_id(
        cur,
        "SELECT industry_id FROM industries WHERE name = %s",
        "INSERT INTO industries (name) VALUES (%s) RETURNING industry_id",
        ("Criteo-Synthetic",),
    )
    advertiser_id = fetch_or_create_id(
        cur,
        "SELECT advertiser_id FROM advertisers WHERE name = %s",
        "INSERT INTO advertisers (name, industry_id) VALUES (%s, %s) RETURNING advertiser_id",
        ("Criteo-Default-Advertiser", industry_id),
    )
    cur.execute("SELECT campaign_id FROM campaigns WHERE advertiser_id = %s ORDER BY campaign_id LIMIT 1", (advertiser_id,))
    row = cur.fetchone()
    if row:
        campaign_id = int(row[0])
    else:
        cur.execute(
            """
            INSERT INTO campaigns (advertiser_id, start_date, end_date)
            VALUES (%s, DATE '2026-01-01', NULL)
            RETURNING campaign_id
            """,
            (advertiser_id,),
        )
        campaign_id = int(cur.fetchone()[0])

    _ = fetch_or_create_id(
        cur,
        "SELECT platform_id FROM platforms WHERE name = %s",
        "INSERT INTO platforms (name) VALUES (%s) RETURNING platform_id",
        ("Criteo",),
    )
    metric_id = fetch_or_create_id(
        cur,
        "SELECT bias_metric_id FROM bias_metrics WHERE metric_name = %s",
        "INSERT INTO bias_metrics (metric_name) VALUES (%s) RETURNING bias_metric_id",
        ("Criteo_Click",),
    )
    cur.execute("INSERT INTO index_types (type_name) VALUES (%s) ON CONFLICT (type_name) DO NOTHING", ("B-Tree",))
    cur.execute("INSERT INTO index_types (type_name) VALUES (%s) ON CONFLICT (type_name) DO NOTHING", ("PGM",))
    return campaign_id, metric_id


def pick_category(rec: dict[str, Any]) -> str:
    for key in ("C1", "c1", "C2", "c2", "category"):
        val = rec.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()[:60]
    return "Unknown"


def region_from_record(rec: dict[str, Any]) -> tuple[str, str, str]:
    raw = f"{rec.get('C1') or ''}|{rec.get('C2') or ''}|{rec.get('C3') or ''}"
    h = int(hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest(), 16)
    bucket = h % 10_000
    return (f"R-{bucket}", "NA", "US")


def load_chunk(
    cur,
    rows: list[dict[str, Any]],
    campaign_id: int,
    metric_id: int,
) -> int:
    if not rows:
        return 0

    creative_rows: list[tuple[int, str]] = []
    content_rows: list[tuple[str, str]] = []
    score_rows: list[tuple[float, datetime]] = []
    region_rows: set[tuple[str, str, str]] = set()

    for rec in rows:
        if "label" not in rec and "Label" in rec:
            rec = {**rec, "label": rec.get("Label")}
        category = pick_category(rec)
        time_metrics = normalize_time_metrics(rec)
        posted_at = posted_at_from_time_metrics(time_metrics)
        label = norm_label(rec.get("label", rec.get("Label", 0)))

        headline = f"{category} | day={time_metrics.get('day', 0)}"
        body_payload = {
            "time_metrics_bigint": time_metrics,
            "I1": rec.get("I1"),
            "I2": rec.get("I2"),
            "I3": rec.get("I3"),
            "C1": rec.get("C1"),
            "C2": rec.get("C2"),
            "C3": rec.get("C3"),
        }

        creative_rows.append((campaign_id, category))
        content_rows.append((headline[:500], json.dumps(body_payload, separators=(",", ":"))))
        score_rows.append((label, posted_at))
        region_rows.add(region_from_record(rec))

    execute_values(
        cur,
        """
        INSERT INTO regions (city, state, country) VALUES %s
        ON CONFLICT (city, state, country) DO NOTHING
        """,
        list(region_rows),
        template="(%s, %s, %s)",
        page_size=1000,
    )

    execute_values(
        cur,
        "INSERT INTO ad_creatives (campaign_id, format) VALUES %s RETURNING ad_creative_id",
        creative_rows,
        template="(%s, %s)",
        page_size=2000,
    )
    creative_ids = [int(r[0]) for r in cur.fetchall()]
    if len(creative_ids) != len(rows):
        raise RuntimeError(f"Expected {len(rows)} inserted creative ids, got {len(creative_ids)}")

    execute_values(
        cur,
        "INSERT INTO ad_content (ad_creative_id, headline, body_text) VALUES %s",
        [(creative_ids[i], content_rows[i][0], content_rows[i][1]) for i in range(len(creative_ids))],
        template="(%s, %s, %s)",
        page_size=2000,
    )

    execute_values(
        cur,
        "INSERT INTO bias_scores (ad_id, metric_id, score_value, measured_at) VALUES %s",
        [(creative_ids[i], metric_id, score_rows[i][0], score_rows[i][1]) for i in range(len(creative_ids))],
        template="(%s, %s, %s, %s)",
        page_size=2000,
    )
    return len(rows)


def iter_local_csv_gz_rows(local_dir: str) -> Iterator[dict[str, Any]]:
    """Stream rows from train_part*.csv.gz (same layout as etl.download_criteo_data)."""
    names = sorted(f for f in os.listdir(local_dir) if f.startswith("train_part") and f.endswith(".csv.gz"))
    if not names:
        raise FileNotFoundError(f"No train_part*.csv.gz under {local_dir}")
    for name in names:
        path = os.path.join(local_dir, name)
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                yield {k: (v or "").strip() if v is not None else "" for k, v in row.items()}


def stream_local(
    local_dir: str,
    max_rows: int,
    chunk_size: int,
) -> int:
    conn = connect_postgres()
    cur = conn.cursor()
    try:
        campaign_id, metric_id = ensure_seed_rows(cur)
        conn.commit()

        inserted = 0
        t0 = time.perf_counter()
        chunk: list[dict[str, Any]] = []

        for rec in iter_local_csv_gz_rows(local_dir):
            if inserted >= max_rows:
                break
            chunk.append(rec)
            if len(chunk) >= chunk_size:
                take = min(len(chunk), max_rows - inserted)
                if take <= 0:
                    break
                inserted += load_chunk(cur, chunk[:take], campaign_id, metric_id)
                conn.commit()
                chunk = chunk[take:]
                print(f"  loaded {inserted} rows...", flush=True)
                if inserted >= max_rows:
                    break

        if chunk and inserted < max_rows:
            take = min(len(chunk), max_rows - inserted)
            inserted += load_chunk(cur, chunk[:take], campaign_id, metric_id)
            conn.commit()

        tag = f"LOCAL:{os.path.abspath(local_dir)}"[:200]
        upsert_source_metadata(cur, tag, inserted)
        conn.commit()
        elapsed = time.perf_counter() - t0
        print(f"Done. Inserted {inserted} rows in {elapsed:.1f}s (~{inserted / max(elapsed, 1e-6):.0f} rows/s).")
        return inserted
    finally:
        cur.close()
        conn.close()


def upsert_source_metadata(cur, source_name: str, record_count: int) -> None:
    cur.execute(
        """
        INSERT INTO data_source_metadata (source_name, record_count, updated_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (source_name)
        DO UPDATE SET
            record_count = EXCLUDED.record_count,
            updated_at = CURRENT_TIMESTAMP
        """,
        (source_name[:200], record_count),
    )


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
        campaign_id, metric_id = ensure_seed_rows(cur)
        conn.commit()

        ds = load_dataset(dataset_id, split=split, streaming=True)
        inserted = 0
        t0 = time.perf_counter()
        chunk: list[dict[str, Any]] = []

        for rec in ds:
            if "label" not in rec and "Label" in rec:
                rec = {**rec, "label": rec.get("Label")}
            chunk.append(rec)
            if len(chunk) >= chunk_size:
                take = min(len(chunk), max_rows - inserted)
                if take <= 0:
                    break
                inserted += load_chunk(cur, chunk[:take], campaign_id, metric_id)
                conn.commit()
                chunk = chunk[take:]
                print(f"  loaded {inserted} rows...", flush=True)
                if inserted >= max_rows:
                    break

        if chunk and inserted < max_rows:
            take = min(len(chunk), max_rows - inserted)
            inserted += load_chunk(cur, chunk[:take], campaign_id, metric_id)
            conn.commit()

        upsert_source_metadata(cur, f"HF:{dataset_id}:{split}", inserted)
        conn.commit()
        elapsed = time.perf_counter() - t0
        print(f"Done. Inserted {inserted} rows in {elapsed:.1f}s (~{inserted / max(elapsed, 1e-6):.0f} rows/s).")
        return inserted
    finally:
        cur.close()
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Load Hugging Face Criteo data into ClearBias PostgreSQL schema.")
    parser.add_argument(
        "--dataset",
        default="reczoo/Criteo_x4",
        help="Hugging Face dataset id (default: reczoo/Criteo_x4).",
    )
    parser.add_argument("--split", default="train", help="Dataset split.")
    parser.add_argument(
        "--from-local",
        metavar="DIR",
        help="Stream from local train_part*.csv.gz (e.g. data/criteo) instead of Hugging Face.",
    )
    parser.add_argument("--max-rows", type=int, default=1_000_000, help="Target rows to ingest.")
    parser.add_argument("--chunk-size", type=int, default=5000, help="Batch size for execute_values.")
    args = parser.parse_args()

    cs = max(500, args.chunk_size)
    if args.from_local:
        inserted = stream_local(
            local_dir=args.from_local,
            max_rows=args.max_rows,
            chunk_size=cs,
        )
    else:
        inserted = stream_hf(
            dataset_id=args.dataset,
            split=args.split,
            max_rows=args.max_rows,
            chunk_size=cs,
        )
    print(f"Final inserted rows: {inserted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
