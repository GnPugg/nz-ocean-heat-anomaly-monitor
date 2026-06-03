from __future__ import annotations

from pathlib import Path
import argparse
import uuid
import logging

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_INPUT_FILE = Path("data/processed/region_daily_anomalies.parquet")
DEFAULT_OUTPUT_FILE = Path("data/processed/heat_events.parquet")

# Event rule:
# - above the regional climatology p90 threshold
# - sustained for at least 5 consecutive days
DEFAULT_ANOMALY_THRESHOLD = 0.0
DEFAULT_MIN_DURATION_DAYS = 5


def load_anomalies(input_path: Path) -> pd.DataFrame:
    """Load the daily regional anomaly table."""
    return pd.read_parquet(input_path)


def prepare_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare anomaly data for event detection.

    Steps:
    - ensure date is datetime
    - sort by region and date
    - calculate exceedance above the p90 climatology threshold
    """
    prepared = df.copy()
    prepared["date"] = pd.to_datetime(prepared["date"])
    prepared = prepared.sort_values(["region_id", "date"]).reset_index(drop=True)
    prepared["exceedance_p90_c"] = prepared["mean_sst_c"] - prepared["clim_p90_sst_c"]
    return prepared


def add_event_flags(df: pd.DataFrame, anomaly_threshold: float) -> pd.DataFrame:
    """
    Create a boolean warm-event candidate flag based on p90 threshold exceedance.

    anomaly_threshold is kept in the signature so the CLI/main flow does not break,
    even though the current rule uses above_p90 rather than anomaly_c.
    """
    flagged = df.copy()
    flagged["is_event_day"] = flagged["above_p90"].fillna(False).astype(bool)
    return flagged


def assign_event_groups(df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign consecutive-day group ids within each region.

    A new group starts whenever:
    - the region changes
    - the event flag changes
    - or the date gap is more than 1 day
    """
    grouped = df.copy()

    grouped["prev_region_id"] = grouped["region_id"].shift(1)
    grouped["prev_is_event_day"] = grouped["is_event_day"].shift(1)
    grouped["prev_date"] = grouped["date"].shift(1)

    grouped["date_gap_days"] = (grouped["date"] - grouped["prev_date"]).dt.days

    new_group = (
        (grouped["region_id"] != grouped["prev_region_id"])
        | (grouped["is_event_day"] != grouped["prev_is_event_day"])
        | (grouped["date_gap_days"] != 1)
    )

    grouped["event_group_id"] = new_group.cumsum()
    return grouped


