-- ClearBias benchmark stack (Postgres/Supabase: ad_impressions + q1–q13 harness + BRIN)
-- Parsed by etl/apply_benchmark_schema.py: blocks separated by lines containing only "-- STATEMENT"

-- STATEMENT
CREATE TABLE IF NOT EXISTS ad_impressions (
  impression_id   BIGSERIAL PRIMARY KEY,
  age_group       TEXT,
  gender          TEXT,
  ad_category     TEXT,
  platform        TEXT,
  region          TEXT,
  click_flag      SMALLINT,
  spend_usd       NUMERIC(10,4),
  impression_time TIMESTAMPTZ
);

-- STATEMENT
CREATE TABLE IF NOT EXISTS benchmark_results (
  id              BIGSERIAL PRIMARY KEY,
  query_id        INT NOT NULL,
  query_label     TEXT NOT NULL,
  method          TEXT NOT NULL,
  latency_ms      NUMERIC(12,3),
  rows_returned   INT,
  run_at          TIMESTAMPTZ DEFAULT NOW()
);

-- STATEMENT
CREATE INDEX IF NOT EXISTS idx_btree_age        ON ad_impressions (age_group);

-- STATEMENT
CREATE INDEX IF NOT EXISTS idx_btree_gender     ON ad_impressions (gender);

-- STATEMENT
CREATE INDEX IF NOT EXISTS idx_btree_category   ON ad_impressions (ad_category);

-- STATEMENT
CREATE INDEX IF NOT EXISTS idx_btree_region     ON ad_impressions (region);

-- STATEMENT
CREATE INDEX IF NOT EXISTS idx_btree_click      ON ad_impressions (click_flag);

-- STATEMENT
CREATE INDEX IF NOT EXISTS idx_btree_spend      ON ad_impressions (spend_usd);

-- STATEMENT
CREATE INDEX IF NOT EXISTS idx_btree_time       ON ad_impressions (impression_time);

-- STATEMENT
CREATE INDEX IF NOT EXISTS idx_btree_multi      ON ad_impressions (age_group, gender, ad_category);

-- STATEMENT
-- BRIN on PK: block min/max per heap range — Postgres-native analogue to learned-index (PGM-style) range skipping.
CREATE INDEX IF NOT EXISTS ad_impressions_brin_impression_id_idx
  ON ad_impressions USING BRIN (impression_id)
  WITH (pages_per_range = 32);

-- STATEMENT
CREATE OR REPLACE FUNCTION q1_point_lookup(p_id BIGINT)
RETURNS TABLE (impression_id BIGINT, age_group TEXT, gender TEXT, ad_category TEXT)
LANGUAGE sql STABLE AS $$
  SELECT impression_id, age_group, gender, ad_category
  FROM ad_impressions
  WHERE impression_id = p_id;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q2_range_lookup(p_start BIGINT, p_end BIGINT)
RETURNS TABLE (impression_id BIGINT, age_group TEXT, ad_category TEXT)
LANGUAGE sql STABLE AS $$
  SELECT impression_id, age_group, ad_category
  FROM ad_impressions
  WHERE impression_id BETWEEN p_start AND p_end;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q3_filter_age(p_age TEXT)
RETURNS TABLE (impression_id BIGINT, gender TEXT, ad_category TEXT, region TEXT)
LANGUAGE sql STABLE AS $$
  SELECT impression_id, gender, ad_category, region
  FROM ad_impressions
  WHERE age_group = p_age;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q4_filter_gender(p_gender TEXT)
RETURNS TABLE (impression_id BIGINT, age_group TEXT, ad_category TEXT)
LANGUAGE sql STABLE AS $$
  SELECT impression_id, age_group, ad_category
  FROM ad_impressions
  WHERE gender = p_gender;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q5_multi_filter(p_age TEXT, p_gender TEXT, p_cat TEXT)
RETURNS TABLE (impression_id BIGINT, region TEXT, click_flag SMALLINT)
LANGUAGE sql STABLE AS $$
  SELECT impression_id, region, click_flag
  FROM ad_impressions
  WHERE age_group = p_age
    AND gender = p_gender
    AND ad_category = p_cat;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q6_count_by_category()
