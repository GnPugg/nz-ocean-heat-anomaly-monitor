from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]

INPUT_FILE = (
    PROJECT_ROOT / "data" / "processed" / "region_daily_sst_full_history.parquet"
)
OUTPUT_FILE = PROJECT_ROOT / "data" / "processed" / "region_sst_projection_10yr.parquet"

N_YEARS_FORWARD = 10
N_MONTHS_FORWARD = N_YEARS_FORWARD * 12

BASELINE_START_YEAR = 1991
BASELINE_END_YEAR = 2020
TREND_START_YEAR = 1991


def find_column(df: pd.DataFrame, candidates: list[str]) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    raise ValueError(
        f"None of these columns found: {candidates}. "
        f"Available columns are: {list(df.columns)}"
    )


def decimal_year(dates: pd.Series) -> np.ndarray:
    dates = pd.to_datetime(dates)
    return dates.dt.year + (dates.dt.dayofyear - 1) / 365.25


def build_monthly_history(df: pd.DataFrame) -> pd.DataFrame:
    date_col = find_column(df, ["date", "month_date", "time"])
    region_col = find_column(df, ["region_id", "region_name", "region"])
    sst_col = find_column(df, ["mean_sst_c", "sst_c", "avg_sst_c", "sst"])

    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col])
    df["month_date"] = df[date_col].dt.to_period("M").dt.to_timestamp()

    monthly = (
        df.groupby([region_col, "month_date"], as_index=False)
        .agg(mean_sst_c=(sst_col, "mean"))
        .rename(columns={region_col: "region_id"})
    )

    monthly["year"] = monthly["month_date"].dt.year
    monthly["month"] = monthly["month_date"].dt.month

    return monthly


def fit_region_projection(region_df: pd.DataFrame) -> pd.DataFrame:
    region_df = region_df.sort_values("month_date").copy()
    region_id = region_df["region_id"].iloc[0]

    last_observed_month = region_df["month_date"].max()

    # Use 1991–2020 climatology where available.
    baseline = region_df[
        (region_df["year"] >= BASELINE_START_YEAR)
        & (region_df["year"] <= BASELINE_END_YEAR)
    ].copy()

    # If your current history does not yet contain 1991–2020,
    # fall back to all available months.
    if baseline["year"].nunique() < 10:
        print(
            f"WARNING: Region {region_id} has limited 1991–2020 baseline data. "
            "Using all available history for monthly climatology."
        )
        baseline = region_df.copy()

    monthly_clim = baseline.groupby("month", as_index=False).agg(
        monthly_climatology_sst_c=("mean_sst_c", "mean")
    )

    region_df = region_df.merge(monthly_clim, on="month", how="left")
    region_df["sst_anomaly_c"] = (
        region_df["mean_sst_c"] - region_df["monthly_climatology_sst_c"]
    )

    trend_df = region_df[region_df["year"] >= TREND_START_YEAR].copy()

    if len(trend_df) < 36:
        print(
            f"WARNING: Region {region_id} has fewer than 36 monthly records "
            "for trend fitting. Projection will be weak."
        )
        trend_df = region_df.copy()

    x = decimal_year(trend_df["month_date"])
    x0 = x.min()
    x_centered = x - x0
    y = trend_df["sst_anomaly_c"].to_numpy()

    slope_c_per_year, intercept_c = np.polyfit(x_centered, y, 1)

    trend_df["fitted_anomaly_c"] = intercept_c + slope_c_per_year * x_centered
    trend_df["residual_c"] = trend_df["sst_anomaly_c"] - trend_df["fitted_anomaly_c"]

    residuals_all = trend_df["residual_c"].dropna().to_numpy()

    observed = region_df.copy()
    observed["observed_or_projected"] = "observed"
    observed["scenario"] = "observed"
    observed["model_id"] = "NOAA_OISST"
    observed["median_sst_c"] = observed["mean_sst_c"]
    observed["p10_sst_c"] = np.nan
    observed["p90_sst_c"] = np.nan
    observed["trend_c_per_year"] = slope_c_per_year
    observed["trend_c_per_decade"] = slope_c_per_year * 10
    observed["warming_from_last_observed_c"] = 0.0

    future_months = pd.date_range(
        last_observed_month + pd.offsets.MonthBegin(1),
        periods=N_MONTHS_FORWARD,
        freq="MS",
    )

    future = pd.DataFrame(
        {
            "region_id": region_id,
            "month_date": future_months,
        }
    )

    future["year"] = future["month_date"].dt.year
    future["month"] = future["month_date"].dt.month
    future = future.merge(monthly_clim, on="month", how="left")

    xf = decimal_year(future["month_date"])
    xf_centered = xf - x0

    future["projected_anomaly_c"] = intercept_c + slope_c_per_year * xf_centered
    future["median_sst_c"] = (
        future["monthly_climatology_sst_c"] + future["projected_anomaly_c"]
    )

    # Month-specific residual uncertainty where possible.
    p10_values = []
    p90_values = []

    for _, row in future.iterrows():
        month_residuals = (
            trend_df.loc[trend_df["month"] == row["month"], "residual_c"]
            .dropna()
            .to_numpy()
        )

        if len(month_residuals) >= 5:
            residuals = month_residuals
        else:
            residuals = residuals_all

        if len(residuals) == 0:
            p10_values.append(np.nan)
            p90_values.append(np.nan)
        else:
            p10_values.append(row["median_sst_c"] + np.quantile(residuals, 0.10))
            p90_values.append(row["median_sst_c"] + np.quantile(residuals, 0.90))

    future["p10_sst_c"] = p10_values
    future["p90_sst_c"] = p90_values

    last_12m_observed = (
        observed.tail(12)["mean_sst_c"].mean()
        if len(observed) >= 12
        else observed["mean_sst_c"].mean()
    )

    future["mean_sst_c"] = np.nan
    future["observed_or_projected"] = "projected"
    future["scenario"] = "local_trend"
    future["model_id"] = "OISST_seasonal_trend_residual"
    future["trend_c_per_year"] = slope_c_per_year
    future["trend_c_per_decade"] = slope_c_per_year * 10
    future["warming_from_last_observed_c"] = future["median_sst_c"] - last_12m_observed

    keep_cols = [
        "region_id",
        "month_date",
        "year",
        "month",
        "observed_or_projected",
        "scenario",
        "model_id",
        "mean_sst_c",
        "median_sst_c",
        "p10_sst_c",
        "p90_sst_c",
        "monthly_climatology_sst_c",
        "trend_c_per_year",
        "trend_c_per_decade",
        "warming_from_last_observed_c",
    ]

    combined = pd.concat(
        [observed[keep_cols], future[keep_cols]],
        ignore_index=True,
    )

    return combined


def main():
    print(f"Loading SST history from: {INPUT_FILE}")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Input file not found: {INPUT_FILE}")

    df = pd.read_parquet(INPUT_FILE)

    monthly = build_monthly_history(df)

    print(f"Monthly history rows: {len(monthly)}")
    print(f"Date range: {monthly['month_date'].min()} to {monthly['month_date'].max()}")
    print(f"Regions: {monthly['region_id'].nunique()}")

    outputs = []

    for region_id, region_df in monthly.groupby("region_id"):
        print(f"Building projection for region: {region_id}")
        outputs.append(fit_region_projection(region_df))

    projection = pd.concat(outputs, ignore_index=True)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    projection.to_parquet(OUTPUT_FILE, index=False)

    print(f"Saved projection to: {OUTPUT_FILE}")
    print(f"Output rows: {len(projection)}")
    print(projection.head())


if __name__ == "__main__":
    main()
