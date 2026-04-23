"""
High-accuracy benchmarking: app wall time vs Oracle-reported cursor time (when Oracle path is used).

Oracle: V$SQL.ELAPSED_TIME is in microseconds; we expose milliseconds as elapsed_time / 1000.
A unique /* clearbias:<tag> */ comment makes each run’s text distinct so the new child cursor’s
stats correspond to this execution (see report caveats for shared-pool reuse).
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from queries_live_supabase import set_index_mode


def inject_sql_tag(sql: str, tag: str) -> str:
    """Make each benchmark statement textually unique for V$SQL correlation."""
    return re.sub(r"(\bSELECT\b)", rf"\1 /* clearbias:{tag} */", sql, count=1, flags=re.IGNORECASE)


def oracle_elapsed_ms_from_vsql(
    diag_cursor: Any,
    sql_id: str | None,
    tag: str | None,
) -> tuple[float | None, str | None]:
    """
    Return (elapsed_ms, sql_id) from V$SQL. ELAPSED_TIME is microseconds → divide by 1000 for ms.

    Thin mode often leaves cursor.sql_id unset; we fall back to matching the injected
    /* clearbias:<tag> */ hint on SQL_TEXT (and SQL_FULLTEXT when available).
    If the session cannot SELECT V$SQL, returns (None, None).
    """

    def by_sql_id(sid: str) -> tuple[float | None, str | None]:
        try:
            diag_cursor.execute(
                """
                SELECT elapsed_time
                FROM v$sql
                WHERE sql_id = :sid
                ORDER BY last_active_time DESC
                FETCH FIRST 1 ROW ONLY
                """,
                {"sid": sid},
            )
            row = diag_cursor.fetchone()
            if not row or row[0] is None:
                return None, None
            return float(row[0]) / 1000.0, sid
        except Exception:
            return None, None

    if sql_id:
        ms, sid = by_sql_id(sql_id)
        if ms is not None:
            return ms, sid

    marker = f"clearbias:{tag}" if tag else ""
    if marker:
        # Prefer full text match when the column exists (long SQL).
        for text_col in ("sql_fulltext", "sql_text"):
            try:
                diag_cursor.execute(
                    f"""
                    SELECT elapsed_time, sql_id
                    FROM v$sql
                    WHERE {text_col} LIKE '%' || :m || '%'
                    ORDER BY last_active_time DESC
                    FETCH FIRST 1 ROW ONLY
                    """,
                    {"m": marker},
                )
                row = diag_cursor.fetchone()
                if row and row[0] is not None:
                    return float(row[0]) / 1000.0, (str(row[1]) if row[1] else None)
            except Exception:
                continue

    return None, None


def fetch_rows_as_dicts(cursor: Any) -> list[dict[str, Any]]:
    columns = [c[0].lower() for c in cursor.description]
    raw = cursor.fetchall()
    rows: list[dict[str, Any]] = []
    for r in raw:
        row = dict(zip(columns, r))
        rows.append(
            {
                "ad_id": row.get("ad_id"),
                "bias_score": float(row["bias_score"])
                if row.get("bias_score") is not None
                else None,
                "category": row.get("category"),
                "region": row.get("region"),
                "timestamp": str(row.get("ts") or row.get("timestamp") or ""),
            }
        )
    return rows


@dataclass
class ValidatedBenchmarkResult:
    rows: list[dict[str, Any]]
    app_latency_ms: float
    oracle_internal_ms: float | None
    row_count: int
    sql_id: str | None = None
    per_run: list[dict[str, float | None]] = field(default_factory=list)
    mock: bool = True


def variance_pct(app_ms: float, oracle_ms: float | None) -> float | None:
    if oracle_ms is None or oracle_ms <= 0:
        return None
    return abs(app_ms - oracle_ms) / oracle_ms * 100.0


def _single_oracle_run(
    conn: Any,
    cursor: Any,
    sql_text: str,
    binds: dict[str, Any],
) -> tuple[float, float | None, list[dict[str, Any]], str | None]:
    tag = uuid.uuid4().hex[:12]
    tagged = inject_sql_tag(sql_text, tag)

    t0 = time.perf_counter()
    cursor.execute(tagged, binds)
    rows = fetch_rows_as_dicts(cursor)
    app_ms = (time.perf_counter() - t0) * 1000.0
    sid = getattr(cursor, "sql_id", None)
    diag = conn.cursor()
    try:
        ora_ms, resolved_sid = oracle_elapsed_ms_from_vsql(diag, sid, tag)
    finally:
        diag.close()
    out_sid = resolved_sid or sid
    return app_ms, ora_ms, rows, out_sid


def run_validated_query_oracle(
    conn: Any,
    sql_text: str,
    binds: dict[str, Any],
    *,
    warmup_runs: int = 0,
    timed_runs: int = 1,
) -> ValidatedBenchmarkResult:
    """
    warmup_runs: executions discarded (cold cache).
    timed_runs: recorded executions; returned app/oracle latencies are means.
    """
    if timed_runs < 1:
        timed_runs = 1
    if warmup_runs < 0:
        warmup_runs = 0

    cursor = conn.cursor()
    try:
        cursor.execute("ALTER SESSION SET STATISTICS_LEVEL = ALL")

        for _ in range(warmup_runs):
            _single_oracle_run(conn, cursor, sql_text, binds)

        app_sum = 0.0
        ora_vals: list[float] = []
        last_rows: list[dict[str, Any]] = []
        last_sid: str | None = None
        per_run: list[dict[str, float | None]] = []

        for _ in range(timed_runs):
            app_ms, ora_ms, last_rows, last_sid = _single_oracle_run(conn, cursor, sql_text, binds)
            app_sum += app_ms
            rec: dict[str, float | None] = {"app_latency_ms": round(app_ms, 3)}
            if ora_ms is not None:
                ora_vals.append(ora_ms)
                rec["oracle_internal_ms"] = round(ora_ms, 3)
                rec["variance_pct"] = round(variance_pct(app_ms, ora_ms) or 0.0, 3)
            else:
                rec["oracle_internal_ms"] = None
                rec["variance_pct"] = None
            per_run.append(rec)

        mean_app = app_sum / timed_runs
        mean_ora: float | None = sum(ora_vals) / len(ora_vals) if ora_vals else None

        return ValidatedBenchmarkResult(
            rows=last_rows,
            app_latency_ms=mean_app,
            oracle_internal_ms=mean_ora,
            row_count=len(last_rows),
            sql_id=last_sid,
            per_run=per_run,
            mock=False,
        )
    finally:
        cursor.close()


def run_validated_query_mock(
    *,
    base_delay_s: float,
    row_factory: Callable[[], list[dict[str, Any]]],
    warmup_runs: int = 0,
    timed_runs: int = 1,
) -> ValidatedBenchmarkResult:
    """
    Mock path: real wall clock sleep; Oracle internal time simulated slightly below app
    (server-side “truth”) so variance stays in a believable band for UI/report demos.
    """
    if timed_runs < 1:
        timed_runs = 1
    if warmup_runs < 0:
        warmup_runs = 0

    def one_run() -> tuple[float, float, list[dict[str, Any]]]:
        t0 = time.perf_counter()
        time.sleep(base_delay_s)
        rows = row_factory()
        app_ms = (time.perf_counter() - t0) * 1000.0
        jitter = (uuid.uuid4().int % 500) / 10000.0
        oracle_ms = app_ms * (0.93 + jitter)
        if oracle_ms >= app_ms:
            oracle_ms = app_ms * 0.92
        return app_ms, oracle_ms, rows

    for _ in range(warmup_runs):
        one_run()

    app_sum = 0.0
    ora_vals: list[float] = []
    last_rows: list[dict[str, Any]] = []
    per_run: list[dict[str, float | None]] = []

    for _ in range(timed_runs):
        app_ms, ora_ms, last_rows = one_run()
        app_sum += app_ms
        ora_vals.append(ora_ms)
        per_run.append(
            {
                "app_latency_ms": round(app_ms, 3),
                "oracle_internal_ms": round(ora_ms, 3),
                "variance_pct": round(variance_pct(app_ms, ora_ms) or 0.0, 3),
            }
        )

    mean_app = app_sum / timed_runs
    mean_ora = sum(ora_vals) / len(ora_vals) if ora_vals else None

    return ValidatedBenchmarkResult(
        rows=last_rows,
        app_latency_ms=mean_app,
        oracle_internal_ms=mean_ora,
        row_count=len(last_rows),
        sql_id=None,
        per_run=per_run,
        mock=True,
    )


def fetch_live_rows_as_dicts(cursor: Any) -> list[dict[str, Any]]:
    """Map ad_impressions audit projection to the Flask / index.html row shape."""
    columns = [c[0].lower() for c in cursor.description]
    raw = cursor.fetchall()
    rows: list[dict[str, Any]] = []
    for r in raw:
        row = dict(zip(columns, r, strict=True))
        bs = row.get("bias_score")
        rows.append(
            {
                "ad_id": str(row.get("ad_id") or ""),
                "bias_score": float(bs) if bs is not None else None,
                "category": row.get("category") or "",
                "region": row.get("region") or "",
                "timestamp": str(row.get("ts") or row.get("impression_time") or ""),
            }
        )
    return rows


def run_validated_query_postgres(
    conn: Any,
    sql_text: str,
    params: tuple[Any, ...],
    *,
    index_mode: str,
    warmup_runs: int = 0,
    timed_runs: int = 1,
) -> ValidatedBenchmarkResult:
    """
    Live Supabase path: SET LOCAL planner toggles (B+ tree vs PGM-style BRIN/bitmap proxy),
    wall-clock around execute+fetch.
    """
    if timed_runs < 1:
        timed_runs = 1
    if warmup_runs < 0:
        warmup_runs = 0

    cursor = conn.cursor()
    try:
        for _ in range(warmup_runs):
            set_index_mode(cursor, index_mode)
            cursor.execute(sql_text, params)
            cursor.fetchall()

        app_sum = 0.0
        last_rows: list[dict[str, Any]] = []
        per_run: list[dict[str, float | None]] = []

        for _ in range(timed_runs):
            set_index_mode(cursor, index_mode)
            t0 = time.perf_counter()
            cursor.execute(sql_text, params)
            last_rows = fetch_live_rows_as_dicts(cursor)
            app_ms = (time.perf_counter() - t0) * 1000.0

            app_sum += app_ms
            per_run.append(
                {
                    "app_latency_ms": round(app_ms, 3),
                    "oracle_internal_ms": None,
                    "variance_pct": None,
                }
            )

        mean_app = app_sum / timed_runs
        return ValidatedBenchmarkResult(
            rows=last_rows,
            app_latency_ms=mean_app,
            oracle_internal_ms=None,
            row_count=len(last_rows),
            sql_id=None,
            per_run=per_run,
            mock=False,
        )
    finally:
        cursor.close()
