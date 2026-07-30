from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import argparse
import re

import numpy as np
import pandas as pd
import xarray as xr


DEFAULT_DOMAIN_AUDIT = Path(
    "data/reference/regions/v2_masked_75km/coastal_grid_audit.csv"
)
DEFAULT_RAW_DIR = Path("data/raw/oisst_baseline")
DEFAULT_OUTPUT_DIRECTORY = Path(
    "data/interim/region-design/v2_75km/historical-cell-sst"
)

OUTPUT_COLUMNS = [
    "date",
    "cell_id",
    "longitude",
    "latitude",
    "sst_c",
]

_FILENAME_DATE_PATTERN = re.compile(r"oisst_(\d{4}-\d{2}-\d{2})\.nc$")


@dataclass(frozen=True)
class YearExtractionSummary:
    year: int
    files_processed: int
    cell_count: int
    row_count: int
    first_date: str
    last_date: str
    output_file: str
    status: str


def load_domain_cells(audit_path: Path) -> pd.DataFrame:
    """Load the included OISST cells from a coastal-grid audit CSV."""
    audit = pd.read_csv(audit_path)

    required_columns = {
        "cell_id",
        "longitude",
        "latitude",
        "included_in_coastal_domain",
    }
    missing_columns = sorted(required_columns - set(audit.columns))

    if missing_columns:
        raise ValueError(
            f"Domain audit is missing required columns: {missing_columns}"
        )

    included_mask = (
        audit["included_in_coastal_domain"]
        .fillna(False)
        .astype(str)
        .str.strip()
        .str.lower()
        .eq("true")
    )

    cells = audit.loc[
        included_mask,
        ["cell_id", "longitude", "latitude"],
    ].copy()

    if cells.empty:
        raise ValueError("Domain audit contains no included coastal cells.")

    cells["cell_id"] = cells["cell_id"].astype(str)
    cells["longitude"] = cells["longitude"].astype(float)
    cells["latitude"] = cells["latitude"].astype(float)

    duplicate_ids = cells["cell_id"].duplicated(keep=False)
    if duplicate_ids.any():
        duplicates = sorted(cells.loc[duplicate_ids, "cell_id"].unique())
        raise ValueError(f"Domain audit contains duplicate cell IDs: {duplicates}")

    duplicate_coordinates = cells.duplicated(
        subset=["longitude", "latitude"],
        keep=False,
    )
    if duplicate_coordinates.any():
        duplicates = (
            cells.loc[
                duplicate_coordinates,
                ["longitude", "latitude"],
            ]
            .drop_duplicates()
            .to_dict("records")
        )
        raise ValueError(
            f"Domain audit contains duplicate coordinates: {duplicates}"
        )

    return cells.sort_values("cell_id").reset_index(drop=True)


