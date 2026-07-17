CREATE TABLE IF NOT EXISTS core.regions (
    region_id INTEGER PRIMARY KEY,
    region_code TEXT NOT NULL UNIQUE,
    region_name TEXT NOT NULL,
    geom_wkt TEXT
);

CREATE TABLE IF NOT EXISTS analytics.region_daily_sst (
    date DATE NOT NULL,
    region_id INTEGER NOT NULL REFERENCES core.regions(region_id),
    region_code TEXT NOT NULL,
    region_name TEXT NOT NULL,
    mean_sst_c NUMERIC(6,2),
    cell_count INTEGER,
    min_sst_c NUMERIC(6,2),
    max_sst_c NUMERIC(6,2),
    PRIMARY KEY (date, region_id)
);

CREATE TABLE IF NOT EXISTS analytics.region_climatology (
    region_id INTEGER NOT NULL REFERENCES core.regions(region_id),
    region_code TEXT NOT NULL,
    region_name TEXT NOT NULL,
    day_of_year INTEGER NOT NULL,
    clim_mean_sst_c NUMERIC(6,2),
    clim_p90_sst_c NUMERIC(6,2),
    sample_size INTEGER,
    PRIMARY KEY (region_id, day_of_year)
);

CREATE TABLE IF NOT EXISTS analytics.region_daily_anomalies (
    date DATE NOT NULL,
    region_id INTEGER NOT NULL REFERENCES core.regions(region_id),
    region_code TEXT NOT NULL,
    region_name TEXT NOT NULL,
    day_of_year INTEGER NOT NULL,
    mean_sst_c NUMERIC(6,2),
    cell_count INTEGER,
    min_sst_c NUMERIC(6,2),
    max_sst_c NUMERIC(6,2),
    clim_mean_sst_c NUMERIC(6,2),
    clim_p90_sst_c NUMERIC(6,2),
    sample_size INTEGER,
    anomaly_c NUMERIC(6,2),
    rolling_7d_anomaly_c NUMERIC(6,2),
    rolling_30d_anomaly_c NUMERIC(6,2),
    warming_rate_7d_c NUMERIC(6,2),
    above_p90 BOOLEAN,
    status_label TEXT,
    PRIMARY KEY (date, region_id)
);

CREATE TABLE IF NOT EXISTS analytics.heat_events (
    event_id UUID PRIMARY KEY,
    region_id INTEGER NOT NULL REFERENCES core.regions(region_id),
    region_code TEXT NOT NULL,
    region_name TEXT NOT NULL,
    event_type TEXT,
    severity_class TEXT,
    start_date DATE,
    end_date DATE,
    duration_days INTEGER,
    max_anomaly_c NUMERIC(6,2),
    mean_anomaly_c NUMERIC(6,2),
    max_exceedance_p90_c DOUBLE PRECISION,
    mean_exceedance_p90_c DOUBLE PRECISION,
    peak_date DATE,
    is_active BOOLEAN,
    threshold_c NUMERIC(6,2),
    min_duration_days INTEGER
);


CREATE TABLE IF NOT EXISTS analytics.region_daily_sst_prelim (
    date DATE NOT NULL,
    region_id INTEGER NOT NULL REFERENCES core.regions(region_id),
    region_code TEXT NOT NULL,
    region_name TEXT NOT NULL,
    mean_sst_c NUMERIC(6,2),
    cell_count INTEGER,
    min_sst_c NUMERIC(6,2),
    max_sst_c NUMERIC(6,2),
    data_product TEXT DEFAULT 'preliminary',
    is_provisional BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (date, region_id)
);

CREATE TABLE IF NOT EXISTS analytics.region_daily_anomalies_prelim (
    date DATE NOT NULL,
    region_id INTEGER NOT NULL REFERENCES core.regions(region_id),
    region_code TEXT NOT NULL,
    region_name TEXT NOT NULL,
    day_of_year INTEGER NOT NULL,
    mean_sst_c NUMERIC(6,2),
    cell_count INTEGER,
    min_sst_c NUMERIC(6,2),
    max_sst_c NUMERIC(6,2),
    clim_mean_sst_c NUMERIC(6,2),
    clim_p90_sst_c NUMERIC(6,2),
    sample_size INTEGER,
    anomaly_c NUMERIC(6,2),
    rolling_7d_anomaly_c NUMERIC(6,2),
    rolling_30d_anomaly_c NUMERIC(6,2),
    warming_rate_7d_c NUMERIC(6,2),
    above_p90 BOOLEAN,
    status_label TEXT,
    data_product TEXT DEFAULT 'preliminary',
    is_provisional BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (date, region_id)
);

CREATE TABLE IF NOT EXISTS analytics.heat_events_prelim (
    event_id UUID PRIMARY KEY,
    region_id INTEGER NOT NULL REFERENCES core.regions(region_id),
    region_code TEXT NOT NULL,
    region_name TEXT NOT NULL,
    event_type TEXT,
    severity_class TEXT,
    start_date DATE,
    end_date DATE,
    duration_days INTEGER,
    max_anomaly_c NUMERIC(6,2),
    mean_anomaly_c NUMERIC(6,2),
    max_exceedance_p90_c DOUBLE PRECISION,
    mean_exceedance_p90_c DOUBLE PRECISION,
    peak_date DATE,
    is_active BOOLEAN,
    threshold_c NUMERIC(6,2),
    min_duration_days INTEGER,
    data_product TEXT DEFAULT 'preliminary',
    is_provisional BOOLEAN DEFAULT TRUE
);


CREATE TABLE IF NOT EXISTS analytics.region_daily_anomalies_monitoring (
    date DATE NOT NULL,
    region_id INTEGER NOT NULL REFERENCES core.regions(region_id),
    region_code TEXT NOT NULL,
    region_name TEXT NOT NULL,
    day_of_year INTEGER NOT NULL,
    mean_sst_c NUMERIC(6,2),
    cell_count INTEGER,
    min_sst_c NUMERIC(6,2),
    max_sst_c NUMERIC(6,2),
    clim_mean_sst_c NUMERIC(6,2),
    clim_p90_sst_c NUMERIC(6,2),
    sample_size INTEGER,
    anomaly_c NUMERIC(6,2),
    rolling_7d_anomaly_c NUMERIC(6,2),
    rolling_30d_anomaly_c NUMERIC(6,2),
    warming_rate_7d_c NUMERIC(6,2),
    above_p90 BOOLEAN,
    status_label TEXT,
    data_product TEXT NOT NULL,
    is_provisional BOOLEAN NOT NULL,
    PRIMARY KEY (date, region_id)
);

CREATE TABLE IF NOT EXISTS meta.pipeline_runs (
    run_id UUID PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    duration_seconds DOUBLE PRECISION,
    message TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS meta.pipeline_log_events (
    log_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES meta.pipeline_runs(run_id) ON DELETE CASCADE,
    logged_at TIMESTAMPTZ NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    extra JSONB
);