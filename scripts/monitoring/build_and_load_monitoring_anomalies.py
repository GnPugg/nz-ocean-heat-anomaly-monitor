from __future__ import annotations

from pathlib import Path

import pandas as pd

from nzheat.load.load_postgres import (
    create_db_engine,
    get_database_url,
    load_dataframe_to_table,
    normalize_dataframe_types,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

FINAL_ANOMALIES_FILE = PROCESSED_DIR / "region_daily_anomalies.parquet"
PRELIM_ANOMALIES_FILE = PROCESSED_DIR / "region_daily_anomalies_recent_prelim.parquet"
OUTPUT_FILE = PROCESSED_DIR / "region_daily_anomalies_monitoring.parquet"

SCHEMA_NAME = "analytics"
TABLE_NAME = "region_daily_anomalies_monitoring"


def main() -> None:
    print("Building combined monitoring anomalies table...")

    if not FINAL_ANOMALIES_FILE.exists():
        raise FileNotFoundError(f"Missing final anomalies file: {FINAL_ANOMALIES_FILE}")

    if not PRELIM_ANOMALIES_FILE.exists():
        raise FileNotFoundError(
            f"Missing preliminary anomalies file: {PRELIM_ANOMALIES_FILE}"
        )

    final_df = pd.read_parquet(FINAL_ANOMALIES_FILE)
    prelim_df = pd.read_parquet(PRELIM_ANOMALIES_FILE)

    final_df["date"] = pd.to_datetime(final_df["date"])
    prelim_df["date"] = pd.to_datetime(prelim_df["date"])

    # Add monitoring metadata to final rows.
    if "data_product" not in final_df.columns:
        final_df["data_product"] = "final"

    if "is_provisional" not in final_df.columns:
        final_df["is_provisional"] = False

    # Ensure preliminary rows are labelled correctly.
    prelim_df["data_product"] = "preliminary"
    prelim_df["is_provisional"] = True

    final_df["source_priority"] = 0
    prelim_df["source_priority"] = 1

    combined = pd.concat([final_df, prelim_df], ignore_index=True)

    # Where final and preliminary overlap, keep preliminary.
    combined = combined.sort_values(["region_id", "date", "source_priority"])
    combined = combined.drop_duplicates(
        subset=["region_id", "date"],
        keep="last",
    )

    combined = combined.drop(columns=["source_priority"])
    combined = combined.sort_values(["date", "region_id"]).reset_index(drop=True)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(OUTPUT_FILE, index=False)

    print("\nSaved combined monitoring anomalies file:")
    print(OUTPUT_FILE)

    print("\nDate range:")
    print(combined["date"].min(), "to", combined["date"].max())

    print("\nRows:")
    print(len(combined))

    print("\nRows by data product:")
    print(combined["data_product"].value_counts(dropna=False))

    print("\nRows by provisional flag:")
    print(combined["is_provisional"].value_counts(dropna=False))

    database_url = get_database_url()
    engine = create_db_engine(database_url)

    db_df = normalize_dataframe_types(TABLE_NAME, combined)

    load_dataframe_to_table(
        engine,
        db_df,
        schema_name=SCHEMA_NAME,
        table_name=TABLE_NAME,
        if_exists="replace",
    )

    print(f"\nLoaded {len(db_df):,} rows into {SCHEMA_NAME}.{TABLE_NAME}")


if __name__ == "__main__":
    main()
