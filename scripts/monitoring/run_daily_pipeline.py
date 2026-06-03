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
MONITORING_DIR = PROJECT_ROOT / "scripts" / "monitoring"
MAINTENANCE_DIR = PROJECT_ROOT / "scripts" / "maintenance"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

FINAL_ANOMALIES_FILE = PROCESSED_DIR / "region_daily_anomalies.parquet"
FINAL_EVENTS_FILE = PROCESSED_DIR / "heat_events.parquet"

PRELIM_SST_FILE = PROCESSED_DIR / "region_daily_sst_recent_prelim.parquet"
PRELIM_ANOMALIES_FILE = PROCESSED_DIR / "region_daily_anomalies_recent_prelim.parquet"
PRELIM_EVENTS_FILE = PROCESSED_DIR / "heat_events_recent_prelim.parquet"

MONITORING_ANOMALIES_FILE = PROCESSED_DIR / "region_daily_anomalies_monitoring.parquet"


def print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def run_script(
    script_path: Path,
    extra_args: list[str] | None = None,
    run_logger: PipelineRunLogger | None = None,
    step_name: str | None = None,
) -> None:
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    command = [sys.executable, str(script_path)]

    if extra_args:
        command.extend(extra_args)

    command_text = " ".join(command)

    if run_logger:
        run_logger.info(
            f"Starting step: {step_name or script_path.name}",
            {
                "step_name": step_name or script_path.name,
                "command": command_text,
            },
        )

    run_command(command)

    if run_logger:
        run_logger.info(
            f"Finished step: {step_name or script_path.name}",
            {
                "step_name": step_name or script_path.name,
                "command": command_text,
            },
        )


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

    if run_logger:
        run_logger.info(
            f"Starting step: {step_name or module_name}",
            {
                "step_name": step_name or module_name,
                "command": command_text,
            },
        )

    run_command(command)

    if run_logger:
        run_logger.info(
            f"Finished step: {step_name or module_name}",
            {
                "step_name": step_name or module_name,
                "command": command_text,
            },
        )


def log_skipped_step(
    run_logger: PipelineRunLogger | None,
    step_name: str,
    reason: str,
) -> None:
    if run_logger:
        run_logger.warning(
            f"Skipped step: {step_name}",
            {
                "step_name": step_name,
                "reason": reason,
            },
        )


def sanitized_args(args: argparse.Namespace) -> dict[str, Any]:
    """
    Return pipeline CLI options for logging, excluding sensitive values.
    """
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
    except Exception as exc:  # pragma: no cover - defensive logging only
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
    load_mode: str = "replace",
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
    except Exception as exc:  # pragma: no cover - defensive logging only
        run_logger.warning(
            f"Could not collect PostgreSQL table metrics: {step_name}",
            {
                "step_name": step_name,
                "target_table": f"{schema_name}.{table_name}",
                "error_message": f"{type(exc).__name__}: {exc}",
            },
        )


def log_final_output_metrics(run_logger: PipelineRunLogger | None) -> None:
    log_parquet_metrics(
        run_logger,
        step_name="final_anomalies",
        path=FINAL_ANOMALIES_FILE,
        count_columns=["status_label", "above_p90"],
    )
    log_parquet_metrics(
        run_logger,
        step_name="final_heat_events",
        path=FINAL_EVENTS_FILE,
        min_date_column="start_date",
        max_date_column="end_date",
        count_columns=["severity_class", "is_active"],
    )
    log_postgres_table_metrics(
        run_logger,
        step_name="load_final_anomalies",
        schema_name="analytics",
        table_name="region_daily_anomalies",
        min_date_column="date",
        max_date_column="date",
        load_mode="truncate_insert",
    )
    log_postgres_table_metrics(
        run_logger,
        step_name="load_final_heat_events",
        schema_name="analytics",
        table_name="heat_events",
        min_date_column="start_date",
        max_date_column="end_date",
        load_mode="truncate_insert",
    )


