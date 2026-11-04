# Connecticut farm-boundary inventory

The Yale workflow has been expanded across **all 169 Connecticut municipalities**. This is a statewide evidence inventory for finding and reviewing farm boundaries, not a verified census of every operating farm. Public imagery cannot establish leases, operated acreage, ownership, or farm-business identity by itself.

## What is ready

- **5,703 satellite-derived field candidates** from the 2025 Fields of the World product.
- **6,056 public mapped agricultural outlines or locations** from OpenStreetMap. These include 2,839 meadow records, which may represent unmanaged grassland; they are intentionally retained as review candidates, not called confirmed farms. Eight records are locations without an outline.
- **15,277 assessor records**, consolidated into **14,911 town-and-parcel keys**, retrieved through statewide agricultural-description screening and spatial intersection with the field candidates.
- **548 distinct CT Grown directory listings**, including farms, producers, stands, and markets. Of these, 492 have approximate Census-geocoded address locations. A sales address is not automatically production land.
- Town links, property-overlap fractions, watershed-overlap fractions, source attribution, review flags, and an app-ready local database.
- An overview map and a separate map for each of the 169 towns.

The 11,759 mapped candidate records are **not 11,759 farms**. One farm can have many fields and parcels; two source records can describe the same land. No neighboring fields have been merged into an assumed farm business. All records remain unreviewed, with no farmer-confirmed operating boundaries and no recommendations enabled.

## Use it without programming

Open **Start Here.cmd**, choose **6** in Farmer View, and enter a municipality name. The screen shows candidates and their supporting evidence, with numbered details and next/previous pages.

Files are under `outputs/statewide`:

- `statewide-map.svg` and `statewide-map.png`: overview.
- `towns`: numbered town maps, full geometry, and plain-language candidate information. Town numbers are in `town-coverage.csv`.
- `boundary-review.csv`: mapped field and public-outline review list.
- `property-without-field-review.csv`: agricultural property candidates that lack a mapped field.
- `directory-review.csv`: named directory leads, approximate locations, and nearby-outline search results.
- `town-coverage.csv`: coverage and missing assessor-description counts for every town.
- `field-candidates.geojson`, `property-candidates.geojson`, and `inventory.sqlite`: spatial data for the developing app.
- `field-property-links.csv`, `field-watershed-links.csv`, `field-town-links.csv`: spatial relationships, including split areas.
- `summary.json` and `validation.json`: counts and checks.

## Measured gaps

Norwalk, Thomaston, West Haven, and Wolcott have **no mapped field/public-outline candidates in the selected sources**. This does not mean they have no farms. All four remain in the coverage report.

There are **752 agricultural property candidates without a mapped field**, **410 directory listings without a nearby outline or with an unresolved location**, **one candidate without a property match**, and **two candidates without a watershed match**. Directory proximity uses a 100-meter search radius around an approximate street location; it does not establish an operator relationship or farm boundary.

The satellite publisher supplies no neighborhood confidence value for the Connecticut candidates in this download. Scores remain missing; they have not been converted to zero or invented. One malformed OSM relation could not be made into a closed boundary and is recorded in the processing audit. The satellite files also have inconsistent collection-level bounding-box metadata; selection was performed using actual geometries instead.

The number of farms missing from **every** source remains unknown. Establishing recall requires an independent farm roster and operator/field checks. No numerical accuracy or statewide completeness percentage is claimed.

## Sources and dates

1. [Fields of the World](https://source.coop/ftw/global-data): published PRUE model outputs derived from Sentinel-2 imagery, **2025**, CC-BY-4.0, Taylor Geospatial and collaborators. These are existing model predictions, not a newly trained Connecticut model. Connecticut and neighboring NY, MA, and RI partitions were checked; geometry duplicates were removed. The original 2024 observations remain in the downloaded source files but are not added to the current inventory.
2. [OpenStreetMap](https://www.openstreetmap.org/copyright): statewide agricultural land-use polygons and farm/community-garden locations, © OpenStreetMap contributors, ODbL. Per-record edit dates are retained; an edit date does not prove the date of agricultural observation or current operation.
3. [CT GIS Office parcel service](https://services3.arcgis.com/3FL1kr7L4LvwA2Kb/arcgis/rest/services/Connecticut_CAMA_and_Parcel_Layer/FeatureServer/0): original record collection years retained. Geometry and completeness vary by municipality. Owner names and mailing addresses were not requested.
4. [CT DOT municipalities](https://services1.arcgis.com/FCaUeJ5SOVtImake/arcgis/rest/services/CT_Municipalities/FeatureServer/0): 169 town boundaries, also unioned to form the Connecticut analysis mask.
5. [CT DEEP watershed boundaries](https://cteco.uconn.edu/guides/Subregional_Basin.htm): existing subregional layer from the earlier project step.
6. [CT Grown map linked by the state](https://portal.ct.gov/sde/nutrition/ct-fresh-ed/ct-farm-to-school-directory): directory export with unknown individual listing dates. The directory includes markets and producers; its listings are not all farms or a complete roster.
7. [Census Geocoder](https://www.census.gov/programs-surveys/geography/technical-documentation/complete-technical-documentation/census-geocoder.html): approximate address locations using Public_AR_Current, not surveyed farm positions.

Download URLs, retrieval timestamps, raw responses, and file hashes are retained under `data/statewide`. The Yale aerial/satellite comparison remains available separately. **High-resolution aerial imagery has not been individually reviewed for every statewide candidate.**

## Method and safeguards against misleading results

Source fields were clipped to the Connecticut town-union mask. Full originals remain available, including cross-border source geometry. Areas and spatial overlaps are calculated in the CONUS equal-area projection EPSG:5070. Field-to-watershed joins use polygon intersections rather than only centroids. Pieces below one square meter are excluded from overlap relationships to avoid boundary slivers. Town boundary detail and legacy watershed detail have their own positional limitations.

Property retrieval combines broad agricultural-use descriptions with spatial searches around every mapped candidate. Solar and tank-farm descriptions are excluded from the text screen. Other misleading descriptions can remain, so a text match alone is never treated as proof of agriculture. Parcel source records sharing a town and parcel ID are grouped; all original record IDs remain attached. Geometries are unioned for that property key, not across assumed operators.

Overlapping satellite and public-map records are linked when at least 10% of the candidate's area overlaps the other source. This is a review aid, not a calibrated confidence measure. Meadow tags, null confidence, locations without polygons, and unmatched boundaries are flagged. No attempt is made to infer planted acreage or crops from the full assessor property.

Validation checks unique identifiers, valid geometry, all-town accounting, area fractions, unconfirmed status, and the Yale regression (parcel 14057; Mill River basin 5302). It is **data-integrity validation**, not proof that every polygon is a correct agricultural field.

## Rebuild

The processing environment is local to `.venv`; dependencies are recorded in `requirements-statewide.txt`. Download scripts cache completed responses and fail on missing/truncated parcel batches instead of silently accepting partial data.

1. `.venv\Scripts\python.exe scripts/fetch_statewide.py sources`
2. `.venv\Scripts\python.exe scripts/fetch_statewide.py ag-parcels`
3. `.venv\Scripts\python.exe scripts/fetch_statewide.py directory`
4. `.venv\Scripts\python.exe scripts/prepare_directory.py --fetch`
5. `.venv\Scripts\python.exe scripts/prepare_statewide.py`
6. `.venv\Scripts\python.exe scripts/fetch_statewide.py field-parcels`
7. `.venv\Scripts\python.exe scripts/build_statewide_inventory.py`
8. `.venv\Scripts\python.exe scripts/validate_statewide.py`
9. `.venv\Scripts\python.exe scripts/render_statewide_maps.py`

These rebuild the current unreviewed snapshot. A future review system must preserve operator corrections separately before allowing refreshes to replace derived geometry. No scheduled downloads, external publishing, or farmer outreach has been set up.
