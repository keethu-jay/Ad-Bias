"""
Terminal-friendly validation table for the report.

Uses the same /run-query logic as the UI (in-process Flask test client).
For Oracle cross-check, also capture SQL*Plus SET TIMING ON / DBMS_XPLAN.DISPLAY_CURSOR
and paste alongside this output.

Usage:
  python validation_script.py
  python validation_script.py --all-queries --rigorous
"""

from __future__ import annotations

import argparse

from app import QUERY_IDS, app


def main() -> None:
    parser = argparse.ArgumentParser(description="Print validation markdown table via Flask test client.")
    parser.add_argument(
        "--all-queries",
        action="store_true",
        help="Include Q1–Q13 (default: Q1 only for a fast smoke table).",
    )
    parser.add_argument(
        "--rigorous",
        action="store_true",
        help="1 warmup (discarded) + 5 timed runs averaged (matches UI checkbox).",
    )
    args = parser.parse_args()

    bench = {"warmup_runs": 1, "timed_runs": 5} if args.rigorous else {"warmup_runs": 0, "timed_runs": 1}

    if args.all_queries:
        queries = sorted(QUERY_IDS, key=lambda x: int(x[1:]))
    else:
        queries = ["Q1"]

    rows_out: list[tuple[str, str, float, float | str, float | str, str]] = []
    client = app.test_client()

    for qid in queries:
        for mode in ("B-Tree", "PGM"):
            res = client.post(
                "/run-query",
                json={"query_id": qid, "mode": mode, "benchmark": bench},
            )
            data = res.get_json()
            if not data or not data.get("ok"):
                err = (data or {}).get("error", res.status)
                rows_out.append((qid, mode, 0, "ERR", "ERR", str(err)))
                continue
            ora = data.get("oracle_internal_ms")
            var = data.get("latency_variance_pct")
            runs = f"{data['benchmark']['warmup_runs']}w+{data['benchmark']['timed_runs']}"
            rows_out.append(
                (
                    qid,
                    mode,
                    float(data["app_latency_ms"]),
                    ora if ora is not None else "N/A",
                    var if var is not None else "N/A",
                    runs,
                )
            )

    print("| Query ID | Mode | App latency (ms) | DB internal (ms) | Variance (%) | Runs |")
    print("| :--- | :--- | ---: | ---: | ---: | :--- |")
    for qid, mode, app_ms, ora, var, runs in rows_out:
        print(f"| **{qid}** | {mode} | {app_ms:.2f} | {ora} | {var} | {runs} |")


if __name__ == "__main__":
    main()