def log_preliminary_file_metrics(run_logger: PipelineRunLogger | None) -> None:
    log_parquet_metrics(
        run_logger,
        step_name="preliminary_sst",
        path=PRELIM_SST_FILE,
        count_columns=["is_provisional"],
    )
    log_parquet_metrics(
        run_logger,
        step_name="preliminary_anomalies",
        path=PRELIM_ANOMALIES_FILE,
        count_columns=["status_label", "above_p90"],
    )
    log_parquet_metrics(
        run_logger,
        step_name="preliminary_heat_events",
        path=PRELIM_EVENTS_FILE,
        min_date_column="start_date",
        max_date_column="end_date",
        count_columns=["severity_class", "is_active"],
    )


def log_preliminary_table_metrics(run_logger: PipelineRunLogger | None) -> None:
    log_postgres_table_metrics(
        run_logger,
        step_name="load_preliminary_sst",
        schema_name="analytics",
        table_name="region_daily_sst_prelim",
        min_date_column="date",
        max_date_column="date",
        load_mode="truncate_insert",
    )
    log_postgres_table_metrics(
        run_logger,
        step_name="load_preliminary_anomalies",
        schema_name="analytics",
        table_name="region_daily_anomalies_prelim",
        min_date_column="date",
        max_date_column="date",
        load_mode="truncate_insert",
    )
    log_postgres_table_metrics(
        run_logger,
        step_name="load_preliminary_heat_events",
        schema_name="analytics",
        table_name="heat_events_prelim",
        min_date_column="start_date",
        max_date_column="end_date",
        load_mode="truncate_insert",
    )


def log_monitoring_metrics(run_logger: PipelineRunLogger | None) -> None:
    log_parquet_metrics(
        run_logger,
        step_name="build_and_load_monitoring_anomalies",
        path=MONITORING_ANOMALIES_FILE,
        count_columns=["data_product", "is_provisional", "status_label"],
    )
    log_postgres_table_metrics(
        run_logger,
        step_name="build_and_load_monitoring_anomalies",
        schema_name="analytics",
        table_name="region_daily_anomalies_monitoring",
        min_date_column="date",
        max_date_column="date",
        load_mode="replace",
    )


