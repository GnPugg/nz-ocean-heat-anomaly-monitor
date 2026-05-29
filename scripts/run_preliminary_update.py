from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import argparse
import sys

import pandas as pd
import requests

from nzheat.utils.commands import run_command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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

ERDDAP_BASE_URL = "https://www.ncei.noaa.gov/erddap/griddap"
PRELIM_DATASET_ID = "ncdc_oisst_v2_avhrr_prelim_by_time_zlev_lat_lon"

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "oisst_prelim"
REGIONS_FILE = PROJECT_ROOT / "assets" / "regions" / "nz_coastal_regions.geojson"

PRELIM_SST_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_daily_sst_recent_prelim.parquet"
)
PRELIM_ANOMALIES_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_daily_anomalies_recent_prelim.parquet"
)
PRELIM_EVENTS_FILE = (
    PROJECT_ROOT / "data" / "processed" / "heat_events_recent_prelim.parquet"
)

CLIMATOLOGY_FILE = PROJECT_ROOT / "data" / "processed" / "region_climatology.parquet"

FINAL_ANOMALIES_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_daily_anomalies.parquet"
)

PRELIM_EVENT_INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "region_daily_anomalies_event_input_prelim.parquet"
)


@dataclass(frozen=True)
class PrelimDownloadConfig:
    output_dir: Path = RAW_DIR
    min_lon: float = 160.0
    max_lon: float = 180.0
    min_lat: float = -50.0
    max_lat: float = -30.0
    timeout_seconds: int = 120


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Use YYYY-MM-DD."
        ) from exc


def build_date_list(start_date: date, end_date: date) -> list[date]:
    if end_date < start_date:
        raise ValueError("end_date must be the same as or after start_date")

    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)

    return dates


def build_prelim_url(target_date: date, config: PrelimDownloadConfig) -> str:
    timestamp = f"{target_date.isoformat()}T00:00:00Z"

    query = (
        f"sst"
        f"[({timestamp})]"
        f"[(0.0)]"
        f"[({config.min_lat}):1:({config.max_lat})]"
        f"[({config.min_lon}):1:({config.max_lon})]"
    )

    return f"{ERDDAP_BASE_URL}/{PRELIM_DATASET_ID}.nc?{query}"


def build_output_path(target_date: date, config: PrelimDownloadConfig) -> Path:
    filename = f"oisst_prelim_nz_subset_{target_date.isoformat()}.nc"
    return config.output_dir / filename


def download_prelim_for_date(
    target_date: date,
    config: PrelimDownloadConfig,
    *,
    overwrite: bool = False,
) -> Path | None:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = build_output_path(target_date, config)

    if output_path.exists() and not overwrite:
        print(f"Using existing preliminary file: {output_path}")
        return output_path

    url = build_prelim_url(target_date, config)

    try:
        print(f"Downloading preliminary OISST for {target_date}")
        with requests.get(url, stream=True, timeout=config.timeout_seconds) as response:
            if response.status_code == 404:
                print(f"Preliminary OISST not available for {target_date}; skipping.")
                return None

            response.raise_for_status()

            with output_path.open("wb") as file_handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file_handle.write(chunk)

        return output_path

    except requests.RequestException as exc:
        print(f"Failed to download preliminary OISST for {target_date}: {exc}")
        return None


def process_single_prelim_date(
    target_date: date,
    regions_gdf,
    config: PrelimDownloadConfig,
    *,
    overwrite_download: bool = False,
) -> pd.DataFrame | None:
    nc_path = download_prelim_for_date(
        target_date=target_date,
        config=config,
        overwrite=overwrite_download,
    )

    if nc_path is None:
        return None

    sst_df = load_oisst_as_dataframe(nc_path)
    points_gdf = make_points_geodataframe(sst_df)
    joined_gdf = spatially_assign_regions(points_gdf, regions_gdf)
    joined_df = keep_useful_columns(joined_gdf)

    prepared_df = prepare_for_aggregation(joined_df)
    aggregated_df = aggregate_region_daily_sst(prepared_df)

    aggregated_df["data_product"] = "preliminary"
    aggregated_df["is_provisional"] = True

    return aggregated_df


def save_prelim_sst(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "region_id"]).reset_index(drop=True)

    df.to_parquet(output_path, index=False)

    print(f"Saved preliminary SST rows: {len(df):,}")
    print(f"Output: {output_path}")
    print("Date range:", df["date"].min().date(), "to", df["date"].max().date())


