-- =============================================================================
-- ClearBias: normalize public.ad_impressions into the 22-table BCNF schema
-- (see etl/create_postgres_schema.py). Extracts distinct platforms, regions,
-- categories (stored as interests.interest_name), age bands, and genders.
--
-- Run in Supabase SQL editor or: psql "$CLEARBIAS_POSTGRES_DSN" -f this_file.sql
--
-- BEFORE RUNNING:
--   1) Backup if needed.
--   2) Re-run: uncomment §0 TRUNCATE or fact rows duplicate.
--   3) etl/create_postgres_schema applied (22 tables). If DB predates interests.industry_id,
--      run sql/postgres/migrate_interests_industry.sql once.
--
-- NOTES:
--   - ad_impressions.region → regions.city; state = '—'; country = 'US'.
--   - ad_category → interests.interest_name; each interest row references industries (sector bucket).
--   - One synthetic advertiser + campaign hold all creatives.
--   - Each impression → one ad_creative + ad_content + bias_score (click → score).
-- =============================================================================

BEGIN;

-- §0 REQUIRED when re-running (uncomment all three lines)
-- TRUNCATE bias_scores, ad_content, ad_creatives RESTART IDENTITY CASCADE;
-- DELETE FROM campaigns WHERE advertiser_id IN (SELECT advertiser_id FROM advertisers WHERE name = 'ClearBias Synthetic Advertiser');
-- DELETE FROM advertisers WHERE name = 'ClearBias Synthetic Advertiser';

-- ---------------------------------------------------------------------------
-- §1 Dimension seeds
-- ---------------------------------------------------------------------------

-- Broad buckets for ad_category → sector (no real advertiser; category is the signal).
INSERT INTO industries (name) VALUES
  ('Real Estate & Housing'),
  ('Financial Services'),
  ('Health & Wellness'),
  ('Retail & Shopping'),
  ('Automotive'),
  ('Media & News'),
  ('General & Other'),
  ('Ad Tech — Synthetic')
ON CONFLICT (name) DO NOTHING;

INSERT INTO query_templates (sql_code)
SELECT 'SELECT 1 /* placeholder for performance_logs FK */'
WHERE NOT EXISTS (SELECT 1 FROM query_templates LIMIT 1);

INSERT INTO target_profiles (profile_name)
VALUES ('General audience')
ON CONFLICT (profile_name) DO NOTHING;

INSERT INTO system_settings (setting_key, setting_value)
VALUES ('normalized_from', 'ad_impressions')
ON CONFLICT (setting_key) DO NOTHING;

INSERT INTO advertisers (name, industry_id)
SELECT 'ClearBias Synthetic Advertiser', i.industry_id
FROM industries i
WHERE i.name = 'Ad Tech — Synthetic'
  AND NOT EXISTS (SELECT 1 FROM advertisers WHERE name = 'ClearBias Synthetic Advertiser');

INSERT INTO campaigns (advertiser_id, start_date, end_date)
SELECT a.advertiser_id, DATE '2026-01-01', NULL
FROM advertisers a
WHERE a.name = 'ClearBias Synthetic Advertiser'
  AND NOT EXISTS (
    SELECT 1 FROM campaigns c
    WHERE c.advertiser_id = a.advertiser_id
      AND c.start_date = DATE '2026-01-01'
  );

-- ---------------------------------------------------------------------------
-- §2 Extract distinct platforms, regions, categories (interests), age_groups
-- ---------------------------------------------------------------------------

INSERT INTO platforms (name)
SELECT DISTINCT TRIM(platform)
FROM ad_impressions
WHERE TRIM(COALESCE(platform, '')) <> ''
ON CONFLICT (name) DO NOTHING;

INSERT INTO regions (city, state, country)
SELECT DISTINCT
  LEFT(TRIM(region), 120),
  '—',
  'US'
FROM ad_impressions
WHERE TRIM(COALESCE(region, '')) <> ''
ON CONFLICT (city, state, country) DO NOTHING;

