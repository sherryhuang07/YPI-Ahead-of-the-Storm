# YPI-Ahead-of-the-Storm

First step: two plain-English terminal windows for a Connecticut farm water-stress app.

Double-click **Start Here.cmd** to open both windows.

- **Farmer View** shows the starting interface. Type 1, 2, or 3 and press Enter to explore it. Type Q to close it.
- **Behind the Scenes** shows actual activity from the farmer window, along with what still needs to be set up. Close this window separately when finished.

Official CT DEEP watershed boundaries are saved locally. Choose **4** in Farmer View to explore eight major drainage areas and their smaller watersheds. Open `watershed-map.svg` for the map.

Choose **5** to inspect the Yale Farm pilot. `yale-farm-boundary-review.svg` compares public property and farm outlines over actual aerial and satellite images. The farm outline is provisional; it is not a measurement of planted land. See `FARM-BOUNDARIES.md` for sources, methods, and review needs.

Choose **6** to browse statewide farm-boundary candidates by town. All 169 towns are included in the coverage audit. Maps and review lists are saved in `outputs/statewide`. Read `STATEWIDE-INVENTORY.md` for the results and known gaps. These candidates are not a verified count of farms.

Choose **7** for cumulative precipitation from PRISM's nominal 800-meter daily grids. The saved snapshot covers 90 days through November 1, 2026; it is not automatically refreshed. Totals are available for Yale Farm, statewide farm candidates, and Connecticut portions of watersheds. See `PRECIPITATION.md` for methods and limitations.

Choose **1** for three separate experimental 14-day forecast baselines. They use only their own precipitation, groundwater, or streamflow history. They are not operationally validated: the rainfall baseline failed its held-out comparison, farm groundwater is unavailable, and streamflow is limited to supported gauges. See `FORECASTS.md` for actual coverage and test results.

Farm sensors, research papers, and local resources are not connected yet. Root-zone soil moisture (historical test plus a live 1-14 day research forecast) is available separately under option 14. This app does not recommend farm actions.

Choose **8** for groundwater observations and monitoring gaps. The initial USGS snapshot includes 67 wells with readings in the past 90 days, contextual nearby-well links for mapped farm candidates, and a town coverage audit. Nearby readings are not farm measurements. The daily forecast check in **11** now displays the separate 14-day groundwater model for 8 monitored wells. See `GROUNDWATER.md` for its measured test error, limits, and improvements needed, and `outputs/groundwater/groundwater-coverage.png` for monitoring coverage.

Choose **9** for USGS streamflow, complete-window averages, and official seasonal percentile bands. The initial snapshot has recent daily data for 69 Connecticut gauges and usable seasonal thresholds for 59. See `STREAMFLOW.md` and `outputs/streamflow/mill-river-streamflow.png`. Farm water access and upstream/downstream connections remain unverified.

Choose **13** for Connecticut DPH drinking-water surface-capacity data and the public-history baseline check. The current local import is the November 12, 2024 snapshot for 34 public water systems. We have assembled 11 dated snapshots in total spanning 2022–2024, but the observations are too sparse and uneven for a reliable current two-week model. See `RESERVOIRS.md` and `RESERVOIR-PUBLIC-HISTORY.md`.

Activity is saved on this computer in `activity.log`. Earlier entries may appear when you reopen the windows. Data import scripts request public datasets online; browsing the saved results works locally.

Choose **14** for the standalone root-zone soil moisture experiment: one-through-fourteen-day historical predictions using USGS/NLDAS watershed histories, with held-out testing, plus a live research forecast from recent NASA NLDAS-2 inputs (double-click `Refresh Soil Moisture.cmd` to refresh). It does not feed an overall drought model. Farm sensor validation remains pending. CPC legacy tables have been deleted. See `ROOT-ZONE-SOIL-MOISTURE.md`.

Choose **15** for the forest fire danger forecast: 14 days of Connecticut's statewide class (LOW to EXTREME, DEEP's scale), recalculated with the 1964 national fire-danger method from airport weather and NOAA forecasts, checked against DEEP's published ratings and tested daily. See `FIRE-DANGER.md`.

Choose **16** for the coastal water temperature forecast: 14 days of daily mean water temperature at Long Island Sound and Connecticut coastal stations from NOAA National Data Buoy Center readings only, tested on held-out 2022-2025 and sealed daily. See `WATER-TEMPERATURE.md`.

Choose **17** for the combined drought forecast: the next two weekly U.S. Drought Monitor maps for Connecticut and its 9 planning regions (each farm takes its region's forecast), with the chance of the drought class worsening or improving, built from every model here plus the Palmer Drought Severity Index. Tested on held-out 2019-2026 and sealed daily. See `DROUGHT.md`.

The geographic foundation is documented in `WATERSHEDS.md`. The original boundary download is in `data/watersheds.geojson`. Run `node build-watersheds.cjs` to rebuild the catalog and map from that saved download.
