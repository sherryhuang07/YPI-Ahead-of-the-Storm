# Streamflow and historical context

Choose **9** in Farmer View to inspect USGS daily mean discharge, recent averages, and historical percentile bands. The first saved snapshot is November 2, 2026, using daily records August 4–November 1 inclusive. It is not refreshed automatically.

## Initial coverage

USGS metadata identifies 205 Connecticut primary daily-mean discharge series at 205 gauges, including historical stations. Sixty-nine gauges have usable observations during this 90-day window, and all 69 have a November 1 daily value. Fifty-nine have a complete set of finite official seasonal percentile thresholds matching the latest observation's date and series. Five gauges have incomplete 90-day histories; their complete 90-day averages are withheld. Ten recent gauges lack the complete seasonal thresholds required by this display. Missing context is not replaced with a different gauge's statistics.

The gauges occur in 57 towns. A town without a gauge is not necessarily hydrologically unrepresented: a gauge upstream or downstream may be relevant, but river-network routing has not yet been implemented. Only Connecticut gauges are included; cross-border upstream monitoring is a future extension.

## Measurement and computation

USGS parameter **00060** is discharge in **cubic feet per second**, and statistic **00003** is the daily mean. A daily average is not an instantaneous flow reading or a volume accumulated over the day. The 7-, 14-, 30-, and 90-day values are arithmetic means of daily means ending November 1. They are only published when every day is present. Zero flow remains zero; missing and nonnumeric values stay missing. Negative numeric flows are preserved as signed measurements, but a low-flow percentile interpretation is withheld.

Approval status and qualifier flags are preserved. Estimated or maintenance-flagged numeric readings can contribute to an average and are counted explicitly in its quality notes. Percentile interpretation is withheld when the latest observation has a qualifier. Recent provisional values may be revised. Daily labels follow USGS's station daily records; they have not been aligned to PRISM's 12 UTC day boundaries. Such alignment is required before event-level rainfall–runoff analysis.

The app keeps each primary series separate. Duplicate or conflicting readings fail validation. If more than one recent primary series exists at a gauge, that gauge is excluded from automatic nearby-gauge links pending review; no such ambiguity occurred in this snapshot.

## Historical percentiles

Thresholds come directly from the modern USGS Statistics API's `observationNormals` endpoint, using discharge, the mean parent statistic, and the approved historical record. Statistics are joined by **parent series ID and day-of-year label**. Month-of-year records returned alongside day-of-year records are explicitly excluded. Only finite, ordered 5th, 10th, 25th, 50th, 75th, 90th, and 95th thresholds are used.

The display reports a **percentile band**, not an invented exact rank. Equality with one or several thresholds is labeled explicitly because tied values can make a precise rank ambiguous. At least 10 historical samples are required for interpretation; this is an application screening rule, not a guarantee of a representative baseline. Sample counts are shown. The API's period-of-record statistics are not a fixed 1991–2020 climate normal. Statistics may reflect a USGS-defined adjusted period, so a metadata series start date is not asserted to be the statistical baseline start. Reservoir regulation, diversions, and changes in the record can affect comparisons.

The latest single-day discharge is compared with the seasonal thresholds for that day. Multi-day averages are **not** compared with single-day thresholds. No 7Q10 low-flow statistic, exact percentile rank, drought category, or forecast is computed.

For the Mill River near Hamden (USGS-01196620), the November 1 daily mean is 23.0 cubic feet/second, provisional. Official thresholds based on 50 historical samples put it in the 50th–75th percentile band; the historical median is 15.75 cubic feet/second. Its past 7-day average is about 24.53 cubic feet/second. This is a stream observation, not Yale Farm's available irrigation water.

## Farm and watershed context

Every mapped farm candidate has up to three closest recent, unambiguous gauges linked by WGS84 geodesic distance from a representative point within the candidate. Shared CT DEEP surface-watershed membership is recorded separately. Neither distance nor shared watershed proves that a gauge is upstream of a field, measures its runoff, or represents a permitted or physically available water supply. Those relationships remain explicitly unestablished.

Yale Farm's nearby gauges include Farm River at Totoket (about 9.03 km, different mapped watershed), Mill River near Hamden (about 11.21 km, same mapped watershed), and Quinnipiac River at Wallingford (about 15.89 km, different mapped watershed). The Mill River chart is an illustrative nearby record, not an automatically selected farm proxy. Flow magnitudes from differently sized basins are not ranked against each other or averaged across a watershed. Upstream drainage area is retained as metadata.

## Files and reproducibility

- `data/streamflow/`: raw metadata, daily records, latest daily records, official percentile thresholds, API schemas and source manifest with URLs, timestamps and hashes.
- `outputs/streamflow/`: gauge histories, daily-discharge CSV, averages, percentile context, coverage, farm links and the Mill River chart.
- `scripts/fetch_streamflow.py`: cached, paginated retrieval of this fixed initial snapshot. Existing raw files are reused. Use a separately dated snapshot design before implementing scheduled updates.
- `scripts/build_streamflow.py`: rebuilds derived data without altering source values.
- `scripts/validate_streamflow.py`: verifies source integrity, raw-series identity, units, zero/missing handling, rolling-window completeness, percentile ties and ordering, and farm links.
- `scripts/render_streamflow.py`: plots daily flow against historical median and the middle 50% band; missing dates are not joined by a line.

The raw geographic daily query includes neighboring-state gauges within its rectangle, then filters observations to Connecticut primary daily series using source metadata. Archived latest observations remain dated and are never treated as current. No climate model, sensors or two-week forecasting logic is added by this step.

Sources: [USGS statistics documentation](https://waterdata.usgs.gov/statistics-documentation), [Connecticut water conditions](https://waterdata.usgs.gov/state/Connecticut/), [USGS Water Data APIs](https://api.waterdata.usgs.gov/), [official statistics API examples](https://doi-usgs.github.io/dataretrieval-python/examples/USGS_WaterData_DailyStatistics_Examples.html). Attribution: U.S. Geological Survey, accessed November 2, 2026.
