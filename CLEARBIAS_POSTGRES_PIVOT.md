# ClearBias PostgreSQL Pivot (Supabase/Neon)

## Why this pivot

Initially, I used an Oracle-first layout. I moved to a cloud-hosted PostgreSQL stack (Supabase) to get past campus network limits and run a stable 1,000,000-row ETL plus benchmark loop.

## Supabase details

- Supabase API URL: `https://<project-ref>.supabase.co` (I take `<project-ref>` from my Supabase dashboard)
- Required for scripts: PostgreSQL connection string (DSN), not the API URL alone.

Example DSN format:

`postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres?sslmode=require`

## Environment setup (PowerShell)

```powershell
$env:CLEARBIAS_POSTGRES_DSN = "postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres?sslmode=require"
python -m pip install -r requirements.txt
```

## Execution sequence

1. Create schema:
   - `python -m etl.create_postgres_schema --drop-first`
2. Stream/load data:
   - `python -m etl.hf_to_postgres_load --dataset criteo/CriteoClickLogs --split train --max-rows 1000000 --chunk-size 5000`
3. Run 13-query benchmark:
   - `python run_benchmarks.py --warmup-runs 1 --timed-runs 3`
4. Review log:
   - `IMPLEMENTATION_LOG.md` (new benchmark section appended)

## Report-ready decision note

"I started on Oracle, but ingestion stalled around 20,000 rows on the institutional network. I switched to managed PostgreSQL, streamed one million rows from Hugging Face, and ran the 13-query benchmark there — that is the setup this repo documents."
