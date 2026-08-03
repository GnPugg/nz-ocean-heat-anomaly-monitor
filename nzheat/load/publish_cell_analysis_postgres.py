from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from nzheat.load.load_postgres import (
    create_db_engine,
    get_database_url,
    load_dataframe_to_table,
)
from nzheat.utils.paths import find_project_root


PROJECT_ROOT = find_project_root()

DEFAULT_FEATURES_FILE = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "region-design"
    / "v2_75km"
    / "historical-cell-features.parquet"
)

DEFAULT_TRENDS_FILE = (
    PROJECT_ROOT
    / "data"
    / "interim"
    / "region-design"
    / "v2_75km"
    / "cell-warming-trends-1991-2020.parquet"
)

DEFAULT_GRID_VERSION = "v2_masked_75km"
DEFAULT_CELL_SIZE_DEGREES = 0.25


FEATURE_COLUMNS = [
    "cell_id",
    "observation_count",
    "mean_sst_c",
    "raw_sst_sd_c",
    "minimum_sst_c",
    "maximum_sst_c",
    "mean_jan_sst_c",
    "mean_feb_sst_c",
    "mean_mar_sst_c",
    "mean_apr_sst_c",
    "mean_may_sst_c",
    "mean_jun_sst_c",
    "mean_jul_sst_c",
    "mean_aug_sst_c",
    "mean_sep_sst_c",
    "mean_oct_sst_c",
    "mean_nov_sst_c",
    "mean_dec_sst_c",
    "summer_mean_sst_c",
    "winter_mean_sst_c",
    "seasonal_amplitude_c",
    "warmest_month",
    "coldest_month",
    "seasonal_shape_jan_c",
    "seasonal_shape_feb_c",
    "seasonal_shape_mar_c",
    "seasonal_shape_apr_c",
    "seasonal_shape_may_c",
    "seasonal_shape_jun_c",
    "seasonal_shape_jul_c",
    "seasonal_shape_aug_c",
    "seasonal_shape_sep_c",
    "seasonal_shape_oct_c",
    "seasonal_shape_nov_c",
    "seasonal_shape_dec_c",
    "deseasonalized_daily_sd_sst_c",
    "annual_mean_sd_sst_c",
]


TREND_COLUMNS = [
    "cell_id",
    "baseline_start_year",
    "baseline_end_year",
    "year_count",
    "observation_count",
    "trend_c_per_year",
    "trend_c_per_decade",
    "trend_standard_error_c_per_year",
    "trend_p_value",
    "trend_r_squared",
    "estimated_change_over_period_c",
]


