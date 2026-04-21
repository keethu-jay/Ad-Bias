#!/usr/bin/env python3
"""
ClearBias — Load Criteo Display Advertising Challenge train.csv into the 22-table BCNF schema.

Dataset: https://www.kaggle.com/c/criteo-display-ad-challenge/data
Columns: label, I1..I13, C1..C26 (tab-separated in the original; comma also supported).

Heuristic mapping (anonymized features → relational facts):
  - label               -> bias_scores.score_value (forced to 0.0 or 1.0), metric \"Criteo_Click\"
  - hash(C1|C2|C3)      -> regions row (synthetic bucket, bounded cardinality)
  - C4, C5              -> folded into headline/body text (raw tokens preserved)
  - I1..I13, C6..C26    -> body_text tail (pipe-delimited, truncated)

Loads ~1M rows using chunked reads + executemany on ad_creatives, ad_content, bias_scores.

Requires: python -m pip install oracledb
Schema: python -m legacy_oracle.create_schema
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
import time
from typing import Any

from legacy_oracle.oracle_config import connect_oracle

try:
    import oracledb
except ImportError:
    oracledb = None  # type: ignore

NULL_TOKENS = {"", "na", "n/a", "null", "none", "-1"}


def _connect():
    if oracledb is None:
        raise RuntimeError("pip install oracledb")
    return connect_oracle(prompt_for_password=True)


def norm_token(val: str | None) -> str | None:
    if val is None:
        return None
    s = val.strip()
    if s.lower() in NULL_TOKENS:
        return None
    return s


def clean_float_label(val: str | None) -> float:
    t = norm_token(val)
    if t is None:
        return 0.0
    try:
        v = float(t)
        return 1.0 if v >= 1.0 else 0.0
    except ValueError:
        return 0.0


def detect_dialect(sample_line: str) -> str:
    return "excel-tab" if sample_line.count("\t") > sample_line.count(",") else "excel"


def _get_one(cur, sql: str, params: dict[str, Any] | None = None) -> Any:
    cur.execute(sql, params or {})
    row = cur.fetchone()
    return row[0] if row else None


def ensure_seed_rows(cur, conn) -> dict[str, int]:
    ids: dict[str, int] = {}

    def ins_industry():
        cur.execute("SELECT industry_id FROM industries WHERE name = :n", {"n": "Criteo-Synthetic"})
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute("INSERT INTO industries (name) VALUES (:n)", {"n": "Criteo-Synthetic"})
        cur.execute("SELECT industry_id FROM industries WHERE name = :n", {"n": "Criteo-Synthetic"})
        return int(cur.fetchone()[0])

    def ins_advertiser(iid: int):
        cur.execute("SELECT advertiser_id FROM advertisers WHERE name = :n", {"n": "Criteo-Default-Advertiser"})
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute(
            "INSERT INTO advertisers (name, industry_id) VALUES (:n, :i)",
            {"n": "Criteo-Default-Advertiser", "i": iid},
        )
        cur.execute("SELECT advertiser_id FROM advertisers WHERE name = :n", {"n": "Criteo-Default-Advertiser"})
        return int(cur.fetchone()[0])

    def ins_campaign(aid: int):
        cur.execute("SELECT MIN(campaign_id) FROM campaigns WHERE advertiser_id = :a", {"a": aid})
        row = cur.fetchone()
        if row and row[0] is not None:
            return int(row[0])
        cur.execute(
            "INSERT INTO campaigns (advertiser_id, start_date, end_date) VALUES (:a, DATE '2014-01-01', NULL)",
            {"a": aid},
        )
        cur.execute("SELECT MAX(campaign_id) FROM campaigns WHERE advertiser_id = :a", {"a": aid})
        return int(cur.fetchone()[0])

    def ins_platform():
        cur.execute("SELECT platform_id FROM platforms WHERE name = :n", {"n": "Criteo"})
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute("INSERT INTO platforms (name) VALUES (:n)", {"n": "Criteo"})
        cur.execute("SELECT platform_id FROM platforms WHERE name = :n", {"n": "Criteo"})
        return int(cur.fetchone()[0])

    def ins_metric():
        cur.execute("SELECT bias_metric_id FROM bias_metrics WHERE metric_name = :n", {"n": "Criteo_Click"})
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute("INSERT INTO bias_metrics (metric_name) VALUES (:n)", {"n": "Criteo_Click"})
        cur.execute("SELECT bias_metric_id FROM bias_metrics WHERE metric_name = :n", {"n": "Criteo_Click"})
        return int(cur.fetchone()[0])

    def ins_query_template():
        n = int(_get_one(cur, "SELECT COUNT(*) FROM query_templates") or 0)
        if n == 0:
            cur.execute(
                "INSERT INTO query_templates (sql_code) VALUES (TO_CLOB('SELECT COUNT(*) FROM ad_creatives'))"
            )
        return int(_get_one(cur, "SELECT MIN(query_template_id) FROM query_templates"))

    iid = ins_industry()
    aid = ins_advertiser(iid)
    cid = ins_campaign(aid)
    _ = ins_platform()
    mid = ins_metric()
    qid = ins_query_template()

    for name in ("B-Tree", "PGM"):
        cur.execute("SELECT COUNT(*) FROM index_types WHERE type_name = :n", {"n": name})
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO index_types (type_name) VALUES (:n)", {"n": name})

    conn.commit()
    ids["industry_id"] = iid
    ids["advertiser_id"] = aid
    ids["campaign_id"] = cid
    ids["metric_id"] = mid
    ids["query_template_id"] = qid
    return ids


def region_bucket_key(c1: str | None, c2: str | None, c3: str | None) -> tuple[str, str, str]:
    raw = f"{c1 or ''}|{c2 or ''}|{c3 or ''}"
    h = int(hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest(), 16)
    bucket = h % 10_000
    return (f"R-{bucket}", "NA", "US")


def region_id_for(cur, cache: dict[tuple[str, str, str], int], city: str, state: str, country: str) -> int:
    key = (city, state, country)
    if key in cache:
        return cache[key]
    cur.execute(
        """
        SELECT region_id FROM regions
        WHERE NVL(city,'__') = :c AND NVL(state,'__') = :s AND country = :co
        """,
        {"c": city, "s": state, "co": country},
    )
    row = cur.fetchone()
    if row:
        rid = int(row[0])
    else:
        cur.execute(
            "INSERT INTO regions (city, state, country) VALUES (:c, :s, :co)",
            {"c": city, "s": state, "co": country},
        )
        cur.execute(
            """
            SELECT region_id FROM regions
            WHERE NVL(city,'__') = :c AND NVL(state,'__') = :s AND country = :co
            """,
            {"c": city, "s": state, "co": country},
        )
        rid = int(cur.fetchone()[0])
    cache[key] = rid
    return rid


def load_chunk(
    cur,
    conn,
    rows: list[dict[str, str]],
    campaign_id: int,
    metric_id: int,
    region_cache: dict[tuple[str, str, str], int],
) -> int:
    if not rows:
        return 0

    creatives_batch: list[tuple[int, str]] = []
    headlines: list[str] = []
    bodies: list[str] = []
    scores: list[float] = []

    for r in rows:
        cvals = [norm_token(r.get(f"C{i}")) or "" for i in range(1, 27)]
        city, state, country = region_bucket_key(cvals[0], cvals[1], cvals[2])
        _ = region_id_for(cur, region_cache, city, state, country)

        headline = "|".join(cvals[0:5])[:500]
        tail_nums = [norm_token(r.get(f"I{i}")) or "" for i in range(1, 14)]
        body = ("|".join(tail_nums) + "||" + "|".join(cvals[5:]))[:4000]

        creatives_batch.append((campaign_id, "Criteo"))
        headlines.append(headline)
        bodies.append(body)
        scores.append(clean_float_label(r.get("label")))

    n = len(rows)
    cur.executemany(
        "INSERT INTO ad_creatives (campaign_id, format) VALUES (:1, :2)",
        creatives_batch,
    )

    cur.execute(
        """
        SELECT ad_creative_id FROM (
          SELECT ad_creative_id FROM ad_creatives
          WHERE campaign_id = :c
          ORDER BY ad_creative_id DESC
        )
        WHERE ROWNUM <= :n
        """,
        {"c": campaign_id, "n": n},
    )
    id_rows = cur.fetchall()
    ids = [int(x[0]) for x in id_rows]
    ids.reverse()
    if len(ids) != n:
        raise RuntimeError(f"Expected {n} new creative ids, got {len(ids)}")

    content_rows = [(ids[i], headlines[i], bodies[i]) for i in range(n)]
    cur.executemany(
        "INSERT INTO ad_content (ad_creative_id, headline, body_text) VALUES (:1, :2, :3)",
        content_rows,
    )

    bias_rows = [(ids[i], metric_id, scores[i]) for i in range(n)]
    cur.executemany(
        "INSERT INTO bias_scores (ad_id, metric_id, score_value) VALUES (:1, :2, :3)",
        bias_rows,
    )

    conn.commit()
    return n


def open_reader(path: str):
    f = open(path, newline="", encoding="utf-8", errors="replace")
    sample = f.readline()
    f.seek(0)
    dialect = detect_dialect(sample)
    reader = csv.DictReader(f, dialect=dialect)
    fields = reader.fieldnames or []
    clean = [x.strip() for x in fields if x]
    if not clean or clean[0].lower() != "label":
        f.seek(0)
        expected = ["label"] + [f"I{i}" for i in range(1, 14)] + [f"C{i}" for i in range(1, 27)]
        reader = csv.DictReader(f, fieldnames=expected, dialect=dialect)
    return f, reader


def load_csv(path: str, max_rows: int, chunk_size: int) -> None:
    conn = _connect()
    cur = conn.cursor()
    region_cache: dict[tuple[str, str, str], int] = {}

    seeds = ensure_seed_rows(cur, conn)
    campaign_id = seeds["campaign_id"]
    metric_id = seeds["metric_id"]

    inserted = 0
    t0 = time.perf_counter()

    f, reader = open_reader(path)
    try:
        batch: list[dict[str, str]] = []
        for row in reader:
            if inserted >= max_rows:
                break
            batch.append(row)
            if len(batch) >= chunk_size:
                take = min(len(batch), max_rows - inserted)
                inserted += load_chunk(cur, conn, batch[:take], campaign_id, metric_id, region_cache)
                batch = batch[take:]
                if inserted >= max_rows:
                    break
                print(f"  loaded {inserted} rows…", flush=True)
        if batch and inserted < max_rows:
            take = min(len(batch), max_rows - inserted)
            inserted += load_chunk(cur, conn, batch[:take], campaign_id, metric_id, region_cache)
    finally:
        f.close()

    cur.execute(
        """
        MERGE INTO data_source_metadata t
        USING (SELECT :name AS source_name, :cnt AS record_count FROM dual) s
        ON (t.source_name = s.source_name)
        WHEN MATCHED THEN UPDATE SET t.record_count = s.record_count
        WHEN NOT MATCHED THEN INSERT (source_name, record_count) VALUES (s.source_name, s.record_count)
        """,
        {"name": "Criteo_train", "cnt": inserted},
    )
    conn.commit()

    elapsed = time.perf_counter() - t0
    rate = inserted / max(elapsed, 1e-6)
    print(f"Done. Inserted {inserted} rows in {elapsed:.1f}s (~{rate:.0f} rows/s).")
    cur.close()
    conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Load Criteo train.csv into ClearBias Oracle schema.")
    p.add_argument("--csv", required=True, help="Path to train.csv")
    p.add_argument("--max-rows", type=int, default=1_000_000, help="Stop after this many rows (default 1M).")
    p.add_argument("--chunk-size", type=int, default=5000, help="Rows per batch.")
    args = p.parse_args()

    if oracledb is None:
        print("Install: pip install oracledb", file=sys.stderr)
        return 1

    load_csv(args.csv, max_rows=args.max_rows, chunk_size=args.chunk_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
