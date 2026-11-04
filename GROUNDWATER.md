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

The daily-history request uses a bounding rectangle and then retains only sites identified as Connecticut wells. Raw neighboring-state observations are excluded. Manual history is filtered by Connecticut and well site type at the service. An absence in the queried window does not mean a well never had historical measurements; complete historical manual records have not been downloaded. The 30-day recency threshold is a display convention, not a hydrologic suitability test. No long-term seasonal percentiles or groundwater forecast has been calculated.

Sources: [NGWMN portal](https://www.usgs.gov/apps/ngwmn/), [NGWMN services](https://www.usgs.gov/apps/ngwmn/web-services.jsp), [USGS Water Data APIs](https://api.waterdata.usgs.gov/), [API documentation](https://api.waterdata.usgs.gov/docs/ogcapi/). Attribution: U.S. Geological Survey, accessed November 2, 2026.
