-- ============================================================
-- 01_schema_and_sizes.sql
-- Initial schema exploration: table sizes, row counts, column list
-- ============================================================

-- Table sizes and estimated row counts
SELECT
  table_name,
  table_rows,
  ROUND(data_length/1024/1024/1024, 3)             AS data_gb,
  ROUND(index_length/1024/1024/1024, 3)            AS index_gb,
  ROUND((data_length+index_length)/1024/1024/1024, 3) AS total_gb
FROM information_schema.tables
WHERE table_schema = 'renewviadb'
ORDER BY (data_length+index_length) DESC;

-- Full column list for all tables
SELECT table_name, column_name, column_type, is_nullable, column_key
FROM information_schema.columns
WHERE table_schema = 'renewviadb'
ORDER BY table_name, ordinal_position;
