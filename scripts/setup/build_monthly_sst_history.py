from __future__ import annotations

from pathlib import Path
import math

import pandas as pd

PROJECT_ROOT = = find_project_root()
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

INPUT_FILES = [
    PROCESSED_DIR / "region_daily_sst_baseline_1991_2020.parquet",
    PROCESSED_DIR / "region_daily_sst_gap_2021_2024.parquet",
    PROCESSED_DIR / "region_daily_sst_history.parquet",
]

OUTPUT_PARQUET = PROCESSED_DIR / "region_monthly_sst_history.parquet"
OUTPUT_CSV = PROCESSED_DIR / "region_monthly_sst_history.csv"


def load_daily_sst_files() -> pd.DataFrame:
    dfs: list[pd.DataFrame] = []

    for path in INPUT_FILES:
        if not path.exists():
            raise FileNotFoundError(f"Missing input file: {path}")

        print(f"Loading: {path}")
        df = pd.read_parquet(path)

        required_cols = {"date", "region_id", "region_name", "mean_sst_c"}
        missing_cols = required_cols - set(df.columns)

        if missing_cols:
            raise ValueError(f"{path} is missing columns: {missing_cols}")

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        dfs.append(df)

    daily = pd.concat(dfs, ignore_index=True)

    daily = (
        daily.drop_duplicates(subset=["date", "region_id"], keep="last")
        .sort_values(["region_id", "date"])
        .reset_index(drop=True)
    )

    return daily


def build_monthly_history(daily: pd.DataFrame) -> pd.DataFrame:
    daily = daily.copy()

    daily["month_date"] = daily["date"].dt.to_period("M").dt.to_timestamp()
    daily["year"] = daily["date"].dt.year
    daily["month"] = daily["date"].dt.month

    monthly = (
        daily.groupby(
            ["region_id", "region_name", "month_date", "year", "month"],
            as_index=False,
        )
        .agg(
            mean_sst_c=("mean_sst_c", "mean"),
            min_sst_c=("mean_sst_c", "min"),
            max_sst_c=("mean_sst_c", "max"),
            sd_sst_c=("mean_sst_c", "std"),
            n_days=("date", "nunique"),
        )
        .sort_values(["region_id", "month_date"])
        .reset_index(drop=True)
    )

    first_month = monthly["month_date"].min()

    monthly["time_index_years"] = (monthly["month_date"] - first_month).dt.days / 365.25

    monthly["sin_month"] = monthly["month"].apply(
        lambda m: math.sin(2 * math.pi * m / 12)
    )

    monthly["cos_month"] = monthly["month"].apply(
        lambda m: math.cos(2 * math.pi * m / 12)
    )

    return monthly


def save_outputs(monthly: pd.DataFrame) -> None:
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)

    monthly.to_parquet(OUTPUT_PARQUET, index=False)
    monthly.to_csv(OUTPUT_CSV, index=False)

    print("\nSaved monthly SST history:")
    print(OUTPUT_PARQUET)
    print(OUTPUT_CSV)


def print_summary(monthly: pd.DataFrame) -> None:
    print("\nDate range:")
    print(monthly["month_date"].min(), "to", monthly["month_date"].max())

    print("\nTotal rows:")
    print(len(monthly))

    print("\nCoverage by region:")
    coverage = (
        monthly.groupby("region_name")
        .agg(
            start_month=("month_date", "min"),
            end_month=("month_date", "max"),
            n_months=("month_date", "nunique"),
            mean_sst_c=("mean_sst_c", "mean"),
        )
        .reset_index()
    )

    print(coverage)

    print("\nRecent months:")
    print(
        monthly.sort_values(["month_date", "region_name"]).tail(18)[
            [
                "region_name",
                "month_date",
                "mean_sst_c",
                "n_days",
                "time_index_years",
            ]
        ]
    )


def main() -> None:
    print("================================")
    print("Building monthly SST history")
    print("================================")

    daily = load_daily_sst_files()

    print("\nDaily input range:")
    print(daily["date"].min(), "to", daily["date"].max())

    print("\nDaily rows:")
    print(len(daily))

    monthly = build_monthly_history(daily)
    save_outputs(monthly)
    print_summary(monthly)

    print("\nDone.")


if __name__ == "__main__":
    main()
