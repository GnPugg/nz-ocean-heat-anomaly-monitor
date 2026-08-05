from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from nzheat.load.load_postgres import (  # noqa: E402
    create_db_engine,
    get_database_url,
)
from nzheat.load import load_projection_10yr_to_postgres as projection_loader  # noqa: E402
from nzheat.load import publish_all_postgres as regional_publisher  # noqa: E402
from nzheat.load import publish_cell_analysis_postgres as cell_publisher  # noqa: E402


VALID_OBJECT_NAME = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")


def load_expected_regional_counts() -> dict[str, int]:
    """Derive expected regional counts using the publication plan itself."""
    plan = regional_publisher.build_publication_plan(
        include_final=True,
        include_preliminary=True,
        include_monitoring=True,
    )

    return {
        item.qualified_name: len(item.dataframe)
        for item in plan
    }


def load_expected_cell_count() -> int:
    """Validate the two cell-analysis inputs and return their expected count."""
    features_path = Path(cell_publisher.DEFAULT_FEATURES_FILE)
    trends_path = Path(cell_publisher.DEFAULT_TRENDS_FILE)

    if not features_path.exists():
        raise FileNotFoundError(
            f"Missing cell historical features file: {features_path}"
        )

    if not trends_path.exists():
        raise FileNotFoundError(
            f"Missing cell warming trends file: {trends_path}"
        )

    features = pd.read_parquet(features_path)
    trends = pd.read_parquet(trends_path)

    for label, dataframe in [
        ("historical features", features),
        ("warming trends", trends),
    ]:
        if "cell_id" not in dataframe.columns:
            raise ValueError(
                f"Cell {label} input is missing the cell_id column."
            )

        duplicate_count = int(dataframe["cell_id"].duplicated().sum())
        if duplicate_count:
            raise ValueError(
                f"Cell {label} input contains "
                f"{duplicate_count} duplicate cell_id values."
            )

    feature_ids = set(features["cell_id"].astype(str))
    trend_ids = set(trends["cell_id"].astype(str))

    if feature_ids != trend_ids:
        missing_from_trends = sorted(feature_ids - trend_ids)[:10]
        missing_from_features = sorted(trend_ids - feature_ids)[:10]

        raise ValueError(
            "Cell-analysis inputs contain different cell_id sets. "
            f"Missing from trends: {missing_from_trends}; "
            f"missing from features: {missing_from_features}"
        )

    return len(features)


def load_expected_projection_count() -> int:
    """Validate and prepare the projection output before counting it."""
    projection = projection_loader.load_parquet(
        Path(projection_loader.DEFAULT_PROJECTION_FILE)
    )

    prepared = projection_loader.prepare_projection_for_load(
        projection,
        Path(projection_loader.DEFAULT_REGIONS_FILE),
    )

    return len(prepared)


def build_expected_counts() -> dict[str, int]:
    """Build expected counts for every required Power BI database object."""
    expected = load_expected_regional_counts()

    cell_count = load_expected_cell_count()

    expected.update(
        {
            "core.coastal_cells": cell_count,
            "analytics.cell_historical_features": cell_count,
            "analytics.cell_warming_trends": cell_count,
            "mart.v_powerbi_cell_summary": cell_count,
            "analytics.region_monthly_sst_projection_10yr":
                load_expected_projection_count(),
        }
    )

    return expected


def relation_exists(
    connection: Connection,
    qualified_name: str,
) -> bool:
    result = connection.execute(
        text("SELECT to_regclass(:qualified_name)"),
        {"qualified_name": qualified_name},
    ).scalar_one_or_none()

    return result is not None


def get_exact_row_count(
    connection: Connection,
    qualified_name: str,
) -> int:
    if not VALID_OBJECT_NAME.fullmatch(qualified_name):
        raise ValueError(
            f"Unsafe or invalid PostgreSQL object name: {qualified_name}"
        )

    if not relation_exists(connection, qualified_name):
        raise RuntimeError(
            f"Required PostgreSQL object does not exist: {qualified_name}"
        )

    return int(
        connection.execute(
            text(f"SELECT COUNT(*) FROM {qualified_name}")
        ).scalar_one()
    )


def verify_database_counts(database_url: str) -> None:
    expected_counts = build_expected_counts()
    engine = create_db_engine(database_url)

    actual_counts: dict[str, int] = {}

    with engine.connect() as connection:
        for qualified_name in expected_counts:
            actual_counts[qualified_name] = get_exact_row_count(
                connection,
                qualified_name,
            )

    print("\n=== FINAL DATABASE ROW-COUNT VERIFICATION ===")

    failures: dict[str, tuple[int, int]] = {}

    for qualified_name, expected_count in expected_counts.items():
        actual_count = actual_counts[qualified_name]
        status = "PASS" if actual_count == expected_count else "FAIL"

        print(
            f"{status:4}  {qualified_name:<48} "
            f"expected={expected_count:>8,}  "
            f"actual={actual_count:>8,}"
        )

        if actual_count != expected_count:
            failures[qualified_name] = (
                expected_count,
                actual_count,
            )

    if failures:
        details = "; ".join(
            (
                f"{name}: expected {expected:,}, "
                f"found {actual:,}"
            )
            for name, (expected, actual) in failures.items()
        )

        raise RuntimeError(
            f"Database row-count verification failed: {details}"
        )

    print("\n=== DATABASE VERIFICATION PASSED ===")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify exact PostgreSQL row counts against the current "
            "validated local outputs."
        )
    )
    parser.add_argument(
        "--database-url",
        help=(
            "Optional SQLAlchemy PostgreSQL URL. DATABASE_URL or "
            "the project database settings are used when omitted."
        ),
    )

    args = parser.parse_args()
    database_url = get_database_url(args.database_url)

    verify_database_counts(database_url)


if __name__ == "__main__":
    main()
