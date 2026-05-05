"""
ClearBias — Flask API and dashboard for bias-query benchmarking.

- Default path: Postgres/Supabase (`USE_POSTGRES=true`) with live SQL in `queries_live_supabase.py`.
- Optional: `USE_ORACLE=true` uses `legacy_oracle/` (BCNF + V$SQL timing).
- Otherwise: mock latencies.

Env (see also `postgres_config.py`, `legacy_oracle/oracle_config.py`):
  USE_POSTGRES, CLEARBIAS_POSTGRES_DSN / PG* vars
  USE_ORACLE, ORACLE_* (only if Oracle path enabled)
  PORT — Flask listen port (default 5000)
"""

from __future__ import annotations

import os
import csv
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from benchmark import (
    run_validated_query_mock,
    run_validated_query_oracle,
    run_validated_query_postgres,
    variance_pct,
)
from legacy_oracle.queries import get_query

app = Flask(__name__)
CORS(app)
_ROOT = os.path.dirname(os.path.abspath(__file__))
_AUDIT_VISUALS_DIR = os.path.join(_ROOT, "audit_visuals")
_DATABRICKS_BENCHMARK_CSV = os.path.join(_ROOT, "ClearBias_Audit_Files", "benchmark_performance_results.csv")
_DATABRICKS_NOTEBOOK_URL = (
    "https://dbc-23063686-87f0.cloud.databricks.com/editor/notebooks/2216068845186789"
    "?o=7474645010599702"
)

QUERY_LABELS = {
    1: "Point Lookup",
    2: "Range on impression_id",
    3: "Filter by Age Group",
    4: "Filter by Gender",
    5: "Multi-Dimensional (modal bias slice)",
    6: "Count by Category",
    7: "Count by Demo Group",
    8: "CTR by Category",
    9: "Avg Spend by Demo",
    10: "Time Range Filter",
    11: "High Spend Filter",
    12: "Region + Category Filter",
    13: "Full Bias Audit",
}

_supabase = None
_supabase_checked = False


