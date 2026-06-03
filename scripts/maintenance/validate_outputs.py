from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

BASE = Path("data/processed")

SST_PATH = BASE / "region_daily_sst_history.parquet"
ANOM_PATH = BASE / "region_daily_anomalies.parquet"
EVENTS_PATH = BASE / "heat_events.parquet"
CLIM_PATH = BASE / "region_climatology.parquet"

EXPECTED_REGION_COUNT = 6
EXPECTED_CLIMATOLOGY_DAYS = 365


def add_error(errors: list[str], message: str) -> None:
    """Record a validation error and print it clearly."""
    errors.append(message)
    print(f"VALIDATION ERROR: {message}")


def load_parquet(path: Path, label: str, errors: list[str]) -> pd.DataFrame | None:
    """Load a parquet file, recording a validation error if it is missing/unreadable."""
    if not path.exists():
        add_error(errors, f"{label} file is missing: {path}")
        return None

    try:
        return pd.read_parquet(path)
    except Exception as exc:
        add_error(errors, f"{label} file could not be read: {path}. Error: {exc}")
        return None


def require_columns(
    df: pd.DataFrame,
    required_columns: list[str],
    label: str,
    errors: list[str],
) -> bool:
    """Check that a dataframe contains required columns."""
    missing = [col for col in required_columns if col not in df.columns]

    if missing:
        add_error(errors, f"{label} is missing required columns: {missing}")
        return False

    return True


def check_sst_history(
    errors: list[str],
) -> tuple[pd.DataFrame | None, pd.DatetimeIndex | None, list[int]]:
    """Validate regional daily SST history output."""
    sst = load_parquet(SST_PATH, "SST history", errors)

    if sst is None:
        return None, None, []

    required_columns = [
        "date",
        "region_id",
        "region_code",
        "region_name",
        "mean_sst_c",
        "cell_count",
        "min_sst_c",
        "max_sst_c",
    ]

    if not require_columns(sst, required_columns, "SST history", errors):
        return None, None, []

    sst = sst.copy()
    sst["date"] = pd.to_datetime(sst["date"])

    print("\n--- SST HISTORY ---")
    print("Rows:", len(sst))
    print("Date range:", sst["date"].min().date(), "to", sst["date"].max().date())
    print("Regions:", sorted(sst["region_code"].unique()))
    print("Number of regions:", sst["region_code"].nunique())
    print("Number of dates:", sst["date"].nunique())

    if sst.empty:
        add_error(errors, "SST history is empty.")
        return sst, None, []

    region_count = sst["region_id"].nunique()

    if region_count != EXPECTED_REGION_COUNT:
        add_error(
            errors,
            f"SST history has {region_count} regions; expected {EXPECTED_REGION_COUNT}.",
        )

    duplicates = int(sst.duplicated(subset=["date", "region_id"]).sum())
    print("Duplicate date-region rows:", duplicates)

    if duplicates > 0:
        add_error(errors, f"SST history has {duplicates} duplicate date-region rows.")

    all_dates = pd.date_range(
        sst["date"].min().normalize(),
        sst["date"].max().normalize(),
        freq="D",
    )

    existing_dates = pd.DatetimeIndex(sst["date"].dt.normalize().unique())
    missing_dates = sorted(set(all_dates) - set(existing_dates))

    print("Missing complete dates:", len(missing_dates))

    for missing_date in missing_dates:
        print("  ", missing_date.date())

    if missing_dates:
        add_error(
            errors,
            f"SST history has {len(missing_dates)} missing complete date(s).",
        )

    expected_regions = sorted(sst["region_id"].unique())

    expected = pd.MultiIndex.from_product(
        [all_dates, expected_regions],
        names=["date", "region_id"],
    ).to_frame(index=False)

    actual = sst[["date", "region_id"]].copy()
    actual["date"] = actual["date"].dt.normalize()

    missing_region_dates = expected.merge(
        actual,
        on=["date", "region_id"],
        how="left",
        indicator=True,
    ).query("_merge == 'left_only'")

    print("Missing region-date combinations:", len(missing_region_dates))

    if len(missing_region_dates) > 0:
        print(missing_region_dates.head(20))
        add_error(
            errors,
            f"SST history has {len(missing_region_dates)} missing region-date combination(s).",
        )

    missing_sst_values = int(
        sst[["mean_sst_c", "cell_count", "min_sst_c", "max_sst_c"]]
        .isna()
        .any(axis=1)
        .sum()
    )

    if missing_sst_values > 0:
        add_error(
            errors,
            f"SST history has {missing_sst_values} rows with missing SST values.",
        )

    return sst, all_dates, expected_regions


def check_climatology(
    expected_regions: list[int], errors: list[str]
) -> pd.DataFrame | None:
    """Validate regional climatology output."""
    clim = load_parquet(CLIM_PATH, "Climatology", errors)

    if clim is None:
        return None

    required_columns = [
        "region_id",
        "region_code",
        "region_name",
        "day_of_year",
        "clim_mean_sst_c",
        "clim_p90_sst_c",
        "sample_size",
    ]

    if not require_columns(clim, required_columns, "Climatology", errors):
        return None

    print("\n--- CLIMATOLOGY ---")
    print("Rows:", len(clim))

    expected_rows = len(expected_regions) * EXPECTED_CLIMATOLOGY_DAYS

    print(
        "Expected rows if 6 regions x 365 days:",
        EXPECTED_REGION_COUNT * EXPECTED_CLIMATOLOGY_DAYS,
    )
    print("Expected rows based on SST regions:", expected_rows)
    print(
        "Day-of-year range:", clim["day_of_year"].min(), "to", clim["day_of_year"].max()
    )
    print("Min sample size:", clim["sample_size"].min())
    print("Max sample size:", clim["sample_size"].max())

    if len(clim) != expected_rows:
        add_error(
            errors,
            f"Climatology has {len(clim)} rows; expected {expected_rows}.",
        )

    if clim["day_of_year"].min() != 1 or clim["day_of_year"].max() != 365:
        add_error(errors, "Climatology day_of_year range should be 1 to 365.")

    duplicates = int(clim.duplicated(subset=["region_id", "day_of_year"]).sum())

    if duplicates > 0:
        add_error(
            errors,
            f"Climatology has {duplicates} duplicate region/day_of_year rows.",
        )

    missing_clim = clim[clim[["clim_mean_sst_c", "clim_p90_sst_c"]].isna().any(axis=1)]

    print("Rows with missing climatology values:", len(missing_clim))

    if len(missing_clim) > 0:
        add_error(
            errors,
            f"Climatology has {len(missing_clim)} rows with missing climatology values.",
        )

    if clim["sample_size"].isna().any():
        add_error(errors, "Climatology has missing sample_size values.")

    if (clim["sample_size"] <= 0).any():
        add_error(
            errors, "Climatology has sample_size values less than or equal to zero."
        )

    return clim


def check_anomalies(
    sst: pd.DataFrame | None,
    expected_regions: list[int],
    errors: list[str],
) -> pd.DataFrame | None:
    """Validate daily anomaly output."""
    anom = load_parquet(ANOM_PATH, "Anomalies", errors)

    if anom is None:
        return None

    required_columns = [
        "date",
        "region_id",
        "region_code",
        "region_name",
        "day_of_year",
        "mean_sst_c",
        "cell_count",
        "min_sst_c",
        "max_sst_c",
        "clim_mean_sst_c",
        "clim_p90_sst_c",
        "sample_size",
        "anomaly_c",
        "rolling_7d_anomaly_c",
        "rolling_30d_anomaly_c",
        "warming_rate_7d_c",
        "above_p90",
        "status_label",
    ]

    if not require_columns(anom, required_columns, "Anomalies", errors):
        return None

    anom = anom.copy()
    anom["date"] = pd.to_datetime(anom["date"])

    print("\n--- ANOMALIES ---")
    print("Rows:", len(anom))
    print("Date range:", anom["date"].min().date(), "to", anom["date"].max().date())

    duplicate_count = int(anom.duplicated(subset=["date", "region_id"]).sum())

    if duplicate_count > 0:
        add_error(
            errors, f"Anomalies have {duplicate_count} duplicate date-region rows."
        )

    missing_anomaly_count = int(anom["anomaly_c"].isna().sum())
    missing_p90_count = int(anom["above_p90"].isna().sum())

    print("Rows with missing anomaly:", missing_anomaly_count)
    print("Rows with missing p90 flag:", missing_p90_count)

    if missing_anomaly_count > 0:
        add_error(
            errors,
            f"Anomalies have {missing_anomaly_count} rows with missing anomaly_c.",
        )

    if missing_p90_count > 0:
        add_error(
            errors, f"Anomalies have {missing_p90_count} rows with missing above_p90."
        )

    if sst is not None:
        if len(anom) != len(sst):
            add_error(
                errors,
                f"Anomalies have {len(anom)} rows but SST history has {len(sst)} rows.",
            )

        if anom["date"].min().normalize() != sst["date"].min().normalize():
            add_error(
                errors, "Anomaly minimum date does not match SST history minimum date."
            )

        if anom["date"].max().normalize() != sst["date"].max().normalize():
            add_error(
                errors, "Anomaly maximum date does not match SST history maximum date."
            )

    latest_date = anom["date"].max()
    latest = anom[anom["date"] == latest_date].copy()

    print("\nLatest available date:", latest_date.date())
    print("Rows on latest date:", len(latest))
    print("Regions above p90 on latest date:", int(latest["above_p90"].sum()))

    if len(latest) != len(expected_regions):
        add_error(
            errors,
            f"Latest anomaly date has {len(latest)} rows; expected {len(expected_regions)}.",
        )

    print("\nLatest-date regional status:")
    print(
        latest[
            [
                "region_code",
                "mean_sst_c",
                "clim_mean_sst_c",
                "clim_p90_sst_c",
                "anomaly_c",
                "above_p90",
                "status_label",
            ]
        ].sort_values("anomaly_c", ascending=False)
    )

    return anom


