# Public drinking-water reservoir history

## What was collected

The public archive at [Connecticut DPH Reservoir Data](https://portal.ct.gov/dph/drinking-water/dws/reservoir-data) provides statewide charts for 2002–2017 and links a November 12, 2024 detailed report. Additional dated system-level reports were found in DPH and Connecticut drought-workgroup PDFs. The local collection currently contains 11 detailed snapshots dated May 20, 2022; July 29, August 5, August 12, September 2, and September 16, 2022; January 6 and May 5, 2023; and October 25, November 1, and November 12, 2024.

Each detailed report has 34 rows. All 34 PWSIDs match across these 11 snapshots, giving 374 system/report rows. Each row retains the PWSID, name, report date, actual reading date, percent full, status, trend symbol, historical average, percent of normal, previous reading date and value, county served, and source URL. County served is not reservoir location. The history does not identify individual reservoir boundaries or agricultural access.

Original PDFs, extracted text, the normalized CSV, and evaluation detail are local under `data/reservoirs/historical/` (that directory is intentionally ignored by Git). `manifest.json` retains each report URL and SHA-256. The checked-in collection and audit tools are:

- `scripts/reservoirs/collect_public_reports.py` downloads the selected official reports and extracts source text.
- `scripts/reservoirs/build_public_history.py` parses and normalizes system rows, flags report row-count discrepancies, and runs the fixed baseline audit.
- `scripts/reservoirs/requirements.txt` lists the added PDF text-reader dependency.

The DPH landing page calls the information monthly, while report text says systems measure and report weekly. The observation dates in each table are retained as authoritative; no regular interval is imputed.

## Exploratory chronological check

No machine-learning model has been trained. Public snapshots are too sparse and uneven for a reliable seasonal model. I ran two pre-specified, no-fit baselines instead:

1. **Persistence:** carry the last published percent-full reading forward unchanged.
2. **Linear continuation:** extend the change between the current and previous readings to the future target date, bounded to 0–100%.

At each report date, the calculation only used that report's current and previous readings. It was scored against the next report only if the target's actual reading date was 7–21 days after the issue report date and the issue reading was no more than 14 days old. This yielded 47 system/target cases across three report-to-report intervals (August–September 2022 and November 2024). The historical reports are unevenly spaced, so this is a near-two-week diagnostic, not a complete test of an exact 14-day operational forecast.

| Fixed baseline | Mean absolute error | Median absolute error | Mean forecast bias |
|---|---:|---:|---:|
| Persistence | 5.01 percentage points | 4.40 points | +4.25 points (too high) |
| Linear continuation | 5.16 percentage points | 2.60 points | −3.72 points (too low) |

The two baselines have similar errors and opposite average bias. These 47 cases are not independent: many share systems and drought periods, and most come from two short historical windows. The results do not establish that either method is accurate or better for future conditions. No tuning was performed against these outcomes, but a model using weather inputs or fitting parameters still needs a larger, denser history and a separate, later holdout period.

The audit details are in `history-audit.json` and `persistence-holdout.csv`. Statewide 2002–2017 charts are not included as numeric training rows: they are plotted aggregates, not per-system measurements. Digitizing them could provide approximate statewide seasonal context, but not system-level labels.

## What is still needed

- DPH's dated source-level history, ideally the original weekly forms or a table export.
- Stable source-facility and reservoir keys, capacity/elevation definitions, and change notes.
- The fields described in [DPH's surface-water reporting instructions](https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/surfacewatercapacityforminstructionspdf.pdf): water elevation, usable storage, withdrawals, precipitation, plant production, and days of supply. Percent full alone cannot distinguish rainfall/recharge from system withdrawals and management.
- More continuous observations covering multiple wet and dry years. Preserve missing reports and never fill them by assumption.
- A rolling-origin evaluation with a final future period held out until the method is selected; compare simple baselines before fitting a richer model.

This is drinking-water system data. It does not measure agricultural reservoir access, farm wells, or any individual reservoir's storage.
