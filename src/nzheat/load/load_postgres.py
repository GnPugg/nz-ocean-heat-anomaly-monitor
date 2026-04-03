from __future__ import annotations

from pathlib import Path
import argparse
import os

from dotenv import load_dotenv

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_REGIONS_FILE = Path("assets/regions/nz_coastal_regions.geojson")
DEFAULT_REGION_DAILY_SST_FILE = Path("data/processed/region_daily_sst_history.parquet")
DEFAULT_CLIMATOLOGY_FILE = Path("data/processed/region_climatology.parquet")
DEFAULT_ANOMALIES_FILE = Path("data/processed/region_daily_anomalies.parquet")
DEFAULT_EVENTS_FILE = Path("data/processed/heat_events.parquet")

# Load environment variables from the project root .env file if present.
load_dotenv()


def get_database_url(cli_database_url: str | None = None) -> str:
    """Resolve the database URL from CLI input or environment variables."""
    if cli_database_url:
        return cli_database_url

    env_database_url = os.getenv("DATABASE_URL")
    if env_database_url:
        return env_database_url

    raise ValueError(
        "No database URL provided. Use --database-url or set DATABASE_URL in your environment."
    )


def create_db_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine for PostgreSQL."""
    return create_engine(database_url, future=True)


def load_regions_geojson(regions_path: Path) -> pd.DataFrame:
    """
    Load region attributes from the GeoJSON file.

    For the first loader version, we store only the core attributes and skip geometry loading.
    Geometry can be added later with GeoPandas/PostGIS-specific handling.
    """
    import geopandas as gpd

    gdf = gpd.read_file(regions_path)

    keep_cols = [
        col for col in ["region_id", "region_code", "region_name"] if col in gdf.columns
    ]
    if not keep_cols:
        raise ValueError(
            "The regions file must contain region_id, region_code, and region_name columns."
        )

    df = gdf[keep_cols].copy()
    df["region_id"] = df["region_id"].astype(int)
    return df


def load_parquet_table(parquet_path: Path) -> pd.DataFrame:
    """Load a parquet file into a pandas DataFrame."""
    return pd.read_parquet(parquet_path)


def normalize_dataframe_types(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize dataframe dtypes before loading to PostgreSQL.

    This helps avoid common issues with pandas/object types and date handling.
    """
    result = df.copy()

    if "date" in result.columns:
        result["date"] = pd.to_datetime(result["date"]).dt.date
    if "start_date" in result.columns:
        result["start_date"] = pd.to_datetime(result["start_date"]).dt.date
    if "end_date" in result.columns:
        result["end_date"] = pd.to_datetime(result["end_date"]).dt.date
    if "peak_date" in result.columns:
        result["peak_date"] = pd.to_datetime(result["peak_date"]).dt.date

    if "region_id" in result.columns:
        result["region_id"] = result["region_id"].astype(int)
    if "day_of_year" in result.columns:
        result["day_of_year"] = result["day_of_year"].astype(int)
    if "sample_size" in result.columns:
        result["sample_size"] = result["sample_size"].astype(int)
    if "cell_count" in result.columns:
        result["cell_count"] = result["cell_count"].astype(int)
    if "duration_days" in result.columns:
        result["duration_days"] = result["duration_days"].astype(int)
    if "min_duration_days" in result.columns:
        result["min_duration_days"] = result["min_duration_days"].astype(int)

    return result


def truncate_table(engine: Engine, schema_name: str, table_name: str) -> None:
    """Truncate a target table before reloading it."""
    statement = text(f"TRUNCATE TABLE {schema_name}.{table_name} CASCADE;")
    with engine.begin() as connection:
        connection.execute(statement)


def load_dataframe_to_table(
    engine: Engine,
    df: pd.DataFrame,
    *,
    schema_name: str,
    table_name: str,
    if_exists: str = "append",
) -> None:
    """Load a dataframe into a PostgreSQL table using pandas.to_sql."""
    df.to_sql(
        name=table_name,
        con=engine,
        schema=schema_name,
        if_exists=if_exists,
        index=False,
        method="multi",
        chunksize=1000,
    )


