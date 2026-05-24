-- ============================================================
-- 02_data_quality.sql
-- Data quality checks across key tables
-- ============================================================

-- ── paymentconfirmations ──────────────────────────────────────
-- Year distribution (NULL and year=0 indicate bad timestamps)
SELECT YEAR(transactionDatetime) AS yr, COUNT(*) AS n
FROM paymentconfirmations
GROUP BY yr ORDER BY yr;

-- paymentProcessor inconsistent formatting
SELECT paymentProcessor, COUNT(*) AS n
FROM paymentconfirmations
GROUP BY paymentProcessor ORDER BY n DESC;

-- Sample of records with bad dates
SELECT paymentProcessor, transactionDatetime, currency, amount, country, projectName
FROM paymentconfirmations
WHERE transactionDatetime IS NULL OR YEAR(transactionDatetime) < 2017
LIMIT 20;

-- ── paymentvalidations ────────────────────────────────────────
SELECT YEAR(transactionDatetime) AS yr, paymentProcessor, COUNT(*) AS n
FROM paymentvalidations
GROUP BY yr, paymentProcessor ORDER BY yr;

-- ── sparkmeterreadings energy fields ─────────────────────────
-- kilowattHours vs kilowattHoursPeriod: avg and max difference
-- (large diff confirms kilowattHours is cumulative, kilowattHoursPeriod is the 15-min delta)
SELECT
  AVG(ABS(kilowattHours - kilowattHoursPeriod)) AS avg_diff,
  MAX(ABS(kilowattHours - kilowattHoursPeriod)) AS max_diff,
  SUM(CASE WHEN ABS(kilowattHours - kilowattHoursPeriod) > 0.001 THEN 1 ELSE 0 END) AS n_differ
FROM (
  SELECT kilowattHours, kilowattHoursPeriod
  FROM sparkmeterreadings
  WHERE heartbeatStart >= '2024-01-01'
  LIMIT 10000
) t;

-- Meter type distribution
SELECT meter_type, COUNT(*) AS n, COUNT(DISTINCT meter_serial) AS n_meters
FROM sparkmeterreadings
GROUP BY meter_type;

-- ── customers ────────────────────────────────────────────────
-- Demographic breakdown (customerType, status, gender)
SELECT customerType, customerStatus, gender, COUNT(*) AS n
FROM customers
GROUP BY customerType, customerStatus, gender
ORDER BY n DESC;

-- ── tariffs ──────────────────────────────────────────────────
-- Many zero-rate rows (placeholder/historical)
SELECT meteringBaseStation, name, startingDatetime, baseRate, totalRate
FROM tariffs ORDER BY meteringBaseStation, startingDatetime LIMIT 30;
