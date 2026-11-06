# Daily forecasts tested against future observations

Each day, the process collects already-published historical observations, saves a new 14-day forecast for each supported location, and compares **previously saved** forecasts with observations that have since arrived. Only target periods that have not started may be forecast. Older retrospective experiments do not count toward this prospective test.

The intended schedule is **6:00 AM Connecticut time every day**. The local computer and desktop app must remain running with this project accessible. An interrupted or missed run is recorded as a gap; it must never be recreated with an earlier issue date.

The app automation is active: **Connecticut daily water forecasts and verification**, ID `connecticut-daily-water-forecasts-and-verification`. It returns to this chat. If a run is interrupted by usage limits, continue by following the operation instructions below; preserve the existing ledger and issue only genuinely future forecasts.

## No looking ahead

- Issue timestamps use UTC; water observation dates and daily scheduling use America/New_York, including daylight saving.
- Every forecast is saved in a new file. Its timestamp, input snapshot, model version and checksum are recorded in an append-only database.
- Target periods must start after the actual issue timestamp. PRISM daily precipitation covers the 24 hours ending at noon UTC, so its date labels can differ from the groundwater/streamflow forecast dates.
- Incoming observations can score an existing forecast, but cannot change its prediction. Those past readings may inform a later forecast for dates still in the future.
- Scores use the **first captured clean observation**. USGS provisional status and later revisions remain in dated raw snapshots. Later revisions do not replace first-observation scores. PRISM daily crops are retained as first captured; they are not silently replaced with revised grids.
- Missing or qualified observations remain unscored. Missing inputs can withhold a forecast; they are never treated as zero.
- Frozen streamflow weights and methods remain unchanged. Groundwater coefficients update from its own past readings. The original precipitation baseline remains in its own ledger; a separate daily NOAA NBM farm forecast is written to `outputs/forecasts/precipitation/noaa-live/issued/` with the NOAA cycle, raw GRIB hashes, farm values and a latest pointer. Complete first-day amounts use NBM QPF. Days 2–11 combine NBM hourly precipitation probabilities with PRISM wet-day history. Days 12–14 blend that estimate with the trailing 42-day PRISM mean; the extension is experimental and uncalibrated.
- The database rejects edits/deletions to forecasts, observations, scores and exclusion records. Forecast hashes and the frozen model registry are checked on every run. Code versions are retained by checksum.

## Current coverage

The successful initial run contains **55 stream gauges**, **8 groundwater monitoring wells**, and **11,760 precipitation locations** (11,759 candidate fields plus the Yale Farm pilot). Groundwater forecasts describe monitored wells; groundwater beneath individual farms is still unavailable. Ungauged streams and lakes remain unforecast. Rainfall is still an experimental history-only baseline with no storm timing information.

The first valid run was issued on the evening of **November 3, 2026 Connecticut time** (November 4 UTC). Streamflow and groundwater target **November 4–17**. Precipitation targets PRISM reporting dates **November 5–18**, whose first period starts November 4 at noon UTC. That avoids forecasting part of an already-started precipitation day.

Three earlier setup records are preserved and excluded with an explicit audit reason: their collection cutoff used the UTC calendar date before the Connecticut day ended. This was corrected **before any target period started**, with zero scored outcomes. Their original files remain unchanged. Future operational exclusions must never be used to remove bad-performing forecasts; missed forecasts and invalid records must remain visible in the audit.

## Scorecard

Farmer View option **11** shows the last completed check, forecast coverage and observed errors. `outputs/prospective/scoreboard.json` reports daily absolute error by variable and forecast day, plus a simple baseline comparison. Precipitation's complete 14-day totals are also scored once all 14 daily observations exist. Units remain separate: rainfall in millimeters, groundwater in feet below land surface, streamflow in cubic feet per second.

Reporting-day publication delays mean comparisons arrive after the target date. The water scorer uses an additional conservative completion delay. Zero completed comparisons initially is expected; it is not a zero-error claim. Thousands of nearby fields can share grid cells, and rolling forecast windows overlap; these are not thousands of independent experiments.

## Root-zone soil moisture ledger

The standalone root-zone model has its own sealed daily test, separate from the three variables above: `scripts/root_zone_daily.py`, ledger `data/root-zone-prospective/ledger.sqlite`, sealed issues in `outputs/root-zone-prospective/issued/`, scorecard `outputs/root-zone-prospective/scoreboard.json`. It reuses this file's append-only rules (hash checks, no backdating, one issue per Connecticut day, scoring only with observations captured after issuance).

