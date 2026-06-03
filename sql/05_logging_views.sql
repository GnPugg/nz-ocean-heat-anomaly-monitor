CREATE SCHEMA IF NOT EXISTS meta;

CREATE OR REPLACE VIEW meta.v_pipeline_step_metrics AS
SELECT
    r.run_id,
    r.pipeline_name,
    r.status AS run_status,
    r.started_at,
    r.finished_at,
    r.duration_seconds,

    e.logged_at,
    e.level,
    e.message,

    e.extra ->> 'step_name' AS step_name,
    e.extra ->> 'target_table' AS target_table,
    e.extra ->> 'output_file' AS output_file,
    e.extra ->> 'load_mode' AS load_mode,

    NULLIF(e.extra ->> 'rows_created', '')::bigint AS rows_created,
    NULLIF(e.extra ->> 'rows_loaded', '')::bigint AS rows_loaded,
    NULLIF(e.extra ->> 'row_count', '')::bigint AS row_count,
    NULLIF(e.extra ->> 'column_count', '')::bigint AS column_count,
    NULLIF(e.extra ->> 'region_count', '')::bigint AS region_count,

    NULLIF(e.extra ->> 'date_min', '')::date AS date_min,
    NULLIF(e.extra ->> 'date_max', '')::date AS date_max,

    e.extra -> 'status_label_counts' AS status_label_counts,
    e.extra -> 'data_product_counts' AS data_product_counts,
    e.extra -> 'is_provisional_counts' AS is_provisional_counts,

    e.extra AS raw_extra
FROM meta.pipeline_runs r
JOIN meta.pipeline_log_events e
    ON r.run_id = e.run_id
WHERE e.extra IS NOT NULL
  AND (
      e.level = 'ERROR'
      OR e.extra ? 'rows_created'
      OR e.extra ? 'rows_loaded'
      OR e.extra ? 'row_count'
      OR e.extra ? 'target_table'
      OR e.extra ? 'output_file'
  );