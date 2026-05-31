from __future__ import annotations

from datetime import date, datetime, timedelta
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

REGION_DAILY_SST_COLUMNS = [
    "date",
    "region_id",
    "region_code",
    "region_name",
    "mean_sst_c",
    "cell_count",
    "min_sst_c",
    "max_sst_c",
]

KEY_COLUMNS = ["date", "region_id"]


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


def keep_region_daily_sst_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the expected columns for the regional daily SST history file."""
    missing_cols = [col for col in REGION_DAILY_SST_COLUMNS if col not in df.columns]

    if missing_cols:
        raise ValueError(f"Missing required SST history columns: {missing_cols}")

    cleaned_df = df[REGION_DAILY_SST_COLUMNS].copy()
    cleaned_df["date"] = pd.to_datetime(cleaned_df["date"]).dt.date

    return cleaned_df


def backup_existing_output(output_path: Path) -> Path | None:
    """Create a timestamped backup before writing a changed history file."""
    if not output_path.exists():
        return None

    backup_dir = output_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = (
        backup_dir / f"{output_path.stem}_backup_{timestamp}{output_path.suffix}"
    )

    existing_df = pd.read_parquet(output_path)
    existing_df.to_parquet(backup_path, index=False)

    return backup_path


def find_missing_rows_only(
    new_df: pd.DataFrame,
    existing_df: pd.DataFrame,
) -> tuple[pd.DataFrame, int]:
    """
    Return only rows from new_df whose date-region key is not already present.

    Existing rows are never replaced.
    """
    existing_keys = pd.MultiIndex.from_frame(existing_df[KEY_COLUMNS])
    new_keys = pd.MultiIndex.from_frame(new_df[KEY_COLUMNS])

    missing_mask = ~new_keys.isin(existing_keys)
    skipped_existing_rows = int((~missing_mask).sum())

    missing_df = new_df.loc[missing_mask].copy()

    return missing_df, skipped_existing_rows


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
    dry_run: bool = False,
) -> pd.DataFrame:
    """
    Run a multi-day backfill.

    Safe behaviour:
    - If the output history file exists, only missing date-region rows are added.
    - Existing date-region rows are never replaced.
    - The full output file is never overwritten with only the requested range.
    - A backup is created before writing.
    """
    dates = build_date_list(start_date, end_date)
    regions_gdf = load_regions(regions_path)

    download_config = OISSTDownloadConfig(output_dir=raw_dir)
    all_results: list[pd.DataFrame] = []

    print(f"Processing {len(dates)} day(s) from {start_date} to {end_date}")
    print(f"Using regions file: {regions_path}")
    print("Mode: safe backfill. Existing rows will not be modified.")

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
    new_df = keep_region_daily_sst_columns(new_df)

    new_df = (
        new_df.sort_values(["date", "region_id"])
        .drop_duplicates(subset=KEY_COLUMNS, keep="last")
        .reset_index(drop=True)
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        print(f"\nReading existing history: {output_path}")

        existing_df = pd.read_parquet(output_path)
        existing_df = keep_region_daily_sst_columns(existing_df)

        missing_df, skipped_existing_rows = find_missing_rows_only(
            new_df=new_df,
            existing_df=existing_df,
        )

        print(f"Rows generated by backfill: {len(new_df):,}")
        print(f"Rows already present and skipped: {skipped_existing_rows:,}")
        print(f"New missing rows to add: {len(missing_df):,}")

        if missing_df.empty:
            print("\nNo missing rows to add.")
            print("Existing history file was not changed.")

            history_df = existing_df.sort_values(["date", "region_id"]).reset_index(
                drop=True
            )

            return history_df

        history_df = pd.concat([existing_df, missing_df], ignore_index=True)

        history_df = (
            history_df.sort_values(["date", "region_id"])
            .drop_duplicates(subset=KEY_COLUMNS, keep="first")
            .reset_index(drop=True)
        )

    else:
        print("\nNo existing history file was found.")
        print("Creating a new history file from the requested backfill range.")

        history_df = new_df.sort_values(["date", "region_id"]).reset_index(drop=True)

    duplicate_count = history_df.duplicated(KEY_COLUMNS).sum()

    if duplicate_count > 0:
        raise RuntimeError(
            f"Backfill would create {duplicate_count} duplicate date-region rows."
        )

    if dry_run:
        print("\nDry run enabled.")
        print("No output file was written.")
    else:
        backup_path = backup_existing_output(output_path)

        if backup_path is not None:
            print(f"\nBackup saved before writing output: {backup_path}")

        history_df.to_parquet(output_path, index=False)

    print("\nBackfill complete.")
    print(f"Rows in final history table: {len(history_df):,}")
    print(f"Date range: {history_df['date'].min()} to {history_df['date'].max()}")
    print(f"Duplicate date-region rows: {history_df.duplicated(KEY_COLUMNS).sum()}")

    if not dry_run:
        print(f"Saved output to: {output_path}")

    print("\nPreview:")
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
        description=(
            "Safely backfill missing daily regional SST summaries. "
            "Existing date-region rows are never replaced."
        ),
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
        help="Path where the regional SST history parquet is stored.",
    )
    parser.add_argument(
        "--overwrite-download",
        action="store_true",
        help="Re-download raw OISST files even if they already exist locally.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process the dates and report what would change, but do not write the output parquet.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help=(
            "Deprecated: safe append-only backfill is now always used. "
            "This flag is kept so older commands still work."
        ),
    )

    args = parser.parse_args()

    run_backfill(
        start_date=args.start_date,
        end_date=args.end_date,
        regions_path=Path(args.regions_file),
        raw_dir=Path(args.raw_dir),
        output_path=Path(args.output_file),
        overwrite_download=args.overwrite_download,
        dry_run=args.dry_run,
    )
