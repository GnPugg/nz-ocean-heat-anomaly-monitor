from __future__ import annotations

from pathlib import Path
from datetime import date
import argparse

import pandas as pd

DEFAULT_INPUT_FILE = Path("data/processed/region_daily_sst_history.parquet")
DEFAULT_OUTPUT_FILE = Path("data/processed/region_climatology.parquet")


def parse_iso_date(value: str | None) -> pd.Timestamp | None:
    """Parse optional CLI date in YYYY-MM-DD format."""
    if value is None:
        return None
    try:
        return pd.Timestamp(date.fromisoformat(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Use YYYY-MM-DD format."
        ) from exc


def load_region_history(input_path: Path) -> pd.DataFrame:
    """Load the backfilled daily regional SST history table."""
    return pd.read_parquet(input_path)


def prepare_history(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare regional SST data for climatology/anomaly calculations.

    We use a no-leap climatology day:
    - Feb 29 is dropped
    - dates after Feb 29 in leap years are shifted back by 1
    This keeps day_of_year in the range 1-365.
    """
    prepared = df.copy()
    prepared["date"] = pd.to_datetime(prepared["date"])

    # Drop Feb 29
    leap_day_mask = (prepared["date"].dt.month == 2) & (prepared["date"].dt.day == 29)
    prepared = prepared.loc[~leap_day_mask].copy()

    raw_doy = prepared["date"].dt.dayofyear
    leap_year_after_feb = prepared["date"].dt.is_leap_year & (raw_doy > 60)

    prepared["day_of_year"] = raw_doy.where(~leap_year_after_feb, raw_doy - 1)
    prepared["day_of_year"] = prepared["day_of_year"].astype(int)

    return prepared


def filter_baseline_period(
    df: pd.DataFrame,
    baseline_start: pd.Timestamp | None,
    baseline_end: pd.Timestamp | None,
) -> pd.DataFrame:
    """Filter history down to the climatology baseline period."""
    filtered = df.copy()

    if baseline_start is not None:
        filtered = filtered.loc[filtered["date"] >= baseline_start].copy()

    if baseline_end is not None:
        filtered = filtered.loc[filtered["date"] <= baseline_end].copy()

    return filtered


def calculate_climatology(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate day-of-year climatology by region.

    Outputs:
    - clim_mean_sst_c: average SST for that region and calendar day
    - clim_p90_sst_c: 90th percentile threshold for later warm-event logic
    - sample_size: number of observations contributing to that climatology row
    """
    group_cols = ["region_id", "region_code", "region_name", "day_of_year"]

    climatology = (
        df.groupby(group_cols, dropna=False)
        .agg(
            clim_mean_sst_c=("mean_sst_c", "mean"),
            clim_p90_sst_c=("mean_sst_c", lambda x: x.quantile(0.90)),
            sample_size=("mean_sst_c", "count"),
        )
        .reset_index()
        .sort_values(["region_id", "day_of_year"])
        .reset_index(drop=True)
    )

    climatology["sample_size"] = climatology["sample_size"].astype(int)
    climatology["region_id"] = climatology["region_id"].astype(int)

    return climatology


def save_output(df: pd.DataFrame, output_path: Path) -> None:
    """Save the climatology table to parquet."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)


def main(
    input_path: Path,
    output_path: Path,
    baseline_start: pd.Timestamp | None,
    baseline_end: pd.Timestamp | None,
) -> None:
    print(f"Loading regional SST history: {input_path}")
    history_df = load_region_history(input_path)
    print(f"Loaded {len(history_df):,} history rows")

    prepared_df = prepare_history(history_df)
    print(f"Rows after preparation: {len(prepared_df):,}")

    baseline_df = filter_baseline_period(
        prepared_df,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
    )
    print(f"Rows in baseline period: {len(baseline_df):,}")

    if baseline_df.empty:
        raise RuntimeError("No rows found in the requested baseline period.")

    climatology_df = calculate_climatology(baseline_df)
    print(f"Created {len(climatology_df):,} climatology rows")

    print("Preview:")
    print(climatology_df.head())

    save_output(climatology_df, output_path)
    print(f"Saved climatology output to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Calculate day-of-year SST climatology by NZ coastal region.",
    )
    parser.add_argument(
        "--input-file",
        default=str(DEFAULT_INPUT_FILE),
        help="Path to the regional SST history parquet produced by backfill.py",
    )
    parser.add_argument(
        "--output-file",
        default=str(DEFAULT_OUTPUT_FILE),
        help="Path where the climatology parquet will be saved.",
    )
    parser.add_argument(
        "--baseline-start",
        type=parse_iso_date,
        default=None,
        help="Baseline start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--baseline-end",
        type=parse_iso_date,
        default=None,
        help="Baseline end date in YYYY-MM-DD format.",
    )
    args = parser.parse_args()

    main(
        input_path=Path(args.input_file),
        output_path=Path(args.output_file),
        baseline_start=args.baseline_start,
        baseline_end=args.baseline_end,
    )
