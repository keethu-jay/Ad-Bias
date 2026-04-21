#!/usr/bin/env python3
"""
ClearBias — Oracle connectivity smoke test using python-oracledb in Thin mode
(no Oracle Client / sqlplus on PATH required).

WPI remote (from SQL Developer → Properties):
  ORACLE_HOST=oracle.wpi.edu
  ORACLE_PORT=1521
  ORACLE_SID=ORCL
  ORACLE_USER=kjayamoorthy
  ORACLE_PASSWORD=...   # env or prompt

Alternatively set ORACLE_DSN, or use ORACLE_SERVICE (and leave ORACLE_SID unset) for service-name connects.
"""

from __future__ import annotations

import sys
import time

from legacy_oracle.oracle_config import connect_oracle, connection_summary


def main() -> int:
    try:
        import oracledb  # noqa: F401
    except ImportError:
        print("Install: pip install oracledb", file=sys.stderr)
        return 1

    summary = connection_summary()
    try:
        t0 = time.perf_counter()
        conn = connect_oracle(prompt_for_password=True)
        cur = conn.cursor()
        cur.execute(
            "SELECT SYS_CONTEXT('USERENV','CURRENT_USER'), "
            "SYS_CONTEXT('USERENV','SERVICE_NAME'), "
            "SYS_CONTEXT('USERENV','DB_NAME') FROM DUAL"
        )
        row = cur.fetchone()
        ms = (time.perf_counter() - t0) * 1000
        print(f"OK — connected ({summary}) in {ms:.1f} ms")
        print(f"    CURRENT_USER: {row[0]}")
        print(f"    SERVICE_NAME: {row[1]}")
        print(f"    DB_NAME:      {row[2]}")
        cur.close()
        conn.close()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"Connection failed ({summary}): {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
