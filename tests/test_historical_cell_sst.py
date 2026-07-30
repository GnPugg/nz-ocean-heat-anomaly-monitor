from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from nzheat.regions.historical_cell_sst import (
    extract_cell_sst_for_file,
    extract_year,
    load_domain_cells,
)


def _write_domain_audit(path: Path) -> None:
    pd.DataFrame(
        {
            "cell_id": ["keep-a", "exclude", "keep-b"],
            "longitude": [170.125, 170.375, 170.625],
            "latitude": [-40.125, -40.375, -40.625],
            "included_in_coastal_domain": [True, False, True],
        }
    ).to_csv(path, index=False)


def _write_daily_oisst(
    path: Path,
    *,
    date: str,
    values: np.ndarray | None = None,
) -> None:
    if values is None:
        values = np.array(
            [
                [10.0, 11.0, 12.0],
                [13.0, 14.0, 15.0],
                [16.0, 17.0, 18.0],
            ],
            dtype=np.float32,
        )

    dataset = xr.Dataset(
        data_vars={
            "sst": (
                ("time", "zlev", "lat", "lon"),
                values[np.newaxis, np.newaxis, :, :],
            )
        },
        coords={
            "time": [pd.Timestamp(date)],
            "zlev": [0.0],
            "lat": [-40.625, -40.375, -40.125],
            "lon": [170.125, 170.375, 170.625],
        },
    )
    dataset.to_netcdf(path, engine="h5netcdf")


