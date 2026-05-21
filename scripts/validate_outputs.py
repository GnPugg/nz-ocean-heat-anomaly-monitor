from pathlib import Path
import pandas as pd

BASE = Path("data/processed")

sst_path = BASE / "region_daily_sst_history.parquet"
anom_path = BASE / "region_daily_anomalies.parquet"
events_path = BASE / "heat_events.parquet"
clim_path = BASE / "region_climatology.parquet"

print("\n=== CHECKING PROCESSED OUTPUTS ===")

# -------------------------
# SST history
# -------------------------
sst = pd.read_parquet(sst_path)
sst["date"] = pd.to_datetime(sst["date"])

print("\n--- SST HISTORY ---")
print("Rows:", len(sst))
print("Date range:", sst["date"].min().date(), "to", sst["date"].max().date())
print("Regions:", sorted(sst["region_code"].unique()))
print("Number of regions:", sst["region_code"].nunique())
print("Number of dates:", sst["date"].nunique())

# Check duplicate region-date rows
duplicates = sst.duplicated(subset=["date", "region_id"]).sum()
print("Duplicate date-region rows:", duplicates)

# Check missing dates
all_dates = pd.date_range(sst["date"].min(), sst["date"].max(), freq="D")
existing_dates = pd.to_datetime(sst["date"].dt.normalize().unique())
missing_dates = sorted(set(all_dates) - set(existing_dates))

print("Missing complete dates:", len(missing_dates))
for d in missing_dates:
    print("  ", d.date())

# Check each date has all regions
expected_regions = sorted(sst["region_id"].unique())
expected = pd.MultiIndex.from_product(
    [all_dates, expected_regions], names=["date", "region_id"]
).to_frame(index=False)

actual = sst[["date", "region_id"]].copy()
actual["date"] = actual["date"].dt.normalize()

missing_region_dates = expected.merge(
    actual, on=["date", "region_id"], how="left", indicator=True
).query("_merge == 'left_only'")

print("Missing region-date combinations:", len(missing_region_dates))
if len(missing_region_dates) > 0:
    print(missing_region_dates.head(20))

# -------------------------
# Climatology
# -------------------------
clim = pd.read_parquet(clim_path)

print("\n--- CLIMATOLOGY ---")
print("Rows:", len(clim))
print("Expected rows if 6 regions x 365 days:", 6 * 365)
print("Day-of-year range:", clim["day_of_year"].min(), "to", clim["day_of_year"].max())
print("Min sample size:", clim["sample_size"].min())
print("Max sample size:", clim["sample_size"].max())

missing_clim = clim[clim[["clim_mean_sst_c", "clim_p90_sst_c"]].isna().any(axis=1)]
print("Rows with missing climatology values:", len(missing_clim))

# -------------------------
# Anomalies
# -------------------------
anom = pd.read_parquet(anom_path)
anom["date"] = pd.to_datetime(anom["date"])

print("\n--- ANOMALIES ---")
print("Rows:", len(anom))
print("Date range:", anom["date"].min().date(), "to", anom["date"].max().date())
print("Rows with missing anomaly:", anom["anomaly_c"].isna().sum())
print("Rows with missing p90 flag:", anom["above_p90"].isna().sum())

latest_date = anom["date"].max()
latest = anom[anom["date"] == latest_date].copy()

print("\nLatest available date:", latest_date.date())
print("Rows on latest date:", len(latest))
print("Regions above p90 on latest date:", int(latest["above_p90"].sum()))

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

# -------------------------
# Events
# -------------------------
events = pd.read_parquet(events_path)

print("\n--- HEAT EVENTS ---")
print("Rows:", len(events))

if len(events) > 0:
    events["start_date"] = pd.to_datetime(events["start_date"])
    events["end_date"] = pd.to_datetime(events["end_date"])
    events["peak_date"] = pd.to_datetime(events["peak_date"])

    print(
        "Date range:",
        events["start_date"].min().date(),
        "to",
        events["end_date"].max().date(),
    )
    print("Active events:", int(events["is_active"].sum()))
    print("\nActive events table:")
    print(
        events.loc[
            events["is_active"] == True,
            [
                "region_code",
                "start_date",
                "end_date",
                "duration_days",
                "max_anomaly_c",
                "mean_anomaly_c",
                "severity_class",
            ],
        ]
    )
else:
    print("No heat events detected.")

print("\n=== VALIDATION COMPLETE ===")
