from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_monitoring_module():
    script_path = (
        PROJECT_ROOT
        / "scripts"
        / "monitoring"
        / "build_and_load_monitoring_anomalies.py"
    )
    spec = importlib.util.spec_from_file_location(
        "build_monitoring_modes_test",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_only_does_not_publish(monkeypatch):
    module = load_monitoring_module()
    combined = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-01-01")],
            "region_id": [1],
        }
    )
    actions: list[str] = []

    monkeypatch.setattr(module, "build_monitoring_dataframe", lambda: combined)
    monkeypatch.setattr(
        module,
        "save_monitoring_output",
        lambda _df: actions.append("save"),
    )
    monkeypatch.setattr(
        module,
        "load_monitoring_output",
        lambda database_url=None: actions.append("load"),
    )

    module.main(build_output=True, load_output=False)

    assert actions == ["save"]


def test_load_only_does_not_rebuild(monkeypatch):
    module = load_monitoring_module()
    actions: list[str] = []

    monkeypatch.setattr(
        module,
        "build_monitoring_dataframe",
        lambda: actions.append("build"),
    )
    monkeypatch.setattr(
        module,
        "save_monitoring_output",
        lambda _df: actions.append("save"),
    )
    monkeypatch.setattr(
        module,
        "load_monitoring_output",
        lambda database_url=None: actions.append("load"),
    )

    module.main(build_output=False, load_output=True)

    assert actions == ["load"]
