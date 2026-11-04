# Cumulative precipitation

PRISM is the first weather input. Choose **7** in Farmer View. The first snapshot uses 90 consecutive daily grids labeled August 4 through November 1, 2026, retrieved November 2. The download and calculation steps write plain-English updates to Behind the Scenes.

Totals cover the preceding 7, 14, 30, 60, and 90 PRISM days, inclusive of the end date. PRISM labels a day by the date its 24-hour period ends at 12:00 UTC. These are not local-midnight calendar days. For example, the 90-day interval is August 3 at 12:00 UTC through November 1 at 12:00 UTC.

## What these numbers mean

- Total precipitation depth: rain plus snow's liquid-water equivalent, shown in millimeters and inches (25.4 mm per inch).
- PRISM's nominal 800-meter product is a 30-arcsecond modeled grid. It is not a network of gauges every 800 meters. Cell dimensions vary with latitude. Fine grids do not guarantee field-scale accuracy.
- The Yale Farm outline and statewide field candidates remain unconfirmed. Nearby farms can have identical rainfall estimates because they share a grid cell. No sensor observations have been added.
- Recent data may be revised during PRISM's rolling six-month update period. This is a reproducible saved snapshot, not a live feed. Refreshes should use a new dated snapshot so earlier results remain auditable.
- Precipitation alone cannot establish drought, effective root-zone rainfall, irrigation need, or runoff. Historical rainfall comparisons, evapotranspiration, soils, crops, irrigation, and sensors remain future inputs. No forecast or farm recommendation is generated.

## Calculation and missing data

Daily source grids are cropped to the Connecticut bounding rectangle without resampling. Original NAD83 (EPSG:4269) coordinates and grid alignment are retained. Daily source metadata, download timestamps, ZIP hashes, and crop hashes are saved beside each crop. Millimeter units are verified in the source metadata. The download is cached and resumable; a failed day prevents publishing a complete snapshot.

Each window sums consecutive daily depths per cell. Any missing day makes that cell's window total missing; missing values never become zero. Farm and watershed averages use polygon intersections with grid cells, measured in the EPSG:5070 equal-area projection. Weights are overlap area divided by the feature area. A partial valid area is reported as coverage, but its total is withheld rather than silently averaging only the available cells. For the eight point-only candidates, the containing grid is used and the method is labeled separately.

Watershed pieces with the same basin ID are dissolved, then clipped to Connecticut. Results describe **only the Connecticut portion**, not upstream rainfall outside Connecticut. Original watershed boundaries are retained separately for later hydrologic modeling. Land outside the state is not included in these precipitation summaries.

## Saved files and rerunning

`data/prism/2026-11-02/` contains daily Connecticut GeoTIFFs, source metadata, release information, and the manifest. National ZIP files downloaded by the importer are removed after successful cropping to conserve space; the initial November 1 sample ZIP is retained.

`outputs/precipitation/` contains cumulative GeoTIFF grids, CSV totals, a grid-overlap audit, JSON records for the app, and a summary. Farm candidate IDs match `outputs/statewide/field-candidates.geojson`; watershed IDs match CT DEEP's basin identifiers. Overlapping candidate records are not independent farms and should not be added together.

Run `.venv\Scripts\python.exe scripts/fetch_prism.py` to resume the initial download, then `.venv\Scripts\python.exe scripts/build_precipitation.py` to calculate totals. The importer accepts `--end YYYY-MM-DD --snapshot YYYY-MM-DD --days 90`. Run the builder with the same `--snapshot` value. No scheduled update is installed. Avoid repeatedly requesting the same PRISM download; the service limits repeat requests.

## Sources

### November 2 map audit

The original map compressed the visible differences with a zero-based color scale and distracting grid seams. The revised map uses a clearly labeled 1.75–3.25 inch display scale, removes drawing seams without changing the cells, and adds location values. This scale highlights spatial differences; it must not be interpreted as drought severity or reused across dates without checking its bounds.

Across Connecticut-centered grid cells, the 30-day totals range from 1.8367 to 3.1457 inches; the 5th–95th percentile range is 2.1683–2.8263 inches. These are equal-cell statistics, not an area-weighted state average. Recalculating the daily sum reproduced the stored grid. The entire October 12 storm-day crop and November 1 crop matched their original national source grids exactly.

A limited NOAA check returned 28 daily reports per station, October 3–30. Bradley Airport reported 2.3701 inches versus PRISM's 2.3641 inches at its location; Sikorsky Memorial Airport reported 1.9882 inches versus PRISM's 2.4682 inches. These comparisons use the same date labels, not exactly aligned observation intervals: station days end at 2400 and PRISM days at 12 UTC. Trace flags are retained. The roughly 0.48-inch Sikorsky difference remains unexplained and is not corrected by changing the map colors. These two stations cannot establish statewide or farm-scale accuracy and may themselves contribute to PRISM.

Run `scripts/audit_precipitation.py` with the project Python environment to reproduce the audit from saved evidence. Results and the NOAA query are in `outputs/precipitation/audit.json`; source evidence is in `data/prism/audit/`. No rainfall values were changed by this audit.

Attribution: **PRISM Group, Oregon State University, https://prism.oregonstate.edu, accessed November 2, 2026.**

- [PRISM Explorer](https://prism.oregonstate.edu/explorer/)
- [PRISM dataset documentation](https://prism.oregonstate.edu/documents/PRISM_datasets.pdf)
- [Download service documentation](https://prism.oregonstate.edu/documents/PRISM_downloads_web_service.pdf)
- [PRISM data revision information](https://prism.oregonstate.edu/data/)
- [800-meter availability announcement](https://prism.oregonstate.edu/whatsnew/)
- [Terms of use](https://prism.oregonstate.edu/terms/)

The alternative [readnoaa R package](https://github.com/charlescoverdale/readnoaa) accesses NOAA station data. It is not installed here. Station observations may later support comparisons with the grid and farm gauges, but they are not automatically independent validation because PRISM itself uses station observations.
