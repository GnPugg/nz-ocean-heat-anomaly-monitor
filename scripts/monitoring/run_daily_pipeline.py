from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from nzheat.load.load_postgres import create_db_engine, get_database_url
from nzheat.utils.commands import run_command
from nzheat.utils.paths import find_project_root
from nzheat.utils.pipeline_logging import PipelineRunLogger

PROJECT_ROOT = find_project_root()
MONITORING_DIR = PROJECT_ROOT / "scripts" / "monitoring"
MAINTENANCE_DIR = PROJECT_ROOT / "scripts" / "maintenance"


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
