import numpy as np
import pandas as pd
import pytest

from nzheat.analytics.projection_10yr import (
    N_MONTHS_FORWARD,
    build_monthly_history,
    decimal_year,
    find_column,
    fit_region_projection,
)


def make_monthly_region_history(region_id=1, months=48):
    month_dates = pd.date_range("2018-01-01", periods=months, freq="MS")

    # Simple synthetic SST pattern:
    # seasonal cycle + small warming trend
    values = [
        15.0 + 2.0 * np.sin(2 * np.pi * (month.month - 1) / 12) + 0.03 * i
        for i, month in enumerate(month_dates)
    ]

    return pd.DataFrame(
        {
            "region_id": [region_id] * months,
            "month_date": month_dates,
            "mean_sst_c": values,
            "year": month_dates.year,
            "month": month_dates.month,
        }
    )


def test_find_column_returns_first_available_candidate():
    df = pd.DataFrame(
        {
            "time": ["2026-01-01"],
            "sst": [18.0],
        }
    )

    assert find_column(df, ["date", "time"]) == "time"
    assert find_column(df, ["mean_sst_c", "sst"]) == "sst"


def test_find_column_raises_when_no_candidate_exists():
    df = pd.DataFrame({"x": [1]})

    with pytest.raises(ValueError):
        find_column(df, ["date", "time"])


def test_decimal_year_starts_at_year_and_increases_through_year():
    dates = pd.Series(pd.to_datetime(["2026-01-01", "2026-07-01", "2026-12-31"]))

    result = decimal_year(dates)

    assert result[0] == pytest.approx(2026.0)
    assert result[1] > result[0]
    assert result[2] > result[1]


def test_build_monthly_history_groups_daily_rows_to_monthly_means():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-02-01",
                    "2026-01-01",
                    "2026-01-02",
                    "2026-02-01",
                ]
            ),
            "region_id": [1, 1, 1, 2, 2, 2],
            "mean_sst_c": [10.0, 12.0, 14.0, 20.0, 22.0, 24.0],
        }
    )

    result = build_monthly_history(df)
    result = result.sort_values(["region_id", "month_date"]).reset_index(drop=True)

    assert len(result) == 4

    assert result.loc[0, "region_id"] == 1
    assert result.loc[0, "month_date"] == pd.Timestamp("2026-01-01")
    assert result.loc[0, "mean_sst_c"] == pytest.approx(11.0)

    assert result.loc[1, "region_id"] == 1
    assert result.loc[1, "month_date"] == pd.Timestamp("2026-02-01")
    assert result.loc[1, "mean_sst_c"] == pytest.approx(14.0)

    assert result.loc[2, "region_id"] == 2
    assert result.loc[2, "month_date"] == pd.Timestamp("2026-01-01")
    assert result.loc[2, "mean_sst_c"] == pytest.approx(21.0)

    assert result.loc[3, "region_id"] == 2
    assert result.loc[3, "month_date"] == pd.Timestamp("2026-02-01")
    assert result.loc[3, "mean_sst_c"] == pytest.approx(24.0)


def test_fit_region_projection_returns_observed_plus_10_year_projection():
    region_df = make_monthly_region_history(region_id=1, months=48)

    result = fit_region_projection(region_df)

    observed = result[result["observed_or_projected"] == "observed"]
    projected = result[result["observed_or_projected"] == "projected"]

    assert len(observed) == 48
    assert len(projected) == N_MONTHS_FORWARD
    assert len(result) == 48 + N_MONTHS_FORWARD

    assert projected["month_date"].min() == pd.Timestamp("2022-01-01")
    assert projected["month_date"].max() == pd.Timestamp("2031-12-01")


def test_fit_region_projection_output_columns_and_labels():
    region_df = make_monthly_region_history(region_id=1, months=48)

    result = fit_region_projection(region_df)

    expected_columns = [
        "region_id",
        "month_date",
        "year",
        "month",
        "observed_or_projected",
        "scenario",
        "model_id",
        "mean_sst_c",
        "median_sst_c",
        "p10_sst_c",
        "p90_sst_c",
        "monthly_climatology_sst_c",
        "trend_c_per_year",
        "trend_c_per_decade",
        "warming_from_last_observed_c",
    ]

    assert result.columns.tolist() == expected_columns

    assert set(result["observed_or_projected"]) == {"observed", "projected"}
    assert set(result["scenario"]) == {"observed", "local_trend"}
    assert set(result["model_id"]) == {
        "NOAA_OISST",
        "OISST_seasonal_trend_residual",
    }


def test_fit_region_projection_observed_and_projected_fields_are_consistent():
    region_df = make_monthly_region_history(region_id=1, months=48)

    result = fit_region_projection(region_df)

    observed = result[result["observed_or_projected"] == "observed"]
    projected = result[result["observed_or_projected"] == "projected"]

    assert observed["median_sst_c"].equals(observed["mean_sst_c"])
    assert observed["p10_sst_c"].isna().all()
    assert observed["p90_sst_c"].isna().all()
    assert observed["warming_from_last_observed_c"].eq(0.0).all()

    assert projected["mean_sst_c"].isna().all()
    assert projected["median_sst_c"].notna().all()
    assert projected["monthly_climatology_sst_c"].notna().all()
    assert projected["warming_from_last_observed_c"].notna().all()


def test_fit_region_projection_trend_per_decade_matches_yearly_trend():
    region_df = make_monthly_region_history(region_id=1, months=48)

    result = fit_region_projection(region_df)

    trend_year = result["trend_c_per_year"].iloc[0]
    trend_decade = result["trend_c_per_decade"].iloc[0]

    assert trend_decade == pytest.approx(trend_year * 10)
