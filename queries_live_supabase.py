"""
Live Supabase / PostgreSQL queries against public.ad_impressions (+ lookup joins).

Architecture (see /api/architecture):
  - ad_category (TEXT on impressions) joins interests.interest_name → industries.name as category label.
  - gender joins demographics.gender where demographics.race IS NULL.

LIVE_QUERY_SPECS (per Q1..Q13 key):
  "title"   — short label for UI.
  "sql"     — parameterized query; columns must match fetch mapping in benchmark.run_validated_query_postgres.
  "params"  — tuple or callable(conn) → tuple of bind values for %s placeholders.

Q5 uses the modal (age_group, gender, ad_category) triple — highest COUNT(*).
"""

from __future__ import annotations

from typing import Any

# Column layout for UI: ad_id, bias_score, category (industry display name), region, timestamp
_BASE_FROM = """
FROM ad_impressions ai
LEFT JOIN interests it ON it.interest_name = LEFT(TRIM(ai.ad_category), 200)
LEFT JOIN industries i ON i.industry_id = it.industry_id
"""

_AUDIT_SELECT = f"""
SELECT
  ai.impression_id::text AS ad_id,
  ai.click_flag::numeric AS bias_score,
  COALESCE(i.name, it.interest_name, ai.ad_category)::text AS category,
  COALESCE(ai.region, '')::text AS region,
  ai.impression_time AS ts
{_BASE_FROM}
"""


def get_modal_triple_sql() -> str:
    """Subquery returning one row: age_group, gender, ad_category for the densest slice."""
    return """
    SELECT age_group, gender, ad_category
    FROM (
      SELECT age_group, gender, ad_category, COUNT(*)::bigint AS n
      FROM ad_impressions
      GROUP BY age_group, gender, ad_category
      ORDER BY n DESC
      LIMIT 1
    ) m
    """


LIVE_QUERY_SPECS: dict[str, dict[str, Any]] = {
    "Q1": {
        "title": "Point Lookup",
        "sql": _AUDIT_SELECT + " WHERE ai.impression_id = %s ORDER BY ai.impression_id LIMIT 500",
        "params": lambda conn: (_default_impression_id(conn),),
    },
    "Q2": {
        "title": "Range on impression_id",
        "sql": _AUDIT_SELECT
        + " WHERE ai.impression_id BETWEEN %s AND %s ORDER BY ai.impression_id LIMIT 500",
        "params": lambda conn: _range_window(conn),
    },
    "Q3": {
        "title": "Filter by Age Group",
        "sql": _AUDIT_SELECT + " WHERE ai.age_group = %s ORDER BY ai.impression_id LIMIT 500",
        "params": ("25-34",),
    },
    "Q4": {
        "title": "Filter by Gender",
        "sql": _AUDIT_SELECT + " WHERE ai.gender = %s ORDER BY ai.impression_id LIMIT 500",
        "params": ("F",),
    },
    "Q5": {
        "title": "Multi-Dimensional Filter (modal slice)",
        "sql": """
WITH modal AS (
  SELECT age_group, gender, ad_category, COUNT(*)::bigint AS n
  FROM ad_impressions
  GROUP BY age_group, gender, ad_category
  ORDER BY n DESC
  LIMIT 1
)
"""
        + _AUDIT_SELECT
        + """
JOIN modal m ON ai.age_group = m.age_group AND ai.gender = m.gender AND ai.ad_category = m.ad_category
ORDER BY ai.impression_id
LIMIT 500
""",
        "params": lambda conn: (),
    },
    "Q6": {
        "title": "Count by Category",
        "sql": """
SELECT
  ROW_NUMBER() OVER (ORDER BY sub.cnt DESC)::text AS ad_id,
  NULL::numeric AS bias_score,
  COALESCE(i.name, it.interest_name, sub.ad_category)::text AS category,
  ''::text AS region,
  NOW() AS ts
FROM (
  SELECT ad_category, COUNT(*)::bigint AS cnt
  FROM ad_impressions
  GROUP BY ad_category
) sub
LEFT JOIN interests it ON it.interest_name = LEFT(TRIM(sub.ad_category), 200)
LEFT JOIN industries i ON i.industry_id = it.industry_id
ORDER BY sub.cnt DESC
LIMIT 500
""",
        "params": lambda conn: (),
    },
    "Q7": {
        "title": "Count by Demo Group",
        "sql": """
SELECT
  ROW_NUMBER() OVER (ORDER BY sub.cnt DESC)::text AS ad_id,
  NULL::numeric AS bias_score,
  (sub.age_group || ' / ' || sub.gender)::text AS category,
  ''::text AS region,
  NOW() AS ts
FROM (
  SELECT age_group, gender, COUNT(*)::bigint AS cnt
  FROM ad_impressions
  GROUP BY age_group, gender
) sub
ORDER BY sub.cnt DESC
LIMIT 500
""",
        "params": lambda conn: (),
    },
    "Q8": {
        "title": "CTR by Category",
        "sql": """
WITH cat AS (
  SELECT
    COALESCE(i.name, it.interest_name, ai.ad_category)::text AS label,
    ROUND(AVG(ai.click_flag::numeric) * 100, 4) AS ctr
  FROM ad_impressions ai
  LEFT JOIN interests it ON it.interest_name = LEFT(TRIM(ai.ad_category), 200)
  LEFT JOIN industries i ON i.industry_id = it.industry_id
  GROUP BY i.name, it.interest_name, ai.ad_category
)
SELECT
  ROW_NUMBER() OVER (ORDER BY ctr DESC NULLS LAST)::text AS ad_id,
  ctr AS bias_score,
  label AS category,
  ''::text AS region,
  NOW() AS ts
FROM cat
ORDER BY ctr DESC NULLS LAST
LIMIT 500
""",
        "params": lambda conn: (),
    },
    "Q9": {
        "title": "Avg Spend by Demo",
        "sql": _AUDIT_SELECT
        + " WHERE ai.age_group = %s ORDER BY ai.spend_usd DESC NULLS LAST LIMIT 500",
        "params": ("25-34",),
    },
    "Q10": {
        "title": "Time Range Filter",
        "sql": _AUDIT_SELECT
        + """ WHERE ai.impression_time BETWEEN %s::timestamptz AND %s::timestamptz
ORDER BY ai.impression_time DESC LIMIT 500""",
        "params": ("2023-01-01T00:00:00+00", "2023-06-30T23:59:59+00"),
    },
    "Q11": {
        "title": "High Spend Filter",
        "sql": _AUDIT_SELECT + " WHERE ai.spend_usd > %s ORDER BY ai.spend_usd DESC LIMIT 500",
        "params": (5.0,),
    },
    "Q12": {
        "title": "Region + Category Filter",
        "sql": _AUDIT_SELECT
        + " WHERE ai.region = %s AND ai.ad_category = %s ORDER BY ai.impression_id LIMIT 500",
        "params": ("Northeast", "Housing"),
    },
    "Q13": {
        "title": "Full Bias Audit (by modal category)",
        "sql": """
WITH modal AS (
  SELECT age_group, gender, ad_category, COUNT(*)::bigint AS n
  FROM ad_impressions
  GROUP BY age_group, gender, ad_category
  ORDER BY n DESC
  LIMIT 1
),
agg AS (
  SELECT
    ai.age_group,
    ai.gender,
    ai.region,
    COUNT(*)::bigint AS impression_count,
    ROUND(AVG(ai.click_flag::numeric), 4) AS avg_click,
    COALESCE(i.name, it.interest_name, ai.ad_category)::text AS label
  FROM ad_impressions ai
  JOIN modal m ON ai.ad_category = m.ad_category
  LEFT JOIN interests it ON it.interest_name = LEFT(TRIM(ai.ad_category), 200)
  LEFT JOIN industries i ON i.industry_id = it.industry_id
  GROUP BY ai.age_group, ai.gender, ai.region, i.name, it.interest_name, ai.ad_category
)
SELECT
  ROW_NUMBER() OVER (ORDER BY impression_count DESC)::text AS ad_id,
  avg_click AS bias_score,
  (age_group || ' / ' || gender || ' @ ' || label)::text AS category,
  COALESCE(region, '')::text AS region,
  NOW() AS ts
FROM agg
ORDER BY impression_count DESC
LIMIT 500
""",
        "params": lambda conn: (),
    },
}


