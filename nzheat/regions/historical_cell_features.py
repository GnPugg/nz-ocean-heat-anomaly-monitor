from __future__ import annotations

from pathlib import Path
import argparse

import numpy as np
import pandas as pd


DEFAULT_INPUT_DIRECTORY = Path(
    "data/interim/region-design/v2_75km/historical-cell-sst"
)

DEFAULT_OUTPUT_FILE = Path(
    "data/interim/region-design/v2_75km/"
    "historical-cell-features.parquet"
)

MONTH_NAMES = {
    1: "jan",
    2: "feb",
    3: "mar",
    4: "apr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "aug",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dec",
}


def find_yearly_files(input_directory: Path) -> list[Path]:
    files = sorted(
        input_directory.glob("cell_daily_sst_*.parquet")
    )

    if not files:
        raise FileNotFoundError(
            f"No yearly cell-SST Parquet files found in "
            f"{input_directory}"
        )

    return files


def load_historical_cell_sst(
    input_directory: Path,
) -> pd.DataFrame:
    files = find_yearly_files(input_directory)

    frames = [
        pd.read_parquet(
            path,
            columns=[
                "date",
                "cell_id",
                "longitude",
                "latitude",
                "sst_c",
            ],
        )
        for path in files
    ]

    history = pd.concat(frames, ignore_index=True)
    history["date"] = pd.to_datetime(history["date"])

    return history


