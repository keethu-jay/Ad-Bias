# Postgres SQL (ClearBias)

| File | What it’s for |
| :--- | :--- |
| **`benchmark_schema.sql`** | `ad_impressions` table, btree helper indexes, **BRIN** on `impression_id`, `benchmark_results`, and `q1`–`q13` SQL functions used by benchmarks / `clearbias_live_index_compare`. Applied via `python -m etl.apply_benchmark_schema`. |
| **`postgres_live_compare_function.sql`** | Defines `clearbias_live_index_compare()` — runs each packaged query twice (B+ friendly vs PGM-style BRIN/bitmap path). Apply after `benchmark_schema.sql`. |
| **`supabase_brin_impression_id.sql`** | Standalone `CREATE INDEX` for BRIN on `impression_id` (same as embedded in `benchmark_schema.sql`) if you only need the index on an existing DB. |
| **`fix_ad_impressions_lookup_alignment.sql`** | Repairs `ad_impressions` ↔ `interests` / `demographics` alignment; run via `python -m etl.referential_integrity align`. |
| **`migrate_interests_industry.sql`** | Backfills `interests.industry_id` + sector rows for older DBs. |
| **`normalize_ad_impressions_to_bcnf.sql`** | Pushes denormalized `ad_impressions` facts into the 22-table BCNF layout. |
| **`query5_ad_category_gender_cross_tab.sql`** | Ad-hoc cross-tab helper for Q5-style analysis (optional). |
