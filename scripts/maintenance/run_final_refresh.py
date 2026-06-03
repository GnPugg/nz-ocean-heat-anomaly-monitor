from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

from nzheat.load.load_postgres import create_db_engine, get_database_url
from nzheat.utils.commands import run_command
from nzheat.utils.paths import find_project_root
from nzheat.utils.pipeline_logging import PipelineRunLogger

PROJECT_ROOT = find_project_root()
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

REGION_DAILY_SST_FILE = PROCESSED_DIR / "region_daily_sst_history.parquet"
CLIMATOLOGY_FILE = PROCESSED_DIR / "region_climatology.parquet"
FINAL_ANOMALIES_FILE = PROCESSED_DIR / "region_daily_anomalies.parquet"
FINAL_EVENTS_FILE = PROCESSED_DIR / "heat_events.parquet"


def print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def run_module(
    module_name: str,
    extra_args: list[str] | None = None,
    run_logger: PipelineRunLogger | None = None,
    step_name: str | None = None,
) -> None:
    command = [sys.executable, "-m", module_name]

    if extra_args:
        command.extend(extra_args)

    command_text = " ".join(command)
    display_name = step_name or module_name

    if run_logger:
        run_logger.info(
            f"Starting step: {display_name}",
            {
                "step_name": display_name,
                "command": command_text,
            },
        )

    run_command(command)

    if run_logger:
        run_logger.info(
            f"Finished step: {display_name}",
            {
                "step_name": display_name,
                "command": command_text,
            },
        )


def sanitized_args(args: argparse.Namespace) -> dict[str, Any]:
    """Return CLI options for logging, excluding sensitive values."""
    values = vars(args).copy()
    values.pop("database_url", None)
    return values


