from __future__ import annotations

from pathlib import Path
import argparse

import numpy as np
import pandas as pd
from scipy.stats import linregress


DEFAULT_INPUT_DIRECTORY = Path(
    "data/interim/region-design/v2_75km/historical-cell-sst"
)

DEFAULT_OUTPUT_FILE = Path(
    "data/interim/region-design/v2_75km/"
    "cell-warming-trends-1991-2020.parquet"
)

DEFAULT_START_YEAR = 1991
DEFAULT_END_YEAR = 2020

SOURCE_COLUMNS = [
    "date",
    "cell_id",
    "longitude",
    "latitude",
    "sst_c",
]

ANNUAL_COLUMNS = {
    "cell_id",
    "longitude",
    "latitude",
    "year",
    "annual_mean_sst_c",
    "observation_count",
}


def find_yearly_files(
    input_directory: Path,
    start_year: int,
    end_year: int,
) -> list[Path]:
    if start_year > end_year:
        raise ValueError(
            "start_year must be less than or equal to end_year."
        )

    expected_files = [
        input_directory / f"cell_daily_sst_{year}.parquet"
        for year in range(start_year, end_year + 1)
    ]

    missing_years = [
        year
        for year, path in zip(
            range(start_year, end_year + 1),
            expected_files,
            strict=True,
        )
        if not path.is_file()
    ]

    if missing_years:
        missing_text = ", ".join(
            str(year) for year in missing_years
        )
        raise FileNotFoundError(
            "Missing yearly cell-SST files for years: "
            f"{missing_text}"
        )

    return expected_files


def summarize_yearly_file(
    path: Path,
    expected_year: int,
) -> pd.DataFrame:
    data = pd.read_parquet(
        path,
        columns=SOURCE_COLUMNS,
    )

    missing_columns = sorted(
        set(SOURCE_COLUMNS) - set(data.columns)
    )

    if missing_columns:
        raise ValueError(
            f"{path.name} is missing columns: {missing_columns}"
        )

    data["date"] = pd.to_datetime(data["date"])

    if data.empty:
        raise ValueError(f"{path.name} contains no rows.")

    years = sorted(data["date"].dt.year.unique().tolist())

    if years != [expected_year]:
        raise ValueError(
            f"{path.name} contains dates from years {years}; "
            f"expected only {expected_year}."
        )

    duplicate_count = int(
        data.duplicated(["date", "cell_id"]).sum()
    )

    if duplicate_count:
        raise ValueError(
            f"{path.name} contains {duplicate_count} "
            "duplicate date-cell rows."
        )

    if data["sst_c"].isna().any():
        raise ValueError(
            f"{path.name} contains missing SST values."
        )

    numeric_values = data[
        ["longitude", "latitude", "sst_c"]
    ].to_numpy()

    if not np.isfinite(numeric_values).all():
        raise ValueError(
            f"{path.name} contains non-finite numeric values."
        )

    coordinates = data[
        ["cell_id", "longitude", "latitude"]
    ].drop_duplicates()

    coordinate_counts = coordinates.groupby("cell_id").size()

    if not coordinate_counts.eq(1).all():
        raise ValueError(
            f"{path.name} contains cells with inconsistent "
            "coordinates."
        )

    expected_dates = pd.date_range(
        start=f"{expected_year}-01-01",
        end=f"{expected_year}-12-31",
        freq="D",
    )

    actual_dates = pd.DatetimeIndex(
        data["date"].drop_duplicates().sort_values()
    )

    observations_per_cell = data.groupby("cell_id").size()

    has_complete_date_index = (
        len(actual_dates) == len(expected_dates)
        and actual_dates.difference(expected_dates).empty
        and expected_dates.difference(actual_dates).empty
    )

    if (
        not has_complete_date_index
        or not observations_per_cell.eq(len(expected_dates)).all()
    ):
        raise ValueError(
            f"{path.name} does not provide complete daily "
            f"coverage for every cell in {expected_year}."
        )

    annual = (
        data.groupby(
            ["cell_id", "longitude", "latitude"],
            as_index=False,
        )
        .agg(
            annual_mean_sst_c=("sst_c", "mean"),
            observation_count=("sst_c", "count"),
        )
    )

    annual["year"] = expected_year

    return annual[
        [
            "cell_id",
            "longitude",
            "latitude",
            "year",
            "annual_mean_sst_c",
            "observation_count",
        ]
    ]


