# Databricks notebook source
#
# Run from Databricks Repos attached at repo root so postgres_config resolves,
# or set PYTHONPATH to this checkout root before exporting into Workspace.

# COMMAND ----------
# MAGIC %pip install psycopg2-binary pandas sqlalchemy

# COMMAND ----------
from __future__ import annotations

import base64
import io
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import psycopg2

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from postgres_config import connect_postgres

# Audit query definitions — Postgres Supabase public.ad_impressions (timing mirrors Flask CSV naming).
QUERIES = [
    (1, "Point_Lookup", "SELECT * FROM ad_impressions WHERE impression_id = 500000;"),
    (
        2,
        "Range_Lookup",
        "SELECT * FROM ad_impressions WHERE impression_id BETWEEN 100000 AND 100100;",
    ),
    (
        3,
        "Age_Group_Filter",
        "SELECT * FROM ad_impressions WHERE age_group IS NOT NULL LIMIT 5000;",
    ),
    (
        4,
        "Gender_Distribution",
        "SELECT gender, COUNT(*) as count FROM ad_impressions GROUP BY gender;",
    ),
    (
        5,
        "Bias_Audit_Sample",
        """
SELECT * FROM ad_impressions WHERE ad_category = (
  SELECT ad_category FROM ad_impressions WHERE ad_category IS NOT NULL
  GROUP BY ad_category ORDER BY COUNT(*) DESC LIMIT 1
) AND gender = (
  SELECT gender FROM ad_impressions WHERE gender IS NOT NULL
  GROUP BY gender ORDER BY COUNT(*) DESC LIMIT 1
) LIMIT 5000;
""".strip(),
    ),
    (
        6,
        "Category_Volume",
        "SELECT ad_category, COUNT(*) as count FROM ad_impressions GROUP BY ad_category;",
    ),
    (
        7,
        "Demographic_Intersection",
        """
SELECT age_group, gender, COUNT(*) as count FROM ad_impressions
GROUP BY age_group, gender;
""".strip(),
    ),
    (
        8,
        "CTR_by_Category",
        "SELECT ad_category, AVG(click_flag) as avg_ctr FROM ad_impressions GROUP BY ad_category;",
    ),
    (
        9,
        "Spend_by_Age_Group",
        "SELECT age_group, SUM(spend_usd) as total_spend FROM ad_impressions GROUP BY age_group;",
    ),
    (
        10,
        "Temporal_Analysis",
        """
SELECT impression_time, spend_usd FROM ad_impressions
WHERE impression_time IS NOT NULL LIMIT 10000;
""".strip(),
    ),
    (
        11,
        "Highest_Spend_Ads",
        "SELECT * FROM ad_impressions ORDER BY spend_usd DESC LIMIT 1000;",
    ),
    (
        12,
        "Regional_Bias_Audit",
        """
SELECT region, ad_category, AVG(spend_usd) as avg_spend FROM ad_impressions
GROUP BY region, ad_category;
""".strip(),
    ),
    (
        13,
        "Cross_Platform_Bias",
        """
SELECT platform, ad_category, AVG(click_flag) as avg_ctr FROM ad_impressions
GROUP BY platform, ad_category;
""".strip(),
    ),
]


def run_export_pipeline() -> None:
    conn = connect_postgres(autocommit=True)
    perf_results: list[dict[str, float | int | str]] = []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for qid, label, sql in QUERIES:
            try:
                cur = conn.cursor()
                cur.execute("SET enable_indexscan = on;")
                start = time.perf_counter()
                cur.execute(sql)
                cur.fetchall()
                btree_latency = (time.perf_counter() - start) * 1000

                cur.execute("SET enable_indexscan = off;")
                start = time.perf_counter()
                cur.execute(sql)
                cur.fetchall()
                pgm_latency = (time.perf_counter() - start) * 1000

                perf_results.append(
                    {
                        "QueryID": qid,
                        "Task": label,
                        "BPlusTree_ms": round(btree_latency, 2),
                        "PGM_Sim_ms": round(pgm_latency, 2),
                    }
                )
                cur.close()

                df = pd.read_sql_query(sql, conn)
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False)
                zip_file.writestr(f"q{qid}_{label}.csv", csv_buffer.getvalue())

            except Exception as e:
                print(f"Error Task {qid}: {str(e)}")

        perf_df = pd.DataFrame(perf_results)
        perf_csv = io.StringIO()
        perf_df.to_csv(perf_csv, index=False)
        zip_file.writestr("benchmark_performance_results.csv", perf_csv.getvalue())

    conn.close()

    zip_buffer.seek(0)
    b64 = base64.b64encode(zip_buffer.read()).decode()
    html_link = f"""
        <div style="padding: 20px; background: #fafafa; border: 1px solid #ddd; border-radius: 8px; text-align: center;">
            <h3>Audit Export Complete</h3>
            <p>Individual CSVs and performance logs archived in ZIP format.</p>
            <a href="data:application/zip;base64,{b64}" download="ClearBias_Audit_Files.zip"
               style="background-color: #000; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block;">
               DOWNLOAD ZIP BUNDLE
            </a>
        </div>
    """
    try:
        displayHTML(html_link)
    except NameError:
        try:
            from IPython.display import HTML, display

            display(HTML(html_link))
        except Exception:
            print("Export ZIP bytes:", len(zip_buffer.getvalue()))


run_export_pipeline()
