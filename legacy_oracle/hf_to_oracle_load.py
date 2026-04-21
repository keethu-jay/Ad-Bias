#!/usr/bin/env python3
"""
ClearBias — Stream Criteo-style rows from Hugging Face into the same Oracle path as load_data.py.

Uses the same inserts as load_data (ad_creatives → ad_content → bias_scores) via load_chunk().

Default source: reczoo/Criteo_x4 (Parquet on the Hub; Kaggle Display Challenge schema, preprocessed).
  The official criteo/CriteoClickLogs repo only hosts raw .gz days; ``datasets`` cannot load it without a
  custom parser. For that data, use --raw-tsv-gz on a downloaded day_*.gz file.

Requires:
  pip install datasets pandas oracledb
  ORACLE_* env vars (see legacy_oracle/oracle_config.py)
  Schema: python -m legacy_oracle.create_schema
"""

from __future__ import annotations

import argparse
import gzip
import sys
import time
from typing import Any, Iterator

from legacy_oracle.oracle_config import connect_oracle

try:
    import oracledb
except ImportError:
    oracledb = None  # type: ignore

from legacy_oracle.load_data import ensure_seed_rows, load_chunk


def _connect():
    if oracledb is None:
        raise RuntimeError("pip install oracledb")
    return connect_oracle(prompt_for_password=True)


def _safe_close(cur, conn) -> None:
    try:
        if cur is not None:
            cur.close()
    except Exception:
        pass
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass


def _is_disconnect_error(exc: BaseException) -> bool:
    msg = str(exc).upper()
    markers = (
        "DPY-4011",
        "DPY-1001",
        "DPI-1010",
        "DPI-1080",
        "ORA-03113",
        "ORA-03114",
        "ORA-03135",
        "WINERROR 10054",
        "WINERROR 10060",
    )
    return any(m in msg for m in markers)


def _open_session():
    conn = _connect()
    cur = conn.cursor()
    seeds = ensure_seed_rows(cur, conn)
    return conn, cur, seeds["campaign_id"], seeds["metric_id"]


def _load_chunk_with_retry(
    cur,
    conn,
    batch_rows: list[dict[str, str]],
    campaign_id: int,
    metric_id: int,
    region_cache: dict[tuple[str, str, str], int],
    max_retries: int,
    retry_delay_s: float,
):
    attempt = 0
    while True:
        try:
            inserted = load_chunk(cur, conn, batch_rows, campaign_id, metric_id, region_cache)
            return inserted, conn, cur, campaign_id, metric_id
        except Exception as exc:
            if not _is_disconnect_error(exc) or attempt >= max_retries:
                raise
            wait_s = retry_delay_s * (2**attempt)
            print(
                f"  connection dropped ({exc}). Reconnecting in {wait_s:.1f}s "
                f"(attempt {attempt + 1}/{max_retries})...",
                flush=True,
            )
            _safe_close(cur, conn)
            time.sleep(wait_s)
            conn, cur, campaign_id, metric_id = _open_session()
            attempt += 1


def _upsert_metadata_with_retry(
    cur,
    conn,
    source_tag: str,
    inserted: int,
    max_retries: int,
    retry_delay_s: float,
):
    attempt = 0
    while True:
        try:
            cur.execute(
                """
                MERGE INTO data_source_metadata t
                USING (SELECT :name AS source_name, :cnt AS record_count FROM dual) s
                ON (t.source_name = s.source_name)
                WHEN MATCHED THEN UPDATE SET t.record_count = s.record_count
                WHEN NOT MATCHED THEN INSERT (source_name, record_count) VALUES (s.source_name, s.record_count)
                """,
                {"name": source_tag, "cnt": inserted},
            )
            conn.commit()
            return conn, cur
        except Exception as exc:
            if not _is_disconnect_error(exc) or attempt >= max_retries:
                raise
            wait_s = retry_delay_s * (2**attempt)
            print(
                f"  connection dropped during metadata upsert ({exc}). "
                f"Reconnecting in {wait_s:.1f}s (attempt {attempt + 1}/{max_retries})...",
                flush=True,
            )
            _safe_close(cur, conn)
            time.sleep(wait_s)
            conn, cur, _, _ = _open_session()
            attempt += 1


def hf_record_to_row(rec: dict[str, Any]) -> dict[str, str]:
    """Map a Hugging Face row (Label/I1/C1…) to load_data CSV-style dict (label/I1/…)."""
    lab = rec.get("label")
    if lab is None:
        lab = rec.get("Label")
    if lab is None:
        lab = 0
    try:
        label_s = str(int(float(lab)))
    except (TypeError, ValueError):
        label_s = (str(lab).strip() or "0")

    out: dict[str, str] = {"label": label_s}
    for i in range(1, 14):
        k = f"I{i}"
        v = rec.get(k)
        out[k] = "" if v is None else str(v).strip()
    for i in range(1, 27):
        k = f"C{i}"
        v = rec.get(k)
        out[k] = "" if v is None else str(v).strip()
    return out


def parse_tsv_line(line: str) -> dict[str, str]:
    """One Criteo TSV line: label, I1..I13, C1..C26 (tab-separated)."""
    parts = line.rstrip("\n\r").split("\t")
    expected = 1 + 13 + 26
    if len(parts) < expected:
        parts = parts + [""] * (expected - len(parts))
    names = ["label"] + [f"I{i}" for i in range(1, 14)] + [f"C{i}" for i in range(1, 27)]
    return dict(zip(names, parts[:expected], strict=True))


