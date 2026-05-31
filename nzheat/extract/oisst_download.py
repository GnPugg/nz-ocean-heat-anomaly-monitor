from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import logging
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LOGGER = logging.getLogger(__name__)

DIRECT_BASE_URL = (
    "https://www.ncei.noaa.gov/data/"
    "sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr"
)
DEFAULT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class OISSTDownloadConfig:
    output_dir: Path
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


class OISSTDownloadError(RuntimeError):
    pass


def ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def build_remote_filename(target_date: date) -> str:
    return f"oisst-avhrr-v02r01.{target_date.strftime('%Y%m%d')}.nc"


def build_direct_file_url(target_date: date) -> str:
    yyyymm = target_date.strftime("%Y%m")
    filename = build_remote_filename(target_date)
    return f"{DIRECT_BASE_URL}/{yyyymm}/{filename}"


def build_output_path(output_dir: Path, target_date: date) -> Path:
    filename = f"oisst_{target_date.isoformat()}.nc"
    return output_dir / filename


def build_session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "nz-ocean-heat-anomaly-monitor/1.0"})
    return session


def download_file(url: str, output_path: Path, timeout_seconds: int) -> Path:
    session = build_session()

    with session.get(url, stream=True, timeout=timeout_seconds) as response:
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
    ensure_output_dir(config.output_dir)
    output_path = build_output_path(config.output_dir, target_date)

    if output_path.exists() and not overwrite:
        LOGGER.info("OISST file already exists, skipping download: %s", output_path)
        return output_path

    url = build_direct_file_url(target_date)

    LOGGER.info("Downloading OISST daily file for %s", target_date.isoformat())
    LOGGER.debug("Direct file URL: %s", url)

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
    if value is None:
        return datetime.utcnow().date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit("Date must be in YYYY-MM-DD format.") from exc
