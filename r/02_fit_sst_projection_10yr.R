library(readr)
library(dplyr)
library(lubridate)
library(purrr)

# -----------------------------
# Paths
# -----------------------------

input_file <- "data/processed/region_monthly_sst_history.csv"

output_file <- "data/processed/region_sst_projection_10yr.csv"

# -----------------------------
# Load monthly SST history
# -----------------------------

monthly_sst <- read_csv(input_file, show_col_types = FALSE) %>%
  mutate(
    month_date = as.Date(month_date),
    year = year(month_date),
    month = month(month_date)
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

first_month <- min(monthly_sst$month_date)
last_month <- max(monthly_sst$month_date)

future_months <- seq(
  from = last_month %m+% months(1),
  by = "month",
  length.out = 120
)

# -----------------------------
# Function to fit one regional model
# -----------------------------

fit_project_region <- function(region_data) {
  region_data <- region_data %>%
    arrange(month_date)

  region_id_value <- unique(region_data$region_id)
  region_name_value <- unique(region_data$region_name)

  model <- lm(
    mean_sst_c ~ time_index_years + factor(month),
    data = region_data
  )

  future_data <- tibble(
    region_id = region_id_value,
    region_name = region_name_value,
    month_date = future_months
  ) %>%
    mutate(
      year = year(month_date),
      month = month(month_date),
      time_index_years = as.numeric(month_date - first_month) / 365.25,
      sin_month = sin(2 * pi * month / 12),
      cos_month = cos(2 * pi * month / 12)
    )

  prediction <- predict(
    model,
    newdata = future_data,
    interval = "prediction",
    level = 0.95
  ) %>%
    as.data.frame()

  future_output <- bind_cols(future_data, prediction) %>%
    rename(
      projected_sst_c = fit,
      lower_ci = lwr,
      upper_ci = upr
    ) %>%
    mutate(
      observed_or_projected = "projected"
    )

  historical_output <- region_data %>%
    transmute(
      region_id,
      region_name,
      month_date,
      year,
      month,
      time_index_years,
      sin_month,
      cos_month,
      projected_sst_c = mean_sst_c,
      lower_ci = NA_real_,
      upper_ci = NA_real_,
      observed_or_projected = "observed"
    )

  bind_rows(historical_output, future_output)
}

# -----------------------------
# Fit model by region and project
# -----------------------------

projection <- monthly_sst %>%
  group_by(region_id, region_name) %>%
  group_split() %>%
  map_dfr(fit_project_region)

# -----------------------------
# Add monthly climatology and anomaly
# -----------------------------

projection <- projection %>%
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

# -----------------------------
# Save output
# -----------------------------

write_csv(projection, output_file, na = "")

cat("\nSaved 10-year SST projection:\n")
cat(output_file, "\n\n")

cat("Date range:\n")
print(range(projection$month_date))

cat("\nRows by region:\n")
print(table(projection$region_name, projection$observed_or_projected))