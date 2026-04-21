-- =============================================================================
-- ClearBias / CS 542 — Oracle DDL (BCNF-oriented)
-- 22+ tables: listed domains + CB_AD (ad instance for Ad_ID) + targeting bridges
-- Run in SQL Developer (F5) or SQL*Plus as a script.
-- =============================================================================
WHENEVER SQLERROR EXIT SQL.SQLCODE;

-- Clean-slate (optional): uncomment for dev rebuild
-- BEGIN FOR r IN (SELECT t.table_name FROM user_tables t) LOOP EXECUTE IMMEDIATE 'DROP TABLE ' || t.table_name || ' CASCADE CONSTRAINTS'; END LOOP; END; /

-- ---------------------------------------------------------------------------
-- ADVERTISERS
-- ---------------------------------------------------------------------------
CREATE TABLE advertiser (
    advertiser_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            VARCHAR2(200) NOT NULL
);

CREATE TABLE industry_category (
    industry_category_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_name          VARCHAR2(120) NOT NULL,
    CONSTRAINT uq_industry_category_name UNIQUE (category_name)
);

CREATE TABLE advertiser_contact (
    contact_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    advertiser_id    NUMBER NOT NULL,
    email            VARCHAR2(320) NOT NULL,
    CONSTRAINT fk_ac_advertiser FOREIGN KEY (advertiser_id) REFERENCES advertiser (advertiser_id),
    CONSTRAINT uq_advertiser_email UNIQUE (advertiser_id, email)
);

-- ---------------------------------------------------------------------------
-- CAMPAIGNS & PLATFORMS
-- ---------------------------------------------------------------------------
CREATE TABLE platform (
    platform_id    NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    platform_name  VARCHAR2(80) NOT NULL,
    CONSTRAINT uq_platform_name UNIQUE (platform_name)
);

