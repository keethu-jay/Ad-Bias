#!/usr/bin/env python3
"""
Clean and normalize loaded ClearBias data for web API testing.

What it does:
  1) Removes orphan rows (if any) from AD_CONTENT / BIAS_SCORES.
  2) Prints key row counts.
  3) Creates compatibility views expected by queries.py (CB_AD, AD_CREATIVE, etc.)
     from the current 22-table schema (AD_CREATIVES, CAMPAIGNS, ADVERTISERS, ...).

Usage (from repo root):
  python -m legacy_oracle.prepare_web_data
"""

from __future__ import annotations

from legacy_oracle.oracle_config import connect_oracle


def _exec_ddl(cur, sql: str) -> None:
    cur.execute(sql)


def _count(cur, table_name: str) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table_name}")
    row = cur.fetchone()
    return int(row[0]) if row else 0


def main() -> int:
    conn = connect_oracle(prompt_for_password=True)
    cur = conn.cursor()
    try:
        # Cleanup: these should already be zero with FK constraints, but this is safe.
        cur.execute(
            """
            DELETE FROM ad_content c
            WHERE NOT EXISTS (
              SELECT 1
              FROM ad_creatives a
              WHERE a.ad_creative_id = c.ad_creative_id
            )
            """
        )
        removed_content = cur.rowcount or 0

        cur.execute(
            """
            DELETE FROM bias_scores b
            WHERE NOT EXISTS (
              SELECT 1
              FROM ad_creatives a
              WHERE a.ad_creative_id = b.ad_id
            )
            """
        )
        removed_scores = cur.rowcount or 0

        # Compatibility views for the Oracle query path in app.py / queries.py.
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW advertiser AS
            SELECT advertiser_id, name
            FROM advertisers
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW campaign AS
            SELECT campaign_id, advertiser_id, start_date, end_date
            FROM campaigns
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW ad_creative AS
            SELECT ad_creative_id, campaign_id, format AS creative_type
            FROM ad_creatives
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW platform AS
            SELECT platform_id, name AS platform_name
            FROM platforms
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW bias_metric_type AS
            SELECT bias_metric_id AS bias_metric_type_id, metric_name
            FROM bias_metrics
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW bias_score AS
            SELECT
              ad_id,
              metric_id AS bias_metric_type_id,
              score_value
            FROM bias_scores
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW cb_ad AS
            SELECT
              a.ad_creative_id AS ad_id,
              a.ad_creative_id AS ad_creative_id,
              (SELECT MIN(p.platform_id) FROM platforms p) AS platform_id,
              CAST(NULL AS NUMBER) AS target_audience_id,
              CAST(FROM_TZ(CAST(c.start_date AS TIMESTAMP), 'UTC') AS TIMESTAMP WITH TIME ZONE) AS posted_at
            FROM ad_creatives a
            JOIN campaigns c
              ON c.campaign_id = a.campaign_id
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW industry_category AS
            SELECT
              ROW_NUMBER() OVER (ORDER BY category_name) AS industry_category_id,
              category_name
            FROM (
              SELECT DISTINCT NVL(format, 'Unknown') AS category_name
              FROM ad_creatives
            )
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW ad_category_map AS
            SELECT
              a.ad_creative_id AS ad_id,
              ic.industry_category_id
            FROM ad_creatives a
            JOIN industry_category ic
              ON ic.category_name = NVL(a.format, 'Unknown')
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW target_audience AS
            SELECT
              CAST(NULL AS NUMBER) AS target_audience_id,
              CAST(NULL AS VARCHAR2(1)) AS name,
              CAST(NULL AS VARCHAR2(1)) AS description
            FROM dual
            WHERE 1 = 0
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW location_region AS
            SELECT
              region_id AS location_region_id,
              SUBSTR(NVL(state, 'NA'), 1, 8) AS state_code,
              SUBSTR(country, 1, 3) AS country_code
            FROM regions
            """,
        )
        _exec_ddl(
            cur,
            """
            CREATE OR REPLACE VIEW target_audience_region AS
            SELECT
              CAST(NULL AS NUMBER) AS target_audience_id,
              CAST(NULL AS NUMBER) AS location_region_id
            FROM dual
            WHERE 1 = 0
            """,
        )

        conn.commit()

        print("Cleanup complete.")
        print(f"  removed orphan ad_content rows: {removed_content}")
        print(f"  removed orphan bias_scores rows: {removed_scores}")
        print("")
        print("Key counts:")
        for t in ("AD_CREATIVES", "AD_CONTENT", "BIAS_SCORES", "CAMPAIGNS", "ADVERTISERS", "PLATFORMS"):
            print(f"  {t}: {_count(cur, t)}")
        print("")
        print("Compatibility views refreshed for web API Oracle query path.")
        return 0
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