def _coordinate_name(dataset: xr.Dataset, candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate in dataset.coords:
            return candidate

    raise ValueError(
        "OISST dataset is missing an expected coordinate. "
        f"Tried: {', '.join(candidates)}"
    )


def _date_from_filename(path: Path) -> pd.Timestamp:
    match = _FILENAME_DATE_PATTERN.fullmatch(path.name)

    if match is None:
        raise ValueError(
            f"OISST filename does not match oisst_YYYY-MM-DD.nc: {path.name}"
        )

    return pd.Timestamp(match.group(1)).normalize()


def extract_cell_sst_for_file(
    nc_path: Path,
    domain_cells: pd.DataFrame,
) -> pd.DataFrame:
    """Extract one daily SST value for every selected OISST grid cell."""
    filename_date = _date_from_filename(nc_path)

    try:
        dataset = xr.open_dataset(nc_path, engine="h5netcdf")
    except Exception as exc:
        raise ValueError(f"Unable to open OISST file {nc_path}: {exc}") from exc

    with dataset:
        if "sst" not in dataset.data_vars:
            raise ValueError(f"OISST file has no 'sst' variable: {nc_path}")

        lon_name = _coordinate_name(dataset, ("lon", "longitude"))
        lat_name = _coordinate_name(dataset, ("lat", "latitude"))

        if "time" not in dataset.coords or dataset.sizes.get("time") != 1:
            raise ValueError(
                f"OISST file must contain exactly one time value: {nc_path}"
            )

        dataset_date = pd.Timestamp(dataset["time"].values[0]).normalize()
        if dataset_date != filename_date:
            raise ValueError(
                "OISST dataset date does not match filename: "
                f"{nc_path.name} contains {dataset_date.date()}"
            )

        available_lons = {
            round(float(value), 3)
            for value in np.asarray(dataset[lon_name].values)
        }
        available_lats = {
            round(float(value), 3)
            for value in np.asarray(dataset[lat_name].values)
        }

        missing_cells = domain_cells.loc[
            ~(
                domain_cells["longitude"]
                .round(3)
                .isin(available_lons)
                & domain_cells["latitude"]
                .round(3)
                .isin(available_lats)
            ),
            ["cell_id", "longitude", "latitude"],
        ]

        if not missing_cells.empty:
            examples = missing_cells.head(10).to_dict("records")
            raise ValueError(
                f"{len(missing_cells)} domain coordinates are absent from "
                f"{nc_path.name}. Examples: {examples}"
            )

        lon_selector = xr.DataArray(
            domain_cells["longitude"].to_numpy(dtype=float),
            dims="cell",
        )
        lat_selector = xr.DataArray(
            domain_cells["latitude"].to_numpy(dtype=float),
            dims="cell",
        )

        sst = dataset["sst"].isel(time=0)

        for depth_dimension in ("zlev", "depth"):
            if depth_dimension in sst.dims:
                sst = sst.isel({depth_dimension: 0})

        remaining_dimensions = set(sst.dims) - {lon_name, lat_name}
        if remaining_dimensions:
            raise ValueError(
                "Unexpected dimensions remain after selecting surface SST: "
                f"{sorted(remaining_dimensions)}"
            )

        values = (
            sst.sel(
                {
                    lon_name: lon_selector,
                    lat_name: lat_selector,
                }
            )
            .values
        )

    values = np.asarray(values, dtype=float).reshape(-1)

    if len(values) != len(domain_cells):
        raise RuntimeError(
            f"Expected {len(domain_cells)} SST values from {nc_path.name}, "
            f"received {len(values)}"
        )

    missing_sst = ~np.isfinite(values)
    if missing_sst.any():
        bad_cells = (
            domain_cells.loc[
                missing_sst,
                ["cell_id", "longitude", "latitude"],
            ]
            .head(10)
            .to_dict("records")
        )
        raise ValueError(
            f"{int(missing_sst.sum())} selected cells have missing SST in "
            f"{nc_path.name}. Examples: {bad_cells}"
        )

    result = domain_cells.copy()
    result.insert(0, "date", filename_date)
    result["sst_c"] = values

    return result[OUTPUT_COLUMNS]


def _expected_year_dates(year: int) -> pd.DatetimeIndex:
    """Return every calendar date expected for a complete year."""
    return pd.date_range(
        start=f"{year}-01-01",
        end=f"{year}-12-31",
        freq="D",
    )


def _validate_year_dates(
    dates: pd.Series | pd.Index | list[pd.Timestamp],
    *,
    year: int,
    require_complete_year: bool,
    source_label: str,
) -> pd.DatetimeIndex:
    """Validate unique dates and optionally require a complete calendar year."""
    normalized = pd.DatetimeIndex(pd.to_datetime(dates)).normalize()

    if normalized.empty:
        raise ValueError(f"{source_label} contains no dates.")

    duplicate_dates = normalized[normalized.duplicated()].unique()
    if len(duplicate_dates):
        formatted = [str(value.date()) for value in duplicate_dates]
        raise ValueError(
            f"{source_label} contains duplicate dates: {formatted}"
        )

    wrong_year = normalized[normalized.year != year].unique()
    if len(wrong_year):
        formatted = [str(value.date()) for value in wrong_year]
        raise ValueError(
            f"{source_label} contains dates outside {year}: {formatted}"
        )

    normalized = normalized.sort_values()

    if require_complete_year:
        expected = _expected_year_dates(year)
        missing = expected.difference(normalized)
        unexpected = normalized.difference(expected)

        if len(missing) or len(unexpected):
            missing_preview = [str(value.date()) for value in missing[:10]]
            unexpected_preview = [
                str(value.date()) for value in unexpected[:10]
            ]
            raise ValueError(
                f"{source_label} is not a complete calendar year for {year}. "
                f"Missing dates: {missing_preview}; "
                f"unexpected dates: {unexpected_preview}."
            )

    return normalized


def _validate_yearly_output(
    yearly: pd.DataFrame,
    *,
    year: int,
    domain_cells: pd.DataFrame,
    require_complete_year: bool,
    source_label: str,
) -> pd.DataFrame:
    """Validate one date-cell row for every expected cell and date."""
    required_columns = set(OUTPUT_COLUMNS)
    missing_columns = sorted(required_columns.difference(yearly.columns))
    if missing_columns:
        raise ValueError(
            f"{source_label} is missing required columns: {missing_columns}"
        )

    if yearly.empty:
        raise ValueError(f"{source_label} is empty.")

    validated = yearly.copy()

    try:
        validated["date"] = pd.to_datetime(
            validated["date"],
            errors="raise",
        ).dt.normalize()
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{source_label} contains invalid dates."
        ) from exc

    validated["cell_id"] = validated["cell_id"].astype("string")

    for column in ("longitude", "latitude", "sst_c"):
        try:
            validated[column] = pd.to_numeric(
                validated[column],
                errors="raise",
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{source_label} contains non-numeric values in {column}."
            ) from exc

    missing_value_counts = validated[OUTPUT_COLUMNS].isna().sum()
    missing_value_counts = missing_value_counts[
        missing_value_counts > 0
    ]
    if not missing_value_counts.empty:
        raise ValueError(
            f"{source_label} contains missing required values: "
            f"{missing_value_counts.to_dict()}"
        )

    numeric_values = validated[
        ["longitude", "latitude", "sst_c"]
    ].to_numpy(dtype=float)
    if not np.isfinite(numeric_values).all():
        raise ValueError(
            f"{source_label} contains non-finite coordinates or SST values."
        )

    validated["cell_id"] = validated["cell_id"].astype(str)

    duplicate_count = int(
        validated.duplicated(subset=["date", "cell_id"]).sum()
    )
    if duplicate_count:
        raise ValueError(
            f"{source_label} contains {duplicate_count} duplicate "
            "date-cell rows."
        )

    expected_coordinates = domain_cells[
        ["cell_id", "longitude", "latitude"]
    ].copy()
    expected_coordinates["cell_id"] = (
        expected_coordinates["cell_id"].astype(str)
    )

    expected_cell_ids = set(expected_coordinates["cell_id"])
    actual_cell_ids = set(validated["cell_id"])

    missing_cells = sorted(expected_cell_ids - actual_cell_ids)
    unexpected_cells = sorted(actual_cell_ids - expected_cell_ids)
    if missing_cells or unexpected_cells:
        raise ValueError(
            f"{source_label} does not match the current coastal domain. "
            f"Missing cells: {missing_cells[:10]}; "
            f"unexpected cells: {unexpected_cells[:10]}."
        )

    coordinate_check = validated.merge(
        expected_coordinates.rename(
            columns={
                "longitude": "expected_longitude",
                "latitude": "expected_latitude",
            }
        ),
        on="cell_id",
        validate="many_to_one",
    )

    coordinate_matches = (
        np.isclose(
            coordinate_check["longitude"],
            coordinate_check["expected_longitude"],
            rtol=0.0,
            atol=1e-9,
        )
        & np.isclose(
            coordinate_check["latitude"],
            coordinate_check["expected_latitude"],
            rtol=0.0,
            atol=1e-9,
        )
    )

    if not coordinate_matches.all():
        examples = coordinate_check.loc[
            ~coordinate_matches,
            [
                "cell_id",
                "longitude",
                "latitude",
                "expected_longitude",
                "expected_latitude",
            ],
        ].head(10).to_dict("records")
        raise ValueError(
            f"{source_label} contains coordinates that do not match "
            f"the current coastal domain. Examples: {examples}"
        )

    unique_dates = _validate_year_dates(
        validated["date"].drop_duplicates(),
        year=year,
        require_complete_year=require_complete_year,
        source_label=source_label,
    )

    cells_per_date = validated.groupby("date")["cell_id"].nunique()
    invalid_dates = cells_per_date[
        cells_per_date != len(expected_cell_ids)
    ]
    if not invalid_dates.empty:
        preview = {
            str(date.date()): int(count)
            for date, count in invalid_dates.head(10).items()
        }
        raise ValueError(
            f"{source_label} does not contain exactly "
            f"{len(expected_cell_ids)} cells for every date: {preview}"
        )

    expected_rows = len(unique_dates) * len(expected_cell_ids)
    if len(validated) != expected_rows:
        raise ValueError(
            f"{source_label} contains {len(validated)} rows; "
            f"expected {expected_rows}."
        )

    return validated.sort_values(
        ["date", "cell_id"]
    ).reset_index(drop=True)


