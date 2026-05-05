#!/usr/bin/env python3
"""
ClearBias — Create 22 BCNF tables in Oracle (Thin mode) and verify presence.

Usage (from repo root):
  set ORACLE_USER, ORACLE_PASSWORD, and either ORACLE_SID (WPI) or ORACLE_SERVICE / ORACLE_DSN
  python -m legacy_oracle.create_schema
  python -m legacy_oracle.create_schema --drop-first   # dev only: drop ClearBias tables in safe order

Does not print passwords. I log outcomes in IMPLEMENTATION_LOG.md when I run this.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from legacy_oracle.oracle_config import connect_oracle

# All ClearBias physical tables (Oracle stores unquoted identifiers as UPPERCASE)
CLEARBIAS_TABLES: tuple[str, ...] = (
    "AUDIT_RESULTS",
    "AUDIT_SESSIONS",
    "AUDITORS",
    "AD_CONTENT",
    "AD_CREATIVES",
    "AGE_GROUPS",
    "BIAS_METRICS",
    "BIAS_SCORES",
    "CAMPAIGNS",
    "DATA_SOURCE_METADATA",
    "DEMOGRAPHICS",
    "INDUSTRIES",
    "INDEX_TYPES",
    "INTERESTS",
    "PERFORMANCE_LOGS",
    "PLATFORMS",
    "QUERY_TEMPLATES",
    "REGIONS",
    "SYSTEM_SETTINGS",
    "TARGET_PROFILES",
    "USER_ROLES",
    "ADVERTISERS",
)


def _connect():
    return connect_oracle(prompt_for_password=True)


def ddl_create_statements() -> list[str]:
    """DDL in dependency order (22 tables)."""
    return [
        """
        CREATE TABLE industries (
            industry_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name VARCHAR2(200) NOT NULL,
            CONSTRAINT uq_industries_name UNIQUE (name)
        )
        """,
        """
        CREATE TABLE user_roles (
            user_role_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            role_name VARCHAR2(80) NOT NULL,
            CONSTRAINT uq_user_roles_name UNIQUE (role_name)
        )
        """,
        """
        CREATE TABLE index_types (
            index_type_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            type_name VARCHAR2(40) NOT NULL,
            CONSTRAINT uq_index_types_name UNIQUE (type_name)
        )
        """,
        """
        CREATE TABLE query_templates (
            query_template_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            sql_code CLOB NOT NULL
        )
        """,
        """
        CREATE TABLE platforms (
            platform_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name VARCHAR2(120) NOT NULL,
            CONSTRAINT uq_platforms_name UNIQUE (name)
        )
        """,
        """
        CREATE TABLE age_groups (
            age_group_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            min_age NUMBER(3) NOT NULL,
            max_age NUMBER(3) NOT NULL,
            CONSTRAINT chk_age_groups_range CHECK (min_age >= 0 AND max_age >= min_age)
        )
        """,
        """
        CREATE TABLE interests (
            interest_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            interest_name VARCHAR2(200) NOT NULL,
            CONSTRAINT uq_interests_name UNIQUE (interest_name)
        )
        """,
        """
        CREATE TABLE demographics (
            demographic_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            race VARCHAR2(120),
            gender VARCHAR2(40),
            income NUMBER(14, 2)
        )
        """,
        """
        CREATE TABLE target_profiles (
            target_profile_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            profile_name VARCHAR2(200) NOT NULL,
            CONSTRAINT uq_target_profiles_name UNIQUE (profile_name)
        )
        """,
        """
        CREATE TABLE regions (
            region_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            city VARCHAR2(120),
            state VARCHAR2(120),
            country VARCHAR2(120) NOT NULL
        )
        """,
        """
        CREATE TABLE advertisers (
            advertiser_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name VARCHAR2(300) NOT NULL,
            industry_id NUMBER NOT NULL,
            CONSTRAINT fk_advertisers_industry FOREIGN KEY (industry_id) REFERENCES industries (industry_id)
        )
        """,
        """
        CREATE TABLE campaigns (
            campaign_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            advertiser_id NUMBER NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE,
            CONSTRAINT fk_campaigns_advertiser FOREIGN KEY (advertiser_id) REFERENCES advertisers (advertiser_id),
            CONSTRAINT chk_campaigns_dates CHECK (end_date IS NULL OR end_date >= start_date)
        )
        """,
        """
        CREATE TABLE ad_creatives (
            ad_creative_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            campaign_id NUMBER NOT NULL,
            format VARCHAR2(60) NOT NULL,
            CONSTRAINT fk_ad_creatives_campaign FOREIGN KEY (campaign_id) REFERENCES campaigns (campaign_id)
        )
        """,
        """
        CREATE TABLE ad_content (
            ad_content_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ad_creative_id NUMBER NOT NULL,
            headline VARCHAR2(500),
            body_text CLOB,
            CONSTRAINT fk_ad_content_creative FOREIGN KEY (ad_creative_id) REFERENCES ad_creatives (ad_creative_id),
            CONSTRAINT uq_ad_content_creative UNIQUE (ad_creative_id)
        )
        """,
        """
        CREATE TABLE bias_metrics (
            bias_metric_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            metric_name VARCHAR2(120) NOT NULL,
            CONSTRAINT uq_bias_metrics_name UNIQUE (metric_name)
        )
        """,
        """
        CREATE TABLE bias_scores (
            bias_score_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ad_id NUMBER NOT NULL,
            metric_id NUMBER NOT NULL,
            score_value NUMBER(5, 4) NOT NULL,
            CONSTRAINT fk_bias_scores_ad FOREIGN KEY (ad_id) REFERENCES ad_creatives (ad_creative_id),
            CONSTRAINT fk_bias_scores_metric FOREIGN KEY (metric_id) REFERENCES bias_metrics (bias_metric_id),
            CONSTRAINT chk_bias_scores_01 CHECK (score_value BETWEEN 0 AND 1)
        )
        """,
        """
        CREATE TABLE auditors (
            auditor_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_role_id NUMBER NOT NULL,
            name VARCHAR2(200) NOT NULL,
            CONSTRAINT fk_auditors_role FOREIGN KEY (user_role_id) REFERENCES user_roles (user_role_id)
        )
        """,
        """
        CREATE TABLE audit_sessions (
            audit_session_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            auditor_id NUMBER NOT NULL,
            start_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
            CONSTRAINT fk_audit_sessions_auditor FOREIGN KEY (auditor_id) REFERENCES auditors (auditor_id)
        )
        """,
        """
        CREATE TABLE audit_results (
            audit_result_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            session_id NUMBER NOT NULL,
            summary VARCHAR2(4000),
            CONSTRAINT fk_audit_results_session FOREIGN KEY (session_id) REFERENCES audit_sessions (audit_session_id)
        )
        """,
        """
        CREATE TABLE performance_logs (
            performance_log_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            query_id NUMBER NOT NULL,
            index_type_id NUMBER NOT NULL,
            latency_ms NUMBER(14, 3) NOT NULL,
            memory_mb NUMBER(14, 3) NOT NULL,
            CONSTRAINT fk_perf_logs_query FOREIGN KEY (query_id) REFERENCES query_templates (query_template_id),
            CONSTRAINT fk_perf_logs_index FOREIGN KEY (index_type_id) REFERENCES index_types (index_type_id),
            CONSTRAINT chk_perf_logs_lat CHECK (latency_ms >= 0),
            CONSTRAINT chk_perf_logs_mem CHECK (memory_mb >= 0)
        )
        """,
        """
        CREATE TABLE system_settings (
            system_setting_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            setting_key VARCHAR2(120) NOT NULL,
            setting_value VARCHAR2(4000),
            CONSTRAINT uq_system_settings_key UNIQUE (setting_key)
        )
        """,
        """
        CREATE TABLE data_source_metadata (
            data_source_metadata_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_name VARCHAR2(200) NOT NULL,
            record_count NUMBER(18, 0) NOT NULL,
            CONSTRAINT uq_data_source_name UNIQUE (source_name),
            CONSTRAINT chk_data_source_count CHECK (record_count >= 0)
        )
        """,
    ]


def ddl_drop_statements() -> list[str]:
    """Reverse dependency order."""
    return [
        "DROP TABLE performance_logs CASCADE CONSTRAINTS",
        "DROP TABLE audit_results CASCADE CONSTRAINTS",
        "DROP TABLE audit_sessions CASCADE CONSTRAINTS",
        "DROP TABLE bias_scores CASCADE CONSTRAINTS",
        "DROP TABLE ad_content CASCADE CONSTRAINTS",
        "DROP TABLE ad_creatives CASCADE CONSTRAINTS",
        "DROP TABLE campaigns CASCADE CONSTRAINTS",
        "DROP TABLE advertisers CASCADE CONSTRAINTS",
        "DROP TABLE auditors CASCADE CONSTRAINTS",
        "DROP TABLE bias_metrics CASCADE CONSTRAINTS",
        "DROP TABLE query_templates CASCADE CONSTRAINTS",
        "DROP TABLE index_types CASCADE CONSTRAINTS",
        "DROP TABLE data_source_metadata CASCADE CONSTRAINTS",
        "DROP TABLE system_settings CASCADE CONSTRAINTS",
        "DROP TABLE regions CASCADE CONSTRAINTS",
        "DROP TABLE target_profiles CASCADE CONSTRAINTS",
        "DROP TABLE demographics CASCADE CONSTRAINTS",
        "DROP TABLE interests CASCADE CONSTRAINTS",
        "DROP TABLE age_groups CASCADE CONSTRAINTS",
        "DROP TABLE platforms CASCADE CONSTRAINTS",
        "DROP TABLE industries CASCADE CONSTRAINTS",
        "DROP TABLE user_roles CASCADE CONSTRAINTS",
    ]


def verify_table_count(cur) -> tuple[int, list[str]]:
    in_list = ", ".join(f"'{n}'" for n in CLEARBIAS_TABLES)
    cur.execute(
        f"""
        SELECT table_name FROM user_tables
        WHERE table_name IN ({in_list})
        ORDER BY table_name
        """
    )
    found = [r[0] for r in cur.fetchall()]
    return len(found), found


def main() -> int:
    parser = argparse.ArgumentParser(description="Create ClearBias Oracle schema (22 tables).")
    parser.add_argument("--drop-first", action="store_true", help="Drop existing ClearBias tables first.")
    parser.add_argument("--verify-only", action="store_true", help="Only run USER_TABLES verification.")
    args = parser.parse_args()

    try:
        import oracledb  # noqa: F401
    except ImportError:
        print("Install: pip install oracledb", file=sys.stderr)
        return 1

    try:
        conn = _connect()
    except Exception as exc:  # noqa: BLE001
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 2

    cur = conn.cursor()
    try:
        if args.drop_first and not args.verify_only:
            print("Dropping existing ClearBias tables (if any)...")
            for stmt in ddl_drop_statements():
                try:
                    cur.execute(stmt)
                except Exception:
                    pass
            conn.commit()

        if not args.verify_only:
            print("Creating 22 BCNF tables...")
            t0 = time.perf_counter()
            for stmt in ddl_create_statements():
                cur.execute(stmt)
            conn.commit()
            print(f"DDL committed in {(time.perf_counter() - t0) * 1000:.1f} ms")

        n, names = verify_table_count(cur)
        print("--- Verification: SELECT table_name FROM user_tables (filtered) ---")
        for t in names:
            print(f"  {t}")
        print(f"--- Count (ClearBias tables found): {n} (expected {len(CLEARBIAS_TABLES)}) ---")
        if n != len(CLEARBIAS_TABLES):
            missing = sorted(set(CLEARBIAS_TABLES) - set(names))
            if missing:
                print(f"Missing: {missing}", file=sys.stderr)
            return 3
    finally:
        cur.close()
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
