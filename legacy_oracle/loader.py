"""
Bulk load Facebook Ads–style CSV into the ClearBias BCNF Oracle schema.
Normalizes free-text dimensions (e.g. category → industry_category) before inserting facts.

Usage (from repo root):
  set ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN
  python -m legacy_oracle.loader --csv path/to/ads.csv

Optional: CLEARBIAS_METRIC_ID (default 1) must exist in bias_metric_type.

Expected CSV columns (any missing → sensible default):
  advertiser_name | page_name, campaign_name, category | ad_category,
  platform, headline | ad_headline, body | ad_body, creative_type,
  state | region, country, ad_id | id, bias_score | skew_score, created_time | timestamp
"""

from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime
try:
    import oracledb
except ImportError:
    oracledb = None  # type: ignore


def connect():
    if oracledb is None:
        raise RuntimeError("Install driver: pip install oracledb")
    user = os.environ.get("ORACLE_USER", "")
    password = os.environ.get("ORACLE_PASSWORD", "")
    dsn = os.environ.get("ORACLE_DSN", "")
    if not (user and password and dsn):
        raise RuntimeError("Set ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN")
    return oracledb.connect(user=user, password=password, dsn=dsn)


def merge_lookup(cur, table: str, id_col: str, name_col: str, value: str) -> int:
    """Insert dimension row if missing; return surrogate key."""
    v = (value or "").strip() or "Unknown"
    cur.execute(
        f"""
        MERGE INTO {table} t
        USING (SELECT :v AS n FROM dual) s
        ON (t.{name_col} = s.n)
        WHEN NOT MATCHED THEN INSERT ({name_col}) VALUES (s.n)
        """,
        {"v": v},
    )
    cur.execute(f"SELECT {id_col} FROM {table} WHERE {name_col} = :v", {"v": v})
    return int(cur.fetchone()[0])


def merge_region(cur, state: str | None, country: str) -> int:
    c = (country or "US").strip()
    s = state.strip() if state else None
    cur.execute(
        """
        MERGE INTO location_region t
        USING (SELECT :st AS state_code, :co AS country_code FROM dual) s
        ON (NVL(t.state_code, '__') = NVL(s.state_code, '__') AND t.country_code = s.country_code)
        WHEN NOT MATCHED THEN INSERT (state_code, country_code) VALUES (s.state_code, s.country_code)
        """,
        {"st": s, "co": c},
    )
    cur.execute(
        """
        SELECT location_region_id FROM location_region
        WHERE NVL(state_code, '__') = NVL(:st, '__') AND country_code = :co
        """,
        {"st": s, "co": c},
    )
    return int(cur.fetchone()[0])


