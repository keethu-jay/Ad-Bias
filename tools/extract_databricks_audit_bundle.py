#!/usr/bin/env python3
"""
Unpack the ClearBias Databricks export ZIP (email-named bundle dropped under audit_visuals/).

Writes:
  - databricks/exports/*          — snapshot from clearbias_export/
  - ClearBias_Audit_Files/*.csv    — query CSVs + benchmark_performance_results.csv from that bundle

Then deletes the ZIP so secrets/metadata never linger beside dashboard PNGs.

Usage (repo root):  python tools/extract_databricks_audit_bundle.py [path/to/bundle.zip]
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    default_zip = root / "audit_visuals" / "keethu.sa.jay@gmail.com.zip"
    zip_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else default_zip
    if not zip_path.is_file():
        print("ZIP not found:", zip_path, file=sys.stderr)
        sys.exit(1)

    inner_prefix = None
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if name.endswith("/clearbias_export/"):
                inner_prefix = name
                break
        if inner_prefix is None:
            print("Could not find clearbias_export/ folder inside ZIP.", file=sys.stderr)
            sys.exit(1)

        exports_prefix = inner_prefix  # e.g. user@…/clearbias_export/
        bundle_root = exports_prefix[: -len("clearbias_export/")]  # …/user@/

        exports_dst = root / "databricks" / "exports"
        audit_dst = root / "ClearBias_Audit_Files"
        exports_dst.mkdir(parents=True, exist_ok=True)

        for name in z.namelist():
            if not name.startswith(exports_prefix) or name.endswith("/"):
                continue
            rel = name[len(exports_prefix) :]
            if not rel:
                continue
            data = z.read(name)
            out_exports = exports_dst / rel
            out_exports.parent.mkdir(parents=True, exist_ok=True)
            out_exports.write_bytes(data)

            if rel == "final_benchmark_results.csv":
                (audit_dst / "benchmark_performance_results.csv").write_bytes(data)
            elif rel.startswith("q") and rel.endswith(".csv"):
                (audit_dst / rel).write_bytes(data)

        for extra in ("benchmark_performance_log.csv",):
            key = bundle_root + extra
            if key in z.namelist():
                (exports_dst / extra).write_bytes(z.read(key))

        if "manifest.mf" in z.namelist():
            (exports_dst / "manifest.mf").write_bytes(z.read("manifest.mf"))

    zip_path.unlink()
    print(
        "Extracted bundle into "
        f"{exports_dst.relative_to(root)} + ClearBias_Audit_Files; removed {zip_path.name}"
    )


if __name__ == "__main__":
    main()
