# Forest fire danger model

A separate 14-day forecast of Connecticut's statewide forest fire danger class: **LOW, MODERATE, HIGH, VERY HIGH, EXTREME**, the scale used by the DEEP Division of Forestry ([explanations](https://portal.ct.gov/DEEP/Forestry/Forest-Fire/Forest-Fire-Weather-Information-and-Danger-Explanations), [daily report](https://portal.ct.gov/deep/forestry/forest-fire/forest-fire-danger-report)). It does not feed any other model. Farmer View option **15** shows it.

## What DEEP publishes, and why the model rebuilds it from weather

DEEP posts one statewide rating for 1:00 PM, usually before 8:00 AM, during the spring (mid-March to mid-May) and fall seasons and other high-danger periods. Only the current rating is online; DEEP's email-list archive is not publicly reachable. The Internet Archive holds 50 snapshots of the report from 2020-2026, of which 31 contain a rating (the rest are DEEP error pages). That is not enough to train a forecast, so, by choice, the model recalculates DEEP's two indexes from public weather records and checks the result against DEEP's real ratings. This uses weather data, so it is not isolated to DEEP's own dataset.

DEEP's ratings come from the 1964 National Fire Danger Rating System: a **Spread Index** (wind, humidity and fine-fuel moisture) and a **Build Up Index** (drying since the last rain over 0.1 inch), with these class limits:

| Class | Spread Index | Build Up Index |
|---|---|---|
| LOW | 0-10 | 0-22 |
| MODERATE | 11-15 | 23-44 |
| HIGH | 16-29 | 45-59 |
| VERY HIGH | 30-39 | 60-74 |
| EXTREME | 40+ | 75+ |

`scripts/fire_danger_model.py` translates subroutine DANGER from W. A. Main (1969), *Computer calculation of fire danger*, USDA Forest Service Research Note NC-79 ([Treesearch](https://research.fs.usda.gov/treesearch/11136)), line by line. The printed listing's `A(2) = -0.85900` is a typo for `-0.0859` (the paper's formula table; only that value keeps fine-fuel moisture continuous where the regimes meet). Herb stage (cured, transition, green) follows DEEP's description by calendar: cured mid-November to April, transition in May and October to mid-November, green June to September. That calendar is an assumption.

## Rebuilt history (1997-2026)

- Weather: five airports (Hartford Bradley, Bridgeport, New Haven, Danbury, Windham). For each day, the report nearest 1 PM (temperature, dew point, wind) from the Iowa Environmental Mesonet ASOS archive (NOAA METAR reports), snow depth from NOAA GHCN-Daily. `scripts/fetch_fire_weather.py`, hashed in `data/fire-danger/weather/manifest.json`.
- Rain in the 24 hours ending 1 PM: hourly airport rain exists only from 2012, so for a consistent 30-year history it is estimated from NOAA daily totals as 11/24 of yesterday plus 13/24 of today. Against the true window (2012 onward) that estimate has correlation 0.70-0.80 and gets the 0.1-inch rain decision right on 86-87% of days. For the last few days, before NOAA's daily totals arrive, the exact hourly window is used.
- Wind: airports measure at 33 ft in the open; the 1964 system uses 20 ft. A standard wind-profile reduction of 0.87 is applied (physics, not fitted).
- Statewide value: median of airports with complete weather (at least 3). A day with missing weather is left blank; the Build Up Index carries forward unchanged, never filled with an assumed dry or wet day. `scripts/build_fire_danger_history.py` writes `data/fire-danger/history.csv`.

## Checked against DEEP's real ratings

`scripts/validate_fire_danger.py` compares the rebuild with every archived DEEP rating (`data/fire-danger/validation.json`). On 32 ratings, the class from the **Build Up Index** (median airport) matched exactly on 50% and within one class on 94%, with almost no bias (+0.12 class). Average class error: Build Up 0.61, Spread 0.65, higher-of-the-two 0.77 (computed on the first 31). That is close to a tie and rests on few ratings. The Build Up rule misses spring wind-driven HIGH days that DEEP rated from the Spread Index (for example March 2021, March 2022, April 2023), and DEEP tends to say LOW in winter regardless of the indexes. Every sealed forecast stores both indexes, so the rule can be revisited once DEEP's daily ratings accumulate next spring.

## Forecast and tests

`scripts/fire_danger_forecast.py`:

- Days with NOAA National Blend of Models weather (about 10): DANGER is run forward at each airport from its current Build Up Index with NBM's 1 PM temperature, dew point and 10 m wind (times 0.87) and NBM rain in the 24 hours ending 1 PM (non-overlapping accumulations). Today is stepped first, without being forecast.
- Later days: the class distribution that followed the last NOAA-forecast class in the same month, learned from the rebuilt 1997-2014 history.
- Held-out test of that second part (`outputs/fire-danger/latest-test.json`; trained 1997-2014, predictions for 2019-2025 sealed before scoring): day-1 accuracy 0.89 vs 0.89 for "no change"; day 7 0.59 vs 0.58; day 14 0.53 vs 0.47. It detects HIGH-or-worse days poorly a week or more out (it regresses toward typical days). Targets there are rebuilt ratings, not DEEP's.
- The NOAA-driven days cannot be tested historically here (archived NBM forecasts are not downloaded). They are tested going forward.

## Daily sealed test and learning version

The night run (12:05 AM, `daily-forecasts.ps1 -Part night`) archives DEEP's latest report (`scripts/fetch_fire_danger_reports.py`), refreshes the last 45 days of airport weather, rebuilds the history, and seals a 14-day forecast with `scripts/fire_danger_daily.py` in its own append-only ledger (`data/fire-danger-prospective`, `outputs/fire-danger-prospective`). Forecasts are scored only against DEEP-published ratings captured after the forecast was issued, in class numbers (0 LOW ... 4 EXTREME), beside "yesterday's rebuilt class, unchanged". DEEP publishes mainly in fire seasons, so many days stay unscored. If NOAA or the airport data fails, nothing is sealed, so a later run the same day can still issue. The morning run also tries to capture DEEP's rating once it is posted. A learning version (`scripts/learning_daily.py`, model `fire-danger`) corrects the forecast from scored comparisons, like the other models.

## Limits

Statewide only, while DEEP sometimes notes county differences. Airport weather is not forest weather. DEEP rates a morning forecast of 1 PM conditions, while the rebuild uses observed weather. This is not a burn-permit decision: always check DEEP's official rating and local open-burning rules.