def _default_impression_id(conn: Any) -> int:
    cur = conn.cursor()
    cur.execute("SELECT impression_id FROM ad_impressions ORDER BY impression_id LIMIT 1")
    row = cur.fetchone()
    return int(row[0]) if row else 1


def _range_window(conn: Any) -> tuple[int, int]:
    cur = conn.cursor()
    cur.execute("SELECT MIN(impression_id), MAX(impression_id) FROM ad_impressions")
    lo, hi = cur.fetchone()
    if lo is None:
        return (1, 1)
    lo, hi = int(lo), int(hi)
    span = max(1, (hi - lo) // 1000)
    return (lo, min(hi, lo + span))


def resolve_params(conn: Any, qid: str) -> tuple[Any, ...]:
    spec = LIVE_QUERY_SPECS.get(qid, LIVE_QUERY_SPECS["Q1"])
    p = spec["params"]
    if callable(p):
        return p(conn)
    return p


def get_live_sql(qid: str) -> str:
    return LIVE_QUERY_SPECS.get(qid, LIVE_QUERY_SPECS["Q1"])["sql"]


def set_index_mode(cur: Any, mode: str) -> None:
    """B-Tree baseline: default planner. PGM-style: BRIN on impression_id (DDL in
    sql/postgres/benchmark_schema.sql) plus no btree Index/Index-Only scans; bitmap scans on so
    BRIN can use Bitmap Index Scan."""
    if mode == "PGM":
        cur.execute("SET LOCAL enable_indexscan = off")
        cur.execute("SET LOCAL enable_indexonlyscan = off")
        cur.execute("SET LOCAL enable_bitmapscan = on")
        cur.execute("SET LOCAL enable_seqscan = on")
    else:
        cur.execute("SET LOCAL enable_indexscan = on")
        cur.execute("SET LOCAL enable_indexonlyscan = on")
        cur.execute("SET LOCAL enable_bitmapscan = on")
        cur.execute("SET LOCAL enable_seqscan = on")
