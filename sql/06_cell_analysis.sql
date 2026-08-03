CREATE TABLE IF NOT EXISTS core.coastal_cells (
    cell_id TEXT PRIMARY KEY,
    longitude DOUBLE PRECISION NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    cell_size_degrees DOUBLE PRECISION NOT NULL DEFAULT 0.25,
    grid_version TEXT NOT NULL DEFAULT 'v2_masked_75km',
    geom_wkt TEXT NOT NULL,

    CHECK (longitude BETWEEN -180.0 AND 180.0),
    CHECK (latitude BETWEEN -90.0 AND 90.0),
    CHECK (cell_size_degrees > 0.0)
);


CREATE TABLE IF NOT EXISTS analytics.cell_historical_features (
    cell_id TEXT PRIMARY KEY
        REFERENCES core.coastal_cells(cell_id),

    observation_count BIGINT NOT NULL,

    mean_sst_c DOUBLE PRECISION NOT NULL,
    raw_sst_sd_c DOUBLE PRECISION NOT NULL,
    minimum_sst_c DOUBLE PRECISION NOT NULL,
    maximum_sst_c DOUBLE PRECISION NOT NULL,

    mean_jan_sst_c DOUBLE PRECISION NOT NULL,
    mean_feb_sst_c DOUBLE PRECISION NOT NULL,
    mean_mar_sst_c DOUBLE PRECISION NOT NULL,
    mean_apr_sst_c DOUBLE PRECISION NOT NULL,
    mean_may_sst_c DOUBLE PRECISION NOT NULL,
    mean_jun_sst_c DOUBLE PRECISION NOT NULL,
    mean_jul_sst_c DOUBLE PRECISION NOT NULL,
    mean_aug_sst_c DOUBLE PRECISION NOT NULL,
    mean_sep_sst_c DOUBLE PRECISION NOT NULL,
    mean_oct_sst_c DOUBLE PRECISION NOT NULL,
    mean_nov_sst_c DOUBLE PRECISION NOT NULL,
    mean_dec_sst_c DOUBLE PRECISION NOT NULL,

    summer_mean_sst_c DOUBLE PRECISION NOT NULL,
    winter_mean_sst_c DOUBLE PRECISION NOT NULL,
    seasonal_amplitude_c DOUBLE PRECISION NOT NULL,

    warmest_month TEXT NOT NULL,
    coldest_month TEXT NOT NULL,

    seasonal_shape_jan_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_feb_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_mar_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_apr_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_may_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_jun_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_jul_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_aug_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_sep_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_oct_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_nov_c DOUBLE PRECISION NOT NULL,
    seasonal_shape_dec_c DOUBLE PRECISION NOT NULL,

    deseasonalized_daily_sd_sst_c DOUBLE PRECISION NOT NULL,
    annual_mean_sd_sst_c DOUBLE PRECISION NOT NULL,

    CHECK (
        warmest_month IN (
            'jan', 'feb', 'mar', 'apr', 'may', 'jun',
            'jul', 'aug', 'sep', 'oct', 'nov', 'dec'
        )
    ),

    CHECK (
        coldest_month IN (
            'jan', 'feb', 'mar', 'apr', 'may', 'jun',
            'jul', 'aug', 'sep', 'oct', 'nov', 'dec'
        )
    )
);


CREATE TABLE IF NOT EXISTS analytics.cell_warming_trends (
    cell_id TEXT PRIMARY KEY
        REFERENCES core.coastal_cells(cell_id),

    baseline_start_year INTEGER NOT NULL,
    baseline_end_year INTEGER NOT NULL,
    year_count INTEGER NOT NULL,
    observation_count BIGINT NOT NULL,

    trend_c_per_year DOUBLE PRECISION NOT NULL,
    trend_c_per_decade DOUBLE PRECISION NOT NULL,
    trend_standard_error_c_per_year DOUBLE PRECISION NOT NULL,
    trend_p_value DOUBLE PRECISION NOT NULL,
    trend_r_squared DOUBLE PRECISION NOT NULL,
    estimated_change_over_period_c DOUBLE PRECISION NOT NULL,

    CHECK (baseline_end_year >= baseline_start_year),
    CHECK (year_count > 1),
    CHECK (observation_count > 0),
    CHECK (trend_p_value BETWEEN 0.0 AND 1.0),
    CHECK (trend_r_squared BETWEEN 0.0 AND 1.0)
);


CREATE OR REPLACE VIEW mart.v_powerbi_cell_summary AS
SELECT
    cells.cell_id,
    cells.longitude,
    cells.latitude,
    cells.cell_size_degrees,
    cells.grid_version,
    cells.geom_wkt,

    trends.baseline_start_year,
    trends.baseline_end_year,
    trends.year_count,
    trends.observation_count AS trend_observation_count,

    features.observation_count AS historical_observation_count,
    features.mean_sst_c,
    features.minimum_sst_c,
    features.maximum_sst_c,
    features.summer_mean_sst_c,
    features.winter_mean_sst_c,
    features.seasonal_amplitude_c,
    features.warmest_month,
    features.coldest_month,
    features.raw_sst_sd_c,
    features.deseasonalized_daily_sd_sst_c,
    features.annual_mean_sd_sst_c,

    trends.trend_c_per_year,
    trends.trend_c_per_decade,
    trends.trend_standard_error_c_per_year,
    trends.trend_standard_error_c_per_year * 10.0
        AS trend_standard_error_c_per_decade,
    trends.trend_p_value,
    trends.trend_r_squared,
    trends.estimated_change_over_period_c

FROM core.coastal_cells AS cells

INNER JOIN analytics.cell_historical_features AS features
    ON cells.cell_id = features.cell_id

INNER JOIN analytics.cell_warming_trends AS trends
    ON cells.cell_id = trends.cell_id;