def iter_raw_tsv_gz(path: str) -> Iterator[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield parse_tsv_line(line)


def load_from_hf(
    dataset_id: str,
    split: str,
    max_rows: int,
    chunk_size: int,
    source_tag: str,
    max_retries: int,
    retry_delay_s: float,
) -> int:
    from datasets import load_dataset

    conn, cur, campaign_id, metric_id = _open_session()
    region_cache: dict[tuple[str, str, str], int] = {}

    ds = load_dataset(dataset_id, split=split, streaming=True)
    inserted = 0
    t0 = time.perf_counter()
    batch: list[dict[str, str]] = []

    for rec in ds:
        if inserted >= max_rows:
            break
        batch.append(hf_record_to_row(rec))
        if len(batch) >= chunk_size:
            take = min(len(batch), max_rows - inserted)
            loaded, conn, cur, campaign_id, metric_id = _load_chunk_with_retry(
                cur,
                conn,
                batch[:take],
                campaign_id,
                metric_id,
                region_cache,
                max_retries,
                retry_delay_s,
            )
            inserted += loaded
            batch = batch[take:]
            print(f"  loaded {inserted} rows…", flush=True)
            if inserted >= max_rows:
                break

    if batch and inserted < max_rows:
        take = min(len(batch), max_rows - inserted)
        loaded, conn, cur, campaign_id, metric_id = _load_chunk_with_retry(
            cur,
            conn,
            batch[:take],
            campaign_id,
            metric_id,
            region_cache,
            max_retries,
            retry_delay_s,
        )
        inserted += loaded

    conn, cur = _upsert_metadata_with_retry(
        cur,
        conn,
        source_tag,
        inserted,
        max_retries,
        retry_delay_s,
    )

    elapsed = time.perf_counter() - t0
    rate = inserted / max(elapsed, 1e-6)
    print(f"Done. Inserted {inserted} rows in {elapsed:.1f}s (~{rate:.0f} rows/s).")
    cur.close()
    conn.close()
    return inserted


def load_from_raw_gz(
    path: str,
    max_rows: int,
    chunk_size: int,
    max_retries: int,
    retry_delay_s: float,
) -> int:
    conn, cur, campaign_id, metric_id = _open_session()
    region_cache: dict[tuple[str, str, str], int] = {}

    inserted = 0
    t0 = time.perf_counter()
    batch: list[dict[str, str]] = []

    for row in iter_raw_tsv_gz(path):
        if inserted >= max_rows:
            break
        batch.append(row)
        if len(batch) >= chunk_size:
            take = min(len(batch), max_rows - inserted)
            loaded, conn, cur, campaign_id, metric_id = _load_chunk_with_retry(
                cur,
                conn,
                batch[:take],
                campaign_id,
                metric_id,
                region_cache,
                max_retries,
                retry_delay_s,
            )
            inserted += loaded
            batch = batch[take:]
            print(f"  loaded {inserted} rows…", flush=True)
            if inserted >= max_rows:
                break

    if batch and inserted < max_rows:
        take = min(len(batch), max_rows - inserted)
        loaded, conn, cur, campaign_id, metric_id = _load_chunk_with_retry(
            cur,
            conn,
            batch[:take],
            campaign_id,
            metric_id,
            region_cache,
            max_retries,
            retry_delay_s,
        )
        inserted += loaded

    tag = f"Criteo_tsv_gz:{path}"
    conn, cur = _upsert_metadata_with_retry(
        cur,
        conn,
        tag[:200],
        inserted,
        max_retries,
        retry_delay_s,
    )

    elapsed = time.perf_counter() - t0
    rate = inserted / max(elapsed, 1e-6)
    print(f"Done. Inserted {inserted} rows in {elapsed:.1f}s (~{rate:.0f} rows/s).")
    cur.close()
    conn.close()
    return inserted


def main() -> int:
    p = argparse.ArgumentParser(
        description="Stream Criteo data (Hugging Face or local .tsv.gz) into ClearBias Oracle tables."
    )
    p.add_argument(
        "--dataset",
        default="reczoo/Criteo_x4",
        help="Hugging Face dataset id (default: reczoo/Criteo_x4, Parquet; works with streaming).",
    )
    p.add_argument("--split", default="train", help="Split name (default: train).")
    p.add_argument("--max-rows", type=int, default=1_000_000, help="Stop after this many rows.")
    p.add_argument("--chunk-size", type=int, default=5000, help="Rows per Oracle batch.")
    p.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Reconnect attempts on transient Oracle/network disconnects.",
    )
    p.add_argument(
        "--retry-delay",
        type=float,
        default=2.0,
        help="Base seconds before retry; uses exponential backoff.",
    )
    p.add_argument(
        "--raw-tsv-gz",
        metavar="PATH",
        help="If set, load from a local Criteo day_*.gz (tab-separated) instead of Hugging Face.",
    )
    args = p.parse_args()

    if oracledb is None:
        print("Install: pip install oracledb", file=sys.stderr)
        return 1

    try:
        import datasets  # noqa: F401
    except ImportError:
        if not args.raw_tsv_gz:
            print("Install: pip install datasets pandas", file=sys.stderr)
            return 1

    if args.raw_tsv_gz:
        load_from_raw_gz(
            args.raw_tsv_gz,
            max_rows=args.max_rows,
            chunk_size=args.chunk_size,
            max_retries=args.max_retries,
            retry_delay_s=max(0.1, args.retry_delay),
        )
        return 0

    tag = f"Criteo_HF_{args.dataset.replace('/', '_')}_{args.split}"
    load_from_hf(
        args.dataset,
        args.split,
        max_rows=args.max_rows,
        chunk_size=args.chunk_size,
        source_tag=tag[:200],
        max_retries=args.max_retries,
        retry_delay_s=max(0.1, args.retry_delay),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
