# Groundwater observations and coverage

Choose **8** in Farmer View. This first connection uses the modern **USGS Water Data APIs**, accessed November 2, 2026. The requested NGWMN portal describes a selected network incorporating federal, state, and local providers. Its documented SOS download endpoint returned HTTP 404 during this attempt. Consequently this import is **not a complete NGWMN inventory**, and NGWMN membership is not asserted for these wells.

The saved window is August 4–November 1, 2026, inclusive (90 days). There is no automatic refresh. The results contain 6,338 USGS Connecticut well-location records, 67 wells with usable recent readings, and 9 wells with daily history. All 67 also have manual measurements. Sixty-six have an imported reading within 30 days of the snapshot. Recent wells occur in 29 towns; 140 towns have none in these imported sources. These are monitoring gaps, not proof of absent groundwater or a complete inventory of all monitoring programs. A historical site record does not imply an active station.

## What is measured

The display uses **USGS parameter 72019: depth to water in feet below local land surface**. Increasing depth means the water level is falling. A negative depth indicates water above the land-surface reference; it is not automatically an error. Levels in different wells cannot be ranked as wetter/drier by comparing raw depths.

The source also provides elevations above NGVD29 (62610) and NAVD88 (62611). Those are retained in the raw downloads and excluded from the depth display. They are often alternative representations of the same measurement, not additional independent observations. They must not be mixed with depth or with one another without datum handling.

Manual readings are limited to primary, static groundwater observations. Daily readings use mean statistic 00003 and unqualified values. Approval status is preserved, including provisional data. Daily means and manual visits are explicitly distinguished. Latest-daily records can be old; observation date, not retrieval or modification date, determines age. Missing observations stay missing. No temporal or spatial gaps are filled. The first import excludes non-static/qualified readings pending review rather than assuming they represent ambient conditions.

## Farm specificity and geography

Every mapped farm candidate is linked to the three closest wells with observations in the window. Distance is WGS84 geodesic distance from a representative point inside the mapped candidate, not from every field edge. These links are **context only**, with no maximum distance interpreted as sufficient coverage. Shared surface-watershed membership is recorded but does not establish a groundwater connection. Aquifers, screened depth, geology, pumping, and well construction must be evaluated before selecting a well as a farm proxy.

Yale Farm's nearest recent well is CT-NHV 201, about 8.67 km (5.39 miles) away and in a different mapped surface watershed. Two Hamden wells are about 9.49 km away and share a surface watershed with Yale Farm; their aquifer connection to the farm is still unverified. No farm-level groundwater level, drought severity, storage volume, well yield, or irrigation recommendation is inferred.

Town boundaries are used to audit local coverage. Source county fields may contain Connecticut planning-region names. The coverage map shows actual well points and towns containing observations; it is not an interpolated groundwater map. Wells close together may overlap on the map.

## Files, checks, and limitations

- `data/groundwater/`: original API responses, schemas, parameter definitions, and a source manifest with query URLs, saved times and SHA-256 hashes. API pagination is checked.
- `outputs/groundwater/`: well histories, CSV observations, town coverage, farm-to-well links, summary, and coverage map.
- `scripts/fetch_groundwater.py`: caches the fixed initial window. `--refresh` explicitly replaces this snapshot's responses; archive the existing folder before refreshing if preserving revisions is needed. Change the declared query dates and manifest together for a different window.
- `scripts/build_groundwater.py`: reconstructs the contextual links and summaries. No rainfall or existing boundary values are changed.
- `scripts/validate_groundwater.py`: checks source hashes, well uniqueness, dates, coverage counts, missing states, and all farm links.

## Full-period USGS histories and research challenger

The full daily records for the 8 forecast series are archived separately in `data/groundwater-history/20261104T210648297209Z/`. The archive contains **58,885 raw daily records**, from **2001–11–21 through 2026–11–03** overall; the shortest series begins in 2016. It preserves USGS approval status and qualifiers and includes a hash manifest. There are **840 provisional records** and **1 qualified record**. The history model excludes qualified readings but retains unqualified provisional readings, matching the current daily-input rule. The existing 90-day snapshot and sealed forecasts were not changed.

The original exploratory report and its separate current challenger forecast are saved in `outputs/forecasts/groundwater/history-challenger/`. The strict replay has three separate steps: `scripts/prepare_groundwater_blind_inputs.py` writes hashed snapshots containing only values through each historical cutoff; `scripts/create_groundwater_blind_hindcast.py` selects a method using training-period data and creates test forecasts from those snapshots only; then `scripts/score_groundwater_blind_hindcast.py` verifies and seals the forecasts before opening test-period values. For each monthly issue, the input cutoff is seven days earlier, targets are issue date +1 through +14, methods are frozen using 2019–2022, and test issues run January 2023–October 2026. The completed scorecard is `outputs/forecasts/groundwater/blind-hindcast/20261105T002058551933Z/scorecard.json`.

