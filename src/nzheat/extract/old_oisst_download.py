from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import logging
from typing import Optional

import requests


LOGGER = logging.getLogger(__name__)

# NOAA ERDDAP dataset info:
# https://www.ncei.noaa.gov/erddap/griddap/ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon.html
ERDDAP_BASE_URL = "https://www.ncei.noaa.gov/erddap/griddap"
DATASET_ID = "ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon"
DEFAULT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class OISSTDownloadConfig:
    """Configuration for downloading NOAA OISST subsets from ERDDAP."""

    output_dir: Path
    min_lon: float = 160.0
    max_lon: float = 180.0
    min_lat: float = -50.0
    max_lat: float = -30.0
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


class OISSTDownloadError(RuntimeError):
    """Raised when a NOAA OISST file cannot be downloaded."""


def ensure_output_dir(path: Path) -> None:
    """Create the output directory if it does not already exist."""
    path.mkdir(parents=True, exist_ok=True)


def format_erddap_timestamp(target_date: date) -> str:
    """Format a Python date for ERDDAP constraint syntax."""
    return f"{target_date.isoformat()}T00:00:00Z"


def build_oisst_subset_url(
    target_date: date,
    min_lon: float,
    max_lon: float,
    min_lat: float,
    max_lat: float,
) -> str:
    """
    Build an ERDDAP URL that downloads a NetCDF subset for one date.

    Notes
    -----
    - NOAA ERDDAP exposes OISST longitude in degrees east from 0.125 to 359.875.
    - This MVP request downloads only the `sst` variable for one date and the single
      surface depth level.
    - The resulting file is a small NZ-area subset, not the full global grid.
    """
    timestamp = format_erddap_timestamp(target_date)
    query = (
        f"sst"
        f"[({timestamp})]"
        f"[(0.0)]"
        f"[({min_lat}):1:({max_lat})]"
        f"[({min_lon}):1:({max_lon})]"
    )
    return f"{ERDDAP_BASE_URL}/{DATASET_ID}.nc?{query}"


def build_output_path(output_dir: Path, target_date: date) -> Path:
    """Return a consistent file name for the downloaded NZ subset."""
    filename = f"oisst_nz_subset_{target_date.isoformat()}.nc"
    return output_dir / filename


def download_file(url: str, output_path: Path, timeout_seconds: int) -> Path:
    """Download a remote file to disk using streamed requests."""
    with requests.get(url, stream=True, timeout=timeout_seconds) as response:
        response.raise_for_status()
        with output_path.open("wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file_handle.write(chunk)
    return output_path


def download_oisst_subset_for_date(
    target_date: date,
    config: OISSTDownloadConfig,
    *,
    overwrite: bool = False,
) -> Path:
    """
    Download a NOAA OISST NetCDF subset for one date and save it locally.

    Parameters
    ----------
    target_date
        The UTC date to request from OISST.
    config
        Download configuration, including output directory and NZ bounding box.
    overwrite
        If False, return the existing file when present.

    Returns
    -------
    Path
        Path to the local NetCDF file.
    """
    ensure_output_dir(config.output_dir)
    output_path = build_output_path(config.output_dir, target_date)

    if output_path.exists() and not overwrite:
        LOGGER.info("OISST file already exists, skipping download: %s", output_path)
        return output_path

    url = build_oisst_subset_url(
        target_date=target_date,
        min_lon=config.min_lon,
        max_lon=config.max_lon,
        min_lat=config.min_lat,
        max_lat=config.max_lat,
    )

    LOGGER.info("Downloading OISST subset for %s", target_date.isoformat())
    LOGGER.debug("ERDDAP URL: %s", url)

    try:
        return download_file(
            url=url,
            output_path=output_path,
            timeout_seconds=config.timeout_seconds,
        )
    except requests.HTTPError as exc:
        raise OISSTDownloadError(
            f"HTTP error while downloading OISST for {target_date.isoformat()}: {exc}"
        ) from exc
    except requests.RequestException as exc:
        raise OISSTDownloadError(
            f"Network error while downloading OISST for {target_date.isoformat()}: {exc}"
        ) from exc


def parse_cli_date(value: Optional[str]) -> date:
    """Parse an ISO date string from the CLI, defaulting to today if omitted."""
    if value is None:
        return datetime.utcnow().date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit("Date must be in YYYY-MM-DD format.") from exc


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Download a NOAA OISST NetCDF subset for New Zealand.",
    )
    parser.add_argument(
        "--date",
        dest="target_date",
        help="Date to download in YYYY-MM-DD format. Defaults to today (UTC).",
    )
    parser.add_argument(
        "--output-dir",
        default="data/raw/oisst",
        help="Directory where downloaded NetCDF files will be saved.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Re-download the file even if it already exists.",
    )
    args = parser.parse_args()

    config = OISSTDownloadConfig(output_dir=Path(args.output_dir))
    target_date = parse_cli_date(args.target_date)
    saved_path = download_oisst_subset_for_date(
        target_date=target_date,
        config=config,
        overwrite=args.overwrite,
    )
    print(saved_path)
