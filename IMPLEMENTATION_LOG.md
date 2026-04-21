# Implementation log (ClearBias)

Scratch pad for what I actually built and why — useful when I write the report or pick this up after a week away. Not a transcript of every command.

---

## How I use this file

- **Date** — when the change landed (approximate is fine).
- **What** — files or behavior.
- **Why** — motivation or constraint (course requirement, accuracy, UX).
- **Evidence** — optional: numbers, screenshots, “query X returns Y”.

---

## 2026-04 — Folder layout (`sql/postgres/`, `etl/`)

- **What:** Moved all hand-authored **Postgres SQL** into **`sql/postgres/`** (benchmark DDL, compare function, BRIN snippet, fix/migrate/normalize, Q5 helper). Moved **load / clean / schema-apply Python** into **`etl/`** (`apply_benchmark_schema`, HF loaders, `create_postgres_schema`, `referential_integrity`, `download_criteo_data`, `category_industry`).
- **Why:** Root was crowded; I wanted one place for SQL I run in Supabase/psql and one package for anything that mutates data or applies DDL.
- **How to run:** From repo root, `python -m etl.apply_benchmark_schema`, `python -m etl.hf_to_postgres_load`, etc. See **`etl/README.md`** and **`sql/postgres/README.md`**.

---

## 2026-04 — Remove Cursor-only docs

- **What:** Deleted **`MASTER_SETUP.md`**, **`CLEARBIAS_MASTER_INSTRUCTIONS.md`**, and **`CLEARBIAS_NEXT_STEPS.md`** — they were written for Cursor/agent workflow, not for the project itself.
- **Why:** README + `IMPLEMENTATION_LOG` + inline comments are enough; Oracle env details stay in **`legacy_oracle/oracle_config.py`**.

---

## 2026-04 — Repo layout + docs cleanup

- **What:** Put all the old Oracle course stack under **`legacy_oracle/`** (`oracle_config`, `create_schema`, `load_data`, `queries`, HF→Oracle loaders, `loader`, `prepare_web_data`, and the hand-run **`schema.sql` / `ddl.sql`**). The app still supports `USE_ORACLE=true`, but day-to-day work is Postgres/Supabase from the repo root.
- **Why:** The root was a mix of two databases; I kept losing track of what mattered for the live demo vs what was for the original BCNF assignment.
- **How to run Oracle scripts now:** From repo root, e.g. `python -m legacy_oracle.create_schema` — env vars are described in `legacy_oracle/oracle_config.py`.

---

## 2026-04 — Live Supabase path (BRIN as PGM-style stand-in)

- **What:** PostgreSQL doesn’t ship a learned PGM index. For “live” comparisons I’m using a **BRIN on `impression_id`** (block min/max summaries) plus planner settings that turn **off** plain btree index/index-only scans but leave **bitmap** scans on, so that BRIN can show up as a bitmap plan when it makes sense. That’s wired the same way in **`queries_live_supabase.py`** (`set_index_mode`) and **`postgres_live_compare_function.sql`** (`clearbias_live_index_compare`).
- **Why:** Turning *all* indexes off was basically “always sequential scan” — too pessimistic and not a fair story for the report. BRIN is the closest built-in thing to “skip big chunks of the table using coarse structure,” which is what I wanted to argue next to a normal B+ tree path.
- **What:** **`sql/postgres/benchmark_schema.sql`** creates the BRIN index with the rest of the benchmark DDL; **`sql/postgres/supabase_brin_impression_id.sql`** is the same index if I only run a snippet in the Supabase SQL editor on an existing DB.
- **Note:** Filters that don’t line up with physical order (e.g. gender-only) won’t magically speed up from BRIN on `impression_id` — that’s expected and worth stating in the write-up.

---

## 2026-04 — Dashboard / UI (`live_dashboard.html`)

- **What:** Databricks snapshot chart is grouped bars with a **shared ms scale** and per-row B+ vs PGM sim numbers so one query doesn’t look like a single smeared color. Live Supabase section uses a **small bar chart** for B+ vs BRIN/PGM-style latency plus a **delta** strip instead of a “speedup” multiplier I didn’t trust interpreting. Removed the “rigorous warmup” checkbox — the API still defaults to a single timed run; if I need averages I’ll use the CLI or hit the API with a `benchmark` payload.
- **What:** Query visual card got a **light panel** behind PNGs so matplotlib text stays readable; `<code>` in dark cards got explicit light styling.
- **Why:** Presentation clarity and not overstating precision I don’t have from one click.

---

## 2026-04 — Interests → industries (category as sector signal)

- **Context:** With no real advertiser entity in the HF/impression pipeline, `ad_category` was the best signal for “what sector this ad belongs to.” `interests.industry_id` ties into `industries`; seven bucket labels plus `General & Other`; same mapping rules in **`etl/category_industry.py`**, **`sql/postgres/migrate_interests_industry.sql`**, and **`sql/postgres/normalize_ad_impressions_to_bcnf.sql`**.
- **Evidence:** Migration against Supabase; spot-check joins `interest_name` → `industries.name`.

---

## 2026-04-13 — Oracle thin mode + WPI connection

- **What:** `python-oracledb` thin mode (no Instant Client path). **`oracle_config`** (now under `legacy_oracle`) supports `ORACLE_SID` vs `ORACLE_SERVICE` / `ORACLE_DSN`. Password only via **`ORACLE_PASSWORD`** (or prompt), never committed.
- **What:** **`create_schema.py`** verifies the **22** ClearBias tables by name in `USER_TABLES` — not a blind `COUNT(*)` on all tables, because other course tables live in the same schema.
- **Host:** `oracle.wpi.edu:1521`, SID `ORCL` (WPI class setup; same vars as `oracle_config`).

---

## Parking lot / optional follow-ups

- [ ] Re-run full benchmark grid after any major DDL change and paste timings into the report appendix.
- [ ] If Oracle path is never used again, could delete `legacy_oracle/` entirely — keeping it for now for reproducibility and course submission.
