"""
Shared Oracle connection for ClearBias (python-oracledb Thin mode).

Resolution order:
  1. ORACLE_DSN — full connect string if set (e.g. from tnsnames or Easy Connect).
  2. ORACLE_SID — host/port + SID (matches SQL Developer “Basic” + SID).
  3. ORACLE_SERVICE — host/port + service name (e.g. XEPDB1).

Environment (typical WPI remote class Oracle):
  ORACLE_HOST=oracle.wpi.edu
  ORACLE_PORT=1521
  ORACLE_SID=ORCL
  ORACLE_USER=kjayamoorthy
  ORACLE_PASSWORD=...   # never commit
"""

from __future__ import annotations

import getpass
import os
from typing import Any


def connect_oracle(*, prompt_for_password: bool = True) -> Any:
    import oracledb

    user = os.environ.get("ORACLE_USER", "SYSTEM").strip()
    password = os.environ.get("ORACLE_PASSWORD")
    if not password:
        if prompt_for_password:
            password = getpass.getpass("Oracle password: ")
        else:
            raise RuntimeError("Set ORACLE_PASSWORD for server-side / Flask use.")

    dsn = (os.environ.get("ORACLE_DSN") or "").strip()
    if dsn:
        return oracledb.connect(user=user, password=password, dsn=dsn)

    host = os.environ.get("ORACLE_HOST", "localhost").strip()
    port = int(os.environ.get("ORACLE_PORT", "1521"))
    sid = (os.environ.get("ORACLE_SID") or "").strip()
    service = (os.environ.get("ORACLE_SERVICE") or "").strip()

    if sid:
        return oracledb.connect(
            user=user,
            password=password,
            host=host,
            port=port,
            sid=sid,
        )
    svc = service or "XEPDB1"
    return oracledb.connect(
        user=user,
        password=password,
        host=host,
        port=port,
        service_name=svc,
    )


def connection_summary() -> str:
    """Non-secret summary for logging."""
    host = os.environ.get("ORACLE_HOST", "localhost")
    port = os.environ.get("ORACLE_PORT", "1521")
    if (os.environ.get("ORACLE_DSN") or "").strip():
        return "dsn=ORACLE_DSN"
    sid = (os.environ.get("ORACLE_SID") or "").strip()
    if sid:
        return f"{host}:{port}/SID={sid}"
    svc = (os.environ.get("ORACLE_SERVICE") or "XEPDB1").strip()
    return f"{host}:{port}/{svc}"
