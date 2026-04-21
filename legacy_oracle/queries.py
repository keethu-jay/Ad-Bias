"""
BCNF-aware audit SQL for ClearBias (Oracle only — enable with USE_ORACLE=true).

get_query(query_id, index_mode) — multi-table joins; index_mode switches optimizer hint prefix
  ("B-Tree" vs "PGM" placeholder comments). Requires binds from app.QUERY_BINDS + :metric_id.

Imported by app.py when USE_ORACLE is set. Postgres live path uses queries_live_supabase instead.
"""

from __future__ import annotations

_HINTS = {
    "B-Tree": "/*+ LEADING(a cr c) USE_NL(bs) INDEX(cb_ad) */",
    "PGM": "/*+ CLEARBIAS_PGM_INDEX_PLACEHOLDER */",
}


def _h(mode: str) -> str:
    return _HINTS.get(mode, _HINTS["B-Tree"])


def get_query(query_id: str, index_mode: str) -> str:
    """
    Parameterized SQL for Q1–Q13. Requires bind :metric_id plus query-specific binds (see app.QUERY_BINDS).
    """
    if index_mode not in ("B-Tree", "PGM"):
        index_mode = "B-Tree"
    hint = _h(index_mode)

    inner_core = f"""
    SELECT {hint}
           a.ad_id,
           NVL(bs.score_value, 0) AS bias_score,
           NVL(ic.category_name, 'Unknown') AS category,
           CASE
             WHEN lr.state_code IS NOT NULL THEN lr.state_code || '-' || lr.country_code
             WHEN lr.country_code IS NOT NULL THEN lr.country_code
             ELSE 'Unknown'
           END AS region,
           CAST(a.posted_at AS VARCHAR2(40)) AS ts
    FROM cb_ad a
    JOIN ad_creative cr ON cr.ad_creative_id = a.ad_creative_id
    JOIN campaign c ON c.campaign_id = cr.campaign_id
    JOIN advertiser adv ON adv.advertiser_id = c.advertiser_id
    JOIN platform p ON p.platform_id = a.platform_id
    LEFT JOIN ad_category_map acm ON acm.ad_id = a.ad_id
    LEFT JOIN industry_category ic ON ic.industry_category_id = acm.industry_category_id
    LEFT JOIN bias_score bs
      ON bs.ad_id = a.ad_id AND bs.bias_metric_type_id = :metric_id
    LEFT JOIN target_audience ta ON ta.target_audience_id = a.target_audience_id
    LEFT JOIN target_audience_region tar ON tar.target_audience_id = ta.target_audience_id
    LEFT JOIN location_region lr ON lr.location_region_id = tar.location_region_id
    WHERE 1 = 1
    """

    q = (query_id or "Q1").upper()
    extra = ""

    if q == "Q1":
        extra = ""
    elif q == "Q2":
        extra = "AND ic.category_name = :cat"
    elif q == "Q3":
        extra = "AND (lr.state_code = :region OR lr.country_code = :region)"
    elif q == "Q4":
        extra = "AND bs.score_value >= :min_score"
    elif q == "Q5":
        extra = "AND a.posted_at BETWEEN :t0 AND :t1"
    elif q == "Q6":
        extra = "AND p.platform_name IS NOT NULL"
    elif q == "Q7":
        inner_core = inner_core.replace("WHERE 1 = 1", "WHERE 1 = 1")
        wrapped = f"""
        SELECT * FROM (
          {inner_core}
          ORDER BY bs.score_value DESC NULLS LAST
        ) ranked
        """
        return f"SELECT * FROM ({wrapped}) WHERE ROWNUM <= :limit".strip()
    elif q == "Q8":
        extra = "AND cr.creative_type = :fp"
    elif q == "Q9":
        extra = "AND adv.advertiser_id = :aid"
    elif q == "Q10":
        extra = "AND (lr.state_code IN (:r1, :r2) OR lr.country_code IN (:r1, :r2))"
    elif q == "Q11":
        extra = "AND ic.category_name = :c AND (lr.state_code = :r OR lr.country_code = :r)"
    elif q == "Q12":
        extra = ""
    elif q == "Q13":
        ordered = f"""
        SELECT * FROM (
          {inner_core}
          ORDER BY a.ad_id
        ) sorted
        """
        return f"SELECT * FROM ({ordered}) WHERE ROWNUM <= :limit".strip()
    else:
        extra = ""

    return f"SELECT * FROM ({inner_core} {extra}) WHERE ROWNUM <= :limit".strip()
