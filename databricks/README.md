# Databricks artifacts

| File | Role |
| :--- | :--- |
| **`clearbias_compute.py`** | Notebook export (Databricks `.py`): connects to Postgres via repo **`postgres_config`** (DSN env vars), toggles `enable_indexscan`, exports per-query CSVs + **`benchmark_performance_results.csv`** inside an in-memory ZIP with download HTML. |
| **`clearbias_benchmark.ipynb`** | Alternate Spark-only timing harness (no live Postgres); optional template. |
| **`exports/`** | Frozen CSV bundle unpacked from the workspace export ZIP (`final_benchmark_results.csv`, `q*.csv`, optional logs). Same column naming as **`ClearBias_Audit_Files/`** at repo root (dashboard reads root copies). |

Extract a dropped ZIP from `audit_visuals/`:

```
python tools/extract_databricks_audit_bundle.py
```

Workspace URL (sign-in required):  
https://dbc-23063686-87f0.cloud.databricks.com/editor/notebooks/2216068845186789?o=7474645010599702
