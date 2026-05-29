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

PROJECTION_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_sst_projection_10yr.parquet"
)

SCHEMA_NAME = "analytics"
TABLE_NAME = "region_monthly_sst_projection_10yr"


def main() -> None:
    database_url = get_database_url()
    engine = create_db_engine(database_url)

    if not PROJECTION_FILE.exists():
        raise FileNotFoundError(f"File not found: {PROJECTION_FILE}")

    print(f"Loading analytics.{TABLE_NAME} from {PROJECTION_FILE}")

    df = pd.read_parquet(PROJECTION_FILE)
    df = normalize_dataframe_types(TABLE_NAME, df)

    load_dataframe_to_table(
        engine,
        df,
        schema_name=SCHEMA_NAME,
        table_name=TABLE_NAME,
        if_exists="replace",
    )

    print(f"Loaded {len(df):,} rows into analytics.{TABLE_NAME}")
    print("Projection table loaded successfully.")


if __name__ == "__main__":
    main()