def build_prelim_event_input(
    final_anomalies_path: Path,
    prelim_anomalies_path: Path,
    output_path: Path,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Build the anomaly table used for preliminary event detection.

    It combines:
    - final historical anomalies before the preliminary period
    - recent preliminary anomalies during the preliminary period

    This allows events that started before the preliminary window to continue
    correctly into the preliminary period.
    """
    prelim_df = pd.read_parquet(prelim_anomalies_path).copy()
    prelim_df["date"] = pd.to_datetime(prelim_df["date"])

    prelim_start = prelim_df["date"].min()
    prelim_end = prelim_df["date"].max()

    if final_anomalies_path.exists():
        final_df = pd.read_parquet(final_anomalies_path).copy()
        final_df["date"] = pd.to_datetime(final_df["date"])

        final_df = final_df.loc[final_df["date"] < prelim_start].copy()

        combined_df = pd.concat([final_df, prelim_df], ignore_index=True)
    else:
        print(f"WARNING: final anomaly file not found: {final_anomalies_path}")
        print("Using preliminary anomalies only for event detection.")
        combined_df = prelim_df

    combined_df = (
        combined_df.drop_duplicates(subset=["date", "region_id"], keep="last")
        .sort_values(["region_id", "date"])
        .reset_index(drop=True)
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined_df.to_parquet(output_path, index=False)

    print(f"Saved preliminary event input rows: {len(combined_df):,}")
    print(
        f"Event input date range: {combined_df['date'].min().date()} to {combined_df['date'].max().date()}"
    )

    return prelim_start, prelim_end


def add_prelim_metadata_to_parquet(path: Path) -> None:
    df = pd.read_parquet(path)
    df["data_product"] = "preliminary"
    df["is_provisional"] = True
    df.to_parquet(path, index=False)


def main(
    start_date: date,
    end_date: date,
    *,
    overwrite_download: bool = False,
) -> None:
    print("===============================")
    print("Running preliminary OISST update")
    print("===============================")
    print(f"Requested date range: {start_date} to {end_date}")

    if not CLIMATOLOGY_FILE.exists():
        raise FileNotFoundError(
            f"Climatology file not found: {CLIMATOLOGY_FILE}. "
            "Build the 1991–2020 climatology first."
        )

    regions_gdf = load_regions(REGIONS_FILE)
    config = PrelimDownloadConfig()

    all_results: list[pd.DataFrame] = []

    for target_date in build_date_list(start_date, end_date):
        print(f"\n--- {target_date} ---")
        daily_df = process_single_prelim_date(
            target_date=target_date,
            regions_gdf=regions_gdf,
            config=config,
            overwrite_download=overwrite_download,
        )

        if daily_df is None:
            continue

        print(f"Created {len(daily_df):,} preliminary region-day rows")
        all_results.append(daily_df)

    if not all_results:
        print("No preliminary dates were available in this date range.")
        return

    prelim_sst_df = pd.concat(all_results, ignore_index=True)
    prelim_sst_df = prelim_sst_df.drop_duplicates(
        subset=["date", "region_id"],
        keep="last",
    )

    save_prelim_sst(prelim_sst_df, PRELIM_SST_FILE)

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.analytics.anomalies",
            "--history-file",
            str(PRELIM_SST_FILE),
            "--climatology-file",
            str(CLIMATOLOGY_FILE),
            "--output-file",
            str(PRELIM_ANOMALIES_FILE),
        ]
    )

    add_prelim_metadata_to_parquet(PRELIM_ANOMALIES_FILE)

    prelim_start, prelim_end = build_prelim_event_input(
        final_anomalies_path=FINAL_ANOMALIES_FILE,
        prelim_anomalies_path=PRELIM_ANOMALIES_FILE,
        output_path=PRELIM_EVENT_INPUT_FILE,
    )

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.analytics.events",
            "--input-file",
            str(PRELIM_EVENT_INPUT_FILE),
            "--output-file",
            str(PRELIM_EVENTS_FILE),
        ]
    )

    if PRELIM_EVENTS_FILE.exists():
        add_prelim_metadata_to_parquet(PRELIM_EVENTS_FILE)

    print("\nPreliminary update complete.")
    print(f"SST:       {PRELIM_SST_FILE}")
    print(f"Anomalies: {PRELIM_ANOMALIES_FILE}")
    print(f"Events:    {PRELIM_EVENTS_FILE}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download recent preliminary OISST and calculate provisional anomalies/events.",
    )

    parser.add_argument(
        "--start-date",
        type=parse_iso_date,
        help="Start date in YYYY-MM-DD format. If omitted, uses today - days-back.",
    )
    parser.add_argument(
        "--end-date",
        type=parse_iso_date,
        help="End date in YYYY-MM-DD format. If omitted, uses today - end-lag-days.",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=21,
        help="How many days back to request when start-date is omitted.",
    )
    parser.add_argument(
        "--end-lag-days",
        type=int,
        default=1,
        help="How many days before today to use as the default end date.",
    )
    parser.add_argument(
        "--overwrite-download",
        action="store_true",
        help="Re-download preliminary NetCDF files even if they already exist.",
    )

    args = parser.parse_args()

    today = datetime.utcnow().date()

    end_date = args.end_date or (today - timedelta(days=args.end_lag_days))
    start_date = args.start_date or (today - timedelta(days=args.days_back))

    main(
        start_date=start_date,
        end_date=end_date,
        overwrite_download=args.overwrite_download,
    )
