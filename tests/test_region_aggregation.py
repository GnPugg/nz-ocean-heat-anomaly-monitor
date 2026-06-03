from datetime import date

import pandas as pd
import pytest

from nzheat.transform.region_aggregate import (
    aggregate_region_daily_sst,
    prepare_for_aggregation,
)


def test_prepare_for_aggregation_drops_unmatched_or_missing_sst_rows():
    df = pd.DataFrame(
        {
            "time": [
                "2026-03-01 12:00:00",
                "2026-03-01 12:00:00",
                "2026-03-01 12:00:00",
                "2026-03-01 12:00:00",
            ],
            "region_id": [1, None, 2, 3],
            "region_code": ["north", None, "south", "east"],
            "region_name": ["North", None, "South", "East"],
            "sst": [18.0, 19.0, None, 20.0],
        }
    )

    result = prepare_for_aggregation(df)

    assert len(result) == 2
    assert result["region_id"].tolist() == [1, 3]
    assert result["date"].tolist() == [
        date(2026, 3, 1),
        date(2026, 3, 1),
    ]


def test_aggregate_region_daily_sst_calculates_summary_metrics():
    df = pd.DataFrame(
        {
            "date": [
                date(2026, 3, 1),
                date(2026, 3, 1),
                date(2026, 3, 1),
            ],
            "region_id": [1, 1, 2],
            "region_code": ["north", "north", "south"],
            "region_name": ["North", "North", "South"],
            "sst": [10.0, 12.0, 20.0],
        }
    )

    result = aggregate_region_daily_sst(df)
    result = result.sort_values(["date", "region_id"]).reset_index(drop=True)

    assert len(result) == 2

    assert result.loc[0, "region_id"] == 1
    assert result.loc[0, "region_code"] == "north"
    assert result.loc[0, "region_name"] == "North"
    assert result.loc[0, "mean_sst_c"] == pytest.approx(11.0)
    assert result.loc[0, "cell_count"] == 2
    assert result.loc[0, "min_sst_c"] == pytest.approx(10.0)
    assert result.loc[0, "max_sst_c"] == pytest.approx(12.0)

    assert result.loc[1, "region_id"] == 2
    assert result.loc[1, "mean_sst_c"] == pytest.approx(20.0)
    assert result.loc[1, "cell_count"] == 1
    assert result.loc[1, "min_sst_c"] == pytest.approx(20.0)
    assert result.loc[1, "max_sst_c"] == pytest.approx(20.0)


def test_aggregate_region_daily_sst_converts_region_id_to_integer():
    df = pd.DataFrame(
        {
            "date": [date(2026, 3, 1)],
            "region_id": [1.0],
            "region_code": ["north"],
            "region_name": ["North"],
            "sst": [18.5],
        }
    )

    result = aggregate_region_daily_sst(df)

    assert result["region_id"].dtype == "int64"
