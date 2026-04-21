# ETL & schema scripts

Run everything **from the repo root** so `postgres_config` and paths resolve.

| Module | Command |
| :--- | :--- |
| Apply benchmark DDL | `python -m etl.apply_benchmark_schema` |
| Create 22-table Postgres schema | `python -m etl.create_postgres_schema` |
| HF → full BCNF load | `python -m etl.hf_to_postgres_load --help` |
| HF → `ad_impressions` only | `python -m etl.hf_to_ad_impressions_load --help` |
| Download Criteo-style data to disk | `python -m etl.download_criteo_data --help` |
| Referential audit / fix | `python -m etl.referential_integrity audit` / `align` |

**`category_industry.py`** — Python bucket map; keep in sync with `sql/postgres/migrate_interests_industry.sql` / `normalize_ad_impressions_to_bcnf.sql` CASE labels.
