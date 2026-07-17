from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from nzheat.load.load_postgres import (
    create_db_engine,
    get_database_url,
    load_dataframe_to_table,
    normalize_dataframe_types,
)
from nzheat.utils.paths import find_project_root

PROJECT_ROOT = find_project_root()
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

FINAL_ANOMALIES_FILE = PROCESSED_DIR / "region_daily_anomalies.parquet"
PRELIM_ANOMALIES_FILE = PROCESSED_DIR / "region_daily_anomalies_recent_prelim.parquet"
OUTPUT_FILE = PROCESSED_DIR / "region_daily_anomalies_monitoring.parquet"

SCHEMA_NAME = "analytics"
TABLE_NAME = "region_daily_anomalies_monitoring"


def build_monitoring_dataframe(
    final_anomalies_file: Path = FINAL_ANOMALIES_FILE,
    prelim_anomalies_file: Path = PRELIM_ANOMALIES_FILE,
) -> pd.DataFrame:
    """Combine final and preliminary anomalies, preferring preliminary overlaps."""
    if not final_anomalies_file.exists():
        raise FileNotFoundError(
            f"Missing final anomalies file: {final_anomalies_file}"
        )

    if not prelim_anomalies_file.exists():
        raise FileNotFoundError(
            f"Missing preliminary anomalies file: {prelim_anomalies_file}"
        )

    final_df = pd.read_parquet(final_anomalies_file).copy()
    prelim_df = pd.read_parquet(prelim_anomalies_file).copy()

    final_df["date"] = pd.to_datetime(final_df["date"])
    prelim_df["date"] = pd.to_datetime(prelim_df["date"])

    final_df["data_product"] = "final"
    final_df["is_provisional"] = False
    prelim_df["data_product"] = "preliminary"
    prelim_df["is_provisional"] = True

    final_df["source_priority"] = 0
    prelim_df["source_priority"] = 1

    combined = pd.concat([final_df, prelim_df], ignore_index=True)
    combined = combined.sort_values(["region_id", "date", "source_priority"])
    combined = combined.drop_duplicates(
        subset=["region_id", "date"],
        keep="last",
    )

    return (
        combined.drop(columns=["source_priority"])
        .sort_values(["date", "region_id"])
        .reset_index(drop=True)
    )


def save_monitoring_output(
    combined: pd.DataFrame,
    output_file: Path = OUTPUT_FILE,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_file, index=False)

    print("\nSaved combined monitoring anomalies file:")
    print(output_file)
    print("\nDate range:")
    print(combined["date"].min(), "to", combined["date"].max())
    print("\nRows:")
    print(len(combined))
    print("\nRows by data product:")
    print(combined["data_product"].value_counts(dropna=False))
    print("\nRows by provisional flag:")
    print(combined["is_provisional"].value_counts(dropna=False))


def load_monitoring_output(
    output_file: Path = OUTPUT_FILE,
    database_url: str | None = None,
) -> None:
    if not output_file.exists():
        raise FileNotFoundError(f"Missing monitoring anomalies file: {output_file}")

    combined = pd.read_parquet(output_file)
    engine = create_db_engine(get_database_url(database_url))
    db_df = normalize_dataframe_types(TABLE_NAME, combined)

    load_dataframe_to_table(
        engine,
        db_df,
        schema_name=SCHEMA_NAME,
        table_name=TABLE_NAME,
        if_exists="replace",
    )

    print(f"\nLoaded {len(db_df):,} rows into {SCHEMA_NAME}.{TABLE_NAME}")


def main(
    *,
    build_output: bool = True,
    load_output: bool = True,
    database_url: str | None = None,
) -> None:
    if not build_output and not load_output:
        raise ValueError("At least one of build_output or load_output must be enabled.")

    if build_output:
        print("Building combined monitoring anomalies table...")
        combined = build_monitoring_dataframe()
        save_monitoring_output(combined)

    if load_output:
        load_monitoring_output(database_url=database_url)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build and/or publish the combined monitoring anomalies table.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--build-only",
        action="store_true",
        help="Build the parquet output without publishing it to PostgreSQL.",
    )
    mode.add_argument(
        "--load-only",
        action="store_true",
        help="Publish the existing validated parquet output without rebuilding it.",
    )
    parser.add_argument(
        "--database-url",
        help="Optional PostgreSQL SQLAlchemy URL.",
    )
    args = parser.parse_args()

    main(
        build_output=not args.load_only,
        load_output=not args.build_only,
        database_url=args.database_url,
    )
