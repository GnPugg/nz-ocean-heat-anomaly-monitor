-- Power BI 10-year regional SST projection table.
--
-- The table is populated separately by:
-- python -m nzheat.load.load_projection_10yr_to_postgres

CREATE TABLE IF NOT EXISTS analytics.region_monthly_sst_projection_10yr (
    region_id integer,
    month_date date,
    year integer,
    month integer,
    observed_or_projected text,
    scenario text,
    model_id text,
    mean_sst_c double precision,
    median_sst_c double precision,
    p10_sst_c double precision,
    p90_sst_c double precision,
    monthly_climatology_sst_c real,
    trend_c_per_year double precision,
    trend_c_per_decade double precision,
    warming_from_last_observed_c double precision,
    region_code text,
    region_name text
);
