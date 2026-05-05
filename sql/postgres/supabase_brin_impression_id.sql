-- =============================================================================
-- BRIN on impression_id — required for ClearBias live “PGM-style” timings.
-- Same definition as sql/postgres/benchmark_schema.sql (use this file alone in Supabase
-- SQL Editor when the table already exists and only this index is needed).
-- =============================================================================

CREATE INDEX IF NOT EXISTS ad_impressions_brin_impression_id_idx
  ON public.ad_impressions
  USING BRIN (impression_id)
  WITH (pages_per_range = 32);

COMMENT ON INDEX ad_impressions_brin_impression_id_idx IS
  'ClearBias PGM-style path: BRIN block summaries on impression_id; pair with clearbias_live_index_compare bitmap-friendly pass.';
