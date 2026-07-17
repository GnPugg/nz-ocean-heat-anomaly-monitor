from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_script_module(module_name: str, relative_path: str):
    script_path = PROJECT_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_daily_pipeline_validates_before_any_publication(monkeypatch):
    module = load_script_module(
        "run_daily_pipeline_test",
        "scripts/monitoring/run_daily_pipeline.py",
    )

    calls: list[tuple[str, str, tuple[str, ...]]] = []

    def fake_run_script(
        script_path,
        extra_args=None,
        run_logger=None,
        step_name=None,
    ):
        calls.append(("script", Path(script_path).name, tuple(extra_args or [])))

    def fake_run_module(
        module_name,
        extra_args=None,
        run_logger=None,
        step_name=None,
    ):
        calls.append(("module", module_name, tuple(extra_args or [])))

    monkeypatch.setattr(module, "run_script", fake_run_script)
    monkeypatch.setattr(module, "run_module", fake_run_module)

    for function_name in [
        "log_final_file_metrics",
        "log_final_table_metrics",
        "log_preliminary_file_metrics",
        "log_preliminary_table_metrics",
        "log_monitoring_file_metrics",
        "log_monitoring_table_metrics",
    ]:
        monkeypatch.setattr(module, function_name, lambda _logger: None)

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_daily_pipeline.py", "--skip-db-log"],
    )

    module.main()

    assert calls == [
        ("script", "run_daily_append.py", ("--skip-load",)),
        (
            "script",
            "run_preliminary_update.py",
            ("--days-back", "21", "--end-lag-days", "1"),
        ),
        (
            "script",
            "build_and_load_monitoring_anomalies.py",
            ("--build-only",),
        ),
        ("script", "validate_outputs.py", ()),
        ("module", "nzheat.load.load_postgres", ()),
        ("module", "nzheat.load.load_preliminary_postgres", ()),
        (
            "script",
            "build_and_load_monitoring_anomalies.py",
            ("--load-only",),
        ),
    ]

    validation_index = next(
        index for index, call in enumerate(calls) if call[1] == "validate_outputs.py"
    )
    publication_indexes = [
        index
        for index, call in enumerate(calls)
        if call[0] == "module" or call[2] == ("--load-only",)
    ]

    assert publication_indexes
    assert validation_index < min(publication_indexes)


def test_daily_append_can_build_without_database_publication(monkeypatch, tmp_path):
    module = load_script_module(
        "run_daily_append_test",
        "scripts/monitoring/run_daily_append.py",
    )

    history_path = tmp_path / "history.parquet"
    history_path.touch()

    history = pd.DataFrame(
        {"date": [pd.Timestamp.today().normalize() - pd.Timedelta(days=20)]}
    )
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "HISTORY_PATH", history_path)
    monkeypatch.setattr(module.pd, "read_parquet", lambda _path: history.copy())
    monkeypatch.setattr(module, "run_command", lambda command: calls.append(command))

    module.main(skip_load=True)

    called_modules = [
        command[2]
        for command in calls
        if len(command) >= 3 and command[1] == "-m"
    ]

    assert "nzheat.pipeline.backfill" in called_modules
    assert "nzheat.analytics.anomalies" in called_modules
    assert "nzheat.analytics.events" in called_modules
    assert "nzheat.load.load_postgres" not in called_modules
