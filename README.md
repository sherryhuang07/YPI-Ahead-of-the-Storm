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

Farm sensors, soil data, research papers, and local resources are not connected yet. This app does not recommend farm actions.

Choose **8** for groundwater observations and monitoring gaps. The initial USGS snapshot includes 67 wells with readings in the past 90 days, contextual nearby-well links for mapped farm candidates, and a town coverage audit. Nearby readings are not farm measurements. See `GROUNDWATER.md` and `outputs/groundwater/groundwater-coverage.png`.

Choose **9** for USGS streamflow, complete-window averages, and official seasonal percentile bands. The initial snapshot has recent daily data for 69 Connecticut gauges and usable seasonal thresholds for 59. See `STREAMFLOW.md` and `outputs/streamflow/mill-river-streamflow.png`. Farm water access and upstream/downstream connections remain unverified.

Activity is saved on this computer in `activity.log`. Earlier entries may appear when you reopen the windows. Data import scripts request public datasets online; browsing the saved results works locally.

The geographic foundation is documented in `WATERSHEDS.md`. The original boundary download is in `data/watersheds.geojson`. Run `node build-watersheds.cjs` to rebuild the catalog and map from that saved download.
