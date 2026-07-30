from pathlib import Path

import pandas as pd
import pytest

from nzheat.regions.cell_warming_trends import (
    build_cell_warming_trends,
    find_yearly_files,
)


START_YEAR = 1991
END_YEAR = 2020


def _example_annual_means() -> pd.DataFrame:
    records = []

    for year in range(START_YEAR, END_YEAR + 1):
        year_offset = year - START_YEAR

        records.extend(
            [
                {
                    "cell_id": "cell-a",
                    "longitude": 170.125,
                    "latitude": -40.125,
                    "year": year,
                    "annual_mean_sst_c": 12.0 + 0.02 * year_offset,
                    "observation_count": 365,
                },
                {
                    "cell_id": "cell-b",
                    "longitude": 170.375,
                    "latitude": -40.375,
                    "year": year,
                    "annual_mean_sst_c": 18.0 - 0.01 * year_offset,
                    "observation_count": 365,
                },
            ]
        )

    return pd.DataFrame(records)


def test_build_cell_warming_trends_recovers_known_slopes() -> None:
    trends = (
        build_cell_warming_trends(
            _example_annual_means(),
            start_year=START_YEAR,
            end_year=END_YEAR,
        )
        .set_index("cell_id")
    )

    assert len(trends) == 2
    assert trends.index.is_unique

    cell_a = trends.loc["cell-a"]
    cell_b = trends.loc["cell-b"]

    assert cell_a["baseline_start_year"] == START_YEAR
    assert cell_a["baseline_end_year"] == END_YEAR
    assert cell_a["year_count"] == 30
    assert cell_a["observation_count"] == 30 * 365

    assert cell_a["trend_c_per_year"] == pytest.approx(0.02)
    assert cell_a["trend_c_per_decade"] == pytest.approx(0.20)
    assert cell_a["estimated_change_over_period_c"] == pytest.approx(
        0.02 * 29
    )
    assert cell_a["trend_r_squared"] == pytest.approx(1.0)
    assert cell_a["trend_standard_error_c_per_year"] == pytest.approx(
        0.0,
        abs=1e-12,
    )

    assert cell_b["trend_c_per_year"] == pytest.approx(-0.01)
    assert cell_b["trend_c_per_decade"] == pytest.approx(-0.10)
    assert cell_b["estimated_change_over_period_c"] == pytest.approx(
        -0.01 * 29
    )
    assert cell_b["trend_r_squared"] == pytest.approx(1.0)


def test_build_cell_warming_trends_rejects_missing_cell_year() -> None:
    annual_means = _example_annual_means()

    annual_means = annual_means[
        ~(
            annual_means["cell_id"].eq("cell-a")
            & annual_means["year"].eq(2005)
        )
    ]

    with pytest.raises(
        ValueError,
        match="complete 1991-2020 coverage",
    ):
        build_cell_warming_trends(
            annual_means,
            start_year=START_YEAR,
            end_year=END_YEAR,
        )


def test_build_cell_warming_trends_rejects_duplicate_cell_years() -> None:
    annual_means = _example_annual_means()
    annual_means = pd.concat(
        [annual_means, annual_means.iloc[[0]]],
        ignore_index=True,
    )

    with pytest.raises(
        ValueError,
        match="duplicate cell-year rows",
    ):
        build_cell_warming_trends(
            annual_means,
            start_year=START_YEAR,
            end_year=END_YEAR,
        )


def test_build_cell_warming_trends_rejects_inconsistent_coordinates() -> None:
    annual_means = _example_annual_means()

    mask = (
        annual_means["cell_id"].eq("cell-a")
        & annual_means["year"].eq(2020)
    )
    annual_means.loc[mask, "longitude"] = 171.125

    with pytest.raises(
        ValueError,
        match="inconsistent coordinates",
    ):
        build_cell_warming_trends(
            annual_means,
            start_year=START_YEAR,
            end_year=END_YEAR,
        )


def test_find_yearly_files_returns_exact_sorted_period(
    tmp_path: Path,
) -> None:
    for year in (1993, 1991, 1992):
        (
            tmp_path
            / f"cell_daily_sst_{year}.parquet"
        ).touch()

    files = find_yearly_files(
        tmp_path,
        start_year=1991,
        end_year=1993,
    )

    assert [path.name for path in files] == [
        "cell_daily_sst_1991.parquet",
        "cell_daily_sst_1992.parquet",
        "cell_daily_sst_1993.parquet",
    ]


def test_find_yearly_files_rejects_missing_year(
    tmp_path: Path,
) -> None:
    for year in (1991, 1993):
        (
            tmp_path
            / f"cell_daily_sst_{year}.parquet"
        ).touch()

    with pytest.raises(
        FileNotFoundError,
        match="Missing yearly cell-SST files.*1992",
    ):
        find_yearly_files(
            tmp_path,
            start_year=1991,
            end_year=1993,
        )

def test_summarize_yearly_file_rejects_incomplete_daily_coverage(
    tmp_path: Path,
) -> None:
    from nzheat.regions.cell_warming_trends import (
        summarize_yearly_file,
    )

    data = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2001-01-01", "2001-01-02"]
            ),
            "cell_id": ["cell-a", "cell-a"],
            "longitude": [170.125, 170.125],
            "latitude": [-40.125, -40.125],
            "sst_c": [15.0, 15.2],
        }
    )

    path = tmp_path / "cell_daily_sst_2001.parquet"
    data.to_parquet(path, index=False)

    with pytest.raises(
        ValueError,
        match="complete daily coverage",
    ):
        summarize_yearly_file(
            path=path,
            expected_year=2001,
        )


def test_change_column_is_period_generic() -> None:
    trends = build_cell_warming_trends(
        _example_annual_means(),
        start_year=START_YEAR,
        end_year=END_YEAR,
    )

    assert "estimated_change_over_period_c" in trends.columns
    assert "estimated_change_1991_2020_c" not in trends.columns
