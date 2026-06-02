library(readr)
library(dplyr)
library(lubridate)
library(purrr)
library(nlme)

# -----------------------------
# Paths
# -----------------------------

input_file <- "data/processed/region_monthly_sst_history.csv"

r_processed_dir <- "data/processed/r"

dir.create(r_processed_dir, recursive = TRUE, showWarnings = FALSE)

gls_output_file <- file.path(
  r_processed_dir,
  "region_sst_projection_10yr_gls_ar1.csv"
)
# -----------------------------
# Load monthly SST history
# -----------------------------

monthly_sst <- read_csv(input_file, show_col_types = FALSE) %>%
  mutate(
    month_date = as.Date(month_date),
    year = year(month_date),
    month = month(month_date)
  )

first_month <- min(monthly_sst$month_date, na.rm = TRUE)
last_month <- max(monthly_sst$month_date, na.rm = TRUE)

monthly_sst <- monthly_sst %>%
  arrange(region_id, month_date) %>%
  mutate(
    time_index_years = as.numeric(month_date - first_month) / 365.25,
    time_index_month = (year(month_date) - year(first_month)) * 12 +
      (month(month_date) - month(first_month)),
    sin_month = sin(2 * pi * month / 12),
    cos_month = cos(2 * pi * month / 12)
  )

# -----------------------------
# Build monthly climatology from 1991-2020
# Used later to express projected anomaly
# -----------------------------

monthly_climatology <- monthly_sst %>%
  filter(year >= 1991, year <= 2020) %>%
  group_by(region_id, region_name, month) %>%
  summarise(
    clim_monthly_mean_sst_c = mean(mean_sst_c, na.rm = TRUE),
    .groups = "drop"
  )

# -----------------------------
# Future monthly dates: 10 years after latest month
# -----------------------------

future_months <- seq(
  from = last_month %m+% months(1),
  by = "month",
  length.out = 120
)

# -----------------------------
# Helper functions
# -----------------------------

make_future_data <- function(region_data) {
  region_id_value <- unique(region_data$region_id)
  region_name_value <- unique(region_data$region_name)

  tibble(
    region_id = region_id_value,
    region_name = region_name_value,
    month_date = future_months
  ) %>%
    mutate(
      year = year(month_date),
      month = month(month_date),
      time_index_years = as.numeric(month_date - first_month) / 365.25,
      time_index_month = (year(month_date) - year(first_month)) * 12 +
        (month(month_date) - month(first_month)),
      sin_month = sin(2 * pi * month / 12),
      cos_month = cos(2 * pi * month / 12)
    )
}

make_historical_output <- function(region_data) {
  region_data %>%
    transmute(
      region_id,
      region_name,
      month_date,
      year,
      month,
      time_index_years,
      time_index_month,
      sin_month,
      cos_month,
      projected_sst_c = mean_sst_c,
      lower_ci = NA_real_,
      upper_ci = NA_real_,
      observed_or_projected = "observed",
      model_type = "gls_ar1"
    )
}

add_climatology_and_anomaly <- function(projection_data) {
  projection_data %>%
    left_join(
      monthly_climatology,
      by = c("region_id", "region_name", "month")
    ) %>%
    mutate(
      projected_anomaly_c = projected_sst_c - clim_monthly_mean_sst_c,
      lower_anomaly_c = lower_ci - clim_monthly_mean_sst_c,
      upper_anomaly_c = upper_ci - clim_monthly_mean_sst_c
    ) %>%
    arrange(region_id, month_date)
}

# -----------------------------
# GLS with AR(1) autocorrelation
# -----------------------------
# This model estimates:
#   SST = long-term trend + monthly seasonality
#
# It also allows neighbouring months to be correlated,
# which is more appropriate for monthly environmental time-series data.

fit_gls_ar1_region <- function(region_data) {
  region_data <- region_data %>%
    arrange(month_date) %>%
    filter(!is.na(mean_sst_c))

  model <- gls(
    mean_sst_c ~ time_index_years + factor(month),
    data = region_data,
    correlation = corAR1(form = ~ time_index_month),
    method = "REML"
  )

  future_data <- make_future_data(region_data)

  fitted_values <- as.numeric(
    predict(
      model,
      newdata = future_data
    )
  )

  # Approximate prediction interval.
  # Useful for visual comparison, but not a formal climate-forecast uncertainty interval.
  residual_sigma <- sigma(model)

  future_output <- future_data %>%
    mutate(
      projected_sst_c = fitted_values,
      lower_ci = projected_sst_c - 1.96 * residual_sigma,
      upper_ci = projected_sst_c + 1.96 * residual_sigma,
      observed_or_projected = "projected",
      model_type = "gls_ar1"
    )

  historical_output <- make_historical_output(region_data)

  bind_rows(historical_output, future_output)
}

# -----------------------------
# Fit GLS AR(1) model by region
# -----------------------------

region_groups <- monthly_sst %>%
  group_by(region_id, region_name) %>%
  group_split()

gls_projection <- map_dfr(region_groups, fit_gls_ar1_region) %>%
  add_climatology_and_anomaly()

# -----------------------------
# Save output
# -----------------------------

write_csv(gls_projection, gls_output_file, na = "")

cat("\nSaved GLS AR(1) 10-year SST projection:\n")
cat(gls_output_file, "\n\n")

cat("Date range, GLS AR(1) projection:\n")
print(range(gls_projection$month_date))

cat("\nRows by region, GLS AR(1) projection:\n")
print(table(gls_projection$region_name, gls_projection$observed_or_projected))