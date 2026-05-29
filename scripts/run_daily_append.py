from pathlib import Path
from datetime import date, timedelta
import sys

import pandas as pd

from nzheat.utils.commands import run_command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = PROJECT_ROOT / "data" / "processed" / "region_daily_sst_history.parquet"

SAFE_LAG_DAYS = 18


def main() -> None:
    print("===============================")
    print("Daily append started")

    target_end = date.today() - timedelta(days=SAFE_LAG_DAYS)

    if not HISTORY_PATH.exists():
        raise FileNotFoundError(f"History file not found: {HISTORY_PATH}")

    history = pd.read_parquet(HISTORY_PATH)
    history["date"] = pd.to_datetime(history["date"])

    latest_existing = history["date"].max().date()
    target_start = latest_existing + timedelta(days=1)

    print(f"Latest existing date: {latest_existing}")
    print(f"Target end date:      {target_end}")

    if target_start > target_end:
        print("No new final OISST dates to process.")
        print("===============================")
        return

    print(f"Processing from {target_start} to {target_end}")

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.pipeline.backfill",
            "--start-date",
            target_start.isoformat(),
            "--end-date",
            target_end.isoformat(),
            "--append",
        ]
    )

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.analytics.anomalies",
        ]
    )

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.analytics.events",
        ]
    )

    run_command(
        [
            sys.executable,
            "-m",
            "nzheat.load.load_postgres",
        ]
    )

    print("Daily append completed successfully.")
    print("===============================")


if __name__ == "__main__":
    main()