CREATE TABLE campaign (
    campaign_id    NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    advertiser_id  NUMBER NOT NULL,
    start_date     DATE NOT NULL,
    end_date       DATE,
    CONSTRAINT fk_campaign_advertiser FOREIGN KEY (advertiser_id) REFERENCES advertiser (advertiser_id),
    CONSTRAINT chk_campaign_dates CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE TABLE campaign_budget (
    campaign_id   NUMBER PRIMARY KEY,
    daily_limit   NUMBER(14, 2) NOT NULL,
    CONSTRAINT fk_budget_campaign FOREIGN KEY (campaign_id) REFERENCES campaign (campaign_id),
    CONSTRAINT chk_daily_limit_nonneg CHECK (daily_limit >= 0)
);

-- ---------------------------------------------------------------------------
-- ADS (creative + content + placed ad + category map)
-- ---------------------------------------------------------------------------
CREATE TABLE ad_creative (
    ad_creative_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    campaign_id      NUMBER NOT NULL,
    creative_type    VARCHAR2(60) NOT NULL,
    CONSTRAINT fk_creative_campaign FOREIGN KEY (campaign_id) REFERENCES campaign (campaign_id)
);

CREATE TABLE ad_content (
    ad_content_id    NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ad_creative_id   NUMBER NOT NULL,
    headline         VARCHAR2(500),
    body_text        CLOB,
    CONSTRAINT fk_content_creative FOREIGN KEY (ad_creative_id) REFERENCES ad_creative (ad_creative_id),
    CONSTRAINT uq_one_content_per_creative UNIQUE (ad_creative_id)
);

-- Ad instance (supplies Ad_ID for bias / category map / audits)
CREATE TABLE cb_ad (
    ad_id             NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ad_creative_id    NUMBER NOT NULL,
    platform_id       NUMBER NOT NULL,
    target_audience_id NUMBER,
    posted_at         TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_cb_ad_creative FOREIGN KEY (ad_creative_id) REFERENCES ad_creative (ad_creative_id),
    CONSTRAINT fk_cb_ad_platform FOREIGN KEY (platform_id) REFERENCES platform (platform_id)
);

CREATE TABLE ad_category_map (
    ad_id                  NUMBER NOT NULL,
    industry_category_id   NUMBER NOT NULL,
    CONSTRAINT pk_ad_category PRIMARY KEY (ad_id, industry_category_id),
    CONSTRAINT fk_acm_ad FOREIGN KEY (ad_id) REFERENCES cb_ad (ad_id),
    CONSTRAINT fk_acm_industry FOREIGN KEY (industry_category_id) REFERENCES industry_category (industry_category_id)
);

-- ---------------------------------------------------------------------------
-- TARGETING (reference + BCNF bridges for M:N)
-- ---------------------------------------------------------------------------
CREATE TABLE target_audience (
    target_audience_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name                 VARCHAR2(200) NOT NULL,
    description          VARCHAR2(1000),
    CONSTRAINT uq_target_audience_name UNIQUE (name)
);

ALTER TABLE cb_ad ADD CONSTRAINT fk_cb_ad_audience
    FOREIGN KEY (target_audience_id) REFERENCES target_audience (target_audience_id);

CREATE TABLE age_group (
    age_group_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    min_age        NUMBER(3) NOT NULL,
    max_age        NUMBER(3) NOT NULL,
    CONSTRAINT chk_age_range CHECK (min_age >= 0 AND max_age >= min_age)
);

CREATE TABLE location_region (
    location_region_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    state_code           VARCHAR2(8),
    country_code         VARCHAR2(3) NOT NULL,
    CONSTRAINT uq_region_state_country UNIQUE (state_code, country_code)
);

CREATE TABLE interest_tag (
    interest_tag_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tag_name          VARCHAR2(120) NOT NULL,
    CONSTRAINT uq_interest_tag_name UNIQUE (tag_name)
);

CREATE TABLE target_audience_age (
    target_audience_id   NUMBER NOT NULL,
    age_group_id         NUMBER NOT NULL,
    CONSTRAINT pk_taa PRIMARY KEY (target_audience_id, age_group_id),
    CONSTRAINT fk_taa_audience FOREIGN KEY (target_audience_id) REFERENCES target_audience (target_audience_id),
    CONSTRAINT fk_taa_age FOREIGN KEY (age_group_id) REFERENCES age_group (age_group_id)
);

CREATE TABLE target_audience_region (
    target_audience_id    NUMBER NOT NULL,
    location_region_id    NUMBER NOT NULL,
    CONSTRAINT pk_tar PRIMARY KEY (target_audience_id, location_region_id),
    CONSTRAINT fk_tar_audience FOREIGN KEY (target_audience_id) REFERENCES target_audience (target_audience_id),
    CONSTRAINT fk_tar_region FOREIGN KEY (location_region_id) REFERENCES location_region (location_region_id)
);

CREATE TABLE target_audience_interest (
    target_audience_id   NUMBER NOT NULL,
    interest_tag_id      NUMBER NOT NULL,
    CONSTRAINT pk_tai PRIMARY KEY (target_audience_id, interest_tag_id),
    CONSTRAINT fk_tai_audience FOREIGN KEY (target_audience_id) REFERENCES target_audience (target_audience_id),
    CONSTRAINT fk_tai_interest FOREIGN KEY (interest_tag_id) REFERENCES interest_tag (interest_tag_id)
);

-- ---------------------------------------------------------------------------
-- BIAS METRICS & AUDIT
-- ---------------------------------------------------------------------------
CREATE TABLE bias_metric_type (
    bias_metric_type_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    metric_name           VARCHAR2(80) NOT NULL,
    CONSTRAINT uq_bias_metric_name UNIQUE (metric_name)
);

CREATE TABLE bias_score (
    ad_id                 NUMBER NOT NULL,
    bias_metric_type_id   NUMBER NOT NULL,
    score_value           NUMBER(5, 4) NOT NULL,
    measured_at           TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT pk_bias_score PRIMARY KEY (ad_id, bias_metric_type_id),
    CONSTRAINT fk_bs_ad FOREIGN KEY (ad_id) REFERENCES cb_ad (ad_id),
    CONSTRAINT fk_bs_metric FOREIGN KEY (bias_metric_type_id) REFERENCES bias_metric_type (bias_metric_type_id),
    CONSTRAINT chk_bias_score_01 CHECK (score_value >= 0 AND score_value <= 1)
);

CREATE TABLE auditor_user (
    auditor_user_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username          VARCHAR2(80) NOT NULL,
    role_name         VARCHAR2(60) NOT NULL,
    CONSTRAINT uq_auditor_username UNIQUE (username)
);

CREATE TABLE audit_log (
    audit_log_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ad_id            NUMBER NOT NULL,
    audit_date       TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    auditor_id       NUMBER NOT NULL,
    CONSTRAINT fk_al_ad FOREIGN KEY (ad_id) REFERENCES cb_ad (ad_id),
    CONSTRAINT fk_al_auditor FOREIGN KEY (auditor_id) REFERENCES auditor_user (auditor_user_id)
);

-- ---------------------------------------------------------------------------
-- BENCHMARKING (B+ tree vs PGM experiments)
-- ---------------------------------------------------------------------------
CREATE TABLE index_type (
    index_type_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type_name       VARCHAR2(40) NOT NULL,
    CONSTRAINT uq_index_type_name UNIQUE (type_name)
);

CREATE TABLE query_template (
    query_template_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sql_template        CLOB NOT NULL,
    query_label         VARCHAR2(20)
);

CREATE TABLE benchmark_result (
    benchmark_result_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    query_template_id     NUMBER NOT NULL,
    index_type_id         NUMBER NOT NULL,
    latency_ms            NUMBER(14, 3) NOT NULL,
    memory_mb             NUMBER(14, 3) NOT NULL,
    run_at                TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_br_query FOREIGN KEY (query_template_id) REFERENCES query_template (query_template_id),
    CONSTRAINT fk_br_index FOREIGN KEY (index_type_id) REFERENCES index_type (index_type_id),
    CONSTRAINT chk_latency_nonneg CHECK (latency_ms >= 0),
    CONSTRAINT chk_memory_nonneg CHECK (memory_mb >= 0)
);

-- ---------------------------------------------------------------------------
-- USERS / SESSIONS / REPORTS
-- ---------------------------------------------------------------------------
CREATE TABLE user_session (
    user_session_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id           NUMBER NOT NULL,
    login_time        TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_us_user FOREIGN KEY (user_id) REFERENCES auditor_user (auditor_user_id)
);

CREATE TABLE audit_report (
    audit_report_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id             NUMBER NOT NULL,
    generation_date     TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT fk_ar_user FOREIGN KEY (user_id) REFERENCES auditor_user (auditor_user_id)
);

-- ---------------------------------------------------------------------------
-- Helpful indexes for audit queries (physical design; not BCNF tables)
-- ---------------------------------------------------------------------------
CREATE INDEX ix_cb_ad_creative ON cb_ad (ad_creative_id);
CREATE INDEX ix_cb_ad_platform ON cb_ad (platform_id);
CREATE INDEX ix_bias_score_metric ON bias_score (bias_metric_type_id);
CREATE INDEX ix_ad_category_industry ON ad_category_map (industry_category_id);

-- ---------------------------------------------------------------------------
-- Seed rows required by loader / default query binds (adjust IDs if needed)
-- ---------------------------------------------------------------------------
INSERT INTO bias_metric_type (metric_name) VALUES ('Composite Skew');
INSERT INTO index_type (type_name) VALUES ('B_TREE');
INSERT INTO index_type (type_name) VALUES ('PGM');

COMMIT;
