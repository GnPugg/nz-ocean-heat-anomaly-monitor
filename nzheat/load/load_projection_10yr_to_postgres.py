from __future__ import annotations

from pathlib import Path
import argparse

import pandas as pd
from sqlalchemy.engine import Engine

from nzheat.load.load_postgres import (
    create_db_engine,
    get_database_url,
    load_dataframe_to_table,
    load_regions_geojson,
)

SCHEMA_NAME = "analytics"
TABLE_NAME = "region_monthly_sst_projection_10yr"

REQUIRED_COLUMNS = [
    "month_date",
    "region_id",
    "observed_or_projected",
]

PRIMARY_KEY_COLUMNS = [
    "month_date",
    "region_id",
    "observed_or_projected",
]


def find_project_root() -> Path:
    """Find the project root from this file location."""
    current = Path(__file__).resolve()

    for parent in current.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent

    raise RuntimeError("Could not find project root. Expected pyproject.toml or .git.")


PROJECT_ROOT = find_project_root()

DEFAULT_PROJECTION_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_sst_projection_10yr.parquet"
)

DEFAULT_REGIONS_FILE = (
    PROJECT_ROOT / "assets" / "regions" / "nz_coastal_regions.geojson"
)


def load_parquet(path: Path) -> pd.DataFrame:
    """Load projection parquet, failing clearly if it does not exist."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    return pd.read_parquet(path)


def require_columns(df: pd.DataFrame, required_columns: list[str]) -> None:
    """Check required projection columns exist."""
    missing_cols = [col for col in required_columns if col not in df.columns]

    if missing_cols:
        raise ValueError(
            f"Projection table is missing required columns: {missing_cols}"
        )


def add_region_labels_if_missing(
    df: pd.DataFrame,
    regions_path: Path,
) -> pd.DataFrame:
    """
    Add region_code and region_name from the regions GeoJSON if they are missing.

    This does not modify the source projection parquet.
    It only enriches the dataframe before loading it to PostgreSQL.
    """
    result = df.copy()

    label_cols = ["region_code", "region_name"]
    missing_label_cols = [col for col in label_cols if col not in result.columns]

    if not missing_label_cols:
        return result

    print(
        "Projection table is missing "
        f"{missing_label_cols}; joining region labels from {regions_path}"
    )

    regions_df = load_regions_geojson(regions_path)
    regions_df = regions_df[["region_id", "region_code", "region_name"]].copy()
    regions_df = regions_df.drop_duplicates(subset=["region_id"])

    merge_cols = ["region_id"] + missing_label_cols

    result = result.merge(
        regions_df[merge_cols],
        on="region_id",
        how="left",
    )

    missing_after_join = int(result[missing_label_cols].isna().any(axis=1).sum())

    if missing_after_join > 0:
        raise ValueError(
            f"Could not add region labels for {missing_after_join} projection row(s)."
        )

    return result


def normalize_projection_types(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize common projection dataframe types before loading."""
    result = df.copy()

    if "month_date" in result.columns:
        result["month_date"] = pd.to_datetime(result["month_date"]).dt.date

    if "region_id" in result.columns:
        result["region_id"] = result["region_id"].astype(int)

    return result


def validate_primary_keys(df: pd.DataFrame) -> None:
    """Fail before loading if duplicate projection keys are present."""
    missing_key_cols = [col for col in PRIMARY_KEY_COLUMNS if col not in df.columns]

    if missing_key_cols:
        raise ValueError(
            f"Projection table is missing primary-key columns: {missing_key_cols}"
        )

    duplicate_count = int(df.duplicated(PRIMARY_KEY_COLUMNS).sum())

    if duplicate_count > 0:
        duplicate_preview = df.loc[
            df.duplicated(PRIMARY_KEY_COLUMNS, keep=False),
            PRIMARY_KEY_COLUMNS,
        ].head(20)

        raise ValueError(
            f"Projection table has {duplicate_count} duplicate key rows "
            f"based on {PRIMARY_KEY_COLUMNS}.\nPreview:\n{duplicate_preview}"
        )


def prepare_projection_for_load(
    df: pd.DataFrame,
    regions_path: Path,
) -> pd.DataFrame:
    """Validate, enrich, and normalize the 10-year projection dataframe."""
    require_columns(df, REQUIRED_COLUMNS)

    prepared_df = add_region_labels_if_missing(df, regions_path)
    prepared_df = normalize_projection_types(prepared_df)

    validate_primary_keys(prepared_df)

    return prepared_df


def load_projection_output(
    engine: Engine,
    projection_path: Path,
    regions_path: Path,
    *,
    if_exists: str = "replace",
) -> None:
    """Load 10-year SST projection output into PostgreSQL."""
    print(f"Loading {SCHEMA_NAME}.{TABLE_NAME} from {projection_path}")

    df = load_parquet(projection_path)
    df = prepare_projection_for_load(df, regions_path)

    load_dataframe_to_table(
        engine,
        df,
        schema_name=SCHEMA_NAME,
        table_name=TABLE_NAME,
        if_exists=if_exists,
    )

    print(f"Loaded {len(df):,} rows into {SCHEMA_NAME}.{TABLE_NAME}")
    print("Projection table loaded successfully.")


def main(
    database_url: str,
    projection_path: Path,
    regions_path: Path,
    if_exists: str,
) -> None:
    engine = create_db_engine(database_url)

    load_projection_output(
        engine=engine,
        projection_path=projection_path,
        regions_path=regions_path,
        if_exists=if_exists,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Load 10-year monthly SST projection output into PostgreSQL.",
    )
    parser.add_argument(
        "--database-url",
        help=(
            "SQLAlchemy PostgreSQL database URL. "
            "If omitted, DATABASE_URL or .env settings are used."
        ),
    )
    parser.add_argument(
        "--projection-file",
        default=str(DEFAULT_PROJECTION_FILE),
        help="Path to the 10-year SST projection parquet.",
    )
    parser.add_argument(
        "--regions-file",
        default=str(DEFAULT_REGIONS_FILE),
        help="Path to the NZ coastal regions GeoJSON.",
    )
    parser.add_argument(
        "--if-exists",
        choices=["replace", "append", "fail"],
        default="replace",
        help="Behaviour if the target PostgreSQL table already exists.",
    )

    args = parser.parse_args()

    database_url = get_database_url(args.database_url)

    main(
        database_url=database_url,
        projection_path=Path(args.projection_file),
        regions_path=Path(args.regions_file),
        if_exists=args.if_exists,
    )