RETURNS TABLE (ad_category TEXT, impression_count BIGINT)
LANGUAGE sql STABLE AS $$
  SELECT ad_category, COUNT(*) AS impression_count
  FROM ad_impressions
  GROUP BY ad_category
  ORDER BY impression_count DESC;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q7_count_by_demo()
RETURNS TABLE (age_group TEXT, gender TEXT, impression_count BIGINT)
LANGUAGE sql STABLE AS $$
  SELECT age_group, gender, COUNT(*) AS impression_count
  FROM ad_impressions
  GROUP BY age_group, gender
  ORDER BY age_group, gender;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q8_ctr_by_category()
RETURNS TABLE (ad_category TEXT, ctr NUMERIC)
LANGUAGE sql STABLE AS $$
  SELECT ad_category,
         ROUND(AVG(click_flag::NUMERIC) * 100, 2) AS ctr
  FROM ad_impressions
  GROUP BY ad_category
  ORDER BY ctr DESC;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q9_avg_spend_by_demo(p_age TEXT)
RETURNS TABLE (gender TEXT, region TEXT, avg_spend NUMERIC)
LANGUAGE sql STABLE AS $$
  SELECT gender, region, ROUND(AVG(spend_usd), 4) AS avg_spend
  FROM ad_impressions
  WHERE age_group = p_age
  GROUP BY gender, region
  ORDER BY avg_spend DESC;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q10_time_range(p_start TIMESTAMPTZ, p_end TIMESTAMPTZ)
RETURNS TABLE (impression_id BIGINT, age_group TEXT, ad_category TEXT)
LANGUAGE sql STABLE AS $$
  SELECT impression_id, age_group, ad_category
  FROM ad_impressions
  WHERE impression_time BETWEEN p_start AND p_end;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q11_high_spend(p_threshold NUMERIC)
RETURNS TABLE (impression_id BIGINT, age_group TEXT, gender TEXT, spend_usd NUMERIC)
LANGUAGE sql STABLE AS $$
  SELECT impression_id, age_group, gender, spend_usd
  FROM ad_impressions
  WHERE spend_usd > p_threshold
  ORDER BY spend_usd DESC;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q12_region_category(p_region TEXT, p_cat TEXT)
RETURNS TABLE (impression_id BIGINT, age_group TEXT, gender TEXT, click_flag SMALLINT)
LANGUAGE sql STABLE AS $$
  SELECT impression_id, age_group, gender, click_flag
  FROM ad_impressions
  WHERE region = p_region
    AND ad_category = p_cat;
$$;

-- STATEMENT
CREATE OR REPLACE FUNCTION q13_bias_audit(p_cat TEXT)
RETURNS TABLE (age_group TEXT, gender TEXT, region TEXT, impression_count BIGINT, avg_spend NUMERIC, ctr NUMERIC)
LANGUAGE sql STABLE AS $$
  SELECT
    age_group,
    gender,
    region,
    COUNT(*)                                    AS impression_count,
    ROUND(AVG(spend_usd), 4)                    AS avg_spend,
    ROUND(AVG(click_flag::NUMERIC) * 100, 2)    AS ctr
  FROM ad_impressions
  WHERE ad_category = p_cat
  GROUP BY age_group, gender, region
  ORDER BY impression_count DESC;
$$;

-- STATEMENT
ALTER TABLE benchmark_results ENABLE ROW LEVEL SECURITY;

-- STATEMENT
DROP POLICY IF EXISTS "benchmark_results_select_anon" ON benchmark_results;

-- STATEMENT
CREATE POLICY "benchmark_results_select_anon" ON benchmark_results FOR SELECT TO anon USING (true);

-- STATEMENT
DROP POLICY IF EXISTS "benchmark_results_select_auth" ON benchmark_results;

-- STATEMENT
CREATE POLICY "benchmark_results_select_auth" ON benchmark_results FOR SELECT TO authenticated USING (true);

-- STATEMENT
GRANT USAGE ON SCHEMA public TO anon, authenticated;

-- STATEMENT
GRANT SELECT ON ad_impressions TO anon, authenticated, service_role;

-- STATEMENT
GRANT SELECT ON benchmark_results TO anon, authenticated, service_role;

-- STATEMENT
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated;
