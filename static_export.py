"""
Build the static audit export: 14 CSV blobs in a ZIP, base64-encoded for browser download.

Layer 0 — architecture manifest (live Supabase vs frozen ZIP for Tableau).
Layers 1–13 — one CSV per audit query (same SQL as queries_live_supabase, row-capped).
"""

from __future__ import annotations

import base64
import csv
import io
import zipfile
from typing import Any

from benchmark import fetch_live_rows_as_dicts
from postgres_config import connect_postgres
from queries_live_supabase import get_live_sql, resolve_params

MAX_EXPORT_ROWS = 10_000


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "ad_id,bias_score,category,region,timestamp\n"
    buf = io.StringIO()
    fieldnames = ["ad_id", "bias_score", "category", "region", "timestamp"]
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(
            {
                "ad_id": r.get("ad_id", ""),
                "bias_score": r.get("bias_score", ""),
                "category": r.get("category", ""),
                "region": r.get("region", ""),
                "timestamp": r.get("timestamp", ""),
            }
        )
    return buf.getvalue()


def _architecture_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["layer", "role", "storage", "notes"])
    w.writerow(
        [
            "live",
            "Real-time bias detection and index benchmarking",
            "Supabase PostgreSQL",
            "1M ad_impressions; TEXT keys; B+ vs PGM-style BRIN/bitmap proxy (planner toggles + optional BRIN)",
        ]
    )
    w.writerow(
        [
            "static",
            "Frozen audit trail for regulatory reporting and Tableau",
            "ZIP of 13 query CSVs + this manifest",
            "Generated in RAM; base64 for browser download — no Databricks filesystem",
        ]
    )
    return buf.getvalue()


def build_static_export_zip_b64() -> tuple[str, dict[str, Any]]:
    """
    Returns (base64_zip, meta) where meta includes filenames and row counts per query.
    """
    conn = connect_postgres()
    cur = conn.cursor()
    meta: dict[str, Any] = {"files": [], "queries": {}}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        arch_name = "00_architecture_manifest.csv"
        zf.writestr(arch_name, _architecture_csv())
        meta["files"].append(arch_name)

        for n in range(1, 14):
            qid = f"Q{n}"
            sql = get_live_sql(qid).strip().rstrip(";")
            if "LIMIT" not in sql.upper():
                sql = f"{sql} LIMIT {MAX_EXPORT_ROWS}"
            params = resolve_params(conn, qid)
            cur.execute(sql, params)
            rows_out = fetch_live_rows_as_dicts(cur)
            fname = f"audit_query_{n:02d}_{qid.lower()}.csv"
            zf.writestr(fname, _rows_to_csv(rows_out))
            meta["files"].append(fname)
            meta["queries"][qid] = len(rows_out)

    cur.close()
    conn.close()

    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    meta["zip_bytes"] = len(buf.getvalue())
    return b64, meta
