# NEWA weather stations (Cornell): nightly 5-day weather for the drought forecast

[NEWA](https://newa.cornell.edu/) (Network for Environment and Weather Applications: Cornell IPM, the Northeast Regional Climate Center and UConn Extension) shows each weather station's measured weather and a forecast for the next days. There is no statewide download, so a scheduled Claude session opens the site in the built-in browser each night and picks every active Connecticut station, the way a person would.

## What a station page carries
- **Measured, hourly since January 1:** rain, temperature, humidity, dew point, leaf wetness, wind and sunshine. Daily totals of rain and high/low temperature are also included.
- **Forecast (National Weather Service), hourly for about 6 days:** temperature, humidity, wind, sky cover, the 12-hour chance of rain, and the rain amount. The rain amount is given for about the first 3 days only, then shows "M" for missing.
- **Daily forecast:** high, low and a weather word (clear, rain-mix, rain, mixed).

There are 36 Connecticut stations listed, **22 active**: 3 airports (Danbury, Bridgeport, Bradley) and 19 farm and orchard stations (`scripts/newa_stations.json`).

## Nightly routine (scheduled task "newa-nightly-station-visits", 11:34 PM)
1. Open newa.cornell.edu in the built-in browser and set the page size (it can't be clicked while the pane is hidden).
2. Run `scripts/newa_capture.js`. This recorder makes no requests of its own; it only summarises the data the page loads when a station is picked.
3. Pick each of the 22 stations in the station box, then re-pick any that didn't load. The page doesn't reload a station that is already showing.
4. Export a compact summary to `data/newa/<date>T<time>.json`. It holds each station's last 7 days of measured rain and temperature, plus 6 forecast days: high, low, chance of rain, rain amount when complete (20+ of 24 hours) and weather word.
5. `scripts/newa_weather.py` turns the capture into 5-day weather for each planning region and statewide (`outputs/newa/latest-regions.json`). Stations are placed by the TIGERweb region boundaries; a region with no active station takes the 2 nearest.

**Gut-checks.** A station whose daily high equals its low on 3 or more days has a stuck thermometer, so its temperatures are left out; on November 19, 2026, Shelton (Jones Family Farm) read 75.2°F all week. A rain gauge that read 0 in for the week while the typical station caught at least 0.2 in is left out of measured rain. On November 19, 9 of 22 gauges did this after the November 12–13 rain, possibly because they are winterised.

## How the drought forecast uses it
`drought_daily.py` (v1 and v2) uses NEWA's regional rain amount for each day it is complete, usually the first 3 days, and NOAA NBM for later days, then normal rain beyond NOAA's reach. Each sealed forecast records how many days came from each source (`rain_ahead_source`) and the NEWA file with its fingerprint. A capture older than 30 hours, or a failed visit, falls back to NOAA NBM automatically. The daily report has a "NEWA weather stations: next 5 days" section.

NEWA's forecast comes from the National Weather Service, the same family as NOAA's NBM, so it is not an independent forecast. The drought model also has no temperature input, so NEWA's temperatures are shown but not used. NEWA's fast measured rain (hourly from 22 stations, against 2–4 days' delay for the NOAA station records) is the most promising next use for the stream and well models.

## Challenges
- **The routine needs the Claude desktop app open and the computer awake at 11:34 PM.** The Windows forecast runs work without the app, but this one doesn't. A missed night just means NOAA rain only for that day's drought forecast.
- **It can break if NEWA changes its page layout.** A station box that can't be found, or fewer than 12 stations captured, produces a `-failed.txt` note instead of data.
- **NEWA publishes no terms of use, and asks that data-access questions go to its help desk** (newa@cornell-ipm.org). The routine loads each station page once a night, like a visitor. Reading NEWA's data service directly was blocked by this session's permission check, so the routine works through the pages only.
- **Station quality is the owners' responsibility**, which is why the gut-checks above exist.
