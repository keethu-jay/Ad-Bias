"""
Thirteen benchmark SQL definitions for ClearBias PostgreSQL (B+ tree baseline).

Each entry: title, parameterized sql, default params tuple (psycopg2 %s placeholders).
Metric id is typically the first %s where applicable; use resolve_benchmark_params().
"""

from __future__ import annotations

from typing import Any

BENCHMARK_QUERIES: dict[str, dict[str, Any]] = {
    "Q1": {
        "title": "Baseline slice",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, b.score_value, a.format, c.start_date
            FROM ad_creatives a
            JOIN campaigns c ON c.campaign_id = a.campaign_id
            LEFT JOIN bias_scores b ON b.ad_id = a.ad_creative_id AND b.metric_id = %s
            ORDER BY a.ad_creative_id
            LIMIT %s
        """,
        "params": (1, 500),
    },
    "Q2": {
        "title": "Category filter",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, a.format, b.score_value
            FROM ad_creatives a
            LEFT JOIN bias_scores b ON b.ad_id = a.ad_creative_id AND b.metric_id = %s
            WHERE a.format = %s
            ORDER BY a.ad_creative_id
            LIMIT %s
        """,
        "params": (1, "Political", 500),
    },
    "Q3": {
        "title": "Region proxy filter",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, r.country, b.score_value
            FROM ad_creatives a
            JOIN campaigns c ON c.campaign_id = a.campaign_id
            JOIN advertisers adv ON adv.advertiser_id = c.advertiser_id
            JOIN industries i ON i.industry_id = adv.industry_id
            JOIN regions r ON r.country = %s
            LEFT JOIN bias_scores b ON b.ad_id = a.ad_creative_id AND b.metric_id = %s
            ORDER BY a.ad_creative_id
            LIMIT %s
        """,
        "params": ("US", 1, 500),
    },
    "Q4": {
        "title": "Bias threshold",
        "sql": """
            SELECT b.ad_id, b.score_value
            FROM bias_scores b
            WHERE b.metric_id = %s
              AND b.score_value >= %s
            ORDER BY b.score_value DESC
            LIMIT %s
        """,
        "params": (1, 0.5, 500),
    },
    "Q5": {
        "title": "Time window (BCNF bias_scores)",
        "sql": """
            SELECT b.ad_id, b.score_value, b.measured_at
            FROM bias_scores b
            WHERE b.metric_id = %s
              AND b.measured_at BETWEEN %s::timestamptz AND %s::timestamptz
            ORDER BY b.measured_at DESC
            LIMIT %s
        """,
        # For ad_impressions / modal bias audit + Tableau static export, use queries_live_supabase Q5 + Flask live path.
        "params": (1, "2026-01-01T00:00:00+00", "2030-01-01T00:00:00+00", 500),
    },
    "Q6": {
        "title": "Campaign join",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, c.campaign_id, adv.name
            FROM ad_creatives a
            JOIN campaigns c ON c.campaign_id = a.campaign_id
            JOIN advertisers adv ON adv.advertiser_id = c.advertiser_id
            ORDER BY a.ad_creative_id
            LIMIT %s
        """,
        "params": (500,),
    },
    "Q7": {
        "title": "Top by bias",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, a.format, b.score_value
            FROM ad_creatives a
            JOIN bias_scores b ON b.ad_id = a.ad_creative_id
            WHERE b.metric_id = %s
            ORDER BY b.score_value DESC NULLS LAST
            LIMIT %s
        """,
        "params": (1, 500),
    },
    "Q8": {
        "title": "Creative format",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, a.format, b.score_value
            FROM ad_creatives a
            LEFT JOIN bias_scores b ON b.ad_id = a.ad_creative_id AND b.metric_id = %s
            WHERE a.format = %s
            ORDER BY a.ad_creative_id
            LIMIT %s
        """,
        "params": (1, "image", 500),
    },
    "Q9": {
        "title": "Advertiser cohort",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, adv.advertiser_id, b.score_value
            FROM ad_creatives a
            JOIN campaigns c ON c.campaign_id = a.campaign_id
            JOIN advertisers adv ON adv.advertiser_id = c.advertiser_id
            LEFT JOIN bias_scores b ON b.ad_id = a.ad_creative_id AND b.metric_id = %s
            WHERE adv.advertiser_id = %s
            ORDER BY a.ad_creative_id
            LIMIT %s
        """,
        "params": (1, 1, 500),
    },
    "Q10": {
        "title": "Cross-region proxy",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, r.country, b.score_value
            FROM ad_creatives a
            LEFT JOIN bias_scores b ON b.ad_id = a.ad_creative_id AND b.metric_id = %s
            JOIN regions r ON r.country IN (%s, %s)
            ORDER BY a.ad_creative_id
            LIMIT %s
        """,
        "params": (1, "US", "CA", 500),
    },
    "Q11": {
        "title": "Category x region proxy",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, a.format, r.country, b.score_value
            FROM ad_creatives a
            LEFT JOIN bias_scores b ON b.ad_id = a.ad_creative_id AND b.metric_id = %s
            JOIN regions r ON r.country = %s
            WHERE a.format = %s
            ORDER BY a.ad_creative_id
            LIMIT %s
        """,
        "params": (1, "US", "News", 500),
    },
    "Q12": {
        "title": "High-volume scan",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, b.score_value
            FROM ad_creatives a
            LEFT JOIN bias_scores b ON b.ad_id = a.ad_creative_id AND b.metric_id = %s
            ORDER BY a.ad_creative_id
            LIMIT %s
        """,
        "params": (1, 5000),
    },
    "Q13": {
        "title": "Audit export",
        "sql": """
            SELECT a.ad_creative_id AS ad_id, a.format, b.score_value, b.measured_at
            FROM ad_creatives a
            LEFT JOIN bias_scores b ON b.ad_id = a.ad_creative_id AND b.metric_id = %s
            ORDER BY a.ad_creative_id
            LIMIT %s
        """,
        "params": (1, 500),
    },
}


def _params_for_qid(
    qid: str,
    t: tuple[Any, ...],
    metric_id: int,
    advertiser_id: int,
) -> tuple[Any, ...]:
    if qid == "Q1":
        return (metric_id, t[1])
    if qid == "Q2":
        return (metric_id, t[1], t[2])
    if qid == "Q3":
        return (t[0], metric_id, t[2])
    if qid == "Q4":
        return (metric_id, t[1], t[2])
    if qid == "Q5":
        return (metric_id, t[1], t[2], t[3])
    if qid == "Q6":
        return t
    if qid == "Q7":
        return (metric_id, t[1])
    if qid == "Q8":
        return (metric_id, t[1], t[2])
    if qid == "Q9":
        return (metric_id, advertiser_id, t[2])
    if qid == "Q10":
        return (metric_id, t[1], t[2], t[3])
    if qid == "Q11":
        return (metric_id, t[1], t[2], t[3])
    if qid == "Q12":
        return (metric_id, t[1])
    if qid == "Q13":
        return (metric_id, t[1])
    return t


def benchmark_params_for(metric_id: int, *, advertiser_id: int = 1) -> dict[str, tuple[Any, ...]]:
    """Build param tuples for each query using resolved metric and advertiser ids."""
    out: dict[str, tuple[Any, ...]] = {}
    for qid, spec in BENCHMARK_QUERIES.items():
        out[qid] = _params_for_qid(qid, spec["params"], metric_id, advertiser_id)
    return out
