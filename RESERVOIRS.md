# Connecticut drinking-water system surface capacity

Farmer View option **13** displays the first imported Connecticut DPH snapshot. The source is the [November 12, 2024 Surface Reservoir Capacity Measurements and Trends report](https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/surface-water-capacity-summary-and-drought-tracking-report-11-12-2024.pdf). Its table has 34 public water systems, current percent-full readings, each system's historical average and percent of normal, a status/trend, and a previous reading. The original PDF is saved at `data/reservoirs/dph-reservoir-capacity-2024-11-12.pdf`; the structured transcription is `data/reservoirs/2024-11-12.json`.

## What the measurement represents

- **Location:** one row per public water system, not one row per reservoir. A system may draw from multiple reservoirs. The `County_Served` column identifies the service county; it does not locate the reservoirs. Do not map these values to a specific reservoir or farm.
- **Value:** system surface-water capacity as percent full. It is not a water-surface elevation, volume available to a farm, groundwater level, or streamflow measurement.
- **Dates:** the report's latest reading dates range from July 7 to November 11, 2024. It also gives a previous reading per system, but previous dates vary. Keep the actual reading and previous-reading dates; do not assign the report date as the measurement date.
- **Frequency:** the report says systems submit weekly readings; the [DPH reservoir data page](https://portal.ct.gov/dph/drinking-water/dws/reservoir-data) describes its information as collected monthly. The dataset therefore treats observed dates as authoritative and does not assume a fixed cadence.

## Snapshot summary

The table footer reports a **79.79% average full**, **83.51% average historical level**, and **95.53% average of normal**. Its county averages of percent of normal are Fairfield 95.86, Hartford 99.50, Litchfield 99.00, Middlesex 88.00, New Haven 95.33, New London 94.40, and Tolland 92.00. These are source-reported system averages, not capacity-weighted reservoir totals. The report counts 3 systems at 100% full, 3 with upward trends, 29 downward, and 2 unchanged. The status column lists 2 approaching a trigger and 1 water-supply advisory.

## Forecast status and next data needs

**No current two-week reservoir-capacity forecast is issued yet.** The Farmer View's displayed system status comes from the November 12, 2024 snapshot. We have also assembled 11 public system-level snapshots from 2022–2024 and run exploratory baseline checks, documented in [RESERVOIR-PUBLIC-HISTORY.md](RESERVOIR-PUBLIC-HISTORY.md). Those reports are sparse and unevenly dated; the small retrospective check is not enough to establish a reliable forecast or current status. The DPH page links the 2024 report and older statewide charts, but does not expose a machine-readable system-level time series.

To improve the model, request DPH's underlying dated time series and richer source-level measurements. Preserve each report as a separate snapshot, use the PWSID as the system key, retain actual reading dates and source revisions, and track missing reports explicitly. A useful evaluation must forecast only after an issue date and compare with readings that arrive later. Until then, the app shows the report snapshot and does not label its 2024 statuses as current.

This dataset describes public drinking-water systems, not agricultural water access. It cannot establish a farm's reservoir, irrigation supply, well yield, or drought condition.