def load_annual_cell_means(
    input_directory: Path,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    files = find_yearly_files(
        input_directory=input_directory,
        start_year=start_year,
        end_year=end_year,
    )

    annual_frames = [
        summarize_yearly_file(
            path=path,
            expected_year=year,
        )
        for year, path in zip(
            range(start_year, end_year + 1),
            files,
            strict=True,
        )
    ]

    return pd.concat(
        annual_frames,
        ignore_index=True,
    )


def build_cell_warming_trends(
    annual_means: pd.DataFrame,
    start_year: int = DEFAULT_START_YEAR,
    end_year: int = DEFAULT_END_YEAR,
) -> pd.DataFrame:
    missing_columns = sorted(
        ANNUAL_COLUMNS - set(annual_means.columns)
    )

    if missing_columns:
        raise ValueError(
            "Annual cell means are missing columns: "
            f"{missing_columns}"
        )

    if start_year > end_year:
        raise ValueError(
            "start_year must be less than or equal to end_year."
        )

    data = annual_means.copy()

    duplicate_count = int(
        data.duplicated(["cell_id", "year"]).sum()
    )

    if duplicate_count:
        raise ValueError(
            f"Annual cell means contain {duplicate_count} "
            "duplicate cell-year rows."
        )

    if data[
        ["annual_mean_sst_c", "longitude", "latitude"]
    ].isna().any().any():
        raise ValueError(
            "Annual cell means contain missing numeric values."
        )

    numeric_values = data[
        [
            "annual_mean_sst_c",
            "longitude",
            "latitude",
            "observation_count",
        ]
    ].to_numpy()

    if not np.isfinite(numeric_values).all():
        raise ValueError(
            "Annual cell means contain non-finite numeric values."
        )

    if (data["observation_count"] <= 0).any():
        raise ValueError(
            "Annual observation counts must be positive."
        )

    coordinates = data[
        ["cell_id", "longitude", "latitude"]
    ].drop_duplicates()

    coordinate_counts = coordinates.groupby("cell_id").size()

    if not coordinate_counts.eq(1).all():
        raise ValueError(
            "One or more cells have inconsistent coordinates."
        )

    expected_years = set(
        range(start_year, end_year + 1)
    )

    coverage = data.groupby("cell_id")["year"].agg(
        lambda years: set(int(year) for year in years)
    )

    incomplete_cells = coverage[
        coverage.map(lambda years: years != expected_years)
    ]

    if not incomplete_cells.empty:
        example_cells = ", ".join(
            incomplete_cells.index.astype(str)[:5]
        )
        raise ValueError(
            "Each cell must have complete "
            f"{start_year}-{end_year} coverage. "
            f"Incomplete cells include: {example_cells}"
        )

    period_data = data[
        data["year"].between(start_year, end_year)
    ].copy()

    if len(period_data) != len(data):
        outside_years = sorted(
            set(data["year"].astype(int)) - expected_years
        )
        raise ValueError(
            "Annual cell means contain years outside the "
            f"{start_year}-{end_year} period: {outside_years}"
        )

    records = []

    for cell_id, cell_data in period_data.groupby(
        "cell_id",
        sort=True,
    ):
        cell_data = cell_data.sort_values("year")

        regression = linregress(
            cell_data["year"].to_numpy(dtype=float),
            cell_data["annual_mean_sst_c"].to_numpy(dtype=float),
        )

        slope = float(regression.slope)

        records.append(
            {
                "cell_id": cell_id,
                "longitude": float(
                    cell_data["longitude"].iloc[0]
                ),
                "latitude": float(
                    cell_data["latitude"].iloc[0]
                ),
                "baseline_start_year": start_year,
                "baseline_end_year": end_year,
                "year_count": int(len(cell_data)),
                "observation_count": int(
                    cell_data["observation_count"].sum()
                ),
                "trend_c_per_year": slope,
                "trend_c_per_decade": slope * 10.0,
                "trend_standard_error_c_per_year": float(
                    regression.stderr
                ),
                "trend_p_value": float(regression.pvalue),
                "trend_r_squared": float(
                    regression.rvalue ** 2
                ),
                "estimated_change_over_period_c": (
                    slope * (end_year - start_year)
                ),
            }
        )

    result = pd.DataFrame.from_records(records)

    numeric_columns = result.select_dtypes(
        include=[np.number]
    ).columns

    if not np.isfinite(
        result[numeric_columns].to_numpy()
    ).all():
        raise ValueError(
            "Cell warming-trend table contains non-finite "
            "numeric values."
        )

    return result.sort_values("cell_id").reset_index(drop=True)


def save_cell_warming_trends(
    trends: pd.DataFrame,
    output_file: Path,
) -> None:
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = output_file.with_suffix(
        ".tmp.parquet"
    )

    trends.to_parquet(
        temporary_file,
        index=False,
    )

    temporary_file.replace(output_file)


def main(
    input_directory: Path,
    output_file: Path,
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    print(
        "Calculating annual cell means from: "
        f"{input_directory}"
    )

    annual_means = load_annual_cell_means(
        input_directory=input_directory,
        start_year=start_year,
        end_year=end_year,
    )

    print(
        f"Created {len(annual_means):,} cell-year means"
    )

    trends = build_cell_warming_trends(
        annual_means=annual_means,
        start_year=start_year,
        end_year=end_year,
    )

    print(f"Calculated trends for {len(trends):,} cells")
    print(
        "Trend range:",
        f"{trends['trend_c_per_decade'].min():.3f} to "
        f"{trends['trend_c_per_decade'].max():.3f} C/decade",
    )

    save_cell_warming_trends(
        trends=trends,
        output_file=output_file,
    )

    print(f"Saved cell warming trends to: {output_file}")

    return trends


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Calculate linear warming trends over a selected year range "
            "for each selected OISST coastal cell."
        )
    )

    parser.add_argument(
        "--input-directory",
        default=str(DEFAULT_INPUT_DIRECTORY),
    )

    parser.add_argument(
        "--output-file",
        default=str(DEFAULT_OUTPUT_FILE),
    )

    parser.add_argument(
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
    )

    parser.add_argument(
        "--end-year",
        type=int,
        default=DEFAULT_END_YEAR,
    )

    args = parser.parse_args()

    main(
        input_directory=Path(args.input_directory),
        output_file=Path(args.output_file),
        start_year=args.start_year,
        end_year=args.end_year,
    )
