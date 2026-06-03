import pandas as pd
import pytest

from nzheat.analytics.anomalies import (
    calculate_anomalies,
    classify_status,
    filter_analysis_period,
    join_history_to_climatology,
    parse_iso_date,
    prepare_history,
)


def test_prepare_history_drops_feb_29_and_uses_no_leap_day_of_year():
    df = pd.DataFrame(
        {
            "date": [
                "2024-02-28",
                "2024-02-29",
                "2024-03-01",
                "2024-12-31",
                "2025-12-31",
            ]
        }
    )

    result = prepare_history(df)

    assert pd.Timestamp("2024-02-29") not in result["date"].tolist()

    day_by_date = dict(zip(result["date"], result["day_of_year"]))

    assert day_by_date[pd.Timestamp("2024-02-28")] == 59
    assert day_by_date[pd.Timestamp("2024-03-01")] == 60
    assert day_by_date[pd.Timestamp("2024-12-31")] == 365
    assert day_by_date[pd.Timestamp("2025-12-31")] == 365


def test_filter_analysis_period_is_inclusive():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]
            ),
            "value": [1, 2, 3, 4],
        }
    )

    result = filter_analysis_period(
        df,
        analysis_start=pd.Timestamp("2026-01-02"),
        analysis_end=pd.Timestamp("2026-01-03"),
    )

    assert result["date"].tolist() == [
        pd.Timestamp("2026-01-02"),
        pd.Timestamp("2026-01-03"),
    ]


def test_join_history_to_climatology_adds_expected_climatology_columns():
    history_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
            "region_id": [1, 1],
            "day_of_year": [1, 2],
            "mean_sst_c": [20.0, 21.0],
        }
    )

    climatology_df = pd.DataFrame(
        {
            "region_id": [1, 1],
            "day_of_year": [1, 2],
            "clim_mean_sst_c": [19.0, 20.0],
            "clim_p90_sst_c": [19.5, 21.5],
            "sample_size": [30, 30],
        }
    )

    result = join_history_to_climatology(history_df, climatology_df)

    assert result["clim_mean_sst_c"].tolist() == [19.0, 20.0]
    assert result["clim_p90_sst_c"].tolist() == [19.5, 21.5]
    assert result["sample_size"].tolist() == [30, 30]


def test_join_history_to_climatology_rejects_duplicate_climatology_keys():
    history_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01"]),
            "region_id": [1],
            "day_of_year": [1],
            "mean_sst_c": [20.0],
        }
    )

    climatology_df = pd.DataFrame(
        {
            "region_id": [1, 1],
            "day_of_year": [1, 1],
            "clim_mean_sst_c": [19.0, 19.1],
            "clim_p90_sst_c": [19.5, 19.6],
            "sample_size": [30, 30],
        }
    )

    with pytest.raises(pd.errors.MergeError):
        join_history_to_climatology(history_df, climatology_df)


def test_calculate_anomalies_core_metrics_and_status_labels():
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-02",
                    "2026-01-03",
                    "2026-01-04",
                    "2026-01-05",
                    "2026-01-06",
                    "2026-01-07",
                    "2026-01-08",
                ]
            ),
            "region_id": [1] * 8,
            "region_code": ["north"] * 8,
            "region_name": ["North"] * 8,
            "day_of_year": list(range(1, 9)),
            "mean_sst_c": [20.0, 20.5, 21.0, 21.5, 22.0, 22.5, 23.0, 24.0],
            "cell_count": [100] * 8,
            "min_sst_c": [19.0] * 8,
            "max_sst_c": [25.0] * 8,
            "clim_mean_sst_c": [19.0] * 8,
            "clim_p90_sst_c": [20.0, 20.0, 20.0, 22.0, 22.0, 22.0, 22.0, 22.0],
            "sample_size": [30] * 8,
        }
    )

    result = calculate_anomalies(df)

    assert result["anomaly_c"].tolist() == [
        1.0,
        1.5,
        2.0,
        2.5,
        3.0,
        3.5,
        4.0,
        5.0,
    ]

    assert result["above_p90"].tolist() == [
        False,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
    ]

    assert result.loc[0, "rolling_7d_anomaly_c"] == pytest.approx(1.0)
    assert result.loc[6, "rolling_7d_anomaly_c"] == pytest.approx(2.5)
    assert result.loc[7, "rolling_7d_anomaly_c"] == pytest.approx(21.5 / 7)

    assert pd.isna(result.loc[0, "warming_rate_7d_c"])
    assert result.loc[7, "warming_rate_7d_c"] == pytest.approx(4.0)

    assert result["status_label"].tolist() == [
        "Hot",
        "Extreme",
        "Extreme",
        "Extreme",
        "Extreme",
        "Extreme",
        "Extreme",
        "Extreme",
    ]


def test_classify_status_thresholds():
    assert classify_status(float("nan")) == "Unknown"
    assert classify_status(0.49) == "Normal"
    assert classify_status(0.50) == "Watch"
    assert classify_status(1.00) == "Hot"
    assert classify_status(1.50) == "Extreme"


def test_parse_iso_date_accepts_valid_date_and_rejects_invalid_date():
    assert parse_iso_date("2026-03-01") == pd.Timestamp("2026-03-01")

    with pytest.raises(Exception):
        parse_iso_date("01-03-2026")