def load_parquet(path: Path, label: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {label} file: {path}")

    data = pd.read_parquet(path)

    if data.empty:
        raise ValueError(f"{label} file contains no rows: {path}")

    return data


def validate_required_columns(
    data: pd.DataFrame,
    required_columns: list[str],
    label: str,
) -> None:
    missing = sorted(set(required_columns) - set(data.columns))

    if missing:
        raise ValueError(
            f"{label} is missing required columns: {missing}"
        )


def validate_cell_table(data: pd.DataFrame, label: str) -> None:
    validate_required_columns(
        data,
        ["cell_id", "longitude", "latitude"],
        label,
    )

    if data["cell_id"].isna().any():
        raise ValueError(f"{label} contains missing cell_id values.")

    duplicate_count = int(data["cell_id"].duplicated().sum())

    if duplicate_count:
        raise ValueError(
            f"{label} contains {duplicate_count} duplicate cell_id rows."
        )

    if data.isna().any().any():
        missing_count = int(data.isna().sum().sum())
        raise ValueError(
            f"{label} contains {missing_count} missing values."
        )

    numeric = data.select_dtypes(include=[np.number])

    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError(
            f"{label} contains non-finite numeric values."
        )


def validate_matching_cells(
    features: pd.DataFrame,
    trends: pd.DataFrame,
) -> None:
    feature_ids = set(features["cell_id"])
    trend_ids = set(trends["cell_id"])

    if feature_ids != trend_ids:
        only_features = sorted(feature_ids - trend_ids)[:10]
        only_trends = sorted(trend_ids - feature_ids)[:10]

        raise ValueError(
            "Feature and trend cell sets do not match. "
            f"Only in features: {only_features}; "
            f"only in trends: {only_trends}"
        )

    coordinates = features[
        ["cell_id", "longitude", "latitude"]
    ].merge(
        trends[["cell_id", "longitude", "latitude"]],
        on="cell_id",
        suffixes=("_features", "_trends"),
        validate="one_to_one",
    )

    longitude_matches = np.isclose(
        coordinates["longitude_features"],
        coordinates["longitude_trends"],
        rtol=0.0,
        atol=1e-10,
    )

    latitude_matches = np.isclose(
        coordinates["latitude_features"],
        coordinates["latitude_trends"],
        rtol=0.0,
        atol=1e-10,
    )

    if not longitude_matches.all() or not latitude_matches.all():
        raise ValueError(
            "Feature and trend coordinates do not match."
        )

    observations = features[
        ["cell_id", "observation_count"]
    ].merge(
        trends[["cell_id", "observation_count"]],
        on="cell_id",
        suffixes=("_features", "_trends"),
        validate="one_to_one",
    )

    if not (
        observations["observation_count_features"]
        == observations["observation_count_trends"]
    ).all():
        raise ValueError(
            "Feature and trend observation counts do not match."
        )


def build_cell_wkt(
    longitude: float,
    latitude: float,
    cell_size_degrees: float,
) -> str:
    half_size = cell_size_degrees / 2.0

    west = longitude - half_size
    east = longitude + half_size
    south = latitude - half_size
    north = latitude + half_size

    return (
        "POLYGON (("
        f"{west:.6f} {south:.6f}, "
        f"{east:.6f} {south:.6f}, "
        f"{east:.6f} {north:.6f}, "
        f"{west:.6f} {north:.6f}, "
        f"{west:.6f} {south:.6f}"
        "))"
    )


def prepare_tables(
    features: pd.DataFrame,
    trends: pd.DataFrame,
    *,
    grid_version: str,
    cell_size_degrees: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    validate_cell_table(features, "Historical feature table")
    validate_cell_table(trends, "Warming trend table")

    validate_required_columns(
        features,
        FEATURE_COLUMNS,
        "Historical feature table",
    )
    validate_required_columns(
        trends,
        TREND_COLUMNS,
        "Warming trend table",
    )

    validate_matching_cells(features, trends)

    if cell_size_degrees <= 0.0:
        raise ValueError("cell_size_degrees must be greater than zero.")

    cells = (
        trends[["cell_id", "longitude", "latitude"]]
        .copy()
        .sort_values("cell_id")
        .reset_index(drop=True)
    )

    cells["cell_size_degrees"] = float(cell_size_degrees)
    cells["grid_version"] = grid_version
    cells["geom_wkt"] = [
        build_cell_wkt(
            longitude=float(longitude),
            latitude=float(latitude),
            cell_size_degrees=cell_size_degrees,
        )
        for longitude, latitude in zip(
            cells["longitude"],
            cells["latitude"],
            strict=True,
        )
    ]

    feature_table = (
        features[FEATURE_COLUMNS]
        .copy()
        .sort_values("cell_id")
        .reset_index(drop=True)
    )

    trend_table = (
        trends[TREND_COLUMNS]
        .copy()
        .sort_values("cell_id")
        .reset_index(drop=True)
    )

    feature_table["observation_count"] = (
        feature_table["observation_count"].astype("int64")
    )

    for column in [
        "baseline_start_year",
        "baseline_end_year",
        "year_count",
        "observation_count",
    ]:
        trend_table[column] = trend_table[column].astype("int64")

    return cells, feature_table, trend_table


def publish_cell_analysis(
    engine: Engine,
    *,
    cells: pd.DataFrame,
    features: pd.DataFrame,
    trends: pd.DataFrame,
) -> None:
    truncate_statement = text(
        """
        TRUNCATE TABLE
            analytics.cell_historical_features,
            analytics.cell_warming_trends,
            core.coastal_cells;
        """
    )

    print("Beginning atomic cell-analysis publication...")

    with engine.begin() as connection:
        connection.execute(truncate_statement)

        load_dataframe_to_table(
            connection,
            cells,
            schema_name="core",
            table_name="coastal_cells",
            if_exists="append",
        )

        load_dataframe_to_table(
            connection,
            features,
            schema_name="analytics",
            table_name="cell_historical_features",
            if_exists="append",
        )

        load_dataframe_to_table(
            connection,
            trends,
            schema_name="analytics",
            table_name="cell_warming_trends",
            if_exists="append",
        )

        cell_count = connection.execute(
            text("SELECT COUNT(*) FROM core.coastal_cells")
        ).scalar_one()

        feature_count = connection.execute(
            text(
                "SELECT COUNT(*) "
                "FROM analytics.cell_historical_features"
            )
        ).scalar_one()

        trend_count = connection.execute(
            text(
                "SELECT COUNT(*) "
                "FROM analytics.cell_warming_trends"
            )
        ).scalar_one()

        view_count = connection.execute(
            text(
                "SELECT COUNT(*) "
                "FROM mart.v_powerbi_cell_summary"
            )
        ).scalar_one()

        expected_count = len(cells)

        actual_counts = {
            "core.coastal_cells": cell_count,
            "analytics.cell_historical_features": feature_count,
            "analytics.cell_warming_trends": trend_count,
            "mart.v_powerbi_cell_summary": view_count,
        }

        unexpected = {
            name: count
            for name, count in actual_counts.items()
            if count != expected_count
        }

        if unexpected:
            raise RuntimeError(
                "Unexpected PostgreSQL row counts: "
                f"{unexpected}; expected {expected_count}"
            )

    print(
        "Atomic cell-analysis publication committed successfully."
    )
    print(f"Loaded {len(cells):,} coastal cells.")
    print(
        "Power BI view ready: "
        "mart.v_powerbi_cell_summary"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Publish static cell-level SST features and warming "
            "trends to PostgreSQL for Power BI."
        )
    )

    parser.add_argument(
        "--database-url",
        help=(
            "Optional SQLAlchemy PostgreSQL URL. Database "
            "environment variables are used when omitted."
        ),
    )

    parser.add_argument(
        "--features-file",
        type=Path,
        default=DEFAULT_FEATURES_FILE,
    )

    parser.add_argument(
        "--trends-file",
        type=Path,
        default=DEFAULT_TRENDS_FILE,
    )

    parser.add_argument(
        "--grid-version",
        default=DEFAULT_GRID_VERSION,
    )

    parser.add_argument(
        "--cell-size-degrees",
        type=float,
        default=DEFAULT_CELL_SIZE_DEGREES,
    )

    args = parser.parse_args()

    features = load_parquet(
        args.features_file,
        "historical feature",
    )

    trends = load_parquet(
        args.trends_file,
        "warming trend",
    )

    cells, feature_table, trend_table = prepare_tables(
        features,
        trends,
        grid_version=args.grid_version,
        cell_size_degrees=args.cell_size_degrees,
    )

    print(f"Validated {len(cells):,} matching cells.")
    print(
        "Trend range: "
        f"{trend_table['trend_c_per_decade'].min():.3f} to "
        f"{trend_table['trend_c_per_decade'].max():.3f} °C/decade"
    )

    engine = create_db_engine(
        get_database_url(args.database_url)
    )

    publish_cell_analysis(
        engine,
        cells=cells,
        features=feature_table,
        trends=trend_table,
    )


if __name__ == "__main__":
    main()
