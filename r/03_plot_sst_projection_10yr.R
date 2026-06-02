library(readr)
library(dplyr)
library(ggplot2)
library(lubridate)

# -----------------------------
# Paths
# -----------------------------
gls_input_file <- "data/processed/r/region_sst_projection_10yr_gls_ar1.csv"

output_dir <- "docs/images"

gls_selected_region_output <- file.path(
  output_dir,
  "r_projection_gls_ar1_selected_region.png"
)

gls_all_regions_output <- file.path(
  output_dir,
  "r_projection_gls_ar1_all_regions.png"
)

dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

# -----------------------------
# Load GLS AR(1) projection output
# -----------------------------

gls_projection <- read_csv(gls_input_file, show_col_types = FALSE) %>%
  mutate(
    month_date = as.Date(month_date),
    observed_or_projected = factor(
      observed_or_projected,
      levels = c("observed", "projected")
    )
  )

# -----------------------------
# Choose one region for main graph
# -----------------------------
# Change this if you want a specific region.
# Example:
# target_region <- "East North Island"
#
# If left as NULL, the script uses the first region alphabetically.

target_region <- NULL

if (is.null(target_region)) {
  target_region <- gls_projection %>%
    distinct(region_name) %>%
    arrange(region_name) %>%
    slice(1) %>%
    pull(region_name)
}

gls_one_region <- gls_projection %>%
  filter(region_name == target_region)

last_observed_month <- gls_one_region %>%
  filter(observed_or_projected == "observed") %>%
  summarise(last_month = max(month_date, na.rm = TRUE)) %>%
  pull(last_month)

# -----------------------------
# Plot 1: GLS AR(1), selected region
# -----------------------------

p_gls_selected <- ggplot(gls_one_region, aes(x = month_date)) +
  geom_ribbon(
    data = gls_one_region %>%
      filter(observed_or_projected == "projected"),
    aes(
      ymin = lower_ci,
      ymax = upper_ci
    ),
    alpha = 0.2
  ) +
  geom_line(
    aes(
      y = projected_sst_c,
      linetype = observed_or_projected
    ),
    linewidth = 0.7
  ) +
  geom_vline(
    xintercept = as.numeric(last_observed_month),
    linetype = "dashed",
    linewidth = 0.5
  ) +
  labs(
    title = paste("10-Year SST Projection - GLS AR(1) Model -", target_region),
    subtitle = "Observed monthly SST followed by GLS projection with AR(1) autocorrelated residuals",
    x = "Month",
    y = "Sea surface temperature (°C)",
    linetype = "Series",
    caption = "Projection is trend-based and should not be interpreted as a formal climate forecast."
  ) +
  theme_minimal(base_size = 12)

ggsave(
  filename = gls_selected_region_output,
  plot = p_gls_selected,
  width = 11,
  height = 6,
  dpi = 300
)

cat("\nSaved GLS selected-region projection plot:\n")
cat(gls_selected_region_output, "\n")

# -----------------------------
# Plot 2: GLS AR(1), all regions
# -----------------------------

p_gls_all <- ggplot(gls_projection, aes(x = month_date)) +
  geom_ribbon(
    data = gls_projection %>%
      filter(observed_or_projected == "projected"),
    aes(
      ymin = lower_ci,
      ymax = upper_ci
    ),
    alpha = 0.15
  ) +
  geom_line(
    aes(
      y = projected_sst_c,
      linetype = observed_or_projected
    ),
    linewidth = 0.4
  ) +
  facet_wrap(~ region_name, scales = "free_y") +
  labs(
    title = "10-Year SST Projection by Coastal Region - GLS AR(1) Model",
    subtitle = "Observed monthly SST followed by GLS projection with autocorrelated residuals",
    x = "Month",
    y = "Sea surface temperature (°C)",
    linetype = "Series",
    caption = "Projection is trend-based and should not be interpreted as a formal climate forecast."
  ) +
  theme_minimal(base_size = 10) +
  theme(
    legend.position = "bottom"
  )

ggsave(
  filename = gls_all_regions_output,
  plot = p_gls_all,
  width = 13,
  height = 9,
  dpi = 300
)

cat("\nSaved GLS all-regions projection plot:\n")
cat(gls_all_regions_output, "\n")