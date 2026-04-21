"""
Maps ad_category labels (from ad_impressions / Criteo-style loads) to broad industry buckets.

Same bucket names as sql/postgres/normalize_ad_impressions_to_bcnf.sql and migrate_interests_industry.sql.
Extend the dict when new category strings show up in the data.
"""

from __future__ import annotations

# Display names must match rows inserted into industries (see migration SQL).
_INDUSTRY_BY_NORMALIZED_LABEL: dict[str, str] = {
    "housing": "Real Estate & Housing",
    "finance": "Financial Services",
    "health": "Health & Wellness",
    "retail": "Retail & Shopping",
    "auto": "Automotive",
    "news": "Media & News",
}

_DEFAULT_INDUSTRY = "General & Other"


def industry_name_for_ad_category(ad_category: str | None) -> str:
    """Return the industries.name bucket for a raw ad_category string (case-insensitive)."""
    if not ad_category or not str(ad_category).strip():
        return _DEFAULT_INDUSTRY
    key = str(ad_category).strip().lower()
    if key in _INDUSTRY_BY_NORMALIZED_LABEL:
        return _INDUSTRY_BY_NORMALIZED_LABEL[key]
    return _DEFAULT_INDUSTRY