def empty_events_df() -> pd.DataFrame:
    """Return an empty heat-events dataframe with the expected schema."""
    return pd.DataFrame(
        columns=[
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
    )


def summarize_events(
    df: pd.DataFrame,
    min_duration_days: int,
    anomaly_threshold: float,
) -> pd.DataFrame:
    """
    Summarize sustained warm events from grouped anomaly rows.

    Keeps only groups where:
    - is_event_day is True
    - duration >= min_duration_days
    """
    event_days = df.loc[df["is_event_day"]].copy()

    if event_days.empty:
        return empty_events_df()

    summary = event_days.groupby(
        ["region_id", "region_code", "region_name", "event_group_id"],
        as_index=False,
    ).agg(
        start_date=("date", "min"),
        end_date=("date", "max"),
        duration_days=("date", "count"),
        max_anomaly_c=("anomaly_c", "max"),
        mean_anomaly_c=("anomaly_c", "mean"),
        max_exceedance_p90_c=("exceedance_p90_c", "max"),
        mean_exceedance_p90_c=("exceedance_p90_c", "mean"),
    )

    summary = summary.loc[summary["duration_days"] >= min_duration_days].copy()

    if summary.empty:
        return empty_events_df()

    peak_rows = (
        event_days.merge(
            summary[["region_id", "event_group_id", "max_exceedance_p90_c"]],
            on=["region_id", "event_group_id"],
            how="inner",
        )
        .loc[lambda x: x["exceedance_p90_c"] == x["max_exceedance_p90_c"]]
        .sort_values(["region_id", "event_group_id", "date"])
        .drop_duplicates(subset=["region_id", "event_group_id"], keep="first")[
            ["region_id", "event_group_id", "date"]
        ]
        .rename(columns={"date": "peak_date"})
    )

    summary = summary.merge(
        peak_rows,
        on=["region_id", "event_group_id"],
        how="left",
    )

    latest_date = df["date"].max()
    summary["is_active"] = summary["end_date"] == latest_date
    summary["event_type"] = "warm_event"
    summary["severity_class"] = summary["max_exceedance_p90_c"].apply(
        classify_event_severity
    )

    # Kept for schema compatibility; under the current rule the operational threshold
    # is above_p90 rather than anomaly_c.
    summary["threshold_c"] = anomaly_threshold
    summary["min_duration_days"] = min_duration_days
    summary["event_id"] = summary.apply(
        lambda row: str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                (
                    f"{row['event_type']}|"
                    f"region_id={row['region_id']}|"
                    f"start_date={pd.to_datetime(row['start_date']).date().isoformat()}"
                ),
            )
        ),
        axis=1,
    )

    round_cols = [
        "max_anomaly_c",
        "mean_anomaly_c",
        "max_exceedance_p90_c",
        "mean_exceedance_p90_c",
    ]
    for col in round_cols:
        summary[col] = summary[col].round(4)

    output_cols = [
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

    return (
        summary[output_cols]
        .sort_values(["region_id", "start_date"])
        .reset_index(drop=True)
    )


def classify_event_severity(max_exceedance_p90: float) -> str:
    """Assign a severity label based on peak exceedance above the p90 threshold."""
    if pd.isna(max_exceedance_p90):
        return "Unknown"
    if max_exceedance_p90 >= 2.0:
        return "Extreme"
    if max_exceedance_p90 >= 1.0:
        return "Severe"
    if max_exceedance_p90 >= 0.5:
        return "Moderate"
    if max_exceedance_p90 > 0:
        return "Weak"
    return "Threshold-only"


def save_output(df: pd.DataFrame, output_path: Path) -> None:
    """Save the heat events table to parquet."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)


def main(
    input_path: Path,
    output_path: Path,
    anomaly_threshold: float,
    min_duration_days: int,
) -> None:
    logger.info("Loading anomaly table: %s", input_path)
    anomalies_df = load_anomalies(input_path)
    logger.info("Loaded %s anomaly rows", len(anomalies_df))

    if anomalies_df.empty:
        raise RuntimeError("Anomaly table is empty. Cannot detect heat events.")

    logger.info(
        "Anomaly input date range: %s to %s",
        anomalies_df["date"].min(),
        anomalies_df["date"].max(),
    )
    logger.info(
        "Regions in anomaly input: %s",
        anomalies_df["region_id"].nunique(),
    )

    prepared_df = prepare_anomalies(anomalies_df)
    logger.info("Rows after event preparation: %s", len(prepared_df))

    flagged_df = add_event_flags(
        prepared_df,
        anomaly_threshold=anomaly_threshold,
    )
    event_day_count = int(flagged_df["is_event_day"].sum())

    logger.info(
        "Event-day candidate rows: %s",
        event_day_count,
    )
    logger.info(
        "Minimum event duration: %s days",
        min_duration_days,
    )

    grouped_df = assign_event_groups(flagged_df)
    logger.info(
        "Assigned event groups: %s groups",
        grouped_df["event_group_id"].nunique(),
    )

    events_df = summarize_events(
        grouped_df,
        min_duration_days=min_duration_days,
        anomaly_threshold=anomaly_threshold,
    )

    logger.info("Created %s event rows", len(events_df))

    if events_df.empty:
        logger.warning("No heat events met the minimum duration threshold.")
    else:
        logger.info(
            "Event date range: %s to %s",
            events_df["start_date"].min(),
            events_df["end_date"].max(),
        )
        logger.info(
            "Active events: %s",
            int(events_df["is_active"].sum()),
        )
        logger.info(
            "Severity counts: %s",
            events_df["severity_class"].value_counts().to_dict(),
        )
        logger.info(
            "Longest event duration: %s days",
            int(events_df["duration_days"].max()),
        )

    logger.info("Event output preview:\n%s", events_df.head().to_string(index=False))

    save_output(events_df, output_path)
    logger.info("Saved events output to: %s", output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Detect sustained warm events from daily regional SST anomalies.",
    )
    parser.add_argument(
        "--input-file",
        default=str(DEFAULT_INPUT_FILE),
        help="Path to the regional anomaly parquet produced by anomalies.py",
    )
    parser.add_argument(
        "--output-file",
        default=str(DEFAULT_OUTPUT_FILE),
        help="Path where the heat events parquet will be saved.",
    )
    parser.add_argument(
        "--anomaly-threshold",
        type=float,
        default=DEFAULT_ANOMALY_THRESHOLD,
        help="Retained for schema compatibility; current event-day rule uses above_p90.",
    )
    parser.add_argument(
        "--min-duration-days",
        type=int,
        default=DEFAULT_MIN_DURATION_DAYS,
        help="Minimum number of consecutive days required to count as an event.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    main(
        input_path=Path(args.input_file),
        output_path=Path(args.output_file),
        anomaly_threshold=args.anomaly_threshold,
        min_duration_days=args.min_duration_days,
    )
