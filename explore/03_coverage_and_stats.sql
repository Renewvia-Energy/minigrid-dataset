-- ============================================================
-- 03_coverage_and_stats.sql
-- Coverage statistics: date ranges, site counts, geographic span
-- ============================================================

-- ── sparkmeterreadings date range and breadth ─────────────────
SELECT
  MIN(heartbeatStart) AS first_reading,
  MAX(heartbeatStart) AS last_reading,
  COUNT(DISTINCT site)         AS n_sites,
  COUNT(DISTINCT meter_serial) AS n_meters
FROM sparkmeterreadings;

-- Readings per site with date span
SELECT site, meter_type, COUNT(*) AS n_readings
FROM sparkmeterreadings
GROUP BY site, meter_type
ORDER BY site, n_readings DESC;

-- ── vrmgeneration (Victron VRM) ───────────────────────────────
SELECT Project_Name, COUNT(*) AS n_rows,
  MIN(timestamp_local) AS first_ts, MAX(timestamp_local) AS last_ts
FROM vrmgeneration
GROUP BY Project_Name ORDER BY first_ts;

-- ── minigridprojects ─────────────────────────────────────────
SELECT projectName, country, company, lat, `long`, sizePv, sizeBattery,
  powerOnDate, powerSoldDate, generationType
FROM minigridprojects ORDER BY country, projectName;

-- ── meteringbasestations ─────────────────────────────────────
SELECT meteringBaseStation, projectName, meteringPlatform, meteringSiteStatus, timezoneOffsetUtc
FROM meteringbasestations ORDER BY projectName;

-- ── sparkmetertransactions ───────────────────────────────────
SELECT site, COUNT(*) AS n, MIN(created) AS first_tx, MAX(created) AS last_tx,
  SUM(amount) AS total_amount
FROM sparkmetertransactions
GROUP BY site ORDER BY n DESC;

-- ── exchangerates date coverage ───────────────────────────────
SELECT country, MIN(date) AS first_date, MAX(date) AS last_date, COUNT(*) AS n_rows
FROM exchangerates GROUP BY country;

-- ── smsSurveys ────────────────────────────────────────────────
SELECT surveyId, COUNT(*) AS n, SUM(optInResponse) AS opt_in, SUM(optOutResponse) AS opt_out
FROM smsSurveys GROUP BY surveyId;

-- ── uniSparkMeterReadings and synota row counts ───────────────
SELECT COUNT(*) AS n_uniReadings FROM uniSparkMeterReadings;
SELECT COUNT(*) AS n_synota FROM synota;