def build_cell_features(
    history: pd.DataFrame,
) -> pd.DataFrame:
    required_columns = {
        "date",
        "cell_id",
        "longitude",
        "latitude",
        "sst_c",
    }

    missing = sorted(required_columns - set(history.columns))

    if missing:
        raise ValueError(
            f"Historical SST data is missing columns: {missing}"
        )

    data = history.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["month"] = data["date"].dt.month
    data["year"] = data["date"].dt.year

    duplicate_count = int(
        data.duplicated(["date", "cell_id"]).sum()
    )

    if duplicate_count:
        raise ValueError(
            f"Historical SST contains {duplicate_count} "
            "duplicate date-cell rows."
        )

    if data["sst_c"].isna().any():
        raise ValueError(
            "Historical SST contains missing SST values."
        )

    coordinates = (
        data[
            [
                "cell_id",
                "longitude",
                "latitude",
            ]
        ]
        .drop_duplicates()
    )

    coordinate_counts = (
        coordinates.groupby("cell_id")
        .size()
    )

    if not coordinate_counts.eq(1).all():
        raise ValueError(
            "One or more cells have inconsistent coordinates."
        )

    overall = (
        data.groupby("cell_id")
        .agg(
            mean_sst_c=("sst_c", "mean"),
            raw_sst_sd_c=("sst_c", "std"),
            minimum_sst_c=("sst_c", "min"),
            maximum_sst_c=("sst_c", "max"),
            observation_count=("sst_c", "count"),
        )
        .reset_index()
    )

    monthly = (
        data.groupby(["cell_id", "month"])["sst_c"]
        .mean()
        .unstack("month")
    )

    monthly = monthly.rename(
        columns={
            month: f"mean_{name}_sst_c"
            for month, name in MONTH_NAMES.items()
        }
    ).reset_index()

    monthly_columns = [
        f"mean_{name}_sst_c"
        for name in MONTH_NAMES.values()
    ]

    seasonal_shape_columns = []

    for name in MONTH_NAMES.values():
        monthly_column = f"mean_{name}_sst_c"
        shape_column = f"seasonal_shape_{name}_c"
        seasonal_shape_columns.append(shape_column)

    missing_month_columns = [
        column
        for column in monthly_columns
        if column not in monthly.columns
    ]

    if missing_month_columns:
        raise ValueError(
            "Missing monthly climatology columns: "
            f"{missing_month_columns}"
        )

    monthly["summer_mean_sst_c"] = monthly[
        [
            "mean_dec_sst_c",
            "mean_jan_sst_c",
            "mean_feb_sst_c",
        ]
    ].mean(axis=1)

    monthly["winter_mean_sst_c"] = monthly[
        [
            "mean_jun_sst_c",
            "mean_jul_sst_c",
            "mean_aug_sst_c",
        ]
    ].mean(axis=1)

    monthly["seasonal_amplitude_c"] = (
        monthly[monthly_columns].max(axis=1)
        - monthly[monthly_columns].min(axis=1)
    )

    monthly["warmest_month"] = (
        monthly[monthly_columns]
        .idxmax(axis=1)
        .str.extract(r"mean_(...)_sst_c")[0]
    )

    monthly["coldest_month"] = (
        monthly[monthly_columns]
        .idxmin(axis=1)
        .str.extract(r"mean_(...)_sst_c")[0]
    )

    annual_means = (
        data.groupby(["cell_id", "year"])["sst_c"]
        .mean()
        .reset_index()
    )

    annual_variability = (
        annual_means.groupby("cell_id")["sst_c"]
        .std()
        .rename("annual_mean_sd_sst_c")
        .reset_index()
    )

    monthly["monthly_cycle_mean_sst_c"] = monthly[
        monthly_columns
    ].mean(axis=1)

    for shape_column, monthly_column in zip(
        seasonal_shape_columns,
        monthly_columns,
        strict=True,
    ):
        monthly[shape_column] = (
            monthly[monthly_column]
            - monthly["monthly_cycle_mean_sst_c"]
        )

    monthly = monthly.drop(columns="monthly_cycle_mean_sst_c")

    monthly_climatology = (
        data.groupby(["cell_id", "month"])["sst_c"]
        .mean()
        .rename("monthly_climatology_sst_c")
        .reset_index()
    )

    deseasonalized = data.merge(
        monthly_climatology,
        on=["cell_id", "month"],
        validate="many_to_one",
    )
    deseasonalized["monthly_anomaly_c"] = (
        deseasonalized["sst_c"]
        - deseasonalized["monthly_climatology_sst_c"]
    )

    daily_variability = (
        deseasonalized.groupby("cell_id")["monthly_anomaly_c"]
        .std()
        .rename("deseasonalized_daily_sd_sst_c")
        .reset_index()
    )

    result = (
        coordinates
        .merge(overall, on="cell_id", validate="one_to_one")
        .merge(monthly, on="cell_id", validate="one_to_one")
        .merge(
            daily_variability,
            on="cell_id",
            validate="one_to_one",
        )
        .merge(
            annual_variability,
            on="cell_id",
            validate="one_to_one",
        )
        .sort_values("cell_id")
        .reset_index(drop=True)
    )

    numeric_columns = result.select_dtypes(
        include=[np.number]
    ).columns

    if not np.isfinite(
        result[numeric_columns].to_numpy()
    ).all():
        raise ValueError(
            "Feature table contains non-finite numeric values."
        )

    return result


def save_features(
    features: pd.DataFrame,
    output_file: Path,
) -> None:
    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = output_file.with_suffix(
        ".tmp.parquet"
    )

    features.to_parquet(
        temporary_file,
        index=False,
    )

    temporary_file.replace(output_file)


def main(
    input_directory: Path,
    output_file: Path,
) -> pd.DataFrame:
    print(
        f"Loading historical cell SST from: "
        f"{input_directory}"
    )

    history = load_historical_cell_sst(
        input_directory
    )

    print(f"Loaded {len(history):,} date-cell rows")

    features = build_cell_features(history)

    print(f"Created features for {len(features):,} cells")
    print(
        "Mean SST range:",
        f"{features['mean_sst_c'].min():.2f} to "
        f"{features['mean_sst_c'].max():.2f} C",
    )
    print(
        "Seasonal amplitude range:",
        f"{features['seasonal_amplitude_c'].min():.2f} to "
        f"{features['seasonal_amplitude_c'].max():.2f} C",
    )

    save_features(
        features,
        output_file,
    )

    print(f"Saved feature table to: {output_file}")

    return features


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Calculate long-term SST characteristics for "
            "each selected OISST coastal cell."
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

    args = parser.parse_args()

    main(
        input_directory=Path(args.input_directory),
        output_file=Path(args.output_file),
    )
