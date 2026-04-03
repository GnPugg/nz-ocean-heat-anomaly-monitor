from __future__ import annotations

from pathlib import Path
from datetime import date
import argparse

import pandas as pd


DEFAULT_HISTORY_FILE = Path("data/processed/region_daily_sst_history.parquet")
DEFAULT_CLIMATOLOGY_FILE = Path("data/processed/region_climatology.parquet")
DEFAULT_OUTPUT_FILE = Path("data/processed/region_daily_anomalies.parquet")


def parse_iso_date(value: str | None) -> pd.Timestamp | None:
    """Parse optional CLI date in YYYY-MM-DD format."""
    if value is None:
        return None
    try:
        return pd.Timestamp(date.fromisoformat(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Use YYYY-MM-DD format."
        ) from exc


def load_history(history_path: Path) -> pd.DataFrame:
    """Load the backfilled daily regional SST history."""
    return pd.read_parquet(history_path)


def load_climatology(climatology_path: Path) -> pd.DataFrame:
    """Load the day-of-year regional climatology table."""
    return pd.read_parquet(climatology_path)


def prepare_history(df: pd.DataFrame) -> pd.DataFrame:
    """
    Prepare the observed regional SST history for anomaly calculations.

    Steps:
    - ensure the date column is datetime
    - derive day_of_year
    - drop leap day for consistency with climatology.py
    """
    prepared = df.copy()
    prepared["date"] = pd.to_datetime(prepared["date"])
    prepared["day_of_year"] = prepared["date"].dt.dayofyear

    leap_day_mask = (prepared["date"].dt.month == 2) & (prepared["date"].dt.day == 29)
    prepared = prepared.loc[~leap_day_mask].copy()

    return prepared


def filter_analysis_period(
    df: pd.DataFrame,
    analysis_start: pd.Timestamp | None,
    analysis_end: pd.Timestamp | None,
) -> pd.DataFrame:
    """Filter observed history down to the analysis period."""
    filtered = df.copy()

    if analysis_start is not None:
        filtered = filtered.loc[filtered["date"] >= analysis_start].copy()

    if analysis_end is not None:
        filtered = filtered.loc[filtered["date"] <= analysis_end].copy()

    return filtered


def join_history_to_climatology(
    history_df: pd.DataFrame,
    climatology_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Join observed daily regional SST with the climatology table.

    Join keys:
    - region_id
    - day_of_year
    """
    clim_cols = [
        "region_id",
        "day_of_year",
        "clim_mean_sst_c",
        "clim_p90_sst_c",
        "sample_size",
    ]

    merged = history_df.merge(
        climatology_df[clim_cols],
        on=["region_id", "day_of_year"],
        how="left",
        validate="many_to_one",
    )

    return merged


def calculate_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate regional daily SST anomaly metrics.
    """
    result = df.copy()

    result["anomaly_c"] = result["mean_sst_c"] - result["clim_mean_sst_c"]
    result["above_p90"] = result["mean_sst_c"] > result["clim_p90_sst_c"]

    result = result.sort_values(["region_id", "date"]).reset_index(drop=True)

    result["rolling_7d_anomaly_c"] = result.groupby("region_id")["anomaly_c"].transform(
        lambda x: x.rolling(window=7, min_periods=1).mean()
    )

    result["rolling_30d_anomaly_c"] = result.groupby("region_id")[
        "anomaly_c"
    ].transform(lambda x: x.rolling(window=30, min_periods=1).mean())

    result["warming_rate_7d_c"] = result.groupby("region_id")["mean_sst_c"].transform(
        lambda x: x - x.shift(7)
    )

    result["status_label"] = result["anomaly_c"].apply(classify_status)

    output_cols = [
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

    return result[output_cols].copy()


def classify_status(anomaly_value: float) -> str:
    """Assign a simple status label based on the anomaly threshold."""
    if pd.isna(anomaly_value):
        return "Unknown"
    if anomaly_value >= 1.5:
        return "Extreme"
    if anomaly_value >= 1.0:
        return "Hot"
    if anomaly_value >= 0.5:
        return "Watch"
    return "Normal"


def save_output(df: pd.DataFrame, output_path: Path) -> None:
    """Save the daily anomaly table to parquet."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)


def main(
    history_path: Path,
    climatology_path: Path,
    output_path: Path,
    analysis_start: pd.Timestamp | None,
    analysis_end: pd.Timestamp | None,
) -> None:
    print(f"Loading regional SST history: {history_path}")
    history_df = load_history(history_path)
    print(f"Loaded {len(history_df):,} history rows")

    print(f"Loading climatology: {climatology_path}")
    climatology_df = load_climatology(climatology_path)
    print(f"Loaded {len(climatology_df):,} climatology rows")

    prepared_history = prepare_history(history_df)
    print(f"Rows after history preparation: {len(prepared_history):,}")

    analysis_history = filter_analysis_period(
        prepared_history,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
    )
    print(f"Rows in analysis period: {len(analysis_history):,}")

    if analysis_history.empty:
        raise RuntimeError("No rows found in the requested analysis period.")

    merged_df = join_history_to_climatology(analysis_history, climatology_df)
    print(f"Rows after climatology join: {len(merged_df):,}")

    anomalies_df = calculate_anomalies(merged_df)
    print(f"Created {len(anomalies_df):,} anomaly rows")

    print("Preview:")
    print(anomalies_df.head())

    save_output(anomalies_df, output_path)
    print(f"Saved anomaly output to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Calculate daily SST anomaly metrics by NZ coastal region.",
    )
    parser.add_argument(
        "--history-file",
        default=str(DEFAULT_HISTORY_FILE),
        help="Path to the regional SST history parquet produced by backfill.py",
    )
    parser.add_argument(
        "--climatology-file",
        default=str(DEFAULT_CLIMATOLOGY_FILE),
        help="Path to the regional climatology parquet produced by climatology.py",
    )
    parser.add_argument(
        "--output-file",
        default=str(DEFAULT_OUTPUT_FILE),
        help="Path where the anomaly parquet will be saved.",
    )
    parser.add_argument(
        "--analysis-start",
        type=parse_iso_date,
        default=None,
        help="Analysis start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--analysis-end",
        type=parse_iso_date,
        default=None,
        help="Analysis end date in YYYY-MM-DD format.",
    )
    args = parser.parse_args()

    main(
        history_path=Path(args.history_file),
        climatology_path=Path(args.climatology_file),
        output_path=Path(args.output_file),
        analysis_start=args.analysis_start,
        analysis_end=args.analysis_end,
    )
