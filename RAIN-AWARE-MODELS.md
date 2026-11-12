# Rain-aware streams and wells (v2)

The original stream (55 Connecticut gauges) and well (8 USGS wells) forecasts use only each site's own past readings, so they cannot see a storm coming. Version 2 adds rain: what has fallen recently over the river's drainage area (or near the well), and NOAA's rain forecast for the days ahead. The v1 models are unchanged and keep running in their own ledgers.

## Rain data

`scripts/build_site_rain.py` builds one daily rain series per site from NOAA GHCN-Daily station rain, 2000 to the present.
- **Stations:** all 1,099 stations within 40.6–42.4 N, 74.2–71.3 W that reported rain in 2000 or later (airports, cooperative observers and CoCoRaHS volunteers). Values that failed NOAA's quality checks are dropped, and missing days stay missing.
- **Stream gauges:** the mean of stations inside the gauge's upstream drainage area. The area comes from the USGS NLDI boundary, widened by about 5 km, and all 55 gauges have one. On days with no station inside, the series uses an inverse-distance mean of the 3 nearest reporting stations within 30 km of the area's centre.
- **Wells:** an inverse-distance mean of the 3 nearest reporting stations within 25 km.
- **Coverage and level:** 99.1% of site-days have a value. The average is 3.6 mm a day (about 52 inches a year).
- **Rain day:** the 24 hours ending about 7 AM, as most stations and PRISM report it. Airports report midnight to midnight, so timing can be off by up to a day.

For live forecasts (`scripts/site_rain.py`), each day takes the first available of:
1. station rain, which NOAA posts 2–4 days late;
2. PRISM for that day: the drainage-area mean, or the cell at a well. PRISM's grid here covers Connecticut only, so it is used only where at least half the drainage area is inside it.
3. NOAA NBM, from the newest cycle issued by 7 AM yesterday, so each forecast day is a full 24 hours of forecast.
4. For past days that stations and PRISM haven't reached yet: the most recent saved NOAA forecast for that day. Each run saves its NOAA values in `data/rain-stations/nbm-archive/` (from November 12, 2026).
5. Normal rain, flagged.

If NOAA's station service is busy, the refresh retries, and a batch that keeps failing uses its saved rain.

## Neighboring-state streams (from November 12, 2026)

The 66 neighbouring-state gauges (MA, VT, NH, NY, RI) get the same treatment from a separate rain set, `build_site_rain.py --set regional` (`site-rain-regional.*`). The Connecticut rain set and its frozen v2 models are untouched.
- **Rain data:** 1,338 stations within about 35 km of the drainage areas, inside 40.4–45.5 N, 76.4–69.6 W. All 66 gauges have NLDI drainage boundaries, every site-day has a value, and the average is 3.5 mm a day.
- **Model:** `train_streamflow_rain.py --set regional`. It uses the same method, splits and adopt rule as Connecticut v2, compared with each gauge's frozen regional-v1 model. This design was fixed before these test years were looked at.

| Test Jan 2024 – Nov 2026, miss per gauge | Perfect rain | Normal rain | v1 | No change |
|---|---|---|---|---|
| Median (cfs) | 49.7 | 64.2 | 66.7 | 82.9 |
| Mean (cfs) | 311.7 | 383.2 | 388.6 | 556.9 |

- **Gauges:** with perfect rain, v2 beats v1 at 65 of 66 gauges. The exception is the Swift River at West Ware, the Quabbin Reservoir outlet, which follows dam releases, not rain. With normal rain, v2 is no worse at 41 of 66.
- **Bands:** the 90% band holds the observed flow 95% (normal rain) and 98% (perfect rain) of the time.
- **Verdict:** it passes the adopt rule.
- **Live forecasts:** these run in the morning after the regional v1 issue, in `data/regional-streamflow-v2-prospective`, with learning version `regional-streamflow-v2`.

## Models

The models are trained by `scripts/train_streamflow_rain.py` and `scripts/train_groundwater_rain.py`.

**Streams.** v1's 11 flow features are kept. Added are rain on the last day and over the last 3, 7 and 30 days, plus rain ahead: from the day after the last reading to the target day, and in the 3 days before the target. Values are entered as log(1 + mm), with one ridge regression per gauge and lead. The splits match v1: fit 2000–2020, choose the penalty on 2021–2022, set the 90% bands on 2023, and test January 2024 – November 2026 every 14 days with a fit through 2023.

**Wells.** Each well predicts the change in depth from the last reading. Level inputs are the last depth, its change over 7 and 30 days, and its departure from the past year's mean. Rain inputs are the last 7, 30 and 90 days, plus rain ahead as for streams. Season is included. There is one ridge regression per well and lead. Fit through 2018, choose on 2019–2021, set bands on 2022, and test January 2023 – November 2026.

**Rain ahead counts only the first 10 days**, NOAA's reach. When NOAA does not cover those days, the model uses "no rain forecast" inputs: the rain-ahead values at their average for that month in the training years.

## Results on the test years

Training used the rain that actually fell. NOAA's old forecasts aren't archived, so the test gives two bounds. **Perfect rain** is what a perfect rain forecast would give; **normal rain** is with no rain forecast at all. Live forecasts fall between them: NOAA for 10 days, typical values beyond.

| Average miss | Perfect rain | Normal rain | v1 | No change |
|---|---|---|---|---|
| Streams, median gauge (cfs) | 21.3 | 26.1 | 25.5 | 38.9 |
| Streams, mean of gauges (cfs) | 154.8 | 189.4 | 191.2 | 252.2 |
| Wells, mean of 8 (ft) | 0.45 | 0.56 | 0.62 | 0.62 |

- **Streams:** v2 beats v1 with perfect rain at all 55 gauges. With normal rain it is no worse at 39 of 55. The 90% band holds the observed flow 97% of the time (normal rain) and 99% (perfect rain); bands are set on normal-rain errors, the wider case.
- **Wells:** v2 beats v1 with perfect rain at all 8 wells, and with normal rain is no worse at 7 of 8. Band coverage is lower than intended: 82% with normal rain and 86% with perfect rain, against 90%.

**Rule fixed before testing:** v2 replaces v1 in the app only if (1) with normal rain it is no worse than v1 at a majority of sites, and (2) with perfect rain its overall error is lower. Both models pass, so the app's stream and well pages show v2 whenever today's v2 forecast is sealed, and v1 otherwise.

**Revision after first seeing the test years (November 11, 2026).** The first run counted rain ahead out to day 14 and represented "normal rain" as the month's average spread over every day. That treated "no forecast" as a steady daily soaking, and stream errors with normal rain came out worse than v1: median 31.6 vs 25.5 cfs, no worse at only 1 of 55 gauges. Both problems were corrected, giving the results above. That first run is kept in `outputs/*-v2/runs/`. Because the test years were seen once before this revision, the sealed daily record is the real test.

## Daily sealed forecasts

- **Wells (night run):** `build_site_rain.py --recent` refreshes the last 60 days of station rain, then `rain_models_daily.py --kind groundwater` runs.
- **Streams (morning run, after v1):** `rain_models_daily.py --kind streamflow`.
- **Ledgers:** each version has its own (`data/<kind>-v2-prospective`, `outputs/<kind>-v2-prospective`), with the same sealing and scoring rules as every other ledger. Observations come from the v1 ledger with their original capture times.
- **What each forecast records:** the rain source behind each day's rain-ahead inputs, plus 90% bands.
- **Learning versions:** `streamflow-v2` and `groundwater-v2` correct them from scored comparisons.
- **App:** the accuracy page shows each version beside v1.

## Limits

Rain station networks change over time, CoCoRaHS grew after 2008, and reporting times differ. The test can't measure NOAA's own forecast error, which the live ledger will. Dams, reservoir releases and withdrawals are still not included.