def extract_year(
    *,
    year: int,
    raw_dir: Path,
    domain_cells: pd.DataFrame,
    output_directory: Path,
    overwrite: bool = False,
    require_complete_year: bool = True,
) -> YearExtractionSummary:
    """Extract one Parquet file containing all selected cells for one year."""
    output_directory.mkdir(parents=True, exist_ok=True)
    output_file = output_directory / f"cell_daily_sst_{year}.parquet"

    if output_file.exists() and not overwrite:
        existing = pd.read_parquet(output_file)
        existing = _validate_yearly_output(
            existing,
            year=year,
            domain_cells=domain_cells,
            require_complete_year=require_complete_year,
            source_label=f"Existing output {output_file}",
        )

        return YearExtractionSummary(
            year=year,
            files_processed=int(existing["date"].nunique()),
            cell_count=int(existing["cell_id"].nunique()),
            row_count=len(existing),
            first_date=str(existing["date"].min().date()),
            last_date=str(existing["date"].max().date()),
            output_file=str(output_file),
            status="skipped_existing",
        )

    files = sorted(raw_dir.glob(f"oisst_{year}-??-??.nc"))

    if not files:
        raise FileNotFoundError(
            f"No OISST files were found for {year} in {raw_dir}"
        )

    _validate_year_dates(
        [_date_from_filename(path) for path in files],
        year=year,
        require_complete_year=require_complete_year,
        source_label=f"OISST input files for {year}",
    )

    yearly_frames: list[pd.DataFrame] = []

    for index, nc_path in enumerate(files, start=1):
        yearly_frames.append(
            extract_cell_sst_for_file(
                nc_path=nc_path,
                domain_cells=domain_cells,
            )
        )

        if index == 1 or index % 50 == 0 or index == len(files):
            print(f"  {year}: processed {index}/{len(files)} files")

    yearly = pd.concat(yearly_frames, ignore_index=True)
    yearly = _validate_yearly_output(
        yearly,
        year=year,
        domain_cells=domain_cells,
        require_complete_year=require_complete_year,
        source_label=f"Extracted output for {year}",
    )

    temp_file = output_file.with_suffix(".tmp.parquet")
    yearly.to_parquet(temp_file, index=False)
    temp_file.replace(output_file)

    return YearExtractionSummary(
        year=year,
        files_processed=len(files),
        cell_count=len(domain_cells),
        row_count=len(yearly),
        first_date=str(yearly["date"].min().date()),
        last_date=str(yearly["date"].max().date()),
        output_file=str(output_file),
        status="written",
    )