def check_events(anom: pd.DataFrame | None, errors: list[str]) -> pd.DataFrame | None:
    """Validate heat event output."""
    events = load_parquet(EVENTS_PATH, "Heat events", errors)

    if events is None:
        return None

    required_columns = [
        "event_id",
        "region_id",
        "region_code",
        "region_name",
        "event_type",
        "severity_class",
        "start_date",
        "end_date",
        "duration_days",
        "max_anomaly_c",
        "mean_anomaly_c",
        "max_exceedance_p90_c",
        "mean_exceedance_p90_c",
        "peak_date",
        "is_active",
        "threshold_c",
        "min_duration_days",
    ]

    if not require_columns(events, required_columns, "Heat events", errors):
        return None

    print("\n--- HEAT EVENTS ---")
    print("Rows:", len(events))

    if len(events) == 0:
        print("No heat events detected.")
        return events

    events = events.copy()
    events["start_date"] = pd.to_datetime(events["start_date"])
    events["end_date"] = pd.to_datetime(events["end_date"])
    events["peak_date"] = pd.to_datetime(events["peak_date"])

    duplicate_events = int(events.duplicated(subset=["event_id"]).sum())

    if duplicate_events > 0:
        add_error(
            errors, f"Heat events have {duplicate_events} duplicate event_id rows."
        )

    bad_date_order = events[events["start_date"] > events["end_date"]]

    if len(bad_date_order) > 0:
        add_error(
            errors,
            f"Heat events have {len(bad_date_order)} rows where start_date > end_date.",
        )

    bad_peak_dates = events[
        (events["peak_date"] < events["start_date"])
        | (events["peak_date"] > events["end_date"])
    ]

    if len(bad_peak_dates) > 0:
        add_error(
            errors,
            f"Heat events have {len(bad_peak_dates)} rows where peak_date is outside the event range.",
        )

    bad_duration = events[events["duration_days"] <= 0]

    if len(bad_duration) > 0:
        add_error(
            errors,
            f"Heat events have {len(bad_duration)} rows with duration_days <= 0.",
        )

    print(
        "Date range:",
        events["start_date"].min().date(),
        "to",
        events["end_date"].max().date(),
    )

    active_events = events[events["is_active"] == True].copy()
    print("Active events:", int(len(active_events)))

    if anom is not None and len(active_events) > 0:
        latest_anomaly_date = anom["date"].max().normalize()

        active_not_latest = active_events[
            active_events["end_date"].dt.normalize() != latest_anomaly_date
        ]

        if len(active_not_latest) > 0:
            add_error(
                errors,
                "Some active heat events do not end on the latest anomaly date.",
            )

    print("\nActive events table:")
    print(
        active_events[
            [
                "region_code",
                "start_date",
                "end_date",
                "duration_days",
                "max_anomaly_c",
                "mean_anomaly_c",
                "severity_class",
            ]
        ]
    )

    return events


def main() -> int:
    errors: list[str] = []

    print("\n=== CHECKING PROCESSED OUTPUTS ===")

    sst, _all_dates, expected_regions = check_sst_history(errors)
    check_climatology(expected_regions, errors)
    anom = check_anomalies(sst, expected_regions, errors)
    check_events(anom, errors)

    if errors:
        print("\n=== VALIDATION FAILED ===")
        print(f"{len(errors)} issue(s) found:")

        for index, error in enumerate(errors, start=1):
            print(f"{index}. {error}")

        return 1

    print("\n=== VALIDATION PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