def load_csv(path: str) -> None:
    metric_id = int(os.environ.get("CLEARBIAS_METRIC_ID", "1"))
    conn = connect()
    cur = conn.cursor()

    cat_maps: list[tuple[int, int]] = []
    bias_rows: list[tuple[int, int, float]] = []

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            advertiser_name = r.get("advertiser_name") or r.get("page_name") or "Unknown Advertiser"
            campaign_name = r.get("campaign_name") or "Default Campaign"
            category = r.get("category") or r.get("ad_category") or "General"
            platform = r.get("platform") or "Facebook"
            headline = (r.get("headline") or r.get("ad_headline") or "")[:500]
            body = r.get("body") or r.get("ad_body") or ""
            creative_type = (r.get("creative_type") or "image")[:60]
            state = r.get("state") or r.get("region")
            country = r.get("country") or "US"
            bias_raw = r.get("bias_score") or r.get("skew_score") or "0.5"
            posted = _parse_ts(r.get("created_time") or r.get("timestamp"))

            adv_id = merge_lookup(cur, "advertiser", "advertiser_id", "name", advertiser_name)
            ind_id = merge_lookup(cur, "industry_category", "industry_category_id", "category_name", category)
            plat_id = merge_lookup(cur, "platform", "platform_id", "platform_name", platform)
            reg_id = merge_region(cur, state, country)

            cur.execute(
                """
                SELECT campaign_id FROM campaign
                WHERE advertiser_id = :a AND ROWNUM = 1
                """,
                {"a": adv_id},
            )
            row = cur.fetchone()
            if row:
                camp_id = int(row[0])
            else:
                cur.execute(
                    """
                    INSERT INTO campaign (advertiser_id, start_date, end_date)
                    VALUES (:a, DATE '2026-01-01', NULL)
                    """,
                    {"a": adv_id},
                )
                cur.execute(
                    "SELECT MAX(campaign_id) FROM campaign WHERE advertiser_id = :a",
                    {"a": adv_id},
                )
                camp_id = int(cur.fetchone()[0])
                cur.execute(
                    "INSERT INTO campaign_budget (campaign_id, daily_limit) VALUES (:c, 1000)",
                    {"c": camp_id},
                )

            ta_name = f"TA-{camp_id}-{campaign_name[:40]}"
            cur.execute(
                "SELECT target_audience_id FROM target_audience WHERE name = :n",
                {"n": ta_name},
            )
            trow = cur.fetchone()
            if trow:
                ta_id = int(trow[0])
            else:
                cur.execute(
                    """
                    INSERT INTO target_audience (name, description)
                    VALUES (:n, :d)
                    """,
                    {"n": ta_name, "d": "Loaded audience for " + campaign_name},
                )
                cur.execute(
                    "SELECT target_audience_id FROM target_audience WHERE name = :n",
                    {"n": ta_name},
                )
                ta_id = int(cur.fetchone()[0])
                cur.execute(
                    """
                    MERGE INTO target_audience_region t
                    USING (SELECT :ta AS ta_id, :reg AS reg_id FROM dual) s
                    ON (t.target_audience_id = s.ta_id AND t.location_region_id = s.reg_id)
                    WHEN NOT MATCHED THEN INSERT (target_audience_id, location_region_id)
                    VALUES (s.ta_id, s.reg_id)
                    """,
                    {"ta": ta_id, "reg": reg_id},
                )

            cur.execute(
                """
                INSERT INTO ad_creative (campaign_id, creative_type)
                VALUES (:c, :t)
                """,
                {"c": camp_id, "t": creative_type},
            )
            cur.execute(
                "SELECT MAX(ad_creative_id) FROM ad_creative WHERE campaign_id = :c",
                {"c": camp_id},
            )
            creative_id = int(cur.fetchone()[0])

            cur.execute(
                """
                INSERT INTO ad_content (ad_creative_id, headline, body_text)
                VALUES (:cr, :h, :b)
                """,
                {"cr": creative_id, "h": headline, "b": body},
            )

            cur.execute(
                """
                INSERT INTO cb_ad (ad_creative_id, platform_id, target_audience_id, posted_at)
                VALUES (:cr, :p, :ta, NVL(:ts, CURRENT_TIMESTAMP))
                """,
                {"cr": creative_id, "p": plat_id, "ta": ta_id, "ts": posted},
            )
            cur.execute(
                "SELECT MAX(ad_id) FROM cb_ad WHERE ad_creative_id = :cr",
                {"cr": creative_id},
            )
            ad_id = int(cur.fetchone()[0])

            cat_maps.append((ad_id, ind_id))

            try:
                score = float(bias_raw)
            except (TypeError, ValueError):
                score = 0.5
            score = max(0.0, min(1.0, score))
            bias_rows.append((ad_id, metric_id, score))

        if cat_maps:
            cur.executemany(
                """
                MERGE INTO ad_category_map t
                USING (SELECT :1 AS ad_id, :2 AS industry_category_id FROM dual) s
                ON (t.ad_id = s.ad_id AND t.industry_category_id = s.industry_category_id)
                WHEN NOT MATCHED THEN INSERT (ad_id, industry_category_id) VALUES (s.ad_id, s.industry_category_id)
                """,
                cat_maps,
            )

        if bias_rows:
            cur.executemany(
                """
                MERGE INTO bias_score t
                USING (SELECT :1 AS ad_id, :2 AS bias_metric_type_id, :3 AS score_value FROM dual) s
                ON (t.ad_id = s.ad_id AND t.bias_metric_type_id = s.bias_metric_type_id)
                WHEN MATCHED THEN UPDATE SET t.score_value = s.score_value, t.measured_at = CURRENT_TIMESTAMP
                WHEN NOT MATCHED THEN INSERT (ad_id, bias_metric_type_id, score_value)
                VALUES (s.ad_id, s.bias_metric_type_id, s.score_value)
                """,
                bias_rows,
            )

    conn.commit()
    cur.close()
    conn.close()


def _parse_ts(val: str | None) -> datetime | None:
    if not val:
        return None
    s = val.strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def main() -> None:
    p = argparse.ArgumentParser(description="Load Facebook-style CSV into ClearBias Oracle schema.")
    p.add_argument("--csv", required=True)
    args = p.parse_args()
    load_csv(args.csv)
    print("Load complete.")


if __name__ == "__main__":
    main()
