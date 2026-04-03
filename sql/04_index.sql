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