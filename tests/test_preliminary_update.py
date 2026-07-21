from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_preliminary_module():
    script_path = (
        PROJECT_ROOT
        / "scripts"
        / "monitoring"
        / "run_preliminary_update.py"
    )
    module_name = "run_preliminary_update_test"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {script_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_build_date_list_is_inclusive():
    module = load_preliminary_module()

    result = module.build_date_list(
        date(2026, 1, 1),
        date(2026, 1, 3),
    )

    assert result == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]


def test_build_date_list_rejects_reversed_range():
    module = load_preliminary_module()

    with pytest.raises(ValueError, match="end_date"):
        module.build_date_list(
            date(2026, 1, 3),
            date(2026, 1, 1),
        )


def test_build_prelim_event_input_keeps_history_and_prefers_preliminary_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = load_preliminary_module()

    final_path = tmp_path / "final_anomalies.parquet"
    prelim_path = tmp_path / "prelim_anomalies.parquet"
    output_path = tmp_path / "event_input.parquet"

    final_df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
            ),
            "region_id": [1, 1, 1, 1],
            "source": ["final", "final", "final", "final"],
        }
    )
    prelim_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-04", "2026-01-05", "2026-01-06"]),
            "region_id": [1, 1, 1],
            "source": ["preliminary", "preliminary", "preliminary"],
        }
    )

    final_path.touch()
    prelim_path.touch()

    parquet_frames = {
        final_path: final_df,
        prelim_path: prelim_df,
    }

    monkeypatch.setattr(
        pd,
        "read_parquet",
        lambda path: parquet_frames[Path(path)].copy(),
    )
    monkeypatch.setattr(
        pd.DataFrame,
        "to_parquet",
        lambda self, path, index=False: parquet_frames.__setitem__(
            Path(path), self.copy()
        ),
    )

    prelim_start, prelim_end = module.build_prelim_event_input(
        final_anomalies_path=final_path,
        prelim_anomalies_path=prelim_path,
        output_path=output_path,
    )

    result = parquet_frames[output_path]

    assert prelim_start == pd.Timestamp("2026-01-04")
    assert prelim_end == pd.Timestamp("2026-01-06")
    assert result["date"].tolist() == pd.date_range("2026-01-01", "2026-01-06").tolist()
    assert result.loc[result["date"] == pd.Timestamp("2026-01-04"), "source"].item() == "preliminary"
    assert not result.duplicated(["date", "region_id"]).any()


def test_preliminary_anomaly_input_has_30_day_history_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    module = load_preliminary_module()

    final_path = tmp_path / "final_sst.parquet"
    prelim_path = tmp_path / "prelim_sst.parquet"
    output_path = tmp_path / "prelim_anomaly_input.parquet"

    final_dates = pd.date_range("2026-01-01", periods=40, freq="D")
    prelim_dates = pd.date_range("2026-02-10", periods=3, freq="D")

    final_path.touch()
    prelim_path.touch()

    parquet_frames = {
        final_path: pd.DataFrame(
            {
                "date": final_dates,
                "region_id": [1] * len(final_dates),
                "source": ["final"] * len(final_dates),
            }
        ),
        prelim_path: pd.DataFrame(
            {
                "date": prelim_dates,
                "region_id": [1] * len(prelim_dates),
                "source": ["preliminary"] * len(prelim_dates),
            }
        ),
    }

    monkeypatch.setattr(
        pd,
        "read_parquet",
        lambda path: parquet_frames[Path(path)].copy(),
    )
    monkeypatch.setattr(
        pd.DataFrame,
        "to_parquet",
        lambda self, path, index=False: parquet_frames.__setitem__(
            Path(path), self.copy()
        ),
    )

    prelim_start, prelim_end = module.build_prelim_anomaly_input(
        final_sst_path=final_path,
        prelim_sst_path=prelim_path,
        output_path=output_path,
    )

    result = parquet_frames[output_path]
    history_before_prelim = result.loc[result["date"] < prelim_start]

    assert prelim_start == pd.Timestamp("2026-02-10")
    assert prelim_end == pd.Timestamp("2026-02-12")
    assert history_before_prelim["date"].nunique() >= 29
    assert result.loc[result["date"] >= prelim_start, "source"].eq("preliminary").all()
    assert not result.duplicated(["date", "region_id"]).any()
