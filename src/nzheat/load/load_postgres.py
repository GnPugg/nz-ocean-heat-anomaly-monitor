from __future__ import annotations

from pathlib import Path
import argparse
import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DEFAULT_REGIONS_FILE = Path("assets/regions/nz_coastal_regions.geojson")
DEFAULT_REGION_DAILY_SST_FILE = Path("data/processed/region_daily_sst_history.parquet")
DEFAULT_CLIMATOLOGY_FILE = Path("data/processed/region_climatology.parquet")
DEFAULT_ANOMALIES_FILE = Path("data/processed/region_daily_anomalies.parquet")
DEFAULT_EVENTS_FILE = Path("data/processed/heat_events.parquet")


EXPECTED_COLUMNS = {
    "regions": [
        "region_id",
        "region_code",
        "region_name",
    ],
    "region_daily_sst": [
        "date",
        "region_id",
        "region_code",
        "region_name",
        "mean_sst_c",
        "cell_count",
        "min_sst_c",
        "max_sst_c",
    ],
    "region_climatology": [
        "region_id",
        "region_code",
        "region_name",
        "day_of_year",
        "clim_mean_sst_c",
        "clim_p90_sst_c",
        "sample_size",
    ],
    "region_daily_anomalies": [
        "date",
        "region_id",
        "region_code",
        "region_name",
        "day_of_year",
        "mean_sst_c",
        "cell_count",
        "min_sst_c",
        "max_sst_c",
        "clim_mean_sst_c",
        "clim_p90_sst_c",
        "sample_size",
        "anomaly_c",
        "rolling_7d_anomaly_c",
        "rolling_30d_anomaly_c",
        "warming_rate_7d_c",
        "above_p90",
        "status_label",
    ],
    "heat_events": [
        "event_id",
        "region_id",
        "region_code",
        "region_name",
        "event_type",
        "severity_class",
        "start_date",
        "end_date",
        "duration_days",
        "max_anomaly_c",
        "mean_anomaly_c",
        "max_exceedance_p90_c",
        "mean_exceedance_p90_c",
        "peak_date",
        "is_active",
        "threshold_c",
        "min_duration_days",
    ],
}


PRIMARY_KEY_COLUMNS = {
    "regions": ["region_id"],
    "region_daily_sst": ["date", "region_id"],
    "region_climatology": ["region_id", "day_of_year"],
    "region_daily_anomalies": ["date", "region_id"],
    "heat_events": ["event_id"],
}


# Load environment variables from the project root .env file if present.
load_dotenv()


def get_database_url(cli_database_url: str | None = None) -> str:
    """
    Resolve the database URL from CLI input or environment variables.

    Supports either:

    DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/dbname

    or separate variables:

    DB_HOST / POSTGRES_HOST
    DB_PORT / POSTGRES_PORT
    DB_NAME / POSTGRES_DB
    DB_USER / POSTGRES_USER
    DB_PASSWORD / POSTGRES_PASSWORD
    """
    if cli_database_url:
        return cli_database_url

    env_database_url = os.getenv("DATABASE_URL")
    if env_database_url:
        return env_database_url

    host = os.getenv("DB_HOST") or os.getenv("POSTGRES_HOST") or "localhost"
    port = os.getenv("DB_PORT") or os.getenv("POSTGRES_PORT") or "5432"
    db_name = os.getenv("DB_NAME") or os.getenv("POSTGRES_DB")
    user = os.getenv("DB_USER") or os.getenv("POSTGRES_USER")
    password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")

    missing = []
    if not db_name:
        missing.append("DB_NAME or POSTGRES_DB")
    if not user:
        missing.append("DB_USER or POSTGRES_USER")
    if not password:
        missing.append("DB_PASSWORD or POSTGRES_PASSWORD")

    if missing:
        raise ValueError(
            "Missing database settings in .env: "
            + ", ".join(missing)
            + ". Alternatively set DATABASE_URL."
        )

    password_safe = quote_plus(password)

    return f"postgresql+psycopg2://{user}:{password_safe}@{host}:{port}/{db_name}"