def get_supabase():
    """Lazy init for Supabase REST client (optional; needs SUPABASE_URL + key env vars)."""
    global _supabase, _supabase_checked
    if _supabase_checked:
        return _supabase
    _supabase_checked = True
    url = (os.environ.get("SUPABASE_URL") or "").strip()
    key = (
        (os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPERBASE_ANON_KEY") or "")
        .strip()
    )
    if not url or not key:
        return None
    try:
        from supabase import create_client

        _supabase = create_client(url, key)
    except Exception:
        _supabase = None
    return _supabase
USE_ORACLE = os.environ.get("USE_ORACLE", "false").lower() in ("1", "true", "yes")
USE_POSTGRES = os.environ.get("USE_POSTGRES", "true").lower() in ("1", "true", "yes")
_DEFAULT_METRIC_ID = int(os.environ.get("CLEARBIAS_METRIC_ID", "1"))

_MOCK_LATENCY_MS = {"B-Tree": 150, "PGM": 45}
QUERY_IDS = {f"Q{i}" for i in range(1, 14)}

# Legacy flat-table SQL for demos when USE_ORACLE=false timing path still references templates — unused when mock skips SQL.
SQL_TEMPLATES_LEGACY: dict[str, str] = {
    "Q1": "SELECT 1 FROM dual WHERE ROWNUM <= :limit",
}

# Binds for BCNF queries (includes :metric_id for bias_score join).
_QUERY_BINDS_BASE: dict[str, dict[str, Any]] = {
    "Q1": {"limit": 500},
    "Q2": {"cat": "Political"},
    "Q3": {"region": "NA"},
    "Q4": {"min_score": 0.5},
    "Q5": {"t0": "2026-01-01", "t1": "2026-12-31"},
    "Q6": {"limit": 500},
    "Q7": {"limit": 500},
    "Q8": {"fp": "image", "limit": 500},
    "Q9": {"aid": 1, "limit": 500},
    "Q10": {"r1": "NA", "r2": "EU", "limit": 500},
    "Q11": {"c": "News", "r": "EU", "limit": 500},
    "Q12": {"limit": 500},
    "Q13": {"limit": 500},
}

QUERY_BINDS: dict[str, dict[str, Any]] = {
    k: {**v, "metric_id": _DEFAULT_METRIC_ID} for k, v in _QUERY_BINDS_BASE.items()
}


def get_oracle_connection() -> Any:
    from legacy_oracle.oracle_config import connect_oracle

    return connect_oracle(prompt_for_password=False)


def use_postgres_live() -> bool:
    """Live Supabase/Postgres path when Oracle is off and DSN is configured."""
    if USE_ORACLE or not USE_POSTGRES:
        return False
    try:
        from postgres_config import get_postgres_dsn

        return bool(get_postgres_dsn().strip())
    except Exception:
        return False


ARCHITECTURE = {
    "live": {
        "name": "Live database (Supabase / PostgreSQL)",
        "role": "Real-time bias detection, index benchmarking, API queries",
        "row_count_hint": "~1,000,000 ad_impressions (normalized pipeline)",
        "keys": "TEXT ad_category / gender aligned to interests.industry_id → industries.name and demographics (race IS NULL)",
        "indexing": "B+ baseline: normal planner; PGM-style: BRIN(impression_id) + enable_indexscan/indexonlyscan off, bitmapscan on (sql/postgres/*.sql)",
    },
    "static": {
        "name": "Static exports (ZIP / Tableau)",
        "role": "Frozen audit trail for regulatory reporting and offline visualization",
        "format": "14 files: architecture manifest + 13 query CSVs; in-memory ZIP, base64 download",
        "query5_note": "Modal (densest) age × gender × ad_category slice for high-density Tableau samples",
    },
    "databricks_notebook": {
        "name": "Databricks compute notebook",
        "role": "Source notebook for ClearBias_Audit_Files/benchmark_performance_results.csv (dashboard snapshot chart).",
        "url": _DATABRICKS_NOTEBOOK_URL,
    },
}


def _mock_rows(query_id: str) -> list[dict[str, Any]]:
    base = hash(query_id) % 10000
    rows: list[dict[str, Any]] = []
    categories = ("Political", "Health", "Finance", "Social", "News")
    regions = ("NA", "EU", "APAC", "LATAM", "MEA")
    for i in range(80):
        n = base + i
        rows.append(
            {
                "ad_id": f"AD-{n:07d}",
                "bias_score": round(0.15 + (n % 73) / 100.0, 3),
                "category": categories[n % len(categories)],
                "region": regions[n % len(regions)],
                "timestamp": f"2026-04-{(n % 28) + 1:02d}T{(n % 12) + 8:02d}:{(n % 60):02d}:00Z",
            }
        )
    return rows


@app.route("/")
def index():
    return send_from_directory(_ROOT, "live_dashboard.html")


@app.route("/audit-visuals/<path:filename>", methods=["GET"])
def audit_visual_asset(filename: str):
    return send_from_directory(_AUDIT_VISUALS_DIR, filename)


@app.route("/api/results", methods=["GET"])
def api_benchmark_results():
    """Latest benchmark result per (query_id, method) from Supabase."""
    sb = get_supabase()
    if sb is None:
        return jsonify({"ok": False, "error": "Supabase not configured (set SUPABASE_URL and SUPABASE_KEY)."}), 503
    data = (
        sb.table("benchmark_results")
        .select("*")
        .order("run_at", desc=True)
        .execute()
    )
    seen: set[tuple[int, str]] = set()
    results: list[dict[str, Any]] = []
    for row in data.data or []:
        key = (int(row["query_id"]), str(row["method"]))
        if key not in seen:
            seen.add(key)
            results.append(row)
    return jsonify(results)


@app.route("/api/results/<int:query_id>", methods=["GET"])
def api_benchmark_result_by_query(query_id: int):
    sb = get_supabase()
    if sb is None:
        return jsonify({"ok": False, "error": "Supabase not configured (set SUPABASE_URL and SUPABASE_KEY)."}), 503
    data = (
        sb.table("benchmark_results")
        .select("*")
        .eq("query_id", query_id)
        .order("run_at", desc=True)
        .limit(2)
        .execute()
    )
    return jsonify(data.data or [])


@app.route("/api/queries", methods=["GET"])
def api_query_list():
    return jsonify([{"id": k, "label": v} for k, v in QUERY_LABELS.items()])


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/architecture", methods=["GET"])
def api_architecture():
    """Live vs static data layers (report / presentation)."""
    return jsonify(ARCHITECTURE)


@app.route("/api/databricks-benchmark", methods=["GET"])
def api_databricks_benchmark():
    """Static benchmark numbers from benchmark_performance_results.csv (exported from the Databricks notebook)."""
    payload: dict[str, Any] = {
        "notebook_url": _DATABRICKS_NOTEBOOK_URL,
        "notebook_label": "Databricks benchmark notebook",
    }
    if not os.path.isfile(_DATABRICKS_BENCHMARK_CSV):
        return jsonify({**payload, "ok": False, "error": "benchmark_performance_results.csv not found.", "rows": []}), 404
    rows: list[dict[str, Any]] = []
    with open(_DATABRICKS_BENCHMARK_CSV, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(
                {
                    "query_id": int(r["QueryID"]),
                    "task": r["Task"],
                    "bplus_ms": float(r["BPlusTree_ms"]),
                    "pgm_sim_ms": float(r["PGM_Sim_ms"]),
                }
            )
    return jsonify({**payload, "ok": True, "rows": rows})


@app.route("/api/postgres-live-compare/<int:query_num>", methods=["GET"])
def api_postgres_live_compare(query_num: int):
    """
    Server-side dual timing via clearbias_live_index_compare (B+ tree vs PGM-style BRIN/bitmap proxy).
    Requires sql/postgres/postgres_live_compare_function.sql applied.
    """
    if not use_postgres_live():
        return jsonify({"ok": False, "error": "Postgres live path not configured."}), 503
    if query_num < 1 or query_num > 13:
        return jsonify({"ok": False, "error": "query_num must be 1–13."}), 400
    from postgres_config import connect_postgres

    conn = connect_postgres()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT clearbias_live_index_compare(%s, %s::jsonb)",
            (query_num, "{}"),
        )
        payload = cur.fetchone()[0]
        return jsonify({"ok": True, "result": payload})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/postgres-live-compare-all", methods=["GET"])
def api_postgres_live_compare_all():
    """Run DB-side B+ tree vs PGM-style BRIN/bitmap proxy for Q1..Q13."""
    if not use_postgres_live():
        return jsonify({"ok": False, "error": "Postgres live path not configured."}), 503
    from postgres_config import connect_postgres

    conn = connect_postgres()
    cur = conn.cursor()
    out: list[dict[str, Any]] = []
    try:
        for i in range(1, 14):
            cur.execute(
                "SELECT clearbias_live_index_compare(%s, %s::jsonb)",
                (i, "{}"),
            )
            payload = cur.fetchone()[0] or {}
            out.append(payload)
        return jsonify({"ok": True, "results": out})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    finally:
        cur.close()
        conn.close()


@app.route("/api/export-static-zip", methods=["GET"])
def api_export_static_zip():
    """Memory ZIP of 14 CSVs (manifest + Q1–Q13), base64 for browser download."""
    if not use_postgres_live():
        return jsonify({"ok": False, "error": "Postgres live path not configured."}), 503
    try:
        from static_export import build_static_export_zip_b64

        b64, meta = build_static_export_zip_b64()
        return jsonify({"ok": True, "zip_base64": b64, "meta": meta})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/run-query", methods=["POST"])
def run_query():
    payload = request.get_json(silent=True) or {}
    query_id = payload.get("query_id") or "Q1"
    if query_id not in QUERY_IDS:
        query_id = "Q1"
    mode = payload.get("mode") or "B-Tree"
    if mode not in ("B-Tree", "PGM"):
        mode = "B-Tree"

    bench = payload.get("benchmark") or {}
    warmup_runs = int(bench.get("warmup_runs", 0))
    timed_runs = int(bench.get("timed_runs", 1))
    if timed_runs < 1:
        timed_runs = 1
    if warmup_runs < 0:
        warmup_runs = 0

    binds = dict(QUERY_BINDS.get(query_id, QUERY_BINDS["Q1"]))
    sql = get_query(query_id, mode) if USE_ORACLE else SQL_TEMPLATES_LEGACY.get(query_id, SQL_TEMPLATES_LEGACY["Q1"])

    data_layer = "mock"

    try:
        if USE_ORACLE:
            data_layer = "oracle"
            conn = get_oracle_connection()
            try:
                result = run_validated_query_oracle(
                    conn,
                    sql,
                    binds,
                    warmup_runs=warmup_runs,
                    timed_runs=timed_runs,
                )
            finally:
                conn.close()
        elif use_postgres_live():
            data_layer = "live_postgres"
            from postgres_config import connect_postgres
            from queries_live_supabase import get_live_sql, resolve_params

            conn = connect_postgres()
            try:
                live_sql = get_live_sql(query_id)
                params = resolve_params(conn, query_id)
                result = run_validated_query_postgres(
                    conn,
                    live_sql,
                    params,
                    index_mode=mode,
                    warmup_runs=warmup_runs,
                    timed_runs=timed_runs,
                )
            finally:
                conn.close()
        else:
            key = "PGM" if mode == "PGM" else "B-Tree"
            delay_s = _MOCK_LATENCY_MS[key] / 1000.0
            result = run_validated_query_mock(
                base_delay_s=delay_s,
                row_factory=lambda qid=query_id: _mock_rows(qid),
                warmup_runs=warmup_runs,
                timed_runs=timed_runs,
            )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500

    var = variance_pct(result.app_latency_ms, result.oracle_internal_ms)

    return jsonify(
        {
            "ok": True,
            "query_id": query_id,
            "mode": mode,
            "data_layer": data_layer,
            "latency_ms": round(result.app_latency_ms, 2),
            "app_latency_ms": round(result.app_latency_ms, 2),
            "oracle_internal_ms": None
            if result.oracle_internal_ms is None
            else round(result.oracle_internal_ms, 2),
            "latency_variance_pct": None if var is None else round(var, 2),
            "sql_id": result.sql_id,
            "rows": result.rows,
            "mock": result.mock,
            "benchmark": {
                "warmup_runs": warmup_runs,
                "timed_runs": timed_runs,
                "per_run": result.per_run,
            },
            "postgres_live_compare_hint": "/api/postgres-live-compare/<1-13> for DB-side B+ vs PGM-style BRIN/bitmap proxy (clearbias_live_index_compare)",
        }
    )


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", "5000")))
