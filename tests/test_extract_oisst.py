from datetime import date
from pathlib import Path

import pytest

from nzheat.extract import oisst_download
from nzheat.extract.oisst_download import (
    OISSTDownloadConfig,
    build_direct_file_url,
    build_output_path,
    build_remote_filename,
    download_oisst_subset_for_date,
    ensure_output_dir,
    parse_cli_date,
)


def test_build_remote_filename():
    target_date = date(2026, 3, 1)

    result = build_remote_filename(target_date)

    assert result == "oisst-avhrr-v02r01.20260301.nc"


def test_build_direct_file_url():
    target_date = date(2026, 3, 1)

    result = build_direct_file_url(target_date)

    assert result == (
        "https://www.ncei.noaa.gov/data/"
        "sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr/"
        "202603/oisst-avhrr-v02r01.20260301.nc"
    )


def test_build_output_path_uses_project_filename_format(tmp_path):
    target_date = date(2026, 3, 1)

    result = build_output_path(tmp_path, target_date)

    assert result == tmp_path / "oisst_2026-03-01.nc"


def test_ensure_output_dir_creates_nested_folder(tmp_path):
    output_dir = tmp_path / "data" / "raw" / "oisst"

    ensure_output_dir(output_dir)

    assert output_dir.exists()
    assert output_dir.is_dir()


def test_parse_cli_date_accepts_iso_date():
    result = parse_cli_date("2026-03-01")

    assert result == date(2026, 3, 1)


def test_parse_cli_date_rejects_non_iso_date():
    with pytest.raises(SystemExit):
        parse_cli_date("01-03-2026")


def test_existing_file_is_skipped_when_overwrite_is_false(tmp_path, monkeypatch):
    target_date = date(2026, 3, 1)
    existing_file = tmp_path / "oisst_2026-03-01.nc"
    existing_file.write_bytes(b"existing file")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("download_file should not be called for existing files")

    monkeypatch.setattr(oisst_download, "download_file", fail_if_called)

    config = OISSTDownloadConfig(output_dir=tmp_path)

    result = download_oisst_subset_for_date(
        target_date,
        config,
        overwrite=False,
    )

    assert result == existing_file
    assert existing_file.read_bytes() == b"existing file"


def test_missing_file_calls_download_file(tmp_path, monkeypatch):
    target_date = date(2026, 3, 1)
    calls = {}

    def fake_download_file(url: str, output_path: Path, timeout_seconds: int) -> Path:
        calls["url"] = url
        calls["output_path"] = output_path
        calls["timeout_seconds"] = timeout_seconds

        output_path.write_bytes(b"fake netcdf content")
        return output_path

    monkeypatch.setattr(oisst_download, "download_file", fake_download_file)

    config = OISSTDownloadConfig(output_dir=tmp_path, timeout_seconds=10)

    result = download_oisst_subset_for_date(
        target_date,
        config,
        overwrite=False,
    )

    expected_output = tmp_path / "oisst_2026-03-01.nc"

    assert result == expected_output
    assert expected_output.exists()
    assert expected_output.read_bytes() == b"fake netcdf content"

    assert calls["url"].endswith("/202603/oisst-avhrr-v02r01.20260301.nc")
    assert calls["output_path"] == expected_output
    assert calls["timeout_seconds"] == 10