INSERT INTO interests (interest_name, industry_id)
SELECT DISTINCT
  LEFT(TRIM(ai.ad_category), 200),
  (
    SELECT ind.industry_id
    FROM industries ind
    WHERE ind.name = (
      CASE UPPER(TRIM(ai.ad_category))
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
  )
FROM ad_impressions ai
WHERE TRIM(COALESCE(ai.ad_category, '')) <> ''
ON CONFLICT (interest_name) DO UPDATE SET
  industry_id = EXCLUDED.industry_id;

INSERT INTO age_groups (min_age, max_age)
SELECT DISTINCT v.min_age, v.max_age
FROM ad_impressions ai
JOIN LATERAL (
  VALUES
    ('18-24', 18, 24),
    ('25-34', 25, 34),
    ('35-44', 35, 44),
    ('45-54', 45, 54),
    ('55+', 55, 120)
) AS v(label, min_age, max_age) ON TRIM(ai.age_group) = v.label;

INSERT INTO age_groups (min_age, max_age)
SELECT 0, 120
WHERE EXISTS (
  SELECT 1 FROM ad_impressions ai
  WHERE TRIM(COALESCE(ai.age_group, '')) <> ''
    AND TRIM(ai.age_group) NOT IN ('18-24','25-34','35-44','45-54','55+')
)
AND NOT EXISTS (SELECT 1 FROM age_groups WHERE min_age = 0 AND max_age = 120);

INSERT INTO demographics (race, gender, income)
SELECT DISTINCT ON (TRIM(gender))
  NULL::varchar(120),
  TRIM(gender),
  NULL::numeric(14,2)
FROM ad_impressions
WHERE TRIM(COALESCE(gender, '')) <> ''
ORDER BY TRIM(gender);

-- ---------------------------------------------------------------------------
-- §3 Auditors chain (minimal rows)
-- ---------------------------------------------------------------------------

INSERT INTO auditors (user_role_id, name)
SELECT ur.user_role_id, 'System auditor'
FROM user_roles ur
WHERE ur.role_name = 'admin'
  AND NOT EXISTS (SELECT 1 FROM auditors WHERE name = 'System auditor')
LIMIT 1;

INSERT INTO audit_sessions (auditor_id, start_time)
SELECT a.auditor_id, NOW()
FROM auditors a
WHERE a.name = 'System auditor'
  AND NOT EXISTS (SELECT 1 FROM audit_sessions)
LIMIT 1;

INSERT INTO audit_results (session_id, summary)
SELECT s.audit_session_id, 'Normalization import from ad_impressions'
FROM audit_sessions s
WHERE NOT EXISTS (SELECT 1 FROM audit_results)
ORDER BY s.audit_session_id DESC
LIMIT 1;

-- ---------------------------------------------------------------------------
-- §4 Fact: ad_creatives (1:1 with ad_impressions, same order)
-- ---------------------------------------------------------------------------

INSERT INTO ad_creatives (campaign_id, format)
SELECT c.campaign_id, LEFT(TRIM(ai.ad_category), 60)
FROM ad_impressions ai
CROSS JOIN LATERAL (
  SELECT camp.campaign_id
  FROM campaigns camp
  JOIN advertisers adv ON adv.advertiser_id = camp.advertiser_id
  WHERE adv.name = 'ClearBias Synthetic Advertiser'
  ORDER BY camp.campaign_id
  LIMIT 1
) c
ORDER BY ai.impression_id;

-- ---------------------------------------------------------------------------
-- §5 ad_content (JOINs for FK ids — avoids per-row subqueries)
-- ---------------------------------------------------------------------------

WITH age_map AS (
  SELECT * FROM (
    VALUES
      ('18-24', 18, 24),
      ('25-34', 25, 34),
      ('35-44', 35, 44),
      ('45-54', 45, 54),
      ('55+', 55, 120)
  ) AS t(label, min_age, max_age)
),
cr AS (
  SELECT
    ac.ad_creative_id,
    ROW_NUMBER() OVER (ORDER BY ac.ad_creative_id) AS rn
  FROM ad_creatives ac
  JOIN campaigns camp ON camp.campaign_id = ac.campaign_id
  JOIN advertisers adv ON adv.advertiser_id = camp.advertiser_id
  WHERE adv.name = 'ClearBias Synthetic Advertiser'
),
ai AS (
  SELECT
    ai.impression_id,
    TRIM(ai.platform) AS platform,
    TRIM(ai.region) AS region,
    TRIM(ai.ad_category) AS ad_category,
    TRIM(ai.age_group) AS age_group,
    TRIM(ai.gender) AS gender,
    ai.click_flag,
    ai.spend_usd,
    ai.impression_time,
    ROW_NUMBER() OVER (ORDER BY ai.impression_id) AS rn
  FROM ad_impressions ai
),
paired AS (
  SELECT
    cr.ad_creative_id,
    ai.impression_id,
    ai.platform,
    ai.region,
    ai.ad_category,
    ai.age_group,
    ai.gender,
    ai.click_flag,
    ai.spend_usd,
    ai.impression_time,
    p.platform_id,
    r.region_id,
    it.interest_id,
    it.industry_id,
    ind.name AS industry_name,
    COALESCE(ag.age_group_id, ag_unk.age_group_id) AS age_group_id,
    d.demographic_id
  FROM cr
  JOIN ai ON ai.rn = cr.rn
  LEFT JOIN platforms p ON p.name = ai.platform
  LEFT JOIN regions r
    ON r.city = LEFT(ai.region, 120) AND r.state = '—' AND r.country = 'US'
  LEFT JOIN interests it ON it.interest_name = LEFT(ai.ad_category, 200)
  LEFT JOIN industries ind ON ind.industry_id = it.industry_id
  LEFT JOIN age_map am ON ai.age_group = am.label
  LEFT JOIN age_groups ag ON ag.min_age = am.min_age AND ag.max_age = am.max_age
  LEFT JOIN age_groups ag_unk ON ag_unk.min_age = 0 AND ag_unk.max_age = 120
  LEFT JOIN demographics d ON d.gender = ai.gender AND d.race IS NULL
)
INSERT INTO ad_content (ad_creative_id, headline, body_text)
SELECT
  p.ad_creative_id,
  LEFT('Impression ' || p.impression_id::text, 500),
  jsonb_build_object(
    'source_impression_id', p.impression_id,
    'platform', p.platform,
    'region', p.region,
    'ad_category', p.ad_category,
    'age_group', p.age_group,
    'gender', p.gender,
    'spend_usd', p.spend_usd,
    'impression_time', p.impression_time,
    'platform_id', p.platform_id,
    'region_id', p.region_id,
    'interest_id', p.interest_id,
    'industry_id', p.industry_id,
    'industry_name', p.industry_name,
    'age_group_id', p.age_group_id,
    'demographic_id', p.demographic_id
  )::text
FROM paired p;

-- ---------------------------------------------------------------------------
-- §6 bias_scores
-- ---------------------------------------------------------------------------

WITH cr AS (
  SELECT
    ac.ad_creative_id,
    ROW_NUMBER() OVER (ORDER BY ac.ad_creative_id) AS rn
  FROM ad_creatives ac
  JOIN campaigns camp ON camp.campaign_id = ac.campaign_id
  JOIN advertisers adv ON adv.advertiser_id = camp.advertiser_id
  WHERE adv.name = 'ClearBias Synthetic Advertiser'
),
ai AS (
  SELECT
    ai.click_flag,
    ai.impression_time,
    ROW_NUMBER() OVER (ORDER BY ai.impression_id) AS rn
  FROM ad_impressions ai
),
bm AS (
  SELECT bias_metric_id FROM bias_metrics WHERE metric_name = 'Criteo_Click' LIMIT 1
)
INSERT INTO bias_scores (ad_id, metric_id, score_value, measured_at)
SELECT
  cr.ad_creative_id,
  bm.bias_metric_id,
  LEAST(1::numeric, GREATEST(0::numeric, ai.click_flag::numeric)),
  COALESCE(ai.impression_time, NOW())
FROM cr
JOIN ai ON ai.rn = cr.rn
CROSS JOIN bm;

-- ---------------------------------------------------------------------------
-- §7 Metadata + one performance_log sample
-- ---------------------------------------------------------------------------

INSERT INTO data_source_metadata (source_name, record_count, updated_at)
VALUES (
  'BCNF:normalized_from_ad_impressions',
  (SELECT COUNT(*)::bigint FROM ad_impressions),
  NOW()
)
ON CONFLICT (source_name) DO UPDATE SET
  record_count = EXCLUDED.record_count,
  updated_at = EXCLUDED.updated_at;

INSERT INTO performance_logs (query_id, index_type_id, latency_ms, memory_mb, logged_at)
SELECT qt.query_template_id, it.index_type_id, 0, 0, NOW()
FROM query_templates qt
CROSS JOIN index_types it
WHERE it.type_name = 'B-Tree'
  AND NOT EXISTS (SELECT 1 FROM performance_logs LIMIT 1)
LIMIT 1;

COMMIT;

-- Verification:
-- SELECT 'platforms', COUNT(*) FROM platforms
-- UNION ALL SELECT 'regions', COUNT(*) FROM regions
-- UNION ALL SELECT 'interests', COUNT(*) FROM interests
-- UNION ALL SELECT 'age_groups', COUNT(*) FROM age_groups
-- UNION ALL SELECT 'demographics', COUNT(*) FROM demographics
-- UNION ALL SELECT 'ad_creatives', COUNT(*) FROM ad_creatives
-- UNION ALL SELECT 'ad_content', COUNT(*) FROM ad_content
-- UNION ALL SELECT 'bias_scores', COUNT(*) FROM bias_scores;