The blind replay issued **46 test windows** (8 wells each), scored **367 of 368 well-windows** and **5,132 well-days**, and left one incomplete window explicitly unscored. Average station error was **0.89 feet**, versus **0.90 feet** for the last-reading baseline; the model did better at **4 of 8 wells**. Error rose from **0.57 feet on day 1** to **0.89 feet on day 7** and **1.17 feet on day 14**; the baseline was nearly identical. This shows no meaningful improvement in accuracy. The historical API values may include revisions made after each simulated issue date, and their original publication timestamps are unavailable, so this is not a true historical data-vintage replay or live prospective verification. No prediction intervals are calibrated. The original prospective v1 remains the scored operational forecast until a separately versioned challenger is deliberately adopted and prospectively verified.

Two earlier artifacts are retained with audit records. Run `20261104T212931953710Z` has its forecasts and scorecard preserved, but is superseded for strict no-peek reporting because forecast generation and scoring were interleaved while the raw series were loaded. Run `20261105T001917655988Z` is also preserved but was not scored because a manifest bug produced only two issue dates. The complete, sanitized-input run above is the result reported here.

## Experimental two-week groundwater forecast

Farmer View option **11** now shows the latest sealed groundwater forecast alongside its verification status. The November 4, 2026 issue forecasts **8 monitored wells** for November 5–18. Each well uses only its own prior daily depth-to-water readings. The current process requires at least 70 clean daily observations in its trailing 90-day window, then selects among persistence, damped trend, and autoregression using two earlier two-week tuning windows. The original prediction files are preserved in `outputs/prospective/issued/`; later observations score them and do not change them.

An earlier retrospective check covers October 19–November 1 at those same 8 wells: average station mean absolute error was **0.42 feet**; a simple hold-the-last-level forecast averaged **0.54 feet**. The model beat that simple comparison at **4 of 8 wells**. This is one held-out two-week period and is much weaker evidence than the multi-year replay above. The prospective forecasts issued November 3 and 4 have **no completed comparisons yet**. There are no calibrated uncertainty ranges; displayed hundredths are not a claim of hundredth-foot accuracy.

The model forecasts the depth at each monitored well. Greater depth below land means a lower water level. It does not forecast groundwater under farms: the eight wells have not been shown to share an aquifer with the farm parcels, and a nearby well or shared surface watershed is not enough to establish that connection. No farm drought rating, usable groundwater volume, well yield, or irrigation advice follows from these forecasts.

### What would improve accuracy and precision

- **History quality and broader coverage.** Full histories for the eight model wells are now archived, but several contain gaps as long as 103–269 days, and the longest series still do not represent all aquifers or farms. USGS publishes daily values over each series' period of record and lets queries select a time-series ID; see the [USGS daily values API documentation](https://api.waterdata.usgs.gov/docs/ogcapi/).
- **More prospective verification.** Preserve every issue and score it when the first eligible daily reading arrives. Accumulate many non-overlapping seasonal and weather conditions; report error by well and lead day, and compare against persistence. Do not treat nearby wells or overlapping two-week windows as independent evidence.
- **Better local observation coverage.** Add active wells across Connecticut and farm-owned sensors, with accurate coordinates, sampling frequency, calibration, measurement method, well depth, screened interval, and aquifer identity. This is essential for farm-specific use.
- **Hydrologic context, if admitted as model inputs.** Groundwater recharge responds to precipitation, evapotranspiration, snow, soils, geology, pumping, and aquifer type, often with a delay. Those sources are not predictors in this groundwater-only model. A future version could use them as timestamped inputs while still forecasting groundwater as its sole output; its issue-time data cutoffs must be enforced and the model tested against the current baseline.
- **Calibrated uncertainty and consistent reference levels.** More historical tests are needed to estimate forecast ranges by well and lead time. Keep depth below land separate from water-level elevation and vertical datum, and flag provisional or revised observations instead of treating them as equally certain.

The daily-history request uses a bounding rectangle and then retains only sites identified as Connecticut wells. Raw neighboring-state observations are excluded. Manual history is filtered by Connecticut and well site type at the service. An absence in the queried window does not mean a well never had historical measurements; complete historical manual records have not been downloaded. The 30-day recency threshold is a display convention, not a hydrologic suitability test. Long-term seasonal groundwater percentiles have not been calculated.

Sources: [NGWMN portal](https://www.usgs.gov/apps/ngwmn/), [NGWMN services](https://www.usgs.gov/apps/ngwmn/web-services.jsp), [USGS Water Data APIs](https://api.waterdata.usgs.gov/), [API documentation](https://api.waterdata.usgs.gov/docs/ogcapi/). Attribution: U.S. Geological Survey, accessed November 2, 2026.
