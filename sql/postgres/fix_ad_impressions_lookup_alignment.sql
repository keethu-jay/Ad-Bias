-- =============================================================================
-- ClearBias: repair ad_impressions ↔ interests / demographics alignment
-- (Supabase / PostgreSQL). Idempotent: safe to re-run after messy loads.
--
-- Fixes:
--   1) Seeds missing interests rows for any ad_category text using the same
--      industry bucket CASE as sql/postgres/normalize_ad_impressions_to_bcnf.sql.
--   2) Canonicalizes ad_impressions.ad_category to the exact interest_name.
--   3) Seeds missing demographics rows (race NULL) for any gender text.
--   4) Canonicalizes ad_impressions.gender to the chosen demographics.gender
--      (lowest demographic_id per lower(gender), race IS NULL).
--
-- Run:
--   python -m etl.referential_integrity align
-- or (single transaction):
--   psql "$CLEARBIAS_POSTGRES_DSN" -v ON_ERROR_STOP=1 -1 -f sql/postgres/fix_ad_impressions_lookup_alignment.sql
-- =============================================================================

-- §1 Missing interests (orphan category labels)
INSERT INTO interests (interest_name, industry_id)
SELECT DISTINCT
  m.cat,
  sub.industry_id
FROM (
  SELECT DISTINCT LEFT(TRIM(ai.ad_category), 200) AS cat
  FROM ad_impressions ai
  WHERE TRIM(COALESCE(ai.ad_category, '')) <> ''
) m
CROSS JOIN LATERAL (
  SELECT ind.industry_id
  FROM industries ind
  WHERE ind.name = (
    CASE UPPER(TRIM(m.cat))
      WHEN 'HOUSING' THEN 'Real Estate & Housing'
      WHEN 'FINANCE' THEN 'Financial Services'
      WHEN 'HEALTH' THEN 'Health & Wellness'
      WHEN 'RETAIL' THEN 'Retail & Shopping'
      WHEN 'AUTO' THEN 'Automotive'
      WHEN 'NEWS' THEN 'Media & News'
      ELSE 'General & Other'
    END
  )
  LIMIT 1
) sub
WHERE NOT EXISTS (
  SELECT 1 FROM interests it WHERE it.interest_name = m.cat
)
ON CONFLICT (interest_name) DO NOTHING;

-- §2 Canonical category text → interests.interest_name
UPDATE ad_impressions ai
SET ad_category = it.interest_name
FROM interests it
WHERE LOWER(TRIM(ai.ad_category)) = LOWER(TRIM(it.interest_name))
  AND ai.ad_category IS DISTINCT FROM it.interest_name;

-- §3 Missing demographics rows (for orphan gender labels)
INSERT INTO demographics (race, gender, income)
SELECT NULL::varchar(120), v.g, NULL::numeric(14, 2)
FROM (
  SELECT DISTINCT TRIM(ai.gender) AS g
  FROM ad_impressions ai
  WHERE TRIM(COALESCE(ai.gender, '')) <> ''
) v
WHERE NOT EXISTS (
  SELECT 1 FROM demographics d
  WHERE d.race IS NULL AND LOWER(TRIM(d.gender)) = LOWER(v.g)
);

-- §4 Canonical gender text → demographics.gender (stable: min demographic_id)
UPDATE ad_impressions ai
SET gender = d.gender
FROM demographics d
WHERE d.race IS NULL
  AND LOWER(TRIM(ai.gender)) = LOWER(TRIM(d.gender))
  AND d.demographic_id = (
    SELECT MIN(d2.demographic_id)
    FROM demographics d2
    WHERE d2.race IS NULL
      AND LOWER(TRIM(d2.gender)) = LOWER(TRIM(ai.gender))
  )
  AND ai.gender IS DISTINCT FROM d.gender;
