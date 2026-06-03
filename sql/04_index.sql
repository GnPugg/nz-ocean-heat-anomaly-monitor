CREATE INDEX IF NOT EXISTS idx_region_daily_sst_region_id
ON analytics.region_daily_sst (region_id);

CREATE INDEX IF NOT EXISTS idx_region_daily_sst_date
ON analytics.region_daily_sst (date);

CREATE INDEX IF NOT EXISTS idx_region_climatology_region_id
ON analytics.region_climatology (region_id);

CREATE INDEX IF NOT EXISTS idx_region_daily_anomalies_region_id
ON analytics.region_daily_anomalies (region_id);

CREATE INDEX IF NOT EXISTS idx_region_daily_anomalies_date
ON analytics.region_daily_anomalies (date);

CREATE INDEX IF NOT EXISTS idx_heat_events_region_id
ON analytics.heat_events (region_id);

CREATE INDEX IF NOT EXISTS idx_heat_events_start_date
ON analytics.heat_events (start_date);

CREATE INDEX IF NOT EXISTS idx_region_daily_sst_prelim_date
ON analytics.region_daily_sst_prelim(date);

CREATE INDEX IF NOT EXISTS idx_region_daily_anomalies_prelim_date
ON analytics.region_daily_anomalies_prelim(date);

CREATE INDEX IF NOT EXISTS idx_region_daily_anomalies_prelim_region_date
ON analytics.region_daily_anomalies_prelim(region_id, date);

CREATE INDEX IF NOT EXISTS idx_heat_events_prelim_active
ON analytics.heat_events_prelim(is_active);

CREATE INDEX IF NOT EXISTS idx_heat_events_prelim_dates
ON analytics.heat_events_prelim(start_date, end_date);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_pipeline_name
ON meta.pipeline_runs (pipeline_name);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at
ON meta.pipeline_runs (started_at);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
ON meta.pipeline_runs (status);

CREATE INDEX IF NOT EXISTS idx_pipeline_log_events_run_id
ON meta.pipeline_log_events (run_id);

CREATE INDEX IF NOT EXISTS idx_pipeline_log_events_logged_at
ON meta.pipeline_log_events (logged_at);