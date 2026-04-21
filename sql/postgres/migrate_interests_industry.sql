-- Links interests (ad categories) to industries (broad sector buckets).
-- Run on DBs created before interests.industry_id existed.
-- Matches etl/category_industry.py and sql/postgres/normalize_ad_impressions_to_bcnf.sql CASE labels.

BEGIN;

INSERT INTO industries (name) VALUES
  ('Real Estate & Housing'),
  ('Financial Services'),
  ('Health & Wellness'),
  ('Retail & Shopping'),
  ('Automotive'),
  ('Media & News'),
  ('General & Other')
ON CONFLICT (name) DO NOTHING;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'interests'
      AND column_name = 'industry_id'
  ) THEN
    ALTER TABLE interests
      ADD COLUMN industry_id INT REFERENCES industries (industry_id);
  END IF;
END $$;

UPDATE interests i
SET industry_id = (
  SELECT ind.industry_id
  FROM industries ind
  WHERE ind.name = (
    CASE UPPER(TRIM(i.interest_name))
      WHEN 'HOUSING' THEN 'Real Estate & Housing'
      WHEN 'FINANCE' THEN 'Financial Services'
      WHEN 'HEALTH' THEN 'Health & Wellness'
      WHEN 'RETAIL' THEN 'Retail & Shopping'
      WHEN 'AUTO' THEN 'Automotive'
      WHEN 'NEWS' THEN 'Media & News'
      ELSE 'General & Other'
    END
  )
  LIMIT 1
)
WHERE i.industry_id IS NULL;

UPDATE interests i
SET industry_id = (SELECT industry_id FROM industries WHERE name = 'General & Other' LIMIT 1)
WHERE i.industry_id IS NULL;

ALTER TABLE interests
  ALTER COLUMN industry_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_interests_industry_id ON interests (industry_id);

COMMIT;
