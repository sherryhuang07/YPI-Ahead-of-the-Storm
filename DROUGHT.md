# Combined drought forecast

The app's final drought model. It forecasts the next two weekly **U.S. Drought Monitor** maps for Connecticut and each of its 9 planning regions, using every other model's data plus the Palmer Drought Severity Index. Every mapped farm takes its planning region's forecast. Farmer View option **17** shows it; daily tests are in option 11.

## Data

| Input | Source | Coverage | Used as |
|---|---|---|---|
| U.S. Drought Monitor | [data service](https://usdmdataservices.unl.edu/api/) (`scripts/fetch_drought_data.py`) | weekly maps 2000-2026, statewide + 9 planning regions | target, and current state + 4-week change |
| Palmer PDSI, PHDI, Z-index | [NOAA NCEI climate divisions](https://www.ncei.noaa.gov/monitoring-content/data/us/climdiv/monthly/current/) | monthly 1895-Sep 2026, 3 CT divisions | statewide mean of the latest month published by the issue date (treated as published on the 10th of the next month) |
| Rain | airport records (fire-danger weather) | daily 1997- | 30/90/180-day totals, rain since the last map, rain until the target map |
| Streamflow | USGS daily discharge, 109 gauges with 2000-2026 records | daily | median gauge departure of 7-day flow |
| Groundwater | USGS daily water levels, 8 wells | daily 2001- | median well departure (deeper = drier) |
| Root-zone soil moisture | NLDAS-2 (USGS archive to 2020; NASA single 17 UTC hour per day 2021-2026; live inputs after) | daily 2000- | statewide departure, 6-day publication lag |
| Fire danger Build Up Index | 1964 NFDRS rebuild | daily 1997- | statewide median |
| Coastal water temperature | NOAA NDBC | daily 2004- | mean station departure |
| VegDRI | USGS EarthExplorer | weekly 2009- | **not yet included**: waiting for USGS account access |
| Reservoirs | CT DPH reports | 11 snapshots | not used: too sparse to train on |

Every input becomes a departure from normal for the time of year, using climatology from 2000-2014 only. Missing values become "normal" with a missing flag; nothing is filled with a guessed dry or wet value. The 2021-2026 soil series uses one NASA hour per day: in a 2020 check, a single 17 UTC hour differed from the 24-hour mean by 0.0004 m3/m3 on average.

The Drought Monitor service has recalculated 2000-present on Connecticut's 9 planning regions, so there is one consistent regional series. Farms are assigned to regions with U.S. Census TIGERweb boundaries (`scripts/build_farm_regions.py`, `data/drought/farm-regions.json`): all 11,760 mapped farm candidates (11 shoreline or border points by nearest region); Yale Farm is in the South Central Connecticut region.

## Model

`scripts/drought_features.py`, `scripts/train_drought.py`. Samples are every weekly map since 2000 for the state and each region (pooled), issued on its Thursday release, with targets 1, 2 and 3 maps later.

- **Chance of change** (the main product): regularised logistic regressions give the probability that the area's class (the most severe Drought Monitor category covering at least half the area) is worse, or better, by the target map.
- **Class**: the current class, moved one step only if worsening or improving is more likely than not.
- **Area percentages**: ridge regressions for the share of area at D0+ through D4+. On the calibration years they did not beat "unchanged" until changes under 60 index points were snapped back, so these stay close to the current map.
- **Rain during the forecast weeks**: training uses the rain that fell. Live forecasts use NOAA NBM at five airports where it reaches (about 10 days), normal rain for the remaining days.

Fit on maps through 2014; penalties and the snap-back threshold chosen on 2015-2018; tested on 2019-2026 (2020, 2022 and 2024 droughts), with predictions sealed before scoring. `outputs/drought/latest.json`:

| Weeks ahead | Class right (unchanged map) | Worsening: AUC / skill (normal rain) | Improving: AUC / skill (normal rain) | Skill with perfect rain (worse / better) |
|---|---|---|---|---|
| 1 | 91% (90%) | 0.87 / +0.11 | 0.87 / +0.11 | +0.14 / +0.19 |
| 2 | 84% (83%) | 0.84 / +0.16 | 0.90 / +0.21 | +0.26 / +0.31 |
| 3 | 80% (76%) | 0.84 / +0.16 | 0.92 / +0.31 | +0.31 / +0.42 |

AUC is the chance that a week whose class really changed got a higher forecast probability than one that didn't (0.5 = no skill). Skill is the Brier skill score against always forecasting the normal frequency of change. The class accuracy is the perfect-rain case. Live forecasts sit between the normal-rain and perfect-rain columns. The model is weak at naming the exact new class, and good at telling which weeks are likely to change. Regions are correlated with each other and with the state, and Drought Monitor maps include expert judgment.

## Daily sealed forecast

The night run (`daily-forecasts.ps1 -Part night`) runs the drought step after all other inputs are refreshed: `fetch_drought_data.py --recent` (Palmer and this year's maps; first-download times recorded in `data/drought/usdm-first-seen.json`), then `scripts/drought_daily.py`. It seals the next two Tuesday maps after today in its own append-only ledger (`data/drought-prospective`, `outputs/drought-prospective`): per area the Drought Severity and Coverage Index (DSCI, 0-500; the scored value), percentages, chance worse and better, and the class. Forecasts are scored only against map values first downloaded after they were issued, beside "unchanged map". A learning version (`learning_daily.py`, model `drought`) corrects the DSCI from scored comparisons, like the other models.

## VegDRI: what's needed

Run `Connect USGS EarthExplorer.cmd`. You need a free USGS account (https://ers.cr.usgs.gov/register), approval for machine-to-machine access (request "Access to EE's M2M API" in your USGS profile), and an application token (https://ers.cr.usgs.gov/password/appgenerate). The window checks the sign-in, saves it with Windows encryption, and lists the VegDRI datasets visible to the account. VegDRI will then be added as a separately versioned model (`drought-v2`), so the sealed `drought-v1` record stays comparable.

## Limits

Drought Monitor maps are broad-scale; a farm's conditions can differ from its region's. The model forecasts dryness only, not excess moisture. Reservoirs are not included.
