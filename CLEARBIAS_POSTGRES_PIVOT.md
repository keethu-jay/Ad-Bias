# ClearBias PostgreSQL Pivot (Supabase/Neon)

## Why this pivot

Initially, the project used an Oracle-first architecture. The team pivoted to a cloud-native PostgreSQL stack to remove institutional network bottlenecks and support a reliable 1,000,000-row ETL and benchmark workflow.

## Supabase details

- Supabase API URL: `https://<project-ref>.supabase.co` (use your project from the Supabase dashboard)
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

"Initially, an Oracle-based architecture was attempted. However, to ensure 1,000,000 row scalability and bypass institutional network constraints that throttled data ingestion at 20,000 rows, the project migrated to a cloud-native PostgreSQL environment. This allowed for seamless ETL streaming from Hugging Face and more accurate benchmarking of high-volume index performance."