def test_load_domain_cells_keeps_only_included_rows(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.csv"
    _write_domain_audit(audit_path)

    result = load_domain_cells(audit_path)

    assert result["cell_id"].tolist() == ["keep-a", "keep-b"]
    assert result["longitude"].tolist() == [170.125, 170.625]
    assert result["latitude"].tolist() == [-40.125, -40.625]


def test_extract_cell_sst_for_file_selects_exact_cells(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.csv"
    nc_path = tmp_path / "oisst_2001-02-03.nc"

    _write_domain_audit(audit_path)
    _write_daily_oisst(nc_path, date="2001-02-03")

    domain = load_domain_cells(audit_path)
    result = extract_cell_sst_for_file(nc_path, domain)

    assert result["cell_id"].tolist() == ["keep-a", "keep-b"]
    assert result["date"].nunique() == 1
    assert result["date"].iloc[0] == pd.Timestamp("2001-02-03")
    assert result["sst_c"].tolist() == [16.0, 12.0]


def test_extract_cell_sst_for_file_rejects_missing_sst(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.csv"
    nc_path = tmp_path / "oisst_2001-02-03.nc"

    _write_domain_audit(audit_path)

    values = np.array(
        [
            [10.0, 11.0, np.nan],
            [13.0, 14.0, 15.0],
            [np.nan, 17.0, 18.0],
        ],
        dtype=np.float32,
    )
    _write_daily_oisst(
        nc_path,
        date="2001-02-03",
        values=values,
    )

    domain = load_domain_cells(audit_path)

    with pytest.raises(ValueError, match="selected cells have missing SST"):
        extract_cell_sst_for_file(nc_path, domain)


def test_extract_year_writes_sorted_parquet(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.csv"
    raw_dir = tmp_path / "raw"
    output_directory = tmp_path / "output"
    raw_dir.mkdir()

    _write_domain_audit(audit_path)
    _write_daily_oisst(
        raw_dir / "oisst_2001-01-02.nc",
        date="2001-01-02",
    )
    _write_daily_oisst(
        raw_dir / "oisst_2001-01-01.nc",
        date="2001-01-01",
    )

    domain = load_domain_cells(audit_path)

    summary = extract_year(
        year=2001,
        raw_dir=raw_dir,
        domain_cells=domain,
        output_directory=output_directory,
        require_complete_year=False,
    )

    output_file = output_directory / "cell_daily_sst_2001.parquet"
    result = pd.read_parquet(output_file)

    assert summary.files_processed == 2
    assert summary.cell_count == 2
    assert summary.row_count == 4
    assert summary.status == "written"
    assert result["date"].tolist() == [
        pd.Timestamp("2001-01-01"),
        pd.Timestamp("2001-01-01"),
        pd.Timestamp("2001-01-02"),
        pd.Timestamp("2001-01-02"),
    ]
    assert result["cell_id"].tolist() == [
        "keep-a",
        "keep-b",
        "keep-a",
        "keep-b",
    ]



def test_extract_year_requires_complete_calendar_year_by_default(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.csv"
    raw_dir = tmp_path / "raw"
    output_directory = tmp_path / "output"
    raw_dir.mkdir()

    _write_domain_audit(audit_path)
    _write_daily_oisst(
        raw_dir / "oisst_2001-01-01.nc",
        date="2001-01-01",
    )
    _write_daily_oisst(
        raw_dir / "oisst_2001-01-02.nc",
        date="2001-01-02",
    )

    domain = load_domain_cells(audit_path)

    with pytest.raises(ValueError, match="not a complete calendar year"):
        extract_year(
            year=2001,
            raw_dir=raw_dir,
            domain_cells=domain,
            output_directory=output_directory,
        )


def test_extract_year_rejects_invalid_existing_output(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.csv"
    raw_dir = tmp_path / "raw"
    output_directory = tmp_path / "output"
    raw_dir.mkdir()
    output_directory.mkdir()

    _write_domain_audit(audit_path)
    domain = load_domain_cells(audit_path)

    existing = pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2001-01-01"),
                pd.Timestamp("2001-01-01"),
                pd.Timestamp("2001-01-02"),
            ],
            "cell_id": ["keep-a", "keep-b", "keep-a"],
            "longitude": [170.125, 170.625, 170.125],
            "latitude": [-40.125, -40.625, -40.125],
            "sst_c": [15.0, 16.0, 15.5],
        }
    )
    existing.to_parquet(
        output_directory / "cell_daily_sst_2001.parquet",
        index=False,
    )

    with pytest.raises(
        ValueError,
        match="does not contain exactly 2 cells for every date",
    ):
        extract_year(
            year=2001,
            raw_dir=raw_dir,
            domain_cells=domain,
            output_directory=output_directory,
            require_complete_year=False,
        )

def test_extract_year_rejects_existing_output_missing_sst(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.csv"
    raw_dir = tmp_path / "raw"
    output_directory = tmp_path / "output"
    raw_dir.mkdir()
    output_directory.mkdir()

    _write_domain_audit(audit_path)
    domain = load_domain_cells(audit_path)

    existing = pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2001-01-01"),
                pd.Timestamp("2001-01-01"),
            ],
            "cell_id": ["keep-a", "keep-b"],
            "longitude": [170.125, 170.625],
            "latitude": [-40.125, -40.625],
        }
    )
    existing.to_parquet(
        output_directory / "cell_daily_sst_2001.parquet",
        index=False,
    )

    with pytest.raises(
        ValueError,
        match="missing required columns.*sst_c",
    ):
        extract_year(
            year=2001,
            raw_dir=raw_dir,
            domain_cells=domain,
            output_directory=output_directory,
            require_complete_year=False,
        )


def test_extract_year_rejects_existing_coordinate_mismatch(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit.csv"
    raw_dir = tmp_path / "raw"
    output_directory = tmp_path / "output"
    raw_dir.mkdir()
    output_directory.mkdir()

    _write_domain_audit(audit_path)
    domain = load_domain_cells(audit_path)

    existing = pd.DataFrame(
        {
            "date": [
                pd.Timestamp("2001-01-01"),
                pd.Timestamp("2001-01-01"),
            ],
            "cell_id": ["keep-a", "keep-b"],
            "longitude": [170.125, 171.625],
            "latitude": [-40.125, -40.625],
            "sst_c": [15.0, 16.0],
        }
    )
    existing.to_parquet(
        output_directory / "cell_daily_sst_2001.parquet",
        index=False,
    )

    with pytest.raises(
        ValueError,
        match="coordinates that do not match",
    ):
        extract_year(
            year=2001,
            raw_dir=raw_dir,
            domain_cells=domain,
            output_directory=output_directory,
            require_complete_year=False,
        )
