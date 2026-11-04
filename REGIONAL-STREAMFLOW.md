# Stream gauges connected across state borders

The regional map identifies 90 connected gauges outside Connecticut: 40 in Massachusetts, 10 in New York, 9 in Rhode Island, 17 in Vermont and 14 in New Hampshire. Upper-basin states are included because water networks cross more than one state border.

Farmer View option 12 lets you search a waterway and see its connected gauges, direction and available forecasts. The Connecticut River group has 64 connected gauges including tributaries; Housatonic has 6, Farmington 1, Quinebaug 2 and Pawcatuck 9. These are network connections, not counts of gauges on each main stem.

## Mapping and limits

Five regional NHDPlus HR geodatabases supply 392,792 river reaches and 397,017 directed connections. The inventory contains 89,919 Connecticut water features, including 39,335 waterbody polygons and 1,488 named waterways. Of these features, 1,583 have an established connection to an included out-of-state gauge. A missing association is displayed as missing, not filled by proximity alone.

Official USGS gauge-to-reach references are preferred. Supplemental associations require a unique containing catchment, matching waterway name and a stream within 100 meters. These are labeled spatial associations and remain less certain than a checked official reference. There are 294 unresolved recent gauges across the five-state inventory; many are outside the regional basins, so this is not a count of missing Connecticut connections.

Coastline, sea and estuary routes are excluded to prevent false connections across Long Island Sound. Reservoir operations, tides and travel time are not simulated. Lakes require inlet/outlet context; no lake-wide discharge is invented.

## Forecasts and honest evaluation

66 of the 90 gauges passed the history and input requirements and have separately archived 14-day forecasts. The other 24 remain without forecasts. Training uses streamflow history alone, with chronological selection in 2021–2022, interval calibration in 2023 and retrospective testing from 2024 onward. 65 of 66 beat persistence in that retrospective comparison; this does not establish future performance or improved Connecticut forecasts.

The regional-v1 model is frozen in data/regional-prospective/model-v1.json. Its first prospective issue was November 4, 2026, for November 5–18. Original Connecticut predictions and models are retained separately. These new forecasts describe their own gauge locations; they are contextual information, not routed predictions at ungauged Connecticut waters.

Run scripts/regional_daily.py after scripts/prospective_daily.py. The regional job maintains its own append-only ledger, timestamped input snapshots, sealed forecast files and scoreboard under data/regional-prospective and outputs/regional-prospective. Neither job may backdate forecasts or use future observations as inputs.

Sources: [USGS water-data API](https://api.waterdata.usgs.gov/) and [USGS national hydrography products](https://www.usgs.gov/national-hydrography/access-national-hydrography-products). Raw inventories, association records and downloaded history are retained locally for review.

## Upstream-input challenger (November 4, 2026)

A separate streamflow-only experiment tested whether upstream gauge readings improve a Connecticut gauge forecast. It uses at most three upstream gauges, tests time delays of 0, 1, 3 and 7 days, selects settings using 2021–2022, calibrates ranges on 2023 and evaluates on disjoint fortnights from 2024 through November 2, 2026. The original forecasts and their ledger remain separate.

Only 15 Connecticut gauges had enough overlapping upstream data for this paired historical comparison. The upstream model reduced average absolute error at 6 of 15 gauges; median error change was a 0.36% increase. Results varied by site: West Branch Farmington River at Riverton improved 11.2%, while Farmington River at Tariffville worsened 2.6%. Housatonic at Stevenson improved 1.6%; at Gaylordsville it improved 0.6%. The experiment did not establish a consistent statewide benefit. Low-flow detection also remains weak: the Riverton model missed 125 of 242 historical low-flow days, where “low flow” means below that gauge’s historical monthly 20th percentile, not an official drought threshold.

A separate leave-one-gauge-out transfer test withheld each target gauge’s complete history from donor selection, training and calibration, then compared estimates at those already monitored test sites. It covered 69 sites; median error was 55% of each site’s mean observed flow. This is evidence that simple transfer can have large errors. It is not validated coverage for unmonitored streams, farms or water supplies.

On November 4, a prospective upstream forecast and a paired own-history forecast were sealed for each of 14 eligible Connecticut gauges. One target gauge was unavailable under the input/model eligibility rules. These are the first live issues; there are no completed target dates or prospective accuracy comparisons yet. The NOAA long-range benchmark returned no usable forecasts for the 69 attempted gauges on this run. It is recorded as unavailable, not as zero flow. The separate regional model still provides context forecasts at 66 out-of-state gauges.

Farm priorities are available in `outputs/streamflow-experiments/coverage-audit.json`, but farm candidate drainage links do not reveal irrigation intakes, wells or withdrawals. The Yale Farm’s actual water source and sensor location must be established with the farm before a gauge can be called a farm-specific supply monitor. Detailed methods and issue ledgers are in `outputs/streamflow-experiments/`, `outputs/challenger-prospective/` and `data/challenger-prospective/`.
