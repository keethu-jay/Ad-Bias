# ClearBias



Bias-focused audit queries over a large ad/impression-style dataset — compare **B+ tree–style** access vs a **PGM-style** proxy in Postgres (BRIN + bitmap-friendly planner settings). There is also an older **Oracle / BCNF** stack under **`legacy_oracle/`** for course reproducibility.



---



## Quick start



1. **Python 3.10+**, `pip install -r requirements.txt`

2. **Postgres / Supabase:** set `CLEARBIAS_POSTGRES_DSN` (or `DATABASE_URL` / `SUPABASE_DB_URL`) — see `postgres_config.py`.

3. **Benchmark DDL:** `python -m etl.apply_benchmark_schema` (applies `sql/postgres/benchmark_schema.sql`).

4. **Compare function (optional, for `/api/postgres-live-*`):** run `sql/postgres/postgres_live_compare_function.sql` in the SQL editor or `psql`.

5. **Web UI:** `python app.py` → `http://127.0.0.1:5000/` (`live_dashboard.html`).



**Env flags** (see `app.py` docstring):



| Variable | Role |

| :--- | :--- |

| `USE_POSTGRES` | `true` (default) — live queries via `queries_live_supabase.py` |

| `USE_ORACLE` | `true` only if using `legacy_oracle/` |

| `PORT` | Flask port (default `5000`) |



---



## Repository layout



### App & benchmarking (repo root)



| Path | Purpose |

| :--- | :--- |

| **`app.py`** | Flask: `/`, `/run-query`, `/api/*`, static assets |

| **`live_dashboard.html`**, **`index.html`** | Dashboard UI |

| **`queries_live_supabase.py`** | Q1–Q13 live SQL + `set_index_mode` (B+ vs BRIN/bitmap) |

| **`benchmark.py`** | Timing: Postgres live, optional Oracle V$SQL, mock |

| **`postgres_config.py`** | DSN + `connect_postgres()` |

| **`run_benchmarks.py`** | Postgres 13-query benchmark driver |

| **`validation_script.py`** | HTTP smoke test against `/run-query` |

| **`static_export.py`** | ZIP export of audit CSVs |

| **`generate_audit_visuals.py`** | Writes PNGs to `audit_visuals/` |

| **`IMPLEMENTATION_LOG.md`** | What changed and why |



### `sql/postgres/` — hand-run & benchmark SQL



See **`sql/postgres/README.md`** for a per-file table. Highlights: **`benchmark_schema.sql`**, **`postgres_live_compare_function.sql`**, alignment / migration / normalize scripts.



### `etl/` — loads, schema bootstrap, DDL apply



See **`etl/README.md`** for commands. Python here talks to Postgres via `postgres_config` (run as `python -m etl.<module>` from repo root).



### Data & assets



| Path | Purpose |

| :--- | :--- |

| **`ClearBias_Audit_Files/`** | Static CSVs + `benchmark_performance_results.csv` (Databricks snapshot) |

| **`audit_visuals/`** | PNGs for the dashboard |



### Legacy Oracle



| Path | Purpose |

| :--- | :--- |

| **`legacy_oracle/`** | Original 22-table Oracle path: config, schema DDL, `load_data`, `queries`, HF→Oracle, etc. Run with `python -m legacy_oracle.<module>`. |



Misc: `vercel.json`, `database_architect.md`, `CLEARBIAS_POSTGRES_PIVOT.md`.



---



## Oracle vs Postgres



- **Postgres / Supabase** — default for the live dashboard.

- **`legacy_oracle/`** — enable with `USE_ORACLE=true` and `ORACLE_*` vars (`legacy_oracle/oracle_config.py`).



---



## Implementation history



**`IMPLEMENTATION_LOG.md`** — dated notes (BRIN choice, UI, folder moves, etc.).