def load_all_outputs(
    engine: Engine,
    regions_path: Path,
    region_daily_sst_path: Path,
    climatology_path: Path,
    anomalies_path: Path,
    events_path: Path,
    *,
    truncate_first: bool = True,
) -> None:
    """Load all processed project outputs into PostgreSQL."""
    print("Loading core.regions...")
    regions_df = normalize_dataframe_types(
        "regions", load_regions_geojson(regions_path)
    )
    if truncate_first:
        truncate_table(engine, "core", "regions")
    load_dataframe_to_table(
        engine, regions_df, schema_name="core", table_name="regions"
    )
    print(f"Loaded {len(regions_df):,} rows into core.regions")

    print("Loading analytics.region_daily_sst...")
    region_daily_sst_df = normalize_dataframe_types(
        "region_daily_sst",
        load_parquet_table(region_daily_sst_path),
    )
    if truncate_first:
        truncate_table(engine, "analytics", "region_daily_sst")
    load_dataframe_to_table(
        engine,
        region_daily_sst_df,
        schema_name="analytics",
        table_name="region_daily_sst",
    )
    print(f"Loaded {len(region_daily_sst_df):,} rows into analytics.region_daily_sst")

    print("Loading analytics.region_climatology...")
    climatology_df = normalize_dataframe_types(
        "region_climatology",
        load_parquet_table(climatology_path),
    )
    if truncate_first:
        truncate_table(engine, "analytics", "region_climatology")
    load_dataframe_to_table(
        engine,
        climatology_df,
        schema_name="analytics",
        table_name="region_climatology",
    )
    print(f"Loaded {len(climatology_df):,} rows into analytics.region_climatology")

    print("Loading analytics.region_daily_anomalies...")
    anomalies_df = normalize_dataframe_types(
        "region_daily_anomalies",
        load_parquet_table(anomalies_path),
    )
    if truncate_first:
        truncate_table(engine, "analytics", "region_daily_anomalies")
    load_dataframe_to_table(
        engine,
        anomalies_df,
        schema_name="analytics",
        table_name="region_daily_anomalies",
    )
    print(f"Loaded {len(anomalies_df):,} rows into analytics.region_daily_anomalies")

    print("Loading analytics.heat_events...")
    events_df = normalize_dataframe_types(
        "heat_events",
        load_parquet_table(events_path),
    )
    if truncate_first:
        truncate_table(engine, "analytics", "heat_events")
    load_dataframe_to_table(
        engine,
        events_df,
        schema_name="analytics",
        table_name="heat_events",
    )
    print(f"Loaded {len(events_df):,} rows into analytics.heat_events")

    print("All processed outputs loaded successfully.")


def main(
    database_url: str,
    regions_path: Path,
    region_daily_sst_path: Path,
    climatology_path: Path,
    anomalies_path: Path,
    events_path: Path,
    truncate_first: bool,
) -> None:
    engine = create_db_engine(database_url)

    load_all_outputs(
        engine=engine,
        regions_path=regions_path,
        region_daily_sst_path=region_daily_sst_path,
        climatology_path=climatology_path,
        anomalies_path=anomalies_path,
        events_path=events_path,
        truncate_first=truncate_first,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load processed NZ heat-monitor parquet outputs into PostgreSQL.",
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy PostgreSQL database URL. If omitted, DATABASE_URL env var is used.",
    )
    parser.add_argument(
        "--regions-file",
        default=str(DEFAULT_REGIONS_FILE),
        help="Path to the NZ coastal regions GeoJSON.",
    )
    parser.add_argument(
        "--region-daily-sst-file",
        default=str(DEFAULT_REGION_DAILY_SST_FILE),
        help="Path to the regional daily SST parquet.",
    )
    parser.add_argument(
        "--climatology-file",
        default=str(DEFAULT_CLIMATOLOGY_FILE),
        help="Path to the regional climatology parquet.",
    )
    parser.add_argument(
        "--anomalies-file",
        default=str(DEFAULT_ANOMALIES_FILE),
        help="Path to the regional daily anomalies parquet.",
    )
    parser.add_argument(
        "--events-file",
        default=str(DEFAULT_EVENTS_FILE),
        help="Path to the heat events parquet.",
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="Append instead of truncating target tables first.",
    )
    args = parser.parse_args()

    database_url = get_database_url(args.database_url)

    main(
        database_url=database_url,
        regions_path=Path(args.regions_file),
        region_daily_sst_path=Path(args.region_daily_sst_file),
        climatology_path=Path(args.climatology_file),
        anomalies_path=Path(args.anomalies_file),
        events_path=Path(args.events_file),
        truncate_first=not args.no_truncate,
    )
