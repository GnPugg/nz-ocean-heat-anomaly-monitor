from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from nzheat.utils.commands import run_command
from nzheat.utils.paths import find_project_root

PROJECT_ROOT = find_project_root()

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "oisst_gap_2021_2024"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

FINAL_OUTPUT = PROCESSED_DIR / "region_daily_sst_gap_2021_2024.parquet"

YEARS = [2021, 2022, 2023, 2024]


def build_year(year: int) -> Path:
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    year_output = PROCESSED_DIR / f"region_daily_sst_gap_{year}.parquet"

    if year_output.exists():
        print(f"Year file already exists, skipping: {year_output}")
        return year_output

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.pipeline.backfill",
            "--start-date",
            start_date,
            "--end-date",
            end_date,
            "--raw-dir",
            str(RAW_DIR),
            "--output-file",
            str(year_output),
        ]
    )

    return year_output


def combine_year_files(year_files: list[Path]) -> None:
    dfs = []

    for path in year_files:
        print(f"Loading {path}")
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"])
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)

    combined = (
        combined.drop_duplicates(subset=["date", "region_id"], keep="last")
        .sort_values(["date", "region_id"])
        .reset_index(drop=True)
    )

    FINAL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(FINAL_OUTPUT, index=False)

    print("\nSaved combined gap file:")
    print(FINAL_OUTPUT)

    print("\nDate range:")
    print(combined["date"].min(), "to", combined["date"].max())

    print("\nRows:")
    print(len(combined))

    print("\nRows by region:")
    print(combined.groupby("region_name").size())

    expected_rows = 1461 * 6  # 2021–2024 includes leap year 2024

    if len(combined) != expected_rows:
        print(
            f"\nWARNING: expected about {expected_rows:,} rows, "
            f"but found {len(combined):,} rows."
        )
    else:
        print("\nRow count looks correct.")


def main() -> None:
    print("======================================")
    print("Building 2021–2024 regional SST gap")
    print("======================================")

    year_files = []

    for year in YEARS:
        year_file = build_year(year)
        year_files.append(year_file)

    combine_year_files(year_files)

    print("\nDone.")


if __name__ == "__main__":
    main()
