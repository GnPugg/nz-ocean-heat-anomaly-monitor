from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from nzheat.load.load_postgres import (
    DEFAULT_ANOMALIES_FILE,
    DEFAULT_CLIMATOLOGY_FILE,
    DEFAULT_EVENTS_FILE,
    DEFAULT_REGION_DAILY_SST_FILE,
    DEFAULT_REGIONS_FILE,
    create_db_engine,
    get_database_url,
    load_dataframe_to_table,
    load_parquet_table,
    load_regions_geojson,
    prepare_table_for_load,
)
from nzheat.load.load_preliminary_postgres import (
    DEFAULT_PRELIM_ANOMALIES_FILE,
    DEFAULT_PRELIM_EVENTS_FILE,
    DEFAULT_PRELIM_SST_FILE,
    load_parquet as load_preliminary_parquet,
    prepare_table_for_load as prepare_preliminary_table_for_load,
)
from nzheat.utils.paths import find_project_root

PROJECT_ROOT = find_project_root()
DEFAULT_MONITORING_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_daily_anomalies_monitoring.parquet"
)

MONITORING_COLUMNS = [
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
    "data_product",
    "is_provisional",
]


@dataclass(frozen=True)
class TableLoad:
    schema_name: str
    table_name: str
    dataframe: pd.DataFrame

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


def prepare_monitoring_table(path: Path) -> pd.DataFrame:
    """Load and validate the combined monitoring anomalies output."""
    if not path.exists():
        raise FileNotFoundError(f"Missing monitoring anomalies file: {path}")

    df = pd.read_parquet(path).copy()
    missing = [column for column in MONITORING_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "region_daily_anomalies_monitoring is missing required columns: "
            f"{missing}"
        )

    df = df[MONITORING_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["region_id"] = df["region_id"].astype(int)
    df["day_of_year"] = df["day_of_year"].astype(int)
    df["sample_size"] = df["sample_size"].astype(int)
    df["cell_count"] = df["cell_count"].astype(int)
    df["above_p90"] = df["above_p90"].astype(bool)
    df["is_provisional"] = df["is_provisional"].astype(bool)

    key_columns = ["date", "region_id"]
    duplicate_count = int(df.duplicated(key_columns).sum())
    if duplicate_count:
        raise ValueError(
            "region_daily_anomalies_monitoring has "
            f"{duplicate_count} duplicate rows based on {key_columns}"
        )

    return df


def build_publication_plan(
    *,
    include_final: bool,
    include_preliminary: bool,
    include_monitoring: bool,
    regions_path: Path = DEFAULT_REGIONS_FILE,
    region_daily_sst_path: Path = DEFAULT_REGION_DAILY_SST_FILE,
    climatology_path: Path = DEFAULT_CLIMATOLOGY_FILE,
    anomalies_path: Path = DEFAULT_ANOMALIES_FILE,
    events_path: Path = DEFAULT_EVENTS_FILE,
    prelim_sst_path: Path = DEFAULT_PRELIM_SST_FILE,
    prelim_anomalies_path: Path = DEFAULT_PRELIM_ANOMALIES_FILE,
    prelim_events_path: Path = DEFAULT_PRELIM_EVENTS_FILE,
    monitoring_path: Path = DEFAULT_MONITORING_FILE,
) -> list[TableLoad]:
    """Prepare every selected table before opening the database transaction."""
    plan: list[TableLoad] = []

    if include_final:
        plan.extend(
            [
                TableLoad(
                    "core",
                    "regions",
                    prepare_table_for_load(
                        "regions", load_regions_geojson(regions_path)
                    ),
                ),
                TableLoad(
                    "analytics",
                    "region_daily_sst",
                    prepare_table_for_load(
                        "region_daily_sst", load_parquet_table(region_daily_sst_path)
                    ),
                ),
                TableLoad(
                    "analytics",
                    "region_climatology",
                    prepare_table_for_load(
                        "region_climatology", load_parquet_table(climatology_path)
                    ),
                ),
                TableLoad(
                    "analytics",
                    "region_daily_anomalies",
                    prepare_table_for_load(
                        "region_daily_anomalies", load_parquet_table(anomalies_path)
                    ),
                ),
                TableLoad(
                    "analytics",
                    "heat_events",
                    prepare_table_for_load(
                        "heat_events", load_parquet_table(events_path)
                    ),
                ),
            ]
        )

    if include_preliminary:
        preliminary_inputs = [
            ("region_daily_sst_prelim", prelim_sst_path),
            ("region_daily_anomalies_prelim", prelim_anomalies_path),
            ("heat_events_prelim", prelim_events_path),
        ]
        for table_name, path in preliminary_inputs:
            plan.append(
                TableLoad(
                    "analytics",
                    table_name,
                    prepare_preliminary_table_for_load(
                        table_name, load_preliminary_parquet(path)
                    ),
                )
            )

    if include_monitoring:
        plan.append(
            TableLoad(
                "analytics",
                "region_daily_anomalies_monitoring",
                prepare_monitoring_table(monitoring_path),
            )
        )

    if not plan:
        raise ValueError("At least one publication group must be enabled.")

    return plan


def publish_tables_atomically(
    engine: Engine,
    plan: list[TableLoad],
) -> None:
    """Replace all selected tables in one PostgreSQL transaction."""
    qualified_names = ", ".join(item.qualified_name for item in plan)
    truncate_statement = text(f"TRUNCATE TABLE {qualified_names} CASCADE;")

    print("Beginning atomic PostgreSQL publication...")

    with engine.begin() as connection:
        connection.execute(truncate_statement)

        for item in plan:
            load_dataframe_to_table(
                connection,
                item.dataframe,
                schema_name=item.schema_name,
                table_name=item.table_name,
                if_exists="append",
            )
            print(f"Loaded {len(item.dataframe):,} rows into {item.qualified_name}")

    print("Atomic PostgreSQL publication committed successfully.")


def publish_selected_outputs(
    *,
    database_url: str,
    include_final: bool,
    include_preliminary: bool,
    include_monitoring: bool,
) -> None:
    plan = build_publication_plan(
        include_final=include_final,
        include_preliminary=include_preliminary,
        include_monitoring=include_monitoring,
    )
    engine = create_db_engine(database_url)
    publish_tables_atomically(engine, plan)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish validated NZ heat-monitor outputs in one transaction."
    )
    parser.add_argument(
        "--database-url",
        help="Optional PostgreSQL SQLAlchemy URL. DB environment variables are used when omitted.",
    )
    parser.add_argument(
        "--skip-final",
        action="store_true",
        help="Do not publish final/core tables.",
    )
    parser.add_argument(
        "--skip-preliminary",
        action="store_true",
        help="Do not publish preliminary tables.",
    )
    parser.add_argument(
        "--skip-monitoring",
        action="store_true",
        help="Do not publish the combined monitoring table.",
    )
    args = parser.parse_args()

    publish_selected_outputs(
        database_url=get_database_url(args.database_url),
        include_final=not args.skip_final,
        include_preliminary=not args.skip_preliminary,
        include_monitoring=not args.skip_monitoring,
    )


if __name__ == "__main__":
    main()
