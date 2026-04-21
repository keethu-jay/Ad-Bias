#!/usr/bin/env python3
"""
Download Criteo-style rows from Hugging Face to local disk (no database).

Default source: reczoo/Criteo_x4 (Parquet-backed; works with streaming).
criteo/CriteoClickLogs is not supported by the datasets library as-is (raw .gz layout).

Usage (from repo root):
  python -m etl.download_criteo_data --out-dir data/criteo --max-rows 1000000
  python -m etl.download_criteo_data --out-dir data/criteo --all   # stream until dataset ends (large)
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import sys
from typing import Any, TextIO


def hf_row_to_csv_dict(rec: dict[str, Any]) -> dict[str, str]:
    lab = rec.get("label") if rec.get("label") is not None else rec.get("Label")
    try:
        label_s = str(int(float(lab))) if lab is not None else "0"
    except (TypeError, ValueError):
        label_s = (str(lab).strip() or "0")
    out: dict[str, str] = {"label": label_s}
    for i in range(1, 14):
        k = f"I{i}"
        v = rec.get(k)
        out[k] = "" if v is None else str(v).strip()
    for i in range(1, 27):
        k = f"C{i}"
        v = rec.get(k)
        out[k] = "" if v is None else str(v).strip()
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Download Hugging Face Criteo data to gzipped CSV chunks.")
    p.add_argument("--dataset", default="reczoo/Criteo_x4", help="HF dataset id (default: reczoo/Criteo_x4).")
    p.add_argument("--split", default="train", help="Split name.")
    p.add_argument("--out-dir", default="data/criteo", help="Output directory.")
    p.add_argument("--chunk-rows", type=int, default=100_000, help="Rows per part file.")
    p.add_argument("--max-rows", type=int, default=1_000_000, help="Stop after this many rows (ignored with --all).")
    p.add_argument("--all", action="store_true", help="Stream until the dataset iterator ends.")
    args = p.parse_args()

    try:
        from datasets import load_dataset
    except ImportError:
        print("Install: pip install datasets", file=sys.stderr)
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    fieldnames = ["label"] + [f"I{i}" for i in range(1, 14)] + [f"C{i}" for i in range(1, 27)]

    ds = load_dataset(args.dataset, split=args.split, streaming=True)
    it = iter(ds)

    total = 0
    part = 0
    f_out: TextIO | None = None
    writer: csv.DictWriter | None = None
    rows_in_part = 0

    def open_new_part() -> tuple[TextIO, csv.DictWriter]:
        nonlocal part
        path = os.path.join(args.out_dir, f"train_part{part:04d}.csv.gz")
        part += 1
        gz = gzip.open(path, "wt", encoding="utf-8", newline="")
        w = csv.DictWriter(gz, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        print(f"Writing {path} ...", flush=True)
        return gz, w

    try:
        while True:
            if not args.all and total >= args.max_rows:
                break
            try:
                rec = next(it)
            except StopIteration:
                break
            if f_out is None or rows_in_part >= args.chunk_rows:
                if f_out is not None:
                    f_out.close()
                f_out, writer = open_new_part()
                rows_in_part = 0
            assert writer is not None
            writer.writerow(hf_row_to_csv_dict(rec))
            rows_in_part += 1
            total += 1
            if total % 50_000 == 0:
                print(f"  ... {total} rows", flush=True)
    finally:
        if f_out is not None:
            f_out.close()

    print(f"Done. Wrote {total} rows under {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
