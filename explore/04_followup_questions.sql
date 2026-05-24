-- ============================================================
-- 04_followup_questions.sql
-- Follow-up queries answering open questions from notes.md
-- ============================================================

-- ── Date range of sparkmeterreadings ─────────────────────────
-- MIN/MAX using index (index name: sitesAndTimestampsIndex)
SELECT MIN(heartbeatStart) AS first_real_reading
FROM sparkmeterreadings WHERE heartbeatStart > '2010-01-01';
-- Result: 2018-04-19

SELECT MAX(heartbeatStart) AS last_reading FROM sparkmeterreadings;
-- Result: 2025-12-16

-- Count of epoch-zero corrupted timestamps
SELECT COUNT(*) AS n_bad FROM sparkmeterreadings WHERE heartbeatStart < '2015-01-01';
-- Result: 183,330 rows (all exactly 1970-01-01 00:00:00)

-- ── meter_customer_code = customerAccountNumber ───────────────
-- Direct join confirms meter_customer_code matches customerAccountNumber exactly
SELECT r.meter_customer_code, c.customerAccountNumber
FROM sparkmeterreadings r
LEFT JOIN customers c ON r.meter_customer_code = c.customerAccountNumber
WHERE r.meter_customer_code IS NOT NULL AND r.heartbeatStart >= '2024-01-01'
LIMIT 5;
-- Result: join works; customers.customerId is NULL for most rows (not populated)

-- ── site UUID maps to meteringbasestations.meteringSiteId ─────
SELECT DISTINCT r.site, m.meteringBaseStation, m.projectName
FROM sparkmeterreadings r
JOIN meteringbasestations m ON m.meteringSiteId = r.site
WHERE r.heartbeatStart >= '2024-06-01' AND r.heartbeatStart < '2024-06-02'
ORDER BY m.projectName;
-- Result: confirmed join works; see notes.md for full site list

-- ── meters_coords in sparkmetercustomers ──────────────────────
SELECT meters_coords, meters_serial, ground_name
FROM sparkmetercustomers WHERE meters_coords IS NOT NULL AND meters_coords != '' LIMIT 5;
-- Result: "RED", "YELLOW", "Yellow" — wiring color codes, NOT GPS. Already excluded.

-- ── isReversed in paymentconfirmations ───────────────────────
SELECT isReversed, COUNT(*) AS n
FROM paymentconfirmations GROUP BY isReversed;
-- Result: NULL=~1.03M (field added retroactively), 0=316, 1=3
-- Only 3 payments were ever reversed — field is almost never populated

-- ── truePowerAvg vs truePowerInst ─────────────────────────────
SELECT heartbeatStart, truePowerAvg, truePowerInst, kilowattHours
FROM sparkmeterreadings
WHERE meter_type='customer' AND truePowerInst IS NOT NULL AND truePowerAvg IS NOT NULL
  AND heartbeatStart >= '2024-06-01'
LIMIT 10;
-- Result: usually equal; they differ when load changes mid-period
-- truePowerInst=0 with truePowerAvg>0 means meter cut off at end of heartbeat

-- ── rate field matches tariffs.totalRate ──────────────────────
-- Akipelai Residential tariff history from tariffs table:
SELECT startingDatetime, totalRate FROM tariffs
WHERE meteringBaseStation = 'Akipelai' AND name = 'Residential' AND totalRate > 0
ORDER BY startingDatetime;
-- Results: 224.68 NGN/kWh (2023-05), 258.00 (2023-09), 356.79 (2023-12),
--          346.38 (2024-12), 430.00 (2024-12)
-- The rate in sparkmeterreadings should match tariffs.totalRate for the
-- applicable period. (JOIN: sparkmeterreadings.site → meteringbasestations.meteringSiteId
--                         → meteringbasestations.meteringBaseStation → tariffs)

-- ── state codes in sparkmeterreadings ────────────────────────
-- Sample from 1 day to get distinct values (full table scan too slow)
SELECT state FROM sparkmeterreadings
WHERE heartbeatStart >= '2025-01-01' AND heartbeatStart < '2025-01-02'
  AND meter_type = 'customer'
LIMIT 200;
-- Results observed: 0, 1, 9, 13
-- State 1 (~74%) = normal active operation
-- State 0 (~14%) = off/unpowered
-- State 13 (~11%) = likely low credit or about to disconnect
-- State 9 (~1%) = tamper detected
-- Full code definitions: https://get.support.sparkmeter.io/servicedesk/customer/portal/4/article/3240263726
