-- =============================================================================
-- ClearBias — server-side “live” index strategy comparison (PostgreSQL).
-- Baseline: btree Index / Index-Only + bitmap + seq as planner chooses.
-- PGM-style proxy: disable btree Index / Index-Only scans but keep bitmap scans
-- ON so BRIN on impression_id (see sql/postgres/benchmark_schema.sql) can participate via Bitmap Index Scan.
-- Pure sequential scan is a poor proxy for PGM; BRIN block summaries are the supported analogue.
--
-- Requires sql/postgres/benchmark_schema.sql functions q1_point_lookup … q13_bias_audit.
-- Apply: psql "$CLEARBIAS_POSTGRES_DSN" -v ON_ERROR_STOP=1 -f sql/postgres/postgres_live_compare_function.sql
-- =============================================================================

CREATE OR REPLACE FUNCTION clearbias_modal_age_gender_category()
RETURNS TABLE (
  age_group text,
  gender text,
  ad_category text,
  slice_count bigint
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    ai.age_group,
    ai.gender,
    ai.ad_category,
    COUNT(*)::bigint AS slice_count
  FROM ad_impressions ai
  GROUP BY ai.age_group, ai.gender, ai.ad_category
  ORDER BY slice_count DESC
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION clearbias_live_index_compare(
  p_query_id integer,
  p_args jsonb DEFAULT '{}'::jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
VOLATILE
AS $$
DECLARE
  t0 timestamptz;
  t1 timestamptz;
  b_ms double precision;
  s_ms double precision;
  lo bigint;
  hi bigint;
  m record;
  cat13 text;
BEGIN
  lo := COALESCE((p_args ->> 'lo')::bigint, (SELECT MIN(impression_id) FROM ad_impressions));
  hi := COALESCE((p_args ->> 'hi')::bigint, lo + 100000);
  SELECT age_group, gender, ad_category INTO m FROM clearbias_modal_age_gender_category() LIMIT 1;
  cat13 := COALESCE(p_args ->> 'category', m.ad_category);

  PERFORM set_config('enable_indexscan', 'on', true);
  PERFORM set_config('enable_indexonlyscan', 'on', true);
  PERFORM set_config('enable_bitmapscan', 'on', true);
  PERFORM set_config('enable_seqscan', 'on', true);
  t0 := clock_timestamp();

  CASE p_query_id
    WHEN 1 THEN PERFORM * FROM q1_point_lookup(COALESCE((p_args ->> 'id')::bigint, lo));
    WHEN 2 THEN PERFORM * FROM q2_range_lookup(lo, hi);
    WHEN 3 THEN PERFORM * FROM q3_filter_age(COALESCE(p_args ->> 'age', '25-34'));
    WHEN 4 THEN PERFORM * FROM q4_filter_gender(COALESCE(p_args ->> 'gender', 'F'));
    WHEN 5 THEN PERFORM * FROM q5_multi_filter(m.age_group, m.gender, m.ad_category);
    WHEN 6 THEN PERFORM * FROM q6_count_by_category();
    WHEN 7 THEN PERFORM * FROM q7_count_by_demo();
    WHEN 8 THEN PERFORM * FROM q8_ctr_by_category();
    WHEN 9 THEN PERFORM * FROM q9_avg_spend_by_demo(COALESCE(p_args ->> 'age', '25-34'));
    WHEN 10 THEN
      PERFORM * FROM q10_time_range(
        COALESCE((p_args ->> 't0')::timestamptz, TIMESTAMPTZ '2023-01-01 00:00:00+00'),
        COALESCE((p_args ->> 't1')::timestamptz, TIMESTAMPTZ '2023-06-30 23:59:59+00')
      );
    WHEN 11 THEN PERFORM * FROM q11_high_spend(COALESCE((p_args ->> 'spend')::numeric, 5.0));
    WHEN 12 THEN
      PERFORM * FROM q12_region_category(
        COALESCE(p_args ->> 'region', 'Northeast'),
        COALESCE(p_args ->> 'ad_category', 'Housing')
      );
    WHEN 13 THEN PERFORM * FROM q13_bias_audit(cat13);
    ELSE PERFORM * FROM q1_point_lookup(lo);
  END CASE;

  t1 := clock_timestamp();
  b_ms := EXTRACT(EPOCH FROM (t1 - t0)) * 1000.0;

  -- PGM-style proxy path: no plain btree index scans; bitmap (e.g. BRIN) still allowed.
  PERFORM set_config('enable_indexscan', 'off', true);
  PERFORM set_config('enable_indexonlyscan', 'off', true);
  PERFORM set_config('enable_bitmapscan', 'on', true);
  PERFORM set_config('enable_seqscan', 'on', true);
  t0 := clock_timestamp();

  CASE p_query_id
    WHEN 1 THEN PERFORM * FROM q1_point_lookup(COALESCE((p_args ->> 'id')::bigint, lo));
    WHEN 2 THEN PERFORM * FROM q2_range_lookup(lo, hi);
    WHEN 3 THEN PERFORM * FROM q3_filter_age(COALESCE(p_args ->> 'age', '25-34'));
    WHEN 4 THEN PERFORM * FROM q4_filter_gender(COALESCE(p_args ->> 'gender', 'F'));
    WHEN 5 THEN PERFORM * FROM q5_multi_filter(m.age_group, m.gender, m.ad_category);
    WHEN 6 THEN PERFORM * FROM q6_count_by_category();
    WHEN 7 THEN PERFORM * FROM q7_count_by_demo();
    WHEN 8 THEN PERFORM * FROM q8_ctr_by_category();
    WHEN 9 THEN PERFORM * FROM q9_avg_spend_by_demo(COALESCE(p_args ->> 'age', '25-34'));
    WHEN 10 THEN
      PERFORM * FROM q10_time_range(
        COALESCE((p_args ->> 't0')::timestamptz, TIMESTAMPTZ '2023-01-01 00:00:00+00'),
        COALESCE((p_args ->> 't1')::timestamptz, TIMESTAMPTZ '2023-06-30 23:59:59+00')
      );
    WHEN 11 THEN PERFORM * FROM q11_high_spend(COALESCE((p_args ->> 'spend')::numeric, 5.0));
    WHEN 12 THEN
      PERFORM * FROM q12_region_category(
        COALESCE(p_args ->> 'region', 'Northeast'),
        COALESCE(p_args ->> 'ad_category', 'Housing')
      );
    WHEN 13 THEN PERFORM * FROM q13_bias_audit(cat13);
    ELSE PERFORM * FROM q1_point_lookup(lo);
  END CASE;

  t1 := clock_timestamp();
  s_ms := EXTRACT(EPOCH FROM (t1 - t0)) * 1000.0;

  RETURN jsonb_build_object(
    'query_id', p_query_id,
    'baseline_ms', round(b_ms::numeric, 3),
    'pgm_brin_proxy_ms', round(s_ms::numeric, 3),
    'modal_slice',
    jsonb_build_object(
      'age_group', m.age_group,
      'gender', m.gender,
      'ad_category', m.ad_category,
      'slice_count', (
        SELECT slice_count FROM clearbias_modal_age_gender_category() LIMIT 1
      )
    )
  );
END;
$$;

COMMENT ON FUNCTION clearbias_live_index_compare(integer, jsonb) IS
  'Runs q1–q13 twice: planner-friendly btree scans vs PGM-style BRIN proxy (indexscan off, bitmapscan on; BRIN on impression_id in sql/postgres/benchmark_schema.sql).';