def build_prelim_args(args: argparse.Namespace) -> list[str]:
    prelim_args: list[str] = []

    if args.prelim_start_date:
        prelim_args.extend(["--start-date", args.prelim_start_date])
    else:
        prelim_args.extend(["--days-back", str(args.prelim_days_back)])

    if args.prelim_end_date:
        prelim_args.extend(["--end-date", args.prelim_end_date])
    else:
        prelim_args.extend(["--end-lag-days", str(args.prelim_end_lag_days)])

    if args.overwrite_prelim_download:
        prelim_args.append("--overwrite-download")

    return prelim_args


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full daily NZ ocean heat monitoring pipeline."
    )

    parser.add_argument(
        "--skip-final",
        action="store_true",
        help="Skip final OISST daily append, final anomalies, final events, and final database load.",
    )
    parser.add_argument(
        "--skip-prelim",
        action="store_true",
        help="Skip preliminary OISST download/anomaly/event calculation.",
    )
    parser.add_argument(
        "--skip-load-prelim",
        action="store_true",
        help="Skip loading preliminary outputs to PostgreSQL.",
    )
    parser.add_argument(
        "--skip-monitoring",
        action="store_true",
        help="Skip building/loading the combined monitoring anomalies table.",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip output validation.",
    )
    parser.add_argument(
        "--skip-db-log",
        action="store_true",
        help="Run the pipeline without writing pipeline logs to PostgreSQL.",
    )
    parser.add_argument(
        "--database-url",
        help="Optional PostgreSQL SQLAlchemy URL. If omitted, DATABASE_URL or DB_* environment variables are used.",
    )

    parser.add_argument(
        "--prelim-start-date",
        help="Optional preliminary start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--prelim-end-date",
        help="Optional preliminary end date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--prelim-days-back",
        type=int,
        default=21,
        help="Used by preliminary update when prelim-start-date is not supplied.",
    )
    parser.add_argument(
        "--prelim-end-lag-days",
        type=int,
        default=1,
        help="Used by preliminary update when prelim-end-date is not supplied.",
    )
    parser.add_argument(
        "--overwrite-prelim-download",
        action="store_true",
        help="Re-download preliminary NetCDF files even if they already exist.",
    )

    args = parser.parse_args()

    run_logger: PipelineRunLogger | None = None

    if not args.skip_db_log:
        engine = create_db_engine(get_database_url(args.database_url))
        run_logger = PipelineRunLogger(
            engine=engine,
            pipeline_name="run_daily_pipeline",
        )
        run_logger.start("Daily monitoring pipeline started")
        run_logger.info("Pipeline options", sanitized_args(args))

    try:
        print_section("Starting full daily pipeline")

        if not args.skip_final:
            print_section(
                "Step 1: Final daily append + final anomalies/events + final database load"
            )
            run_script(
                MONITORING_DIR / "run_daily_append.py",
                run_logger=run_logger,
                step_name="final_daily_append",
            )
            log_final_output_metrics(run_logger)
        else:
            print_section("Step 1 skipped: final daily append")
            log_skipped_step(
                run_logger,
                step_name="final_daily_append",
                reason="--skip-final was supplied",
            )

        if not args.skip_prelim:
            print_section(
                "Step 2: Preliminary SST update + preliminary anomalies/events"
            )

            run_script(
                MONITORING_DIR / "run_preliminary_update.py",
                extra_args=build_prelim_args(args),
                run_logger=run_logger,
                step_name="preliminary_update",
            )
            log_preliminary_file_metrics(run_logger)
        else:
            print_section("Step 2 skipped: preliminary update")
            log_skipped_step(
                run_logger,
                step_name="preliminary_update",
                reason="--skip-prelim was supplied",
            )

        if not args.skip_load_prelim:
            print_section("Step 3: Load preliminary outputs to PostgreSQL")
            run_module(
                "nzheat.load.load_preliminary_postgres",
                run_logger=run_logger,
                step_name="load_preliminary_postgres",
            )
            log_preliminary_table_metrics(run_logger)
        else:
            print_section("Step 3 skipped: preliminary PostgreSQL load")
            log_skipped_step(
                run_logger,
                step_name="load_preliminary_postgres",
                reason="--skip-load-prelim was supplied",
            )

        if not args.skip_monitoring:
            print_section("Step 4: Build and load combined monitoring anomalies table")
            run_script(
                MONITORING_DIR / "build_and_load_monitoring_anomalies.py",
                run_logger=run_logger,
                step_name="build_and_load_monitoring_anomalies",
            )
            log_monitoring_metrics(run_logger)
        else:
            print_section("Step 4 skipped: monitoring anomalies table")
            log_skipped_step(
                run_logger,
                step_name="build_and_load_monitoring_anomalies",
                reason="--skip-monitoring was supplied",
            )

        if not args.skip_validate:
            print_section("Step 5: Validate processed outputs")
            run_script(
                MAINTENANCE_DIR / "validate_outputs.py",
                run_logger=run_logger,
                step_name="validate_outputs",
            )
        else:
            print_section("Step 5 skipped: validation")
            log_skipped_step(
                run_logger,
                step_name="validate_outputs",
                reason="--skip-validate was supplied",
            )

        print_section("Daily pipeline completed successfully")

        if run_logger:
            run_logger.finish_success(
                "Daily monitoring pipeline completed successfully"
            )

    except Exception as exc:
        if run_logger:
            run_logger.finish_failed(exc)
        raise


if __name__ == "__main__":
    main()