def path_for_logging(path: Path) -> str:
    """Return a readable project-relative path when possible."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def build_parquet_metrics(
    path: Path,
    *,
    min_date_column: str | None = "date",
    max_date_column: str | None = "date",
    count_columns: list[str] | None = None,
) -> dict[str, Any]:
    """Build lightweight output metrics from a parquet file."""
    metrics: dict[str, Any] = {
        "output_file": path_for_logging(path),
        "output_file_exists": path.exists(),
    }

    if not path.exists():
        return metrics

    df = pd.read_parquet(path)

    metrics["rows_created"] = int(len(df))
    metrics["column_count"] = int(len(df.columns))

    if "region_id" in df.columns:
        metrics["region_count"] = int(df["region_id"].nunique())

    if min_date_column and min_date_column in df.columns and not df.empty:
        min_date = pd.to_datetime(df[min_date_column]).min()
        metrics["date_min"] = min_date.date().isoformat()

    if max_date_column and max_date_column in df.columns and not df.empty:
        max_date = pd.to_datetime(df[max_date_column]).max()
        metrics["date_max"] = max_date.date().isoformat()

    for column in count_columns or []:
        if column in df.columns:
            counts = df[column].value_counts(dropna=False).to_dict()
            metrics[f"{column}_counts"] = {
                str(key): int(value) for key, value in counts.items()
            }

    return metrics


def log_parquet_metrics(
    run_logger: PipelineRunLogger | None,
    *,
    step_name: str,
    path: Path,
    min_date_column: str | None = "date",
    max_date_column: str | None = "date",
    count_columns: list[str] | None = None,
) -> None:
    """Write parquet output metrics to the PostgreSQL pipeline log."""
    if run_logger is None:
        return

    try:
        metrics = build_parquet_metrics(
            path,
            min_date_column=min_date_column,
            max_date_column=max_date_column,
            count_columns=count_columns,
        )
        metrics["step_name"] = step_name

        run_logger.info(
            f"Output metrics: {step_name}",
            metrics,
        )
    except Exception as exc:  # defensive logging only
        run_logger.warning(
            f"Could not collect output metrics: {step_name}",
            {
                "step_name": step_name,
                "output_file": path_for_logging(path),
                "error_message": f"{type(exc).__name__}: {exc}",
            },
        )


def log_postgres_table_metrics(
    run_logger: PipelineRunLogger | None,
    *,
    step_name: str,
    schema_name: str,
    table_name: str,
    min_date_column: str | None = None,
    max_date_column: str | None = None,
    load_mode: str = "truncate_insert",
) -> None:
    """Write target PostgreSQL table metrics to the pipeline log."""
    if run_logger is None:
        return

    try:
        select_parts = ["COUNT(*) AS rows_loaded"]

        if min_date_column:
            select_parts.append(f"MIN({min_date_column}) AS date_min")

        if max_date_column:
            select_parts.append(f"MAX({max_date_column}) AS date_max")

        statement = text(f"""
            SELECT {", ".join(select_parts)}
            FROM {schema_name}.{table_name};
            """)

        with run_logger.engine.connect() as connection:
            row = connection.execute(statement).mappings().one()

        metrics = {
            "step_name": step_name,
            "target_table": f"{schema_name}.{table_name}",
            "load_mode": load_mode,
            "rows_loaded": int(row["rows_loaded"]),
        }

        if "date_min" in row and row["date_min"] is not None:
            metrics["date_min"] = str(row["date_min"])

        if "date_max" in row and row["date_max"] is not None:
            metrics["date_max"] = str(row["date_max"])

        run_logger.info(
            f"PostgreSQL load metrics: {step_name}",
            metrics,
        )
    except Exception as exc:  # defensive logging only
        run_logger.warning(
            f"Could not collect PostgreSQL table metrics: {step_name}",
            {
                "step_name": step_name,
                "target_table": f"{schema_name}.{table_name}",
                "error_message": f"{type(exc).__name__}: {exc}",
            },
        )


def log_anomaly_output_metrics(run_logger: PipelineRunLogger | None) -> None:
    log_parquet_metrics(
        run_logger,
        step_name="calculate_final_anomalies",
        path=FINAL_ANOMALIES_FILE,
        count_columns=["status_label", "above_p90"],
    )


def log_event_output_metrics(run_logger: PipelineRunLogger | None) -> None:
    log_parquet_metrics(
        run_logger,
        step_name="detect_final_heat_events",
        path=FINAL_EVENTS_FILE,
        min_date_column="start_date",
        max_date_column="end_date",
        count_columns=["severity_class", "is_active"],
    )


def log_final_load_metrics(run_logger: PipelineRunLogger | None) -> None:
    log_postgres_table_metrics(
        run_logger,
        step_name="load_region_daily_sst",
        schema_name="analytics",
        table_name="region_daily_sst",
        min_date_column="date",
        max_date_column="date",
    )
    log_postgres_table_metrics(
        run_logger,
        step_name="load_region_climatology",
        schema_name="analytics",
        table_name="region_climatology",
    )
    log_postgres_table_metrics(
        run_logger,
        step_name="load_final_anomalies",
        schema_name="analytics",
        table_name="region_daily_anomalies",
        min_date_column="date",
        max_date_column="date",
    )
    log_postgres_table_metrics(
        run_logger,
        step_name="load_final_heat_events",
        schema_name="analytics",
        table_name="heat_events",
        min_date_column="start_date",
        max_date_column="end_date",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run final/historical refresh with PostgreSQL pipeline logging."
    )
    parser.add_argument(
        "--skip-db-log",
        action="store_true",
        help="Run the refresh without writing pipeline logs to PostgreSQL.",
    )
    parser.add_argument(
        "--database-url",
        help="Optional PostgreSQL SQLAlchemy URL. If omitted, DATABASE_URL or DB_* environment variables are used.",
    )

    args = parser.parse_args()

    run_logger: PipelineRunLogger | None = None

    if not args.skip_db_log:
        engine = create_db_engine(get_database_url(args.database_url))
        run_logger = PipelineRunLogger(
            engine=engine,
            pipeline_name="run_final_refresh",
        )
        run_logger.start("Final/historical refresh started")
        run_logger.info("Pipeline options", sanitized_args(args))

    try:
        print_section("Running final/historical refresh")

        run_module(
            "nzheat.analytics.anomalies",
            run_logger=run_logger,
            step_name="calculate_final_anomalies",
        )
        log_anomaly_output_metrics(run_logger)

        run_module(
            "nzheat.analytics.events",
            run_logger=run_logger,
            step_name="detect_final_heat_events",
        )
        log_event_output_metrics(run_logger)

        load_args: list[str] = []
        if args.database_url:
            load_args.extend(["--database-url", args.database_url])

        run_module(
            "nzheat.load.load_postgres",
            extra_args=load_args,
            run_logger=run_logger,
            step_name="load_final_outputs_to_postgres",
        )
        log_final_load_metrics(run_logger)

        print_section("Final/historical refresh complete")

        if run_logger:
            run_logger.finish_success("Final/historical refresh completed successfully")

    except Exception as exc:
        if run_logger:
            run_logger.finish_failed(exc)
        raise


if __name__ == "__main__":
    main()
