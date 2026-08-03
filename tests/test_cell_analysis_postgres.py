from __future__ import annotations

from contextlib import AbstractContextManager

import pandas as pd
import pytest

from nzheat.load import publish_cell_analysis_postgres as publisher


def make_features(
    *,
    cell_id: str = "cell-a",
    longitude: float = 170.125,
    latitude: float = -40.125,
) -> pd.DataFrame:
    row: dict[str, object] = {
        column: 1.0
        for column in publisher.FEATURE_COLUMNS
    }

    row.update(
        {
            "cell_id": cell_id,
            "longitude": longitude,
            "latitude": latitude,
            "observation_count": 10_958,
            "warmest_month": "feb",
            "coldest_month": "aug",
        }
    )

    return pd.DataFrame([row])


def make_trends(
    *,
    cell_id: str = "cell-a",
    longitude: float = 170.125,
    latitude: float = -40.125,
) -> pd.DataFrame:
    row: dict[str, object] = {
        column: 1.0
        for column in publisher.TREND_COLUMNS
    }

    row.update(
        {
            "cell_id": cell_id,
            "longitude": longitude,
            "latitude": latitude,
            "baseline_start_year": 1991,
            "baseline_end_year": 2020,
            "year_count": 30,
            "observation_count": 10_958,
            "trend_c_per_year": 0.02,
            "trend_c_per_decade": 0.20,
            "trend_standard_error_c_per_year": 0.003,
            "trend_p_value": 0.001,
            "trend_r_squared": 0.50,
            "estimated_change_over_period_c": 0.58,
        }
    )

    return pd.DataFrame([row])


def test_prepare_tables_builds_powerbi_cell_geometry() -> None:
    cells, features, trends = publisher.prepare_tables(
        make_features(),
        make_trends(),
        grid_version="test-grid",
        cell_size_degrees=0.25,
    )

    assert len(cells) == 1
    assert len(features) == 1
    assert len(trends) == 1

    cell = cells.iloc[0]

    assert cell["cell_id"] == "cell-a"
    assert cell["grid_version"] == "test-grid"
    assert cell["cell_size_degrees"] == pytest.approx(0.25)
    assert cell["geom_wkt"] == (
        "POLYGON (("
        "170.000000 -40.250000, "
        "170.250000 -40.250000, "
        "170.250000 -40.000000, "
        "170.000000 -40.000000, "
        "170.000000 -40.250000"
        "))"
    )

    assert list(features.columns) == publisher.FEATURE_COLUMNS
    assert list(trends.columns) == publisher.TREND_COLUMNS


def test_prepare_tables_rejects_mismatched_cell_sets() -> None:
    with pytest.raises(
        ValueError,
        match="cell sets do not match",
    ):
        publisher.prepare_tables(
            make_features(cell_id="cell-a"),
            make_trends(cell_id="cell-b"),
            grid_version="test-grid",
            cell_size_degrees=0.25,
        )


def test_prepare_tables_rejects_coordinate_mismatch() -> None:
    with pytest.raises(
        ValueError,
        match="coordinates do not match",
    ):
        publisher.prepare_tables(
            make_features(longitude=170.125),
            make_trends(longitude=171.125),
            grid_version="test-grid",
            cell_size_degrees=0.25,
        )


def test_prepare_tables_rejects_observation_count_mismatch() -> None:
    trends = make_trends()
    trends.loc[0, "observation_count"] = 10_957

    with pytest.raises(
        ValueError,
        match="observation counts do not match",
    ):
        publisher.prepare_tables(
            make_features(),
            trends,
            grid_version="test-grid",
            cell_size_degrees=0.25,
        )


class FakeScalarResult:
    def __init__(self, value: int):
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class FakeConnection:
    def __init__(self, expected_count: int):
        self.expected_count = expected_count
        self.statements: list[str] = []

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)

        if "COUNT(*)" in sql:
            return FakeScalarResult(self.expected_count)

        return None


class FakeTransaction(AbstractContextManager):
    def __init__(self, connection: FakeConnection):
        self.connection = connection
        self.exit_exception_type = None

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.exit_exception_type = exc_type
        return False


class FakeEngine:
    def __init__(self, expected_count: int):
        self.connection = FakeConnection(expected_count)
        self.transaction = FakeTransaction(self.connection)
        self.begin_calls = 0

    def begin(self) -> FakeTransaction:
        self.begin_calls += 1
        return self.transaction


def test_publication_uses_one_atomic_transaction(
    monkeypatch,
) -> None:
    cells, features, trends = publisher.prepare_tables(
        make_features(),
        make_trends(),
        grid_version="test-grid",
        cell_size_degrees=0.25,
    )

    engine = FakeEngine(expected_count=1)
    loaded_tables: list[tuple[int, str, str]] = []

    def fake_load(
        connection,
        dataframe,
        *,
        schema_name,
        table_name,
        if_exists,
    ) -> None:
        loaded_tables.append(
            (
                id(connection),
                schema_name,
                table_name,
            )
        )

    monkeypatch.setattr(
        publisher,
        "load_dataframe_to_table",
        fake_load,
    )

    publisher.publish_cell_analysis(
        engine,
        cells=cells,
        features=features,
        trends=trends,
    )

    assert engine.begin_calls == 1
    assert engine.transaction.exit_exception_type is None

    assert loaded_tables == [
        (
            id(engine.connection),
            "core",
            "coastal_cells",
        ),
        (
            id(engine.connection),
            "analytics",
            "cell_historical_features",
        ),
        (
            id(engine.connection),
            "analytics",
            "cell_warming_trends",
        ),
    ]

    truncate_sql = engine.connection.statements[0]

    assert truncate_sql.lstrip().startswith("TRUNCATE TABLE")
    assert "analytics.cell_historical_features" in truncate_sql
    assert "analytics.cell_warming_trends" in truncate_sql
    assert "core.coastal_cells" in truncate_sql