- Each day, NASA NLDAS-2 inputs are assembled first (`root-zone-update.ps1 -Step daily`). The frozen model (registered once in `data/root-zone-prospective/model-v1.json`; any change stops the run) forecasts days 1-14 starting tomorrow from a 28-day input window ending six days before issue, for 69 watersheds.
- Targets are the first captured NLDAS watershed values for each day (published about four days late). Scores include the unchanged-moisture baseline and the share of observations inside the sealed nominal 90% band.
- First issue: Connecticut day **2026-11-05**, 69 of 69 watersheds, targets November 6-19.

## Daily runner for every model

`Run Daily Forecasts.cmd` (script `daily-forecasts.ps1`) runs all four ledgers independently: `prospective_daily.py`, `regional_daily.py`, then the root-zone daily step. One failing job does not stop the others; a summary goes to `outputs/daily-run-summary.json` and `activity.log`. Reservoir capacity has no daily public feed and therefore no daily forecast.

**Scheduled on this PC:** Windows Task Scheduler task **"Ahead of the Storm - Daily Forecasts"** runs `daily-forecasts.ps1 -Scheduled` at **6:30 AM** every day (hidden window, current Windows user, only while signed in so the encrypted NASA sign-in can be unlocked). A run missed while the PC was off or asleep starts when it is next available. Each scheduled run's output is saved in `outputs/daily-run-logs/`.

**Allowed hours: 5:00 AM to 10:00 PM Connecticut time.** Each variable gets one sealed issue per Connecticut day. Streamflow needs yesterday's clean USGS reading; a run just after midnight, before USGS publishes it, would seal an issue with streamflow withheld for the whole day, and a run after 10 PM could cross midnight partway through. Outside those hours the runner logs a skip (`-Force` overrides). If the earlier ChatGPT/Codex 6:00 AM automation is still active, the 6:30 run only refreshes observations and scores; same-day issues are never duplicated.

To pause or remove the schedule: open Task Scheduler and disable or delete that task, or run `Unregister-ScheduledTask -TaskName 'Ahead of the Storm - Daily Forecasts'` in PowerShell.

## Operation and recovery

Network recovery on November 5, 2026: restricted execution produced DNS failures for USGS, PRISM and NOAA although workstation DNS worked. Run the two daily Python commands with their authorized network permissions (`sandbox_permissions=require_escalated`). If permission is unavailable, report that explicitly. A connection failure does not establish that daily data were unpublished. Successful same-day retries refresh inputs and scores but retain the day's sealed records, including empty streamflow coverage. New scheduled issues use the recovered inputs under the existing model policy.

Also run `.venv/Scripts/python.exe scripts/regional_daily.py` for connected neighboring-state stream gauges. Inspect `outputs/regional-prospective/last-run.json` and `scoreboard.json` and verify its separate sealed ledger. This adds 66 eligible gauge forecasts from 90 mapped connected gauges without changing the original Connecticut model. The remaining 24 lack an eligible trained forecast. See REGIONAL-STREAMFLOW.md and Farmer View option 12. Report failures in either job independently.

Run `.venv/Scripts/python.exe scripts/prospective_daily.py` from this workspace. It also retrieves the current NOAA NBM QPF grid and writes a separate mapped farm forecast. Inspect `outputs/prospective/last-run.json` and `outputs/forecasts/precipitation/noaa-live/latest.json`; any source errors produce a nonzero exit and must be reported. Repeating a run on the same Connecticut date can refresh observations and scores but does not replace that day's sealed predictions. See NOAA-PRECIPITATION.md for the 11-day NBM horizon and labeled three-day extension.

`data/prospective/ledger.sqlite` is the audit index; `outputs/prospective/issued/` holds original predictions; `data/prospective/snapshots/` holds inputs and raw USGS responses; `data/prospective/model-v1.json` freezes the model policy; `data/prospective/code/` retains code versions. Never delete these to force a rerun or reconstruct missed predictions. A partial file/database write requires explicit recovery that preserves the original issue timestamp and contents.

`scripts/test_prospective_daily.py` checks future-period boundaries, overwrite protection, delayed scoring, repeat-run behavior, and tamper detection. The schedule should keep updating the files quietly during routine runs and report failures, first completed comparisons, coverage losses or sustained material deterioration.

Local scheduling requirements: [official OpenAI documentation](https://learn.chatgpt.com/docs/automations?surface=app).
