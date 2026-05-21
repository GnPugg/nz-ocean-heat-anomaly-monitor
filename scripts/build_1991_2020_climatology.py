from __future__ import annotations

from datetime import date
from pathlib import Path
import os
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

BASELINE_START_YEAR = 1991
BASELINE_END_YEAR = 2020

BASELINE_SST_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_daily_sst_baseline_1991_2020.parquet"
)
BASELINE_RAW_DIR = PROJECT_ROOT / "data" / "raw" / "oisst_baseline"
CLIMATOLOGY_FILE = PROJECT_ROOT / "data" / "processed" / "region_climatology.parquet"


def run_command(command: list[str]) -> None:
    """
    Run a project command with src/ added to PYTHONPATH.

    This project uses a src layout:
        src/nzheat/...

    Therefore modules should be run as:
        python -m nzheat.pipeline.backfill

    not:
        python -m src.nzheat.pipeline.backfill
    """
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")

    if existing_pythonpath:
        env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + existing_pythonpath
    else:
        env["PYTHONPATH"] = str(SRC_DIR)

    print("\nRunning:")
    print(" ".join(command))
    print(f"PYTHONPATH={env['PYTHONPATH']}")

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}")


def main() -> None:
    print("===============================")
    print("Building 1991–2020 OISST climatology baseline")
    print("===============================")

    BASELINE_RAW_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_SST_FILE.parent.mkdir(parents=True, exist_ok=True)

    for year in range(BASELINE_START_YEAR, BASELINE_END_YEAR + 1):
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)

        print("\n===============================")
        print(f"Processing baseline year: {year}")
        print("===============================")

        run_command(
            [
                sys.executable,
                "-m",
                "nzheat.pipeline.backfill",
                "--start-date",
                start_date.isoformat(),
                "--end-date",
                end_date.isoformat(),
                "--raw-dir",
                str(BASELINE_RAW_DIR),
                "--output-file",
                str(BASELINE_SST_FILE),
                "--append",
            ]
        )

    print("\n===============================")
    print("Creating climatology from 1991–2020 baseline")
    print("===============================")

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.analytics.climatology",
            "--input-file",
            str(BASELINE_SST_FILE),
            "--output-file",
            str(CLIMATOLOGY_FILE),
        ]
    )

    print("\nFinished building 1991–2020 climatology.")
    print(f"Baseline SST file: {BASELINE_SST_FILE}")
    print(f"Climatology file: {CLIMATOLOGY_FILE}")


if __name__ == "__main__":
    main()
