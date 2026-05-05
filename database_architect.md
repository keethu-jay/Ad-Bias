# Context: CS 542 ClearBias Project

**Goal:** Implement 22+ BCNF tables in Oracle for Ad Bias Auditing.

**Email / instructor:** Official feedback for Prof. Kong goes through **my WPI Outlook** (same address I used in Phase 1). I use that mailbox for late progress reports and replies.

## Task 1: DDL Generation

Using the table list in the project brief, generate a complete Oracle SQL script.

- **Canonical script:** `legacy_oracle/schema.sql` (duplicate `legacy_oracle/ddl.sql` for SQL Developer convenience).
- Use `NUMBER … GENERATED ALWAYS AS IDENTITY` for primary keys.
- Foreign keys must reference the correct parent keys.
- Add `CHECK` constraints (e.g. `bias_score` in \[0, 1\], non-negative budgets/latency).

## Task 2: Data Loading Logic

`loader.py` should:

- Read a Facebook Ads–style CSV (column names configurable via CLI / env).
- Use **`cursor.executemany`** for bulk inserts where possible.
- **Normalization:** e.g. if a row has category `"Housing"`, resolve or insert `industry_category` first, then use its surrogate key in `ad_category_map` — never duplicate free-text category as a determinant in fact tables.

## Task 3: Audit Interface (Backend)

- Implement **`get_query(query_id, index_mode)`** in `queries.py`: returns the SQL string for that audit task.
- Queries should **join 3–5 BCNF tables** (e.g. `cb_ad` → `ad_creative` → `campaign` → `advertiser`, plus `bias_score`, `industry_category`, `location_region` as needed).
- `index_mode` should switch **hint comments** (B+ tree vs PGM-oriented) without changing the relational logic.

## After Oracle install

1. Connect in **SQL Developer** (e.g. as `SYSTEM` or my app user), then **Run Script** on `legacy_oracle/schema.sql` / `legacy_oracle/ddl.sql`.
2. Grant my app schema `SELECT` on `V_$SQL` (or equivalent) if I use validated timing from `benchmark.py`.