def run_extraction(
    *,
    audit_path: Path,
    raw_dir: Path,
    output_directory: Path,
    start_year: int,
    end_year: int,
    overwrite: bool = False,
) -> pd.DataFrame:
    """Extract yearly cell-level SST files and write a manifest."""
    if end_year < start_year:
        raise ValueError("end_year must be the same as or after start_year")

    domain_cells = load_domain_cells(audit_path)
    print(f"Loaded {len(domain_cells):,} included domain cells")

    summaries: list[YearExtractionSummary] = []

    for year in range(start_year, end_year + 1):
        print(f"\nExtracting historical cell SST for {year}")
        summary = extract_year(
            year=year,
            raw_dir=raw_dir,
            domain_cells=domain_cells,
            output_directory=output_directory,
            overwrite=overwrite,
        )
        summaries.append(summary)
        print(
            f"  {summary.status}: {summary.row_count:,} rows "
            f"from {summary.files_processed} files"
        )

    manifest = pd.DataFrame(asdict(summary) for summary in summaries)
    manifest_path = output_directory / "historical_cell_sst_manifest.csv"
    manifest.to_csv(manifest_path, index=False)

    print(f"\nManifest: {manifest_path}")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Extract daily historical SST for a reproducible set of OISST cells. "
            "Writes one Parquet file per year."
        )
    )
    parser.add_argument(
        "--domain-audit",
        default=str(DEFAULT_DOMAIN_AUDIT),
        help="Coastal-grid audit CSV containing included cell coordinates.",
    )
    parser.add_argument(
        "--raw-dir",
        default=str(DEFAULT_RAW_DIR),
        help="Directory containing daily OISST NetCDF files.",
    )
    parser.add_argument(
        "--output-directory",
        default=str(DEFAULT_OUTPUT_DIRECTORY),
        help="Directory for yearly cell-level SST Parquet files.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=1991,
        help="First baseline year to extract.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2020,
        help="Last baseline year to extract.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing yearly Parquet files.",
    )
    args = parser.parse_args()

    run_extraction(
        audit_path=Path(args.domain_audit),
        raw_dir=Path(args.raw_dir),
        output_directory=Path(args.output_directory),
        start_year=args.start_year,
        end_year=args.end_year,
        overwrite=args.overwrite,
    )
