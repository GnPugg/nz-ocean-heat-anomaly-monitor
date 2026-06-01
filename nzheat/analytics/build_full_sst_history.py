from pathlib import Path
import pandas as pd

from nzheat.utils.paths import find_project_root

PROJECT_ROOT = find_project_root()

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

OUTPUT_FILE = PROCESSED_DIR / "region_daily_sst_full_history.parquet"

INPUT_FILES = [
    "region_daily_sst_baseline_1991_2020.parquet",
    "region_daily_sst_gap_2021_2024.parquet",
    "region_daily_sst_history.parquet",
]


def standardise_sst_file(path: Path, priority: int) -> pd.DataFrame:
    df = pd.read_parquet(path)

    required_cols = [
        "date",
        "region_id",
        "region_code",
        "region_name",
        "mean_sst_c",
        "cell_count",
        "min_sst_c",
        "max_sst_c",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name} is missing columns: {missing}")

    out = df[required_cols].copy()

    out["date"] = pd.to_datetime(out["date"])
    out["mean_sst_c"] = pd.to_numeric(out["mean_sst_c"], errors="coerce")
    out["source_file"] = path.name
    out["source_priority"] = priority

    out = out.dropna(subset=["date", "region_id", "mean_sst_c"])

    return out


def main():
    print("Building full regional SST history...")

    frames = []

    for priority, filename in enumerate(INPUT_FILES):
        path = PROCESSED_DIR / filename

        if not path.exists():
            raise FileNotFoundError(f"Missing input file: {path}")

        print(f"\nReading: {filename}")
        part = standardise_sst_file(path, priority=priority)

        print(f"Rows: {len(part):,}")
        print(f"Date range: {part['date'].min()} to {part['date'].max()}")
        print(f"Regions: {part['region_id'].nunique()}")

        frames.append(part)

    full = pd.concat(frames, ignore_index=True)

    before = len(full)

    full = full.sort_values(["region_id", "date", "source_priority"])

    full = full.drop_duplicates(
        subset=["region_id", "date"],
        keep="last",
    )

    after = len(full)

    full = full.sort_values(["region_id", "date"]).reset_index(drop=True)

    print("\nCombined full SST history")
    print(f"Rows before duplicate removal: {before:,}")
    print(f"Rows after duplicate removal:  {after:,}")
    print(f"Duplicates removed:            {before - after:,}")
    print(f"Date range: {full['date'].min()} to {full['date'].max()}")
    print(f"Regions: {full['region_id'].nunique()}")
    print(f"Unique dates: {full['date'].nunique():,}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    full.to_parquet(OUTPUT_FILE, index=False)

    print(f"\nSaved:")
    print(OUTPUT_FILE)


if __name__ == "__main__":
    main()
