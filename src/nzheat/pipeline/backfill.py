from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import argparse

import pandas as pd

from nzheat.extract.oisst_download import (
    OISSTDownloadConfig,
    download_oisst_subset_for_date,
)
from nzheat.transform.region_join import (
    keep_useful_columns,
    load_oisst_as_dataframe,
    load_regions,
    make_points_geodataframe,
    spatially_assign_regions,
)
from nzheat.transform.region_aggregate import (
    aggregate_region_daily_sst,
    prepare_for_aggregation,
)

DEFAULT_RAW_DIR = Path("data/raw/oisst")
DEFAULT_REGIONS_FILE = Path("assets/regions/nz_coastal_regions.geojson")
DEFAULT_OUTPUT_FILE = Path("data/processed/region_daily_sst_history.parquet")


def build_date_list(start_date: date, end_date: date) -> list[date]:
    """Return a list of dates from start_date to end_date, inclusive."""
    if end_date < start_date:
        raise ValueError("end_date must be the same as or after start_date")

    dates: list[date] = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def process_single_date(
    target_date: date,
    regions_gdf,
    download_config: OISSTDownloadConfig,
    *,
    overwrite_download: bool = False,
) -> pd.DataFrame:
    """
    Run the single-day pipeline for one date and return aggregated regional SST.

    Steps:
    1. download the OISST NZ subset
    2. flatten SST to a dataframe
    3. convert points to a GeoDataFrame
    4. spatially join points to regions
    5. aggregate to one row per region-day
    """
    nc_path = download_oisst_subset_for_date(
        target_date=target_date,
        config=download_config,
        overwrite=overwrite_download,
    )

    sst_df = load_oisst_as_dataframe(nc_path)
    points_gdf = make_points_geodataframe(sst_df)
    joined_gdf = spatially_assign_regions(points_gdf, regions_gdf)
    joined_df = keep_useful_columns(joined_gdf)

    prepared_df = prepare_for_aggregation(joined_df)
    aggregated_df = aggregate_region_daily_sst(prepared_df)

    return aggregated_df


def run_backfill(
    start_date: date,
    end_date: date,
    regions_path: Path,
    raw_dir: Path,
    output_path: Path,
    *,
    overwrite_download: bool = False,
    append: bool = False,
) -> pd.DataFrame:
    """Run a multi-day backfill and save or append regional SST history."""
    dates = build_date_list(start_date, end_date)
    regions_gdf = load_regions(regions_path)

    download_config = OISSTDownloadConfig(output_dir=raw_dir)
    all_results: list[pd.DataFrame] = []

    print(f"Processing {len(dates)} day(s) from {start_date} to {end_date}")
    print(f"Using regions file: {regions_path}")

    for target_date in dates:
        print(f"\n--- {target_date.isoformat()} ---")
        try:
            daily_df = process_single_date(
                target_date=target_date,
                regions_gdf=regions_gdf,
                download_config=download_config,
                overwrite_download=overwrite_download,
            )
            print(f"Created {len(daily_df):,} region-day rows")
            all_results.append(daily_df)
        except Exception as exc:
            print(f"Failed for {target_date.isoformat()}: {exc}")

    if not all_results:
        raise RuntimeError("No dates were processed successfully.")

    new_df = pd.concat(all_results, ignore_index=True)
    new_df["date"] = pd.to_datetime(new_df["date"]).dt.date

    if append and output_path.exists():
        print(f"\nAppend mode enabled. Reading existing history: {output_path}")

        existing_df = pd.read_parquet(output_path)
        existing_df["date"] = pd.to_datetime(existing_df["date"]).dt.date

        history_df = pd.concat([existing_df, new_df], ignore_index=True)

        history_df = (
            history_df.drop_duplicates(subset=["date", "region_id"], keep="last")
            .sort_values(["date", "region_id"])
            .reset_index(drop=True)
        )

    else:
        if append:
            print("\nAppend mode enabled, but no existing history file was found.")
            print("Creating a new history file.")

        history_df = new_df.sort_values(["date", "region_id"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    history_df.to_parquet(output_path, index=False)

    print("\nBackfill complete.")
    print(f"Saved {len(history_df):,} total rows to: {output_path}")
    print(f"Date range: {history_df['date'].min()} to {history_df['date'].max()}")
    print("Preview:")
    print(history_df.tail())

    return history_df


def parse_iso_date(value: str) -> date:
    """Parse a CLI date in YYYY-MM-DD format."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Use YYYY-MM-DD format."
        ) from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill daily regional SST summaries across a date range.",
    )
    parser.add_argument(
        "--start-date",
        required=True,
        type=parse_iso_date,
        help="Start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        type=parse_iso_date,
        help="End date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--regions-file",
        default=str(DEFAULT_REGIONS_FILE),
        help="Path to the NZ coastal regions GeoJSON.",
    )
    parser.add_argument(
        "--raw-dir",
        default=str(DEFAULT_RAW_DIR),
        help="Directory where downloaded OISST subsets are stored.",
    )
    parser.add_argument(
        "--output-file",
        default=str(DEFAULT_OUTPUT_FILE),
        help="Path where the combined history parquet will be saved.",
    )
    parser.add_argument(
        "--overwrite-download",
        action="store_true",
        help="Re-download files even if they already exist locally.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append new dates to the existing history parquet instead of overwriting it.",
    )
    args = parser.parse_args()

    run_backfill(
        start_date=args.start_date,
        end_date=args.end_date,
        regions_path=Path(args.regions_file),
        raw_dir=Path(args.raw_dir),
        output_path=Path(args.output_file),
        overwrite_download=args.overwrite_download,
        append=args.append,
    )
