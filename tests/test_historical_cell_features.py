from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nzheat.regions.historical_cell_features import (
    build_cell_features,
    find_yearly_files,
)


def _example_history() -> pd.DataFrame:
    records = []

    for year_offset, year in enumerate((2000, 2001)):
        for month in range(1, 13):
            for cell_id, longitude, latitude, offset in (
                ("cell-a", 170.125, -40.125, 0.0),
                ("cell-b", 170.375, -40.375, 10.0),
            ):
                records.append(
                    {
                        "date": pd.Timestamp(
                            year=year,
                            month=month,
                            day=15,
                        ),
                        "cell_id": cell_id,
                        "longitude": longitude,
                        "latitude": latitude,
                        "sst_c": month + year_offset + offset,
                    }
                )

    return pd.DataFrame(records)


def test_build_cell_features_creates_one_row_per_cell() -> None:
    features = (
        build_cell_features(_example_history())
        .set_index("cell_id")
    )

    assert len(features) == 2
    assert features.index.is_unique

    cell_a = features.loc["cell-a"]

    assert cell_a["observation_count"] == 24
    assert cell_a["mean_sst_c"] == pytest.approx(7.0)
    assert cell_a["mean_jan_sst_c"] == pytest.approx(1.5)
    assert cell_a["mean_dec_sst_c"] == pytest.approx(12.5)
    assert cell_a["summer_mean_sst_c"] == pytest.approx(5.5)
    assert cell_a["winter_mean_sst_c"] == pytest.approx(7.5)
    assert cell_a["seasonal_amplitude_c"] == pytest.approx(11.0)
    assert cell_a["raw_sst_sd_c"] > cell_a[
        "deseasonalized_daily_sd_sst_c"
    ]
    assert cell_a["deseasonalized_daily_sd_sst_c"] == pytest.approx(
        np.sqrt(6 / 23)
    )
    assert cell_a["annual_mean_sd_sst_c"] == pytest.approx(
        np.sqrt(0.5)
    )

    seasonal_shape_columns = [
        f"seasonal_shape_{month}_c"
        for month in (
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        )
    ]

    assert cell_a[seasonal_shape_columns].mean() == pytest.approx(0.0)
    assert cell_a["seasonal_shape_jan_c"] == pytest.approx(-5.5)
    assert cell_a["seasonal_shape_dec_c"] == pytest.approx(5.5)

    np.testing.assert_allclose(
        features.loc["cell-a", seasonal_shape_columns].astype(float),
        features.loc["cell-b", seasonal_shape_columns].astype(float),
    )


def test_build_cell_features_rejects_duplicate_date_cell_rows() -> None:
    history = _example_history()
    history = pd.concat(
        [history, history.iloc[[0]]],
        ignore_index=True,
    )

    with pytest.raises(
        ValueError,
        match="duplicate date-cell rows",
    ):
        build_cell_features(history)


def test_build_cell_features_rejects_inconsistent_coordinates() -> None:
    history = _example_history()

    mask = (
        history["cell_id"].eq("cell-a")
        & history["date"].eq(pd.Timestamp("2001-12-15"))
    )

    history.loc[mask, "longitude"] = 171.125

    with pytest.raises(
        ValueError,
        match="inconsistent coordinates",
    ):
        build_cell_features(history)


def test_find_yearly_files_returns_sorted_files(
    tmp_path: Path,
) -> None:
    for year in (2002, 2000, 2001):
        (
            tmp_path
            / f"cell_daily_sst_{year}.parquet"
        ).touch()

    files = find_yearly_files(tmp_path)

    assert [path.name for path in files] == [
        "cell_daily_sst_2000.parquet",
        "cell_daily_sst_2001.parquet",
        "cell_daily_sst_2002.parquet",
    ]
