# NZ Coastal Ocean Heat Anomaly Monitor

An end-to-end environmental data engineering project for monitoring sea surface temperature (SST) anomalies around New Zealand coastal regions using NOAA OISST data.

The project downloads daily SST data, aggregates it into six New Zealand coastal regions, calculates a fixed 1991–2020 climatology baseline, detects sustained warm events, stores final and preliminary monitoring outputs in PostgreSQL, and visualises the results in Power BI.

The purpose of this project is to demonstrate the data pipeline, modelling workflow, and dashboard communication layer rather than to provide an authoritative climate forecast.

---

## What this project demonstrates

- Incremental ingestion of daily NOAA OISST data
- Geospatial aggregation with xarray and GeoPandas
- Fixed-baseline anomaly and heat-event calculations
- PostgreSQL analytical and monitoring data models
- Dockerised execution and automated testing
- Scheduled final and preliminary data updates
- Power BI reporting

## Architecture

NOAA OISST 
    │
    ▼
Python extraction 
    │
    ▼
Regional transformation 
    │
    ├── Parquet processing layer
    │
    ▼
PostgreSQL 
    │
    ▼
Power BI

Tests ──► Pipeline
Logs  ◄── Pipeline
Scheduler ──► Daily update

## Contents
- [Review Quick Start](#Review-Quick-Start)
- [Project Overview](#project-overview)
- [Data Source](#data-source)
- [Architecture](#architecture)
- [Power BI Dashboard](#power-bi-dashboard)
- [Analytical Logic](#analytical-logic)
- [Technical Reference](#technical-reference)
---

<details>
<summary><strong>Dashboard preview</strong></summary>

![NZ Coastal Ocean Heat overview](docs/images/nz_overview.png)

![NZ coastal heat footprint](docs/images/nz_coastal_heat.png)

![10-year SST projection](docs/images/nz_10_yr_projection.png)
</details>

---
## Review Quick Start

This project can be run either locally or with Docker Compose. The Docker workflow includes:

* a PostgreSQL database container
* automatic schema and table creation from the `sql/` folder
* a Python application container for tests, ETL, analytics, validation, and database loading
* local access to the Docker PostgreSQL database from pgAdmin or Power BI

### 1. Create the environment file

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

The default Docker database settings are:

```env
POSTGRES_DB=nzheat
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_PORT_HOST=5433

DB_HOST=localhost
DB_PORT=5433
DB_NAME=nzheat
DB_USER=postgres
DB_PASSWORD=postgres
```

Local tools such as pgAdmin, Power BI, and local Python connect to the Docker PostgreSQL database through:

```text
localhost:5433
```

The Python app container connects to the database internally through:

```text
postgres:5432
```

### 2. Build the Docker image

```powershell
docker compose build
```

### 3. Start PostgreSQL

```powershell
docker compose up -d postgres
```

Check that the database is running:

```powershell
docker compose ps
```

Expected port mapping:

```text
localhost:5433 -> postgres container:5432
```

### 4. Run the test suite inside Docker

```powershell
docker compose run --rm app python -m pytest -q
```

Expected result:

```text
36 passed
```

### 5. Run validation or pipeline commands inside Docker

```powershell
docker compose run --rm app python scripts/maintenance/validate_outputs.py
```

Example final refresh command:

```powershell
docker compose run --rm app python scripts/maintenance/run_final_refresh.py
```

Example database load command:

```powershell
docker compose run --rm app python -m nzheat.load.load_postgres
```

### 6. Connect Power BI to the Docker database

Power BI can connect directly to the PostgreSQL database running in Docker.

Use:

```text
Server: localhost:5433
Database: nzheat
Username: postgres
Password: postgres
```

Use Import mode for the dashboard.

### Notes

Large raw and processed data files are not committed to the repository. The Docker app mounts the local `data/` folder at runtime, so full pipeline execution requires the expected local data files to be present or rebuilt from the source data workflow.

PostgreSQL schema files in `sql/` are executed automatically only when the Docker database volume is first created. To rebuild the database from scratch:

```powershell
docker compose down -v
docker compose up -d postgres
```

---
## Project Overview

This project is designed as a small production-style monitoring system. It aims to answer practical questions such as:

- Which New Zealand coastal regions are warmer than normal?
- How large is the SST anomaly relative to the long-term baseline?
- Which regions are above their historical 90th percentile threshold?
- Are any regions experiencing active heat events?
- How do recent conditions compare with validated final OISST records?
- How could recent regional SST trends be represented as an exploratory 10-year scenario?

The project maintains both validated final OISST outputs and recent preliminary OISST outputs.

- Final OISST data supports the validated historical record, long-term anomaly calculations, and stable trend reporting.
- Preliminary OISST data supports the most recent monitoring layer, including latest-status indicators and possible active heat events.

In the Power BI dashboard, these outputs are brought together into a monitoring view so users can see stable historical context alongside the most recent provisional conditions.

---


## Data Source

The project uses NOAA Optimum Interpolation Sea Surface Temperature v2.1 (OISST).

Two OISST data streams are used:

### Final OISST

Final OISST is used for the validated historical record.

It supports:

- long-term regional SST history
- validated regional SST history from 2021 onward
- the fixed 1991–2020 climatology baseline
- stable anomaly calculations
- final warm-event detection
- historical dashboard trends

Final OISST is treated as the authoritative source for validated historical analysis, but it is delayed relative to near-real-time conditions.

### Preliminary OISST

Preliminary OISST is used for the recent monitoring layer.

It supports:

- latest regional SST conditions
- recent anomaly monitoring
- possible active heat-event indicators
- latest-status dashboard cards and tables

Preliminary OISST is more recent than final OISST, but it is provisional and may change when final data become available.

Together, the final and preliminary outputs allow the dashboard to show both validated historical context and recent provisional monitoring conditions.

---

## Coastal Regions

The MVP monitors six broad New Zealand coastal regions:

| Code | Region |
|---|---|
| NNI | North North Island |
| WNI | West North Island |
| ENI | East North Island |
| NSI | North South Island |
| WSI | West South Island |
| ESI | East South Island |

The region polygons are stored in:

```text
assets/regions/nz_coastal_regions.geojson
```

NOAA OISST has a 0.25° spatial resolution, so this project focuses on regional coastal monitoring rather than farm-scale or site-scale conditions.

---

## Architecture scientific workflow


```text
NOAA OISST final data
        ↓
Python extraction and regional aggregation
        ↓
┌──────────────────────────────────────┐
│ 1991–2020 climatology baseline       │
│ Validated monitoring record          │
│ from 2021 onward                     │
└──────────────────────────────────────┘
        ↓
Anomaly calculation against fixed 1991–2020 baseline
        ↓
Final heat-event detection
        ↓
PostgreSQL final analytics tables
```

```text
NOAA OISST preliminary data
        ↓
Recent provisional regional aggregation
        ↓
Anomaly calculation against fixed 1991–2020 baseline
        ↓
Preliminary heat-event detection
        ↓
PostgreSQL preliminary monitoring tables
```

```text
PostgreSQL analytics tables
        ↓
Power BI monitoring dashboard
        ↓
Overview trends, active-event table, 10-year projection, and NZ coastal heat map
```

The final OISST workflow has two roles: it builds the fixed 1991–2020 climatology baseline and provides the validated post-baseline monitoring record from 2021 onward. The years after 2020 are not part of the baseline; they are observed years compared against the baseline. Preliminary OISST extends the dashboard with the most recent provisional monitoring conditions.



## What the Pipeline Does

The pipeline:

- downloads NOAA OISST final and preliminary data
- subsets data to New Zealand coastal waters
- assigns OISST grid cells to six coastal regions
- aggregates SST by region and date
- builds a 1991–2020 day-of-year climatology
- uses final OISST from 2021 onward as the validated post-baseline monitoring record
- calculates SST anomalies against the fixed 1991–2020 baseline
- calculates rolling anomaly metrics
- flags days above the climatological 90th percentile
- detects sustained warm events
- loads final and preliminary outputs to PostgreSQL
- supports Power BI dashboard reporting, including overview trends, recent active-event monitoring, 10-year projection, and the NZ coastal heat map

---
## Technical Reference

<details>
<summary><strong>Project Structure</strong></summary>

```text
nz-ocean-heat-anomaly-monitor/
│
├── assets/
│   └── regions/
│       ├── nz_coastal_regions.geojson
│       ├── nz_coastal_regions_coastal_powerbi.json
│       └── nz_coastal_regions.qmd
│
├── data/
│   ├── raw/
│   │   ├── oisst/
│   │   ├── oisst_baseline/
│   │   └── oisst_prelim/
│   │
│   └── processed/
│       ├── region_daily_sst_history.parquet
│       ├── region_daily_sst_baseline_1991_2020.parquet
│       ├── region_climatology.parquet
│       ├── region_daily_anomalies.parquet
│       ├── heat_events.parquet
│       ├── region_daily_sst_recent_prelim.parquet
│       ├── region_daily_anomalies_recent_prelim.parquet
│       ├── heat_events_recent_prelim.parquet
│       └── r/
│           └── region_sst_projection_10yr_gls_ar1.csv
├── docs/
│   ├── images/
│   │   ├── nz_overview.png
│   │   ├── nz_coastal_heat.png
│   │   └── nz_10_yr_projection.png
│   └── powerbi_measures.md
│
├── r/
│   ├── fit_gls_projection_10yr.R
│   └── plot_gls_projection_10yr.R
│
├── scripts/ 
│   ├── setup/ 
│   │   ├── build_1991_2020_climatology.py 
│   │   ├── build_gap_2021_2024_history.py 
│   │   └── build_monthly_sst_history.py 
│   │    
│   ├── monitoring/
│   │   ├── build_and_load_monitoring_anomalies.py 
│   │   ├── run_daily_append.py
│   │   ├── run_daily_pipeline.py
│   │   └── run_preliminary_update.py 
│   │   
│   └── maintenance/ 
│       ├── run_final_refresh.py 
│       └── validate_outputs.py
│
├── sql/
│   ├── 01_extensions.sql
│   ├── 02_schema.sql
│   ├── 03_tables.sql
│   ├── 04_index.sql
│   └── 05_logging_views.sql
│
├── tests/
│   ├── test_anomalies.py
│   ├── test_events.py
│   ├── test_extract_oisst.py
│   ├── test_paths.py
│   ├── test_projection_10yr.py
│   └── test_region_aggregation.py
│
├── nzheat/
│   ├── extract/
│   ├── transform/
│   ├── analytics/
│   ├── pipeline/
│   └── load/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── daily_update.bat
├── requirements.txt
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```
</details>


---
<details>
<summary><strong>Tech Stack</strong></summary>

### Data manipulation and analysis

- Python 3.11
- pandas
- geopandas
- xarray
- netCDF4
- requests
- pyarrow
- SQLAlchemy
- psycopg2

### Database

- PostgreSQL
- PostgreSQL schemas for `core`, `analytics`, `mart` and `meta`
- SQL-based schema, table, index, and logging-view creation

### Reproducibility and deployment workflow

- Docker
- Docker Compose
- Containerised PostgreSQL
- Containerised Python application environment

### Testing and validation
- pytest
- Python output validation scripts
- PostgreSQL pipeline logging tables/views

### Dashboard

- Power BI

### Automation

- Windows Task Scheduler
- Batch script for daily local refresh
- Docker Compose workflow for reproducible local execution
---
</details>

---

<details>
<summary><strong>Environment and Database Setup</strong></summary>

Create and activate the Conda environment:

```powershell
conda create -n nzheat python=3.11
conda activate nzheat
```

Install dependencies:

```powershell
pip install -r requirements.txt
```
---

## Database Setup

Run the SQL scripts in this order:

```text
sql/01_extensions.sql
sql/02_schema.sql
sql/03_tables.sql
sql/04_index.sql
sql/05_logging_views.sql
```

The main schemas are:

```text
core
analytics
mart
meta
```

### Core table

```text
core.regions
```

### Final OISST analytics tables

```text
analytics.region_daily_sst
analytics.region_climatology
analytics.region_daily_anomalies
analytics.heat_events
```

### Preliminary OISST analytics tables

```text
analytics.region_daily_sst_prelim
analytics.region_daily_anomalies_prelim
analytics.heat_events_prelim
```

---
</details>

---
<details>
<summary><strong>Data Model</strong></summary>

### `core.regions`

Reference table for the six coastal regions.

Main fields:

```text
region_id
region_code
region_name
geom_wkt
```

### `analytics.region_daily_sst`

Daily final OISST regional SST values.

Main fields:

```text
date
region_id
region_code
region_name
mean_sst_c
cell_count
min_sst_c
max_sst_c
```

### `analytics.region_climatology`

Day-of-year climatology based on the 1991–2020 baseline.

Main fields:

```text
region_id
day_of_year
clim_mean_sst_c
clim_p90_sst_c
sample_size
```

### `analytics.region_daily_anomalies`

Final OISST anomaly table.

Main fields:

```text
date
region_id
day_of_year
mean_sst_c
clim_mean_sst_c
clim_p90_sst_c
anomaly_c
rolling_7d_anomaly_c
rolling_30d_anomaly_c
warming_rate_7d_c
above_p90
status_label
```

### `analytics.heat_events`

Detected final-data heat events.

Main fields:

```text
event_id
region_id
event_type
severity_class
start_date
end_date
duration_days
max_anomaly_c
mean_anomaly_c
peak_date
is_active
threshold_c
min_duration_days
```

### Preliminary tables

The preliminary tables mirror the final tables but include:

```text
data_product = preliminary
is_provisional = true
```

These tables are used for recent dashboard indicators and possible active events.

---

## Climatology Baseline

The climatology baseline is built from final OISST data for:

```text
1991-01-01 to 2020-12-31
```
The years after 2020 are not included in the climatology baseline. Instead, final OISST records from 2021 onward are used as the post-baseline monitoring period. These observed SST values are compared against the fixed 1991–2020 climatology to calculate anomalies, above-p90 flags, rolling metrics, and detected warm events.



The climatology is calculated for each:

```text
region × day_of_year
```

Expected climatology output:

```text
365 days × 6 regions = 2,190 rows
```

With a full 1991–2020 baseline, the expected sample size is approximately:

```text
30 observations per region/day-of-year
```

### Leap-year handling

The climatology uses a no-leap 365-day calendar:

- February 29 is removed.
- Dates after February 29 in leap years are shifted back by one day.

This avoids misalignment between leap and non-leap years.

---
---
</details>

---

<details>
<summary><strong>Main Pipeline Commands</strong></summary>

### 1. Build the 1991–2020 climatology

```powershell
python scripts\setup\build_1991_2020_climatology.py
```

This creates:

```text
data/processed/region_daily_sst_baseline_1991_2020.parquet
data/processed/region_climatology.parquet
```

This is a long-running step because it processes approximately 30 years of daily OISST files but runs only once.

---
### 2. Build the 2021–2024 post-baseline gap history

```powershell
python scripts\setup\build_gap_2021_2024_history.py
```

This creates the validated post-baseline SST history for the gap years:

```text
data/processed/region_daily_sst_gap_2021_2024.parquet
```

These years are not part of the climatology baseline. They are observed final-OISST years compared against the fixed 1991–2020 baseline.

---

### 3. Recalculate final anomalies and events

```powershell
python scripts\maintenance\run_final_refresh.py
```
After building or updating the climatology, run:

```powershell
python -m nzheat.analytics.anomalies
python -m nzheat.analytics.events
python -m nzheat.load.load_postgres
```

This updates:

```text
data/processed/region_daily_anomalies.parquet
data/processed/heat_events.parquet
```

and loads the final outputs to PostgreSQL.

---

### 4. Run the daily final-OISST append

```powershell
python scripts\monitoring\run_daily_append.py
```

The daily append script:

- checks the latest existing final OISST date in the history file
- calculates the latest safe final OISST date using a lag
- appends only missing dates
- recalculates anomalies
- recalculates events
- reloads final tables to PostgreSQL

The final SST history is stored in:

```text
data/processed/region_daily_sst_history.parquet
```

---

### 5. Run the preliminary OISST update

```powershell
python scripts\monitoring\run_preliminary_update.py
python -m nzheat.load.load_preliminary_postgres
```

This creates and loads:

```text
data/processed/region_daily_sst_recent_prelim.parquet
data/processed/region_daily_anomalies_recent_prelim.parquet
data/processed/heat_events_recent_prelim.parquet
```

into the PostgreSQL preliminary monitoring tables:

```text
analytics.region_daily_sst_prelim 
analytics.region_daily_anomalies_prelim 
analytics.heat_events_prelim
```
These outputs support recent monitoring indicators and possible active heat events.
---

### 6. Build the combined monitoring anomaly table

```powershell
python scripts\monitoring\build_and_load_monitoring_anomalies.py
```

This combines final and preliminary anomaly outputs into a single monitoring table:

```text
data/processed/region_daily_anomalies_monitoring.parquet 
analytics.region_daily_anomalies_monitoring
```
This table is used by the Power BI monitoring pages, including the latest anomaly cards and the NZ coastal heat map.

---

### 7. Build and load the 10-year projection table

This project includes two parallel 10-year SST projection workflows:

- a main Python workflow used by PostgreSQL and Power BI
- a parallel R workflow used for exploratory modelling and comparison

The main production workflow is the Python workflow.

#### Main workflow: Python projection loaded to PostgreSQL

First, build the full regional SST history table:
```powershell
python -m nzheat.analytics.build_full_sst_history
```

This creates:

```powershell
data/processed/region_daily_sst_full_history.parquet
```

This file contains the regional daily SST history needed to estimate recent warming trends.

Next, build the 10-year regional SST projection table:

```powershell
python -m nzheat.analytics.projection_10yr
```
This creates:
```powershell
data/processed/region_sst_projection_10yr.parquet
```
Then load the projection output into PostgreSQL:
```powershell
python -m nzheat.load.load_projection_10yr_to_postgres
```
This loads the data into:
```powershell
analytics.region_monthly_sst_projection_10yr
```
Power BI reads this PostgreSQL table for the 10-year projection page.

Run the full main projection pipeline with:
```powershell
python -m nzheat.analytics.build_full_sst_history
python -m nzheat.analytics.projection_10yr
python -m nzheat.load.load_projection_10yr_to_postgres
```

#### Parallel workflow: R projection model

An alternative R-based projection workflow is also included for exploratory modelling and validation.

The R workflow uses a GLS model with AR(1) autocorrelated residuals. This model estimates a long-term SST trend while controlling for monthly seasonality and accounting for correlation between neighbouring months.

Run: 

```powershell
Rscript r\fit_gls_projection_10yr.R
```
This creates:
```powershell
data/processed/r/region_sst_projection_10yr.csv
```
To create exploratory plots from the GLS AR(1) projection output, run:

```powershell
Rscript r\plot_gls_projection_10yr.R
```
This creates:

```powershell
docs/images/r_projection_gls_ar1_selected_region.png
docs/images/r_projection_gls_ar1_all_regions.png
```
The R output is kept as a parallel exploratory modelling workflow.   
It is useful for reviewing the projected SST trend and checking a more statistically defensible time-series model, but it is not loaded into PostgreSQL by default.
The main Power BI dashboard continues to use the Python-generated parquet projection loaded into PostgreSQL.




---
### 8. Validate outputs

```powershell
python scripts\maintenance\validate_outputs.py
```

Useful checks include:

```text
Duplicate date-region rows
Missing complete dates
Missing region-date combinations
Rows with missing anomaly
Rows with missing p90 flag
Latest available date
Active events
Climatology sample size
```

Expected final climatology check after the 1991–2020 baseline:

```text
Rows: 2190
Day-of-year range: 1 to 365
Min sample size: approximately 30
Max sample size: approximately 30
Rows with missing climatology values: 0
```

### 9. Maintenance backfill if missing dates

The normal daily pipeline only processes newly available final OISST dates and recent preliminary data. It does not automatically go backwards to repair older gaps.

Use the backfill command only when a past final SST date is missing, corrupted, or needs to be regenerated.
Backfill is a maintenance/repair command. It is not required for the normal daily update.

#### When to use backfill

Use backfill if validation reports missing final SST dates, for example:

Missing complete dates:
2026-05-05
2026-05-06

In this case, run:
```powershell
python -m nzheat.pipeline.backfill --start-date 2026-05-05 --end-date 2026-05-06
```
#### After running backfill
After a successful backfill, rebuild the downstream outputs:
```powershell
python -m nzheat.analytics.anomalies 
python -m nzheat.analytics.events 
python -m nzheat.load.load_postgres 
python scripts\monitoring\build_and_load_monitoring_anomalies.py 
python scripts\maintenance\validate_outputs.py
```
</details>

---


<details>
<summary><strong>Testing</strong></summary>

The project includes pytest coverage for the core analytics pipeline, including:

- regional SST aggregation
- anomaly calculation
- marine heat-event detection
- 10-year projection output structure
- OISST extraction filename/date logic
- project path utilities

Run the test suite with:

```powershell
python -m pytest -q
```
or a single test for example:

```powershell
python -m pytest tests\test_events.py -q
```
or to check if everything complies:

```powershell
python -m compileall nzheat scripts
```

</details>

---

<details>
<summary><strong>Daily Automation</strong></summary>

The project uses Windows Task Scheduler for local daily automation.

The scheduled task runs:

```text
daily_update.bat
```

The file:

- opens the project directory
- activates the nzheat Conda environment
- scripts/monitoring/run_daily_append.py
- scripts/monitoring/run_preliminary_update.py
- runs python -m nzheat.load.load_preliminary_postgres
- rebuilds/loads the combined monitoring anomaly table if required
- writes logs to logs/daily_update.log

The daily automation combines two update layers:

1. scripts/monitoring/run_daily_append.py checks whether new validated final OISST dates are available....
2. python -m nzheat.load.load_preliminary_postgres` loads the most recent preliminary SST, anomaly, and heat-event outputs into PostgreSQL..

The preliminary load is required so that recent monitoring indicators and possible active heat events remain populated in Power BI.

A successful Task Scheduler run should show:

Last Run Result: 0x0

The log can be checked with:

Get-Content logs\daily_update.log -Tail 40

A successful log should include lines similar to:

Running run_daily_append.py
Running load_preliminary_postgres.py
Loaded rows into analytics.heat_events_prelim
Daily update finished

</details>

---


## Power BI Dashboard


Power BI connects directly to the PostgreSQL database.

The dashboard includes three main pages:

1. **Monitoring Overview**

   Shows recent SST anomalies, 7-day anomaly trends, latest monitoring status, and possible active heat events based on preliminary OISST outputs.

2. **10-Year Projection**

   Shows recent SST history together with a simple 10-year regional warming projection. This page is designed as an exploratory scenario rather than a formal forecast.

3. **NZ Coastal Heat Footprint**

   Shows a custom New Zealand coastal region map coloured by latest 30-day SST anomaly. This page highlights which coastal regions are currently warmest relative to their 1991–2020 climatology.

The dashboard separates absolute SST from SST anomaly so that naturally warmer northern regions are not confused with regions experiencing stronger relative warming.


---

## Analytical Logic

### Fixed climatology baseline

The project uses a fixed 1991–2020 climatology baseline. This baseline represents the expected seasonal SST cycle for each coastal region and day of year.

The years after 2020 are not included in the baseline. Instead, final OISST records from 2021 onward are treated as the validated post-baseline monitoring period and are compared against the fixed baseline.

### SST anomaly

Daily SST anomaly is calculated as:

```text
anomaly_c = observed mean SST - climatological mean SST
```

where the climatological mean is calculated from the 1991–2020 baseline for the same region and day of year.

### 90th percentile threshold

Each region/day-of-year also has a climatological 90th percentile threshold:

```text
clim_p90_sst_c
```

A day is flagged as above p90 when:

```text
mean_sst_c > clim_p90_sst_c
```
This identifies days where SST is unusually warm for that region and time of year

### Rolling metrics

The anomaly table includes:

```text
rolling_7d_anomaly_c
rolling_30d_anomaly_c
warming_rate_7d_c
```

The 7-day anomaly supports short-term monitoring, while the 30-day anomaly is used to summarise persistent regional heat patterns, including the NZ coastal heat map.

### Heat events

Heat events are detected from sustained warm conditions, based on consecutive days above the climatological 90th percentile.

The event table includes:

```text
start_date
end_date
duration_days
peak_date
max_anomaly_c
mean_anomaly_c
severity_class
is_active
```

The final heat-event table reflects validated final OISST data. The preliminary heat-event table reflects recent provisional OISST data and is used for possible active-event monitoring in the dashboard.

### Monitoring dashboard logic

The dashboard combines final and preliminary outputs:

- final OISST provides the validated historical context and stable post-baseline monitoring record
- preliminary OISST provides the most recent provisional monitoring layer
- anomaly values are always interpreted relative to the fixed 1991–2020 baseline

The NZ coastal heat map uses the latest 30-day SST anomaly by region. This avoids confusing absolute temperature with relative warming: a naturally warmer northern region is not automatically treated as the strongest heat signal unless it is also warmer than expected relative to its own climatology.

### 10-year projection logic

The 10-year projection page is an exploratory scenario based on recent regional SST behaviour. It is not presented as a formal climate forecast.

The projection is intended to help users interpret how recent warming patterns could extend over the next decade, while keeping the observed SST history and projected values visually distinct.

---





