from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path

import pandas as pd
import pytest

from nzheat.load import publish_all_postgres as publisher


class FakeTransaction(AbstractContextManager):
    def __init__(self, connection):
        self.connection = connection
        self.exit_exception_type = None

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        self.exit_exception_type = exc_type
        return False


class FakeEngine:
    def __init__(self):
        self.connection = FakeConnection()
        self.transaction = FakeTransaction(self.connection)
        self.begin_calls = 0

    def begin(self):
        self.begin_calls += 1
        return self.transaction


class FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(str(statement))


def make_plan() -> list[publisher.TableLoad]:
    return [
        publisher.TableLoad("core", "regions", pd.DataFrame({"region_id": [1]})),
        publisher.TableLoad(
            "analytics",
            "region_daily_anomalies",
            pd.DataFrame({"date": [pd.Timestamp("2026-01-01")]}),
        ),
    ]


def test_atomic_publish_uses_one_transaction_and_one_connection(monkeypatch):
    engine = FakeEngine()
    connection_ids: list[int] = []

    def fake_load(connection, dataframe, **kwargs):
        connection_ids.append(id(connection))

    monkeypatch.setattr(publisher, "load_dataframe_to_table", fake_load)

    publisher.publish_tables_atomically(engine, make_plan())

    assert engine.begin_calls == 1
    assert len(engine.connection.statements) == 1
    assert engine.connection.statements[0].startswith("TRUNCATE TABLE")
    assert "core.regions" in engine.connection.statements[0]
    assert "analytics.region_daily_anomalies" in engine.connection.statements[0]
    assert connection_ids == [id(engine.connection), id(engine.connection)]
    assert engine.transaction.exit_exception_type is None


def test_atomic_publish_propagates_failure_for_transaction_rollback(monkeypatch):
    engine = FakeEngine()
    calls = 0

    def failing_load(connection, dataframe, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated load failure")

    monkeypatch.setattr(publisher, "load_dataframe_to_table", failing_load)

    with pytest.raises(RuntimeError, match="simulated load failure"):
        publisher.publish_tables_atomically(engine, make_plan())

    assert engine.begin_calls == 1
    assert engine.transaction.exit_exception_type is RuntimeError


def test_monitoring_preparation_rejects_duplicate_keys(monkeypatch, tmp_path: Path):
    path = tmp_path / "monitoring.parquet"
    path.touch()
    row = {
        "date": pd.Timestamp("2026-01-01"),
        "region_id": 1,
        "region_code": "north",
        "region_name": "North",
        "day_of_year": 1,
        "mean_sst_c": 20.0,
        "cell_count": 2,
        "min_sst_c": 19.0,
        "max_sst_c": 21.0,
        "clim_mean_sst_c": 19.0,
        "clim_p90_sst_c": 20.0,
        "sample_size": 30,
        "anomaly_c": 1.0,
        "rolling_7d_anomaly_c": 1.0,
        "rolling_30d_anomaly_c": 1.0,
        "warming_rate_7d_c": 0.1,
        "above_p90": True,
        "status_label": "moderate",
        "data_product": "final",
        "is_provisional": False,
    }
    duplicate_df = pd.DataFrame([row, row])
    monkeypatch.setattr(publisher.pd, "read_parquet", lambda _path: duplicate_df)

    with pytest.raises(ValueError, match="duplicate rows"):
        publisher.prepare_monitoring_table(path)