def create_db_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine for PostgreSQL."""
    return create_engine(database_url, future=True)


def load_regions_geojson(regions_path: Path) -> pd.DataFrame:
    """
    Load region attributes from the GeoJSON file.

    The Postgres core.regions table also allows geom_wkt, but this loader keeps
    only the core region attributes used by the analytics tables.
    """
    import geopandas as gpd

    gdf = gpd.read_file(regions_path)

    required_cols = ["region_id", "region_code", "region_name"]
    missing_cols = [col for col in required_cols if col not in gdf.columns]

    if missing_cols:
        raise ValueError(
            f"The regions file is missing required columns: {missing_cols}"
        )

    df = gdf[required_cols].copy()
    df["region_id"] = df["region_id"].astype(int)

    return df


def load_parquet_table(parquet_path: Path) -> pd.DataFrame:
    """Load a parquet file into a pandas DataFrame."""
    if not parquet_path.exists():
        raise FileNotFoundError(f"Missing parquet file: {parquet_path}")

    return pd.read_parquet(parquet_path)


def select_expected_columns(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only the columns expected by the target PostgreSQL table.

    This prevents extra columns in parquet files from breaking the database load.
    """
    if table_name not in EXPECTED_COLUMNS:
        raise ValueError(f"No expected-column definition for table: {table_name}")

    expected_cols = EXPECTED_COLUMNS[table_name]
    missing_cols = [col for col in expected_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(f"{table_name} is missing required columns: {missing_cols}")

    extra_cols = [col for col in df.columns if col not in expected_cols]

    if extra_cols:
        print(f"{table_name}: dropping unexpected columns: {extra_cols}")

    return df[expected_cols].copy()


def normalize_dataframe_types(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize dataframe dtypes before loading to PostgreSQL.

    This helps avoid common issues with pandas/object types and date handling.
    """
    result = df.copy()

    if "date" in result.columns:
        result["date"] = pd.to_datetime(result["date"]).dt.date
    if "month_date" in result.columns:
        result["month_date"] = pd.to_datetime(result["month_date"]).dt.date
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

    if "above_p90" in result.columns:
        result["above_p90"] = result["above_p90"].astype(bool)
    if "is_active" in result.columns:
        result["is_active"] = result["is_active"].astype(bool)

    return result


def validate_primary_keys(table_name: str, df: pd.DataFrame) -> None:
    """Fail early if a dataframe would violate the target table primary key."""
    key_cols = PRIMARY_KEY_COLUMNS.get(table_name)

    if not key_cols:
        return

    missing_key_cols = [col for col in key_cols if col not in df.columns]

    if missing_key_cols:
        raise ValueError(
            f"{table_name} is missing primary-key columns: {missing_key_cols}"
        )

    duplicate_count = df.duplicated(key_cols).sum()

    if duplicate_count > 0:
        duplicate_preview = df.loc[df.duplicated(key_cols, keep=False), key_cols].head(
            20
        )

        raise ValueError(
            f"{table_name} has {duplicate_count} duplicate primary-key rows "
            f"based on {key_cols}.\nPreview:\n{duplicate_preview}"
        )


def prepare_table_for_load(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Select expected columns, normalize dtypes, and validate primary keys.
    """
    prepared_df = select_expected_columns(table_name, df)
    prepared_df = normalize_dataframe_types(table_name, prepared_df)
    validate_primary_keys(table_name, prepared_df)

    return prepared_df


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
    regions_df = prepare_table_for_load(
        "regions",
        load_regions_geojson(regions_path),
    )
    if truncate_first:
        truncate_table(engine, "core", "regions")
    load_dataframe_to_table(
        engine,
        regions_df,
        schema_name="core",
        table_name="regions",
    )
    print(f"Loaded {len(regions_df):,} rows into core.regions")

    print("Loading analytics.region_daily_sst...")
    region_daily_sst_df = prepare_table_for_load(
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
    climatology_df = prepare_table_for_load(
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
    anomalies_df = prepare_table_for_load(
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
    events_df = prepare_table_for_load(
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
