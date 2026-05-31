from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nzheat.utils.commands import run_command

SCRIPTS_DIR = Path("scripts")


def print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def run_script(script_name: str, extra_args: list[str] | None = None) -> None:
    command = [sys.executable, str(SCRIPTS_DIR / script_name)]

    if extra_args:
        command.extend(extra_args)

    run_command(command)


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

    print_section("Starting full daily pipeline")

    if not args.skip_final:
        print_section(
            "Step 1: Final daily append + final anomalies/events + final database load"
        )
        run_script("run_daily_append.py")
    else:
        print_section("Step 1 skipped: final daily append")

    if not args.skip_prelim:
        print_section("Step 2: Preliminary SST update + preliminary anomalies/events")

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

        run_script("run_preliminary_update.py", prelim_args)
    else:
        print_section("Step 2 skipped: preliminary update")

    if not args.skip_load_prelim:
        print_section("Step 3: Load preliminary outputs to PostgreSQL")
        run_script("load_preliminary_postgres.py")
    else:
        print_section("Step 3 skipped: preliminary PostgreSQL load")

    if not args.skip_monitoring:
        print_section("Step 4: Build and load combined monitoring anomalies table")
        run_script("build_and_load_monitoring_anomalies.py")
    else:
        print_section("Step 4 skipped: monitoring anomalies table")

    if not args.skip_validate:
        print_section("Step 5: Validate processed outputs")
        run_script("validate_outputs.py")
    else:
        print_section("Step 5 skipped: validation")

    print_section("Daily pipeline completed successfully")


if __name__ == "__main__":
    main()
