# Coastal water temperature model

A separate 14-day forecast of daily mean water temperature at Long Island Sound and Connecticut coastal stations. It uses only NOAA National Data Buoy Center (NDBC) water temperature, no other dataset, and feeds no other model. Farmer View option **16** shows it; daily tests appear in option 11.

## Data

`scripts/fetch_water_temp.py` reads NDBC standard meteorological files (column `WTMP`, deg C) in three layers, preferring the earlier, quality-controlled one where they overlap: yearly history (`data/historical/stdmet/<id>h<year>.txt.gz`), current-year monthly files (`data/stdmet/<Mon>/<id>.txt`), and the provisional last 45 days (`data/realtime2/<ID>.txt`). Raw files are cached in `data/water-temp/raw`. Daily means use Connecticut local days and need readings in at least 12 different hours; values outside -3 to 35 C and readings more than 5 C from that day's median are dropped. Missing days stay missing. Output: `data/water-temp/daily.csv`, hashed in `manifest.json`.

| Station | NDBC id | Daily means | Status (November 2026) |
|---|---|---|---|
| Bridgeport, CT (NOAA 8467150) | brhc3 | 2004-2026 | live |
| New Haven, CT (NOAA 8465705) | nwhc3 | 2004-2026 | live |
| New London, CT (NOAA 8461490) | nlnc3, then nlhc3 from 2023 | 2004-2026 | live (two ids joined) |
| Montauk, NY (eastern entrance) | mtkn6 | 2004-2026 | live |
| Kings Point, NY (western Sound) | kptn6 | 2004-2025 | no water temperature since 2025-12-31 |
| Central Long Island Sound buoy | 44039 | 2004-2024 | stopped April 2024 |
| Execution Rocks buoy | 44022 | 2005-2023 | stopped September 2023; too few complete examples |
| Western Long Island Sound buoy | 44040 | 2004-2005 | too short |
| New London Ledge Light | ldlc3 | none | no water temperature column |

Buoys in the Sound are seasonal and have long gaps. The model still learns from their history, but only stations whose data is arriving can be forecast each day.

## Model and held-out test

`scripts/water_temp_model.py` and `scripts/train_water_temp.py`. For each station and forecast day, the forecast is the station's seasonal normal (annual and semiannual cycle fitted on training years) plus a ridge regression on yesterday's departure from normal, the mean departure over the last 7 days, the 7-day change, and seasonal terms of the target day. It is used only where it beat "unchanged since yesterday" on the calibration years; elsewhere the forecast is "unchanged". Nominal 90% ranges come from calibration errors.

Fit on target days through 2018; choice and ranges on 2019-2021; test on 2022-2025, with predictions sealed and hashed before scoring (`outputs/water-temp/latest.json`):

| Forecast day | Model error (C) | Unchanged | Seasonal normal | 90% range held |
|---|---|---|---|---|
| 1 | 0.51 | 0.56 | 1.23 | 89% |
| 7 | 0.85 | 1.22 | 1.23 | 87% |
| 14 | 0.96 | 1.89 | 1.24 | 86% |

It beat both comparisons at every station tested. Bias grows to -0.2 C by day 14 (forecasts slightly too cool; recent years ran warm). Nearby stations and overlapping windows are correlated, not independent tests. Daily means are NDBC readings, which are themselves provisional in the latest 45 days.

## Daily sealed test

The night run (`daily-forecasts.ps1 -Part night`, 12:05 AM) refreshes recent NDBC data (`fetch_water_temp.py --recent`) and seals a forecast with `scripts/water_temp_daily.py` in its own append-only ledger (`data/water-temp-prospective`, `outputs/water-temp-prospective`). Yesterday is the last input day; forecasts cover tomorrow through 14 days ahead. A station missing yesterday's daily mean, or with fewer than 5 of the last 7, is withheld for the day. The frozen model is registered once and checked by hash. Later runs record each target day's first captured daily mean and score sealed forecasts against it, beside "unchanged since yesterday". A learning version (`learning_daily.py`, model `water-temp`) corrects forecasts from scored comparisons, like the other models.

## Limits

No weather forecast is used, so the model cannot foresee a sudden storm, heat wave or upwelling. Values describe each buoy or pier, not every cove, river mouth or farm pond.
