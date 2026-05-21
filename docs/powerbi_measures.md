# Power BI DAX Measures

This file documents the DAX measures used in the Power BI dashboard for the NZ Coastal Ocean Heat Anomaly Monitor.

The dashboard uses:

- final OISST tables for validated historical anomaly trends
- preliminary OISST tables for latest-status cards and possible active events

---

## Latest Final OISST Date

```DAX
Latest Final OISST Date =
MAX ( 'analytics region_daily_anomalies'[date] )
```

Purpose:

Shows the most recent date available from the final OISST anomaly table.

---

## Latest Preliminary OISST Date

```DAX
Latest Preliminary Date =
MAX ( 'analytics region_daily_anomalies_prelim'[date] )
```

Purpose:

Shows the most recent date available from the preliminary OISST anomaly table.

---

## Active Events

```DAX
Active Events =
COALESCE (
    CALCULATE (
        DISTINCTCOUNT ( 'analytics heat_events_prelim'[event_id] ),
        'analytics heat_events_prelim'[is_active] = TRUE ()
    ),
    0
)
```

Purpose:

Counts possible active heat events using the preliminary OISST event table.

This measure uses preliminary data because the dashboard headline cards are intended to show the latest possible status.

---

## Regions Above P90 Latest

```DAX
Regions Above P90 Latest =
VAR LatestDate =
    [Latest Preliminary Date]
RETURN
COALESCE (
    CALCULATE (
        DISTINCTCOUNT ( 'analytics region_daily_anomalies_prelim'[region_id] ),
        'analytics region_daily_anomalies_prelim'[date] = LatestDate,
        'analytics region_daily_anomalies_prelim'[above_p90] = TRUE ()
    ),
    0
)
```

Purpose:

Counts how many regions are above the climatological 90th percentile on the latest preliminary date.

---

## Max Anomaly Latest

```DAX
Max Anomaly Latest =
VAR LatestDate =
    [Latest Preliminary Date]
RETURN
CALCULATE (
    MAX ( 'analytics region_daily_anomalies_prelim'[anomaly_c] ),
    'analytics region_daily_anomalies_prelim'[date] = LatestDate
)
```

Purpose:

Shows the highest SST anomaly among all regions on the latest preliminary date.

---

## Mean Anomaly Latest

```DAX
Mean Anomaly Latest =
VAR LatestDate =
    [Latest Preliminary Date]
RETURN
CALCULATE (
    AVERAGE ( 'analytics region_daily_anomalies_prelim'[anomaly_c] ),
    'analytics region_daily_anomalies_prelim'[date] = LatestDate
)
```

Purpose:

Shows the average SST anomaly across all regions on the latest preliminary date.

---

## Notes

Final OISST data is stable but delayed.

Preliminary OISST data is more recent but provisional and may change after final validation.

Dashboard interpretation:

```text
Historical anomaly charts = final OISST
Latest status cards = preliminary OISST
```