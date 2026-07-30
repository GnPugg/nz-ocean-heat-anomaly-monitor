from __future__ import annotations

from pathlib import Path
import argparse

import pandas as pd


DEFAULT_INPUT_FILE = Path("data/interim/oisst_points_with_regions.parquet")
DEFAULT_OUTPUT_FILE = Path("data/processed/region_daily_sst.parquet")


def load_joined_points(input_path: Path) -> pd.DataFrame:
    """Load the point-to-region parquet produced by region_join.py."""
    return pd.read_parquet(input_path)


def prepare_for_aggregation(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the joined SST point data before aggregation.

    Steps:
    - drop rows that were not matched to any region
    - ensure time is datetime
    - derive a date column for daily regional summaries
    """
    cleaned = df.copy()

    # Keep only rows that were successfully assigned to a region.
    cleaned = cleaned.dropna(subset=["region_id", "region_name", "sst"])

    # Ensure time is parsed correctly, then create a daily date column.
    cleaned["time"] = pd.to_datetime(cleaned["time"])
    cleaned["date"] = cleaned["time"].dt.date

    return cleaned


def aggregate_region_daily_sst(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate SST grid-cell points to one row per date and region.

    Outputs:
    - mean_sst_c
    - cell_count
    - min_sst_c
    - max_sst_c
    """
    group_cols = ["date", "region_id", "region_code", "region_name"]

    aggregated = (
        df.groupby(group_cols, dropna=False)
        .agg(
            mean_sst_c=("sst", "mean"),
            cell_count=("sst", "count"),
            min_sst_c=("sst", "min"),
            max_sst_c=("sst", "max"),
        )
        .reset_index()
    )

    # region_id often comes back as float after joins if unmatched rows existed.
    aggregated["region_id"] = aggregated["region_id"].astype("int64")

    return aggregated


def save_output(df: pd.DataFrame, output_path: Path) -> None:
    """Save the aggregated daily regional SST table."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)


def main(input_path: Path, output_path: Path) -> None:
    print(f"Loading joined point data: {input_path}")
    joined_df = load_joined_points(input_path)
    print(f"Loaded {len(joined_df):,} joined rows")

    prepared_df = prepare_for_aggregation(joined_df)
    print(f"Rows after dropping unmatched points: {len(prepared_df):,}")

    aggregated_df = aggregate_region_daily_sst(prepared_df)
    print(f"Created {len(aggregated_df):,} aggregated region-day rows")

    print("Preview:")
    print(aggregated_df.head())

    save_output(aggregated_df, output_path)
    print(f"Saved aggregated output to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Aggregate SST grid-cell points to daily regional SST summaries.",
    )
    parser.add_argument(
        "--input-file",
        default=str(DEFAULT_INPUT_FILE),
        help="Path to the parquet file created by region_join.py",
    )
    parser.add_argument(
        "--output-file",
        default=str(DEFAULT_OUTPUT_FILE),
        help="Path where the aggregated daily regional SST parquet will be saved.",
    )
    args = parser.parse_args()

    main(
        input_path=Path(args.input_file),
        output_path=Path(args.output_file),
    )
