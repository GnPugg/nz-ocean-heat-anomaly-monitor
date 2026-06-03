import pandas as pd
import pytest

from nzheat.analytics.events import (
    add_event_flags,
    assign_event_groups,
    classify_event_severity,
    empty_events_df,
    prepare_anomalies,
    summarize_events,
)


def make_anomaly_rows(
    dates,
    above_p90,
    region_id=1,
    region_code="north",
    region_name="North",
    exceedances=None,
):
    if exceedances is None:
        exceedances = [0.8 if flag else -0.2 for flag in above_p90]

    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "region_id": [region_id] * len(dates),
            "region_code": [region_code] * len(dates),
            "region_name": [region_name] * len(dates),
            "mean_sst_c": [20.0 + value for value in exceedances],
            "clim_p90_sst_c": [20.0] * len(dates),
            "anomaly_c": exceedances,
            "above_p90": above_p90,
        }
    )


def prepare_grouped_events(df):
    prepared = prepare_anomalies(df)
    flagged = add_event_flags(prepared, anomaly_threshold=0.0)
    grouped = assign_event_groups(flagged)
    return grouped


def test_prepare_anomalies_sorts_rows_and_calculates_p90_exceedance():
    df = make_anomaly_rows(
        dates=["2026-01-03", "2026-01-01", "2026-01-02"],
        above_p90=[True, False, True],
        exceedances=[1.0, -0.5, 0.7],
    )

    result = prepare_anomalies(df)

    assert result["date"].tolist() == [
        pd.Timestamp("2026-01-01"),
        pd.Timestamp("2026-01-02"),
        pd.Timestamp("2026-01-03"),
    ]

    assert result["exceedance_p90_c"].tolist() == pytest.approx([-0.5, 0.7, 1.0])


def test_add_event_flags_uses_above_p90_boolean_rule():
    df = make_anomaly_rows(
        dates=["2026-01-01", "2026-01-02", "2026-01-03"],
        above_p90=[True, False, None],
    )

    prepared = prepare_anomalies(df)
    result = add_event_flags(prepared, anomaly_threshold=999.0)

    assert result["is_event_day"].tolist() == [True, False, False]


def test_assign_event_groups_splits_when_event_flag_changes():
    df = make_anomaly_rows(
        dates=[
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
        ],
        above_p90=[False, True, True, False, True],
    )

    grouped = prepare_grouped_events(df)

    # Expected groups:
    # Jan 1 false
    # Jan 2-3 true
    # Jan 4 false
    # Jan 5 true
    assert grouped["event_group_id"].nunique() == 4


def test_assign_event_groups_splits_when_date_gap_exists():
    df = make_anomaly_rows(
        dates=[
            "2026-01-01",
            "2026-01-02",
            "2026-01-05",
            "2026-01-06",
        ],
        above_p90=[True, True, True, True],
    )

    grouped = prepare_grouped_events(df)

    # Jan 1-2 and Jan 5-6 should be separate events because Jan 3-4 are missing.
    assert grouped["event_group_id"].nunique() == 2


def test_summarize_events_keeps_only_events_meeting_min_duration():
    df = make_anomaly_rows(
        dates=pd.date_range("2026-01-01", periods=8, freq="D"),
        above_p90=[True, True, True, True, True, False, True, True],
        exceedances=[0.5, 0.8, 1.2, 1.8, 2.2, -0.2, 0.7, 0.9],
    )

    grouped = prepare_grouped_events(df)

    events = summarize_events(
        grouped,
        min_duration_days=5,
        anomaly_threshold=0.0,
    )

    assert len(events) == 1
    assert events.loc[0, "start_date"] == pd.Timestamp("2026-01-01")
    assert events.loc[0, "end_date"] == pd.Timestamp("2026-01-05")
    assert events.loc[0, "duration_days"] == 5
    assert events.loc[0, "peak_date"] == pd.Timestamp("2026-01-05")
    assert events.loc[0, "max_exceedance_p90_c"] == pytest.approx(2.2)
    assert events.loc[0, "severity_class"] == "Extreme"
    assert events.loc[0, "event_type"] == "warm_event"


def test_summarize_events_marks_event_active_when_it_ends_on_latest_date():
    df = make_anomaly_rows(
        dates=pd.date_range("2026-01-01", periods=5, freq="D"),
        above_p90=[True, True, True, True, True],
        exceedances=[0.5, 0.6, 0.7, 0.8, 0.9],
    )

    grouped = prepare_grouped_events(df)

    events = summarize_events(
        grouped,
        min_duration_days=5,
        anomaly_threshold=0.0,
    )

    assert len(events) == 1
    assert events.loc[0, "is_active"] is True or events.loc[0, "is_active"] == True


def test_summarize_events_separates_regions():
    region_1 = make_anomaly_rows(
        dates=pd.date_range("2026-01-01", periods=5, freq="D"),
        above_p90=[True, True, True, True, True],
        region_id=1,
        region_code="north",
        region_name="North",
    )

    region_2 = make_anomaly_rows(
        dates=pd.date_range("2026-01-01", periods=5, freq="D"),
        above_p90=[True, True, True, True, True],
        region_id=2,
        region_code="south",
        region_name="South",
    )

    df = pd.concat([region_2, region_1], ignore_index=True)
    grouped = prepare_grouped_events(df)

    events = summarize_events(
        grouped,
        min_duration_days=5,
        anomaly_threshold=0.0,
    )

    assert len(events) == 2
    assert events["region_id"].tolist() == [1, 2]


def test_summarize_events_returns_empty_schema_when_no_event_meets_duration():
    df = make_anomaly_rows(
        dates=pd.date_range("2026-01-01", periods=4, freq="D"),
        above_p90=[True, True, True, True],
    )

    grouped = prepare_grouped_events(df)

    events = summarize_events(
        grouped,
        min_duration_days=5,
        anomaly_threshold=0.0,
    )

    expected_columns = empty_events_df().columns.tolist()

    assert events.empty
    assert events.columns.tolist() == expected_columns


def test_classify_event_severity_thresholds():
    assert classify_event_severity(float("nan")) == "Unknown"
    assert classify_event_severity(0.0) == "Threshold-only"
    assert classify_event_severity(0.1) == "Weak"
    assert classify_event_severity(0.5) == "Moderate"
    assert classify_event_severity(1.0) == "Severe"
    assert classify_event_severity(2.0) == "Extreme"
