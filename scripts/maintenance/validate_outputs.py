from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

from nzheat.utils.paths import find_project_root

PROJECT_ROOT = find_project_root()
BASE = PROJECT_ROOT / "data" / "processed"

SST_PATH = BASE / "region_daily_sst_history.parquet"
ANOM_PATH = BASE / "region_daily_anomalies.parquet"
EVENTS_PATH = BASE / "heat_events.parquet"
CLIM_PATH = BASE / "region_climatology.parquet"

PRELIM_SST_PATH = BASE / "region_daily_sst_recent_prelim.parquet"
PRELIM_ANOM_PATH = BASE / "region_daily_anomalies_recent_prelim.parquet"
PRELIM_EVENTS_PATH = BASE / "heat_events_recent_prelim.parquet"
MONITORING_ANOM_PATH = BASE / "region_daily_anomalies_monitoring.parquet"

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



def check_preliminary_outputs(errors: list[str]) -> pd.DataFrame | None:
    """Validate preliminary SST, anomaly, and event outputs as one dataset."""
    prelim_sst = load_parquet(PRELIM_SST_PATH, "Preliminary SST", errors)
    prelim_anom = load_parquet(PRELIM_ANOM_PATH, "Preliminary anomalies", errors)
    prelim_events = load_parquet(PRELIM_EVENTS_PATH, "Preliminary heat events", errors)

    if prelim_sst is None or prelim_anom is None or prelim_events is None:
        return prelim_anom

    sst_columns = [
        "date",
        "region_id",
        "region_code",
        "region_name",
        "mean_sst_c",
        "cell_count",
        "min_sst_c",
        "max_sst_c",
        "data_product",
        "is_provisional",
    ]
    anomaly_columns = [
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
        "data_product",
        "is_provisional",
    ]
    event_columns = [
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
        "data_product",
        "is_provisional",
    ]

    columns_ok = all(
        [
            require_columns(prelim_sst, sst_columns, "Preliminary SST", errors),
            require_columns(
                prelim_anom, anomaly_columns, "Preliminary anomalies", errors
            ),
            require_columns(
                prelim_events, event_columns, "Preliminary heat events", errors
            ),
        ]
    )

    if not columns_ok:
        return prelim_anom

    prelim_sst = prelim_sst.copy()
    prelim_anom = prelim_anom.copy()
    prelim_events = prelim_events.copy()
    prelim_sst["date"] = pd.to_datetime(prelim_sst["date"])
    prelim_anom["date"] = pd.to_datetime(prelim_anom["date"])

    print("\n--- PRELIMINARY OUTPUTS ---")
    print("SST rows:", len(prelim_sst))
    print("Anomaly rows:", len(prelim_anom))
    print("Event rows:", len(prelim_events))

    if prelim_sst.empty:
        add_error(errors, "Preliminary SST is empty.")
    if prelim_anom.empty:
        add_error(errors, "Preliminary anomalies are empty.")

    for label, df in [
        ("Preliminary SST", prelim_sst),
        ("Preliminary anomalies", prelim_anom),
    ]:
        duplicate_count = int(df.duplicated(subset=["date", "region_id"]).sum())
        if duplicate_count:
            add_error(
                errors,
                f"{label} has {duplicate_count} duplicate date-region rows.",
            )

        if not df.empty and df["region_id"].nunique() != EXPECTED_REGION_COUNT:
            add_error(
                errors,
                f"{label} has {df['region_id'].nunique()} regions; "
                f"expected {EXPECTED_REGION_COUNT}.",
            )

        if not (df["data_product"] == "preliminary").all():
            add_error(errors, f"{label} contains non-preliminary data_product values.")

        if not df["is_provisional"].astype(bool).all():
            add_error(errors, f"{label} contains rows not marked provisional.")

    sst_keys = pd.MultiIndex.from_frame(prelim_sst[["date", "region_id"]])
    anomaly_keys = pd.MultiIndex.from_frame(prelim_anom[["date", "region_id"]])

    missing_anomaly_keys = sst_keys.difference(anomaly_keys)
    extra_anomaly_keys = anomaly_keys.difference(sst_keys)

    if len(missing_anomaly_keys):
        add_error(
            errors,
            f"Preliminary anomalies are missing {len(missing_anomaly_keys)} "
            "SST date-region rows.",
        )
    if len(extra_anomaly_keys):
        add_error(
            errors,
            f"Preliminary anomalies contain {len(extra_anomaly_keys)} unexpected "
            "date-region rows.",
        )

    if not prelim_anom.empty:
        latest_date = prelim_anom["date"].max()
        latest_rows = prelim_anom.loc[prelim_anom["date"] == latest_date]
        if len(latest_rows) != EXPECTED_REGION_COUNT:
            add_error(
                errors,
                f"Latest preliminary anomaly date has {len(latest_rows)} rows; "
                f"expected {EXPECTED_REGION_COUNT}.",
            )

    if not prelim_events.empty:
        if int(prelim_events.duplicated(subset=["event_id"]).sum()):
            add_error(errors, "Preliminary heat events contain duplicate event_id rows.")

        for column in ["start_date", "end_date", "peak_date"]:
            prelim_events[column] = pd.to_datetime(prelim_events[column])

        if (prelim_events["start_date"] > prelim_events["end_date"]).any():
            add_error(
                errors,
                "Preliminary heat events contain start_date values after end_date.",
            )

        invalid_peaks = (
            (prelim_events["peak_date"] < prelim_events["start_date"])
            | (prelim_events["peak_date"] > prelim_events["end_date"])
        )
        if invalid_peaks.any():
            add_error(
                errors,
                "Preliminary heat events contain peak dates outside their event range.",
            )

        if not (prelim_events["data_product"] == "preliminary").all():
            add_error(
                errors,
                "Preliminary heat events contain non-preliminary data_product values.",
            )
        if not prelim_events["is_provisional"].astype(bool).all():
            add_error(
                errors,
                "Preliminary heat events contain rows not marked provisional.",
            )

    return prelim_anom


def check_monitoring_output(
    final_anom: pd.DataFrame | None,
    prelim_anom: pd.DataFrame | None,
    errors: list[str],
) -> pd.DataFrame | None:
    """Validate the combined final/preliminary monitoring anomaly output."""
    monitoring = load_parquet(
        MONITORING_ANOM_PATH, "Monitoring anomalies", errors
    )

    if monitoring is None:
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
        "data_product",
        "is_provisional",
    ]

    if not require_columns(
        monitoring, required_columns, "Monitoring anomalies", errors
    ):
        return None

    monitoring = monitoring.copy()
    monitoring["date"] = pd.to_datetime(monitoring["date"])

    print("\n--- MONITORING ANOMALIES ---")
    print("Rows:", len(monitoring))
    if not monitoring.empty:
        print(
            "Date range:",
            monitoring["date"].min().date(),
            "to",
            monitoring["date"].max().date(),
        )
        print("Rows by data product:")
        print(monitoring["data_product"].value_counts(dropna=False))

    if monitoring.empty:
        add_error(errors, "Monitoring anomalies are empty.")
        return monitoring

    duplicate_count = int(
        monitoring.duplicated(subset=["date", "region_id"]).sum()
    )
    if duplicate_count:
        add_error(
            errors,
            f"Monitoring anomalies have {duplicate_count} duplicate date-region rows.",
        )

    allowed_products = {"final", "preliminary"}
    unexpected_products = set(monitoring["data_product"].dropna().unique()) - allowed_products
    if unexpected_products:
        add_error(
            errors,
            f"Monitoring anomalies contain unexpected data products: "
            f"{sorted(unexpected_products)}.",
        )

    inconsistent_flags = monitoring[
        ((monitoring["data_product"] == "final") & monitoring["is_provisional"].astype(bool))
        | (
            (monitoring["data_product"] == "preliminary")
            & ~monitoring["is_provisional"].astype(bool)
        )
    ]
    if not inconsistent_flags.empty:
        add_error(
            errors,
            f"Monitoring anomalies have {len(inconsistent_flags)} rows with "
            "inconsistent product/provisional metadata.",
        )

    if final_anom is not None and prelim_anom is not None:
        final_expected = final_anom[["date", "region_id"]].copy()
        final_expected["date"] = pd.to_datetime(final_expected["date"])
        final_expected["expected_product"] = "final"
        final_expected["priority"] = 0

        prelim_expected = prelim_anom[["date", "region_id"]].copy()
        prelim_expected["date"] = pd.to_datetime(prelim_expected["date"])
        prelim_expected["expected_product"] = "preliminary"
        prelim_expected["priority"] = 1

        expected = pd.concat([final_expected, prelim_expected], ignore_index=True)
        expected = expected.sort_values(["region_id", "date", "priority"])
        expected = expected.drop_duplicates(["date", "region_id"], keep="last")
        expected = expected.drop(columns=["priority"])

        comparison = expected.merge(
            monitoring[["date", "region_id", "data_product"]],
            on=["date", "region_id"],
            how="outer",
            indicator=True,
        )

        missing_rows = comparison[comparison["_merge"] == "left_only"]
        extra_rows = comparison[comparison["_merge"] == "right_only"]
        product_mismatches = comparison[
            (comparison["_merge"] == "both")
            & (comparison["expected_product"] != comparison["data_product"])
        ]

        if not missing_rows.empty:
            add_error(
                errors,
                f"Monitoring anomalies are missing {len(missing_rows)} expected rows.",
            )
        if not extra_rows.empty:
            add_error(
                errors,
                f"Monitoring anomalies contain {len(extra_rows)} unexpected rows.",
            )
        if not product_mismatches.empty:
            add_error(
                errors,
                f"Monitoring anomalies have {len(product_mismatches)} rows with "
                "the wrong source priority.",
            )

    return monitoring

def main(
    *,
    skip_preliminary: bool = False,
    skip_monitoring: bool = False,
) -> int:
    errors: list[str] = []

    print("\n=== CHECKING PROCESSED OUTPUTS ===")

    sst, _all_dates, expected_regions = check_sst_history(errors)
    check_climatology(expected_regions, errors)
    anom = check_anomalies(sst, expected_regions, errors)
    check_events(anom, errors)

    prelim_anom: pd.DataFrame | None = None
    if skip_preliminary:
        print("\nSkipping preliminary output validation.")
    else:
        prelim_anom = check_preliminary_outputs(errors)

    if skip_monitoring:
        print("\nSkipping monitoring output validation.")
    else:
        check_monitoring_output(anom, prelim_anom, errors)

    if errors:
        print("\n=== VALIDATION FAILED ===")
        print(f"{len(errors)} issue(s) found:")

        for index, error in enumerate(errors, start=1):
            print(f"{index}. {error}")

        return 1

    print("\n=== VALIDATION PASSED ===")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate final, preliminary, and monitoring pipeline outputs.",
    )
    parser.add_argument(
        "--skip-preliminary",
        action="store_true",
        help="Skip validation of preliminary SST, anomaly, and event outputs.",
    )
    parser.add_argument(
        "--skip-monitoring",
        action="store_true",
        help="Skip validation of the combined monitoring anomalies output.",
    )
    args = parser.parse_args()

    sys.exit(
        main(
            skip_preliminary=args.skip_preliminary,
            skip_monitoring=args.skip_monitoring,
        )
    )
