-- Query 5 validation: counts for every (ad_category, gender) pair in ad_impressions.
-- Top row is the highest-volume pair for bias audits.

SELECT
  ad_category,
  gender,
  COUNT(*) AS row_count
FROM ad_impressions
GROUP BY ad_category, gender
ORDER BY row_count DESC;

-- Single top pair (headline for reports)
-- SELECT ad_category, gender, COUNT(*) AS row_count
-- FROM ad_impressions
-- GROUP BY ad_category, gender
-- ORDER BY row_count DESC
-- LIMIT 1;
