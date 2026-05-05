#!/usr/bin/env python3
"""Emit databricks/clearbias_benchmark.ipynb — run from repo root: python tools/generate_databricks_notebook.py"""

from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out = root / "databricks" / "clearbias_benchmark.ipynb"
    out.parent.mkdir(parents=True, exist_ok=True)

    md_intro = """# ClearBias — Databricks benchmark notebook

Run on a **Databricks** cluster with Spark SQL. Register or mount a table **`AD_IMPRESSIONS_TABLE`** with columns matching Postgres `public.ad_impressions`:

`impression_id`, `click_flag`, `ad_category`, `region`, `impression_time`, `spend_usd`, `age_group`, `gender`

Each audit query is timed twice:

- **BPlusTree_ms**: `spark.sql.adaptive.enabled=false`, `spark.sql.autoBroadcastJoinThreshold=-1` (heavy shuffle / sort baseline).
- **PGM_Sim_ms**: adaptive execution **on**, default broadcast threshold **on** (AQE-friendly plans).

Output **`benchmark_performance_results.csv`** with columns `QueryID,Task,BPlusTree_ms,PGM_Sim_ms` — copy into `ClearBias_Audit_Files/` for the Flask dashboard.

Workspace notebook URL (requires login):  
https://dbc-23063686-87f0.cloud.databricks.com/editor/notebooks/2216068845186789?o=7474645010599702

This checked-in `.ipynb` is the portable twin you can submit with the ZIP; keep it in sync with edits you make in the workspace UI if numbers must match exactly.
"""

    code_cfg = r'''# --- Configuration ---
AD_IMPRESSIONS_TABLE = "hive_metastore.default.ad_impressions"  # full Spark catalog name or path

NUM_TIMED_RUNS = 2  # mean wall-clock ms per mode

from pyspark.sql import SparkSession
import statistics
import time

spark = SparkSession.builder.getOrCreate()

def audit_select_sql() -> str:
    return f"""
SELECT
  CAST(ai.impression_id AS STRING) AS ad_id,
  CAST(ai.click_flag AS DOUBLE) AS bias_score,
  CAST(ai.ad_category AS STRING) AS category,
  COALESCE(ai.region, CAST('' AS STRING)) AS region,
  ai.impression_time AS ts
FROM {AD_IMPRESSIONS_TABLE} ai
"""

def modal_cte() -> str:
    return f"""
SELECT age_group, gender, ad_category FROM (
  SELECT age_group, gender, ad_category, COUNT(*) AS n
  FROM {AD_IMPRESSIONS_TABLE}
  GROUP BY age_group, gender, ad_category
  ORDER BY n DESC
  LIMIT 1
) m
"""

def run_sql_ms(sql: str, mode: str) -> float:
    """mode: 'bplus' | 'pgm'"""
    if mode == "bplus":
        spark.conf.set("spark.sql.adaptive.enabled", "false")
        spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "-1")
    else:
        spark.conf.set("spark.sql.adaptive.enabled", "true")
        spark.conf.set("spark.sql.autoBroadcastJoinThreshold", "10485760")
    runs = []
    for _ in range(NUM_TIMED_RUNS):
        spark.catalog.clearCache()
        t0 = time.perf_counter()
        spark.sql(sql).collect()
        runs.append((time.perf_counter() - t0) * 1000.0)
    return statistics.mean(runs)

print("Spark:", spark.version)
print("Table:", AD_IMPRESSIONS_TABLE)
'''

    code_specs = r'''def build_specs(spark):
    """Return list of (query_id, task_slug, sql)."""
    row = spark.sql(
        f"SELECT MIN(impression_id) AS lo, MAX(impression_id) AS hi FROM {AD_IMPRESSIONS_TABLE}"
    ).collect()[0]
    lo, hi = int(row.lo), int(row.hi)
    span = max(1, (hi - lo) // 20)
    hi_r = min(hi, lo + span)

    sel = audit_select_sql()
    m = modal_cte()

    specs = [
        (
            1,
            "Point_Lookup",
            f"{sel} WHERE ai.impression_id = {lo} ORDER BY ai.impression_id LIMIT 500",
        ),
        (
            2,
            "Range_Lookup",
            f"{sel} WHERE ai.impression_id BETWEEN {lo} AND {hi_r} ORDER BY ai.impression_id LIMIT 500",
        ),
        (
            3,
            "Age_Group_Filter",
            f"{sel} WHERE ai.age_group = '25-34' ORDER BY ai.impression_id LIMIT 500",
        ),
        (
            4,
            "Gender_Distribution",
            f"{sel} WHERE ai.gender = 'F' ORDER BY ai.impression_id LIMIT 500",
        ),
        (
            5,
            "Bias_Audit_Sample",
            f"""
WITH modal AS ({m.strip()})
{sel}
JOIN modal m ON ai.age_group = m.age_group AND ai.gender = m.gender AND ai.ad_category = m.ad_category
ORDER BY ai.impression_id
LIMIT 500
""".strip(),
        ),
        (
            6,
            "Category_Volume",
            f"""
SELECT
  CAST(ROW_NUMBER() OVER (ORDER BY sub.cnt DESC) AS STRING) AS ad_id,
  CAST(NULL AS DOUBLE) AS bias_score,
  CAST(sub.ad_category AS STRING) AS category,
  CAST('' AS STRING) AS region,
  current_timestamp() AS ts
FROM (
  SELECT ad_category, COUNT(*) AS cnt
  FROM {AD_IMPRESSIONS_TABLE}
  GROUP BY ad_category
) sub
ORDER BY sub.cnt DESC
LIMIT 500
""".strip(),
        ),
        (
            7,
            "Demographic_Intersection",
            f"""
SELECT
  CAST(ROW_NUMBER() OVER (ORDER BY sub.cnt DESC) AS STRING) AS ad_id,
  CAST(NULL AS DOUBLE) AS bias_score,
  CAST(CONCAT(sub.age_group, ' / ', sub.gender) AS STRING) AS category,
  CAST('' AS STRING) AS region,
  current_timestamp() AS ts
FROM (
  SELECT age_group, gender, COUNT(*) AS cnt
  FROM {AD_IMPRESSIONS_TABLE}
  GROUP BY age_group, gender
) sub
ORDER BY sub.cnt DESC
LIMIT 500
""".strip(),
        ),
        (
            8,
            "CTR_by_Category",
            f"""
WITH cat AS (
  SELECT
    CAST(ai.ad_category AS STRING) AS label,
    ROUND(100 * AVG(CAST(ai.click_flag AS DOUBLE)), 4) AS ctr
  FROM {AD_IMPRESSIONS_TABLE} ai
  GROUP BY ai.ad_category
)
SELECT
  CAST(ROW_NUMBER() OVER (ORDER BY ctr DESC NULLS LAST) AS STRING) AS ad_id,
  CAST(ctr AS DOUBLE) AS bias_score,
  CAST(label AS STRING) AS category,
  CAST('' AS STRING) AS region,
  current_timestamp() AS ts
FROM cat
ORDER BY ctr DESC NULLS LAST
LIMIT 500
""".strip(),
        ),
        (
            9,
            "Spend_by_Age_Group",
            f"{sel} WHERE ai.age_group = '25-34' ORDER BY ai.spend_usd DESC NULLS LAST LIMIT 500",
        ),
        (
            10,
            "Temporal_Analysis",
            f"""
{sel}
WHERE ai.impression_time >= TIMESTAMP '2023-01-01 00:00:00'
  AND ai.impression_time <= TIMESTAMP '2023-06-30 23:59:59'
ORDER BY ai.impression_time DESC
LIMIT 500
""".strip(),
        ),
        (
            11,
            "Highest_Spend_Ads",
            f"{sel} WHERE ai.spend_usd > 5 ORDER BY ai.spend_usd DESC LIMIT 500",
        ),
        (
            12,
            "Regional_Bias_Audit",
            f"{sel} WHERE ai.region = 'Northeast' AND ai.ad_category = 'Housing' ORDER BY ai.impression_id LIMIT 500",
        ),
        (
            13,
            "Cross_Platform_Bias",
            f"""
WITH modal AS ({m.strip()}),
agg AS (
  SELECT
    ai.age_group,
    ai.gender,
    ai.region,
    COUNT(*) AS impression_count,
    ROUND(AVG(CAST(ai.click_flag AS DOUBLE)), 4) AS avg_click,
    CAST(ai.ad_category AS STRING) AS label
  FROM {AD_IMPRESSIONS_TABLE} ai
  JOIN modal m ON ai.ad_category = m.ad_category
  GROUP BY ai.age_group, ai.gender, ai.region, ai.ad_category
)
SELECT
  CAST(ROW_NUMBER() OVER (ORDER BY impression_count DESC) AS STRING) AS ad_id,
  CAST(avg_click AS DOUBLE) AS bias_score,
  CAST(CONCAT(age_group, ' / ', gender, ' @ ', label) AS STRING) AS category,
  COALESCE(region, CAST('' AS STRING)) AS region,
  current_timestamp() AS ts
FROM agg
ORDER BY impression_count DESC
LIMIT 500
""".strip(),
        ),
    ]
    return specs

spec_list = build_specs(spark)
for qid, task, _ in spec_list:
    print(qid, task)
'''

    code_run = r'''rows_out = []
for qid, task, sql_text in build_specs(spark):
    b_ms = run_sql_ms(sql_text, "bplus")
    p_ms = run_sql_ms(sql_text, "pgm")
    rows_out.append(
        {"QueryID": qid, "Task": task, "BPlusTree_ms": round(b_ms, 2), "PGM_Sim_ms": round(p_ms, 2)}
    )
    print(f"Q{qid} {task}  B+={b_ms:.2f}ms  PGM={p_ms:.2f}ms")

spark.createDataFrame(rows_out).show(20, truncate=False)

import pandas as pd

pdf = pd.DataFrame(rows_out)
try:
    display(pdf)
except NameError:
    print(pdf.to_string(index=False))

out_csv = "/dbfs/tmp/benchmark_performance_results.csv"
pdf.to_csv(out_csv, index=False)
print("Wrote", out_csv, "— download or copy into repo ClearBias_Audit_Files/benchmark_performance_results.csv")
'''

    def cell_md(text: str) -> dict:
        return {"cell_type": "markdown", "metadata": {}, "source": [line + "\n" for line in text.strip().split("\n")]}

    def cell_code(text: str) -> dict:
        lines = text.strip("\n").split("\n")
        return {
            "cell_type": "code",
            "metadata": {},
            "outputs": [],
            "execution_count": None,
            "source": [ln + "\n" for ln in lines],
        }

    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "cells": [
            cell_md(md_intro),
            cell_code(code_cfg),
            cell_code(code_specs),
            cell_code(code_run),
        ],
    }

    out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print(f"Wrote {out.relative_to(root)}")


if __name__ == "__main__":
    main()
