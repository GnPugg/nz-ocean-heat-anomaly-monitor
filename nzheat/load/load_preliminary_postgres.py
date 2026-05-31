from __future__ import annotations

from pathlib import Path
import argparse

import pandas as pd
from sqlalchemy.engine import Engine

from nzheat.load.load_postgres import (
    create_db_engine,
    get_database_url,
    load_dataframe_to_table,
    truncate_table,
)


def find_project_root() -> Path:
    """Find the project root from this file location."""
    current = Path(__file__).resolve()

    for parent in current.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent

    raise RuntimeError("Could not find project root. Expected pyproject.toml or .git.")


PROJECT_ROOT = find_project_root()
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

DEFAULT_PRELIM_SST_FILE = PROCESSED_DIR / "region_daily_sst_recent_prelim.parquet"
DEFAULT_PRELIM_ANOMALIES_FILE = (
    PROCESSED_DIR / "region_daily_anomalies_recent_prelim.parquet"
)
DEFAULT_PRELIM_EVENTS_FILE = PROCESSED_DIR / "heat_events_recent_prelim.parquet"


EXPECTED_COLUMNS = {
    "region_daily_sst_prelim": [
        "date",
        "region_id",
        "region_code",
        "region_name",
        "mean_sst_c",
        "cell_count",
        "min_sst_c",
        "max_sst_c",
    ],
    "region_daily_anomalies_prelim": [
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
    "heat_events_prelim": [
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
    "region_daily_sst_prelim": ["date", "region_id"],
    "region_daily_anomalies_prelim": ["date", "region_id"],
    "heat_events_prelim": ["event_id"],
}


def load_parquet(path: Path) -> pd.DataFrame:
    """Load a parquet file, failing clearly if it does not exist."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    return pd.read_parquet(path)


def select_expected_columns(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the expected columns for the target preliminary table."""
    expected_cols = EXPECTED_COLUMNS[table_name]
    missing_cols = [col for col in expected_cols if col not in df.columns]

    if missing_cols:
        raise ValueError(f"{table_name} is missing required columns: {missing_cols}")

    extra_cols = [col for col in df.columns if col not in expected_cols]

    if extra_cols:
        print(f"{table_name}: dropping unexpected columns: {extra_cols}")

    return df[expected_cols].copy()


def normalize_dataframe_types(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize common date, integer, and boolean columns before loading."""
    result = df.copy()

    for col in ["date", "start_date", "end_date", "peak_date"]:
        if col in result.columns:
            result[col] = pd.to_datetime(result[col]).dt.date

    for col in [
        "region_id",
        "day_of_year",
        "sample_size",
        "cell_count",
        "duration_days",
        "min_duration_days",
    ]:
        if col in result.columns:
            result[col] = result[col].astype(int)

    for col in ["above_p90", "is_active"]:
        if col in result.columns:
            result[col] = result[col].astype(bool)

    return result


def validate_primary_keys(table_name: str, df: pd.DataFrame) -> None:
    """Fail before loading if duplicate primary-key rows are present."""
    key_cols = PRIMARY_KEY_COLUMNS[table_name]

    duplicate_count = int(df.duplicated(key_cols).sum())

    if duplicate_count > 0:
        duplicate_preview = df.loc[df.duplicated(key_cols, keep=False), key_cols].head(
            20
        )

        raise ValueError(
            f"{table_name} has {duplicate_count} duplicate primary-key rows "
            f"based on {key_cols}.\nPreview:\n{duplicate_preview}"
        )


def prepare_table_for_load(table_name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Select expected columns, normalize dtypes, and validate keys."""
    prepared_df = select_expected_columns(table_name, df)
    prepared_df = normalize_dataframe_types(prepared_df)
    validate_primary_keys(table_name, prepared_df)

    return prepared_df


def load_preliminary_outputs(
    engine: Engine,
    prelim_sst_path: Path,
    prelim_anomalies_path: Path,
    prelim_events_path: Path,
    *,
    truncate_first: bool = True,
) -> None:
    """Load preliminary monitoring outputs into PostgreSQL."""
    tables = [
        (
            "region_daily_sst_prelim",
            prelim_sst_path,
        ),
        (
            "region_daily_anomalies_prelim",
            prelim_anomalies_path,
        ),
        (
            "heat_events_prelim",
            prelim_events_path,
        ),
    ]

    for table_name, path in tables:
        print(f"Loading analytics.{table_name} from {path}")

        df = load_parquet(path)
        df = prepare_table_for_load(table_name, df)

        if truncate_first:
            truncate_table(engine, "analytics", table_name)

        load_dataframe_to_table(
            engine,
            df,
            schema_name="analytics",
            table_name=table_name,
        )

        print(f"Loaded {len(df):,} rows into analytics.{table_name}")

    print("Preliminary outputs loaded successfully.")


def main(
    database_url: str,
    prelim_sst_path: Path,
    prelim_anomalies_path: Path,
    prelim_events_path: Path,
    truncate_first: bool,
) -> None:
    engine = create_db_engine(database_url)

    load_preliminary_outputs(
        engine=engine,
        prelim_sst_path=prelim_sst_path,
        prelim_anomalies_path=prelim_anomalies_path,
        prelim_events_path=prelim_events_path,
        truncate_first=truncate_first,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load preliminary NZ heat-monitor parquet outputs into PostgreSQL.",
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy PostgreSQL database URL. If omitted, DATABASE_URL or .env settings are used.",
    )
    parser.add_argument(
        "--prelim-sst-file",
        default=str(DEFAULT_PRELIM_SST_FILE),
        help="Path to the preliminary regional daily SST parquet.",
    )
    parser.add_argument(
        "--prelim-anomalies-file",
        default=str(DEFAULT_PRELIM_ANOMALIES_FILE),
        help="Path to the preliminary regional daily anomalies parquet.",
    )
    parser.add_argument(
        "--prelim-events-file",
        default=str(DEFAULT_PRELIM_EVENTS_FILE),
        help="Path to the preliminary heat events parquet.",
    )
    parser.add_argument(
        "--no-truncate",
        action="store_true",
        help="Append instead of truncating target preliminary tables first.",
    )

    args = parser.parse_args()

    database_url = get_database_url(args.database_url)

    main(
        database_url=database_url,
        prelim_sst_path=Path(args.prelim_sst_file),
        prelim_anomalies_path=Path(args.prelim_anomalies_file),
        prelim_events_path=Path(args.prelim_events_file),
        truncate_first=not args.no_truncate,
    )
