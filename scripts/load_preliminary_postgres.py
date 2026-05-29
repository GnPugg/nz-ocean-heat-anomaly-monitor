from __future__ import annotations

from pathlib import Path

import pandas as pd

from nzheat.load.load_postgres import (
    create_db_engine,
    get_database_url,
    load_dataframe_to_table,
    normalize_dataframe_types,
    truncate_table,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PRELIM_SST_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_daily_sst_recent_prelim.parquet"
)
PRELIM_ANOMALIES_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_daily_anomalies_recent_prelim.parquet"
)
PRELIM_EVENTS_FILE = (
    PROJECT_ROOT / "data" / "processed" / "heat_events_recent_prelim.parquet"
)


def load_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return pd.read_parquet(path)


def main() -> None:
    database_url = get_database_url()
    engine = create_db_engine(database_url)

    tables = [
        (
            PRELIM_SST_FILE,
            "region_daily_sst_prelim",
        ),
        (
            PRELIM_ANOMALIES_FILE,
            "region_daily_anomalies_prelim",
        ),
        (
            PRELIM_EVENTS_FILE,
            "heat_events_prelim",
        ),
    ]

    for path, table_name in tables:
        print(f"Loading analytics.{table_name} from {path}")

        df = load_parquet(path)
        df = normalize_dataframe_types(table_name, df)

        truncate_table(engine, "analytics", table_name)

        load_dataframe_to_table(
            engine,
            df,
            schema_name="analytics",
            table_name=table_name,
            if_exists="append",
        )

        print(f"Loaded {len(df):,} rows into analytics.{table_name}")

    print("Preliminary outputs loaded successfully.")


if __name__ == "__main__":
    main()
