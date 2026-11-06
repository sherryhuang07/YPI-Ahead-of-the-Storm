# Standalone root-zone soil moisture experiment

This module predicts only the average volumetric water content in the top
100 centimetres of soil, one through fourteen days ahead. It does not produce
a drought index, irrigation recommendation, groundwater level, or CMI. It does
not feed the other forecast models or the daily automation.

## Data and spatial meaning

The first trained version uses the public USGS release
[10.5066/P9IKHEM3](https://doi.org/10.5066/P9IKHEM3), a watershed aggregation of
NASA/NOAA NLDAS-2 Noah. Its daily history covers 1980-01-01 through 2020-12-31.
The existing GAGES-II station catalog selects 69 watersheds whose gauge outlets
are in Connecticut. A gauge identifies a watershed here: its streamflow is NOT
an input. Some upstream watershed areas extend beyond Connecticut. These are
watershed-average modeled soil moisture, not gauge measurements, farm readings,
or a complete partition of Connecticut. Overlapping basins are correlated.

Three separate layer-storage files are downloaded and checked against the
publisher's MD5 checksums and file sizes. Local SHA-256 hashes protect the raw
files, extraction, and prediction artifacts. The model sums water storage in
0-10, 10-40 and 40-100 cm and divides by 1000 mm of soil depth. The result is
m3/m3; 0.30 means 30% of the soil volume is water, not 30% of field capacity or
plant-available water. Fixed one-metre depth is a convention, not a crop-specific
rooting depth. Missing/invalid layers result in missing values, never zero-fill.

Two source-documentation issues are retained explicitly:

- The downloaded XML has the advertised size and parses as XML, but differs
  from its advertised checksum. Its actual hash and the failed publisher check
  are recorded. All THREE numeric source files pass their publisher checksums.
- The XML describes a daily boundary as both Central Standard Time and UTC-5,
  which conflict. Original source day labels are retained. Exact alignment to
  Connecticut local calendar days must be resolved before operational use.

Source access and documentation:

- [USGS release description](https://www.usgs.gov/data/daily-average-soil-moisture-and-ancillary-data-noah-land-surface-model-national-land-data)
- [NASA NLDAS access](https://ldas.gsfc.nasa.gov/nldas/nldas-get-data)
- [NASA NLDAS FAQ](https://ldas.gsfc.nasa.gov/faq/all)
- [NASA SMAP Level 4](https://nsidc.org/data/spl4smgp)

## Forecasting and testing

The versioned policy is in `root-zone-policy.json`. Its choices were fixed before
scoring the held-out years. Each watershed and each lead day gets a separate
regularized regression using last-available moisture, trailing 7/28-day means,
a past-week change, and annual/semiannual seasonal terms. A persistence baseline
predicts the last available value unchanged. There is no future observed weather
input and no use of CPC data.

- Fit coefficients and scaling on target dates through 2009 only.
- Select regression versus persistence separately per watershed/lead using
  2010-2014 calibration errors only. Freeze coefficients; do not refit on test data.
- Set nominal 90% error bands from calibration absolute errors. These are
  empirical bands; their held-out coverage is reported, not assumed.
- Issue retrospective predictions on 2015-2020 issue dates for later targets.
  Inputs end six source days before issue. A later test-period observation may
  become a lagged input to a later forecast; it never retunes the frozen model.
- Save predictions, models and policy and seal their hashes before the separate
  scorer reads target values. Originals remain in timestamped run folders.
- Report error and persistence comparison separately for all fourteen horizons,
  by watershed, with missing observations and distinct target-date counts.

This is a **retrospective** evaluation against modeled NLDAS values. The USGS
archive was published after its observation period; historical publication
vintages are unavailable. The six-day delay is a conservative simulation, not
proof of actual availability on each historical date. It is not a prospective
accuracy claim. Thousands of correlated watershed/day cases are not thousands
of independent experiments.

## Running and viewing

Use Farmer View option **14**; refresh the live forecast with `root-zone-update.ps1`. The background activity view includes the new
module. Scripts run from the workspace with `.venv/Scripts/python.exe`:

1. `scripts/fetch_root_zone_history.py` — authorized network download (~2.6 GB).
2. `scripts/prepare_root_zone.py` — verify sources and extract Connecticut series.
3. `scripts/test_root_zone.py` — causal-input and unit-conversion checks.
4. `scripts/train_root_zone.py` — train, select, and seal historical predictions.
5. `scripts/score_root_zone.py` — verify seals and score held-out outcomes.

`outputs/root-zone/latest.json` points to a timestamped run, whose `scoreboard.json`
contains its results. `data/root-zone` holds raw and extracted history. Neither
the training script nor scorer overwrites older runs. Repeating a test does not
make it a fresh independent holdout.

## Live daily inputs and current forecast

The frozen model is connected to current data. Run `root-zone-update.ps1`
(uses the saved, Windows-encrypted NASA sign-in) or its steps separately:

1. `scripts/build_root_zone_basins.py` — boundaries for all 69 watersheds from USGS
   NLDI (cached in `data/hydrography/nldi`, missing ones fetched to
   `data/root-zone/basins/nldi`) and area weights for each NLDAS 1/8-degree cell.
   58 boundaries are within 10% of the GAGES-II drainage area; 11 are flagged for
   review in `data/root-zone/basins/weights.json`.
2. `scripts/assemble_root_zone_inputs.py live` — fetches hourly NASA
   `NLDAS_NOAH0125_H` v2.0 `SoilM_0_100cm` (kg m-2) as small OPeNDAP subsets over
   the watershed box (cached per hour in `data/root-zone/nldas-hourly`), averages
   all 24 hours per day, takes area-weighted watershed means and divides by 1000
   mm. A day with any hour unpublished is incomplete and never filled; a watershed
   with under half its area valid is missing. Output: `data/root-zone/daily-inputs/latest.csv`
   plus `latest.json`.
3. `scripts/forecast_root_zone.py` — hash-checks the sealed `model.json`, uses the
   same timing as the historical test (28-day window ending six days before the
   issue date), and writes `outputs/root-zone/live/<timestamp>/forecast.csv` with
   prediction, nominal 90% band, method, last input and the newest published day
   (context only). `outputs/root-zone/live/latest.json` points to it. Coefficients
   are never refit.

**Daily boundary resolved and inputs checked against the archive.**
`assemble_root_zone_inputs.py check-archive` rebuilt 2020-06-01 to 2020-07-15
from hourly NLDAS v2.0 and compared it with the USGS archive for candidate day
starts. A day of 05:00-04:59 UTC (UTC-5) matched best: mean absolute difference
0.017 soil-water percentage points, bias -0.009, correlation 0.9997, largest
single difference 0.24 points (00 UTC: 0.060; 06 UTC: 0.025). This settles the
metadata's CST/UTC-5 conflict in favour of UTC-5 for this purpose; live inputs use
that boundary. The worst watershed (01191000) has a steady -0.23 point offset from
boundary delineation. These mismatches are far below the model's 1.15-point
one-day error, but they are not included in the historical score or the bands.
Report: `data/root-zone/daily-inputs/archive-check.json`. One summer window was
checked, not every season.

First live run (issued 2026-11-05, inputs 2026-10-03 to 2026-10-30, all days
complete): 69 of 69 watersheds forecast; 14-day median 23.1% soil water
(19.8% to 26.1%). NLDAS is typically published about four days behind, so the
six-day delay leaves margin. This is a research forecast of modeled moisture
with no future weather input; its live accuracy is not yet established.

## What remains for farm forecasts
Create an account at https://urs.earthdata.nasa.gov/; never paste credentials into
chat or commit them. Then open `Connect NASA Earthdata.cmd` locally. It checks
NASA sign-in and saves the password using Windows DPAPI encryption for the current
Windows user under the Git-ignored `data/root-zone/auth` directory. The password
is supplied to the authentication child process only and is cleared from the
launcher environment afterward; no plaintext netrc is written. The authentication
status records no credentials. Successful sign-in alone does not verify dataset
download authorization. The connector dependency is in `earthdata-requirements.txt`.

Download access check on November 5, 2026 (Connecticut local date): the saved
Earthdata sign-in works. A SMAP v008 granule for November 3 was downloaded,
hashed, and successfully opened; its root-zone variable contains usable values
in the Connecticut bounding rectangle. NLDAS download was rejected with
`EulaNotAccepted` on the first attempt. After the user accepted the GES DISC
agreement, the retry succeeded for BOTH datasets. NLDAS's sampled granule is
November 1 at 23:00 UTC; its `SoilM_0_100cm` variable was readable, including
115 valid cells in the Connecticut bounding rectangle. The SMAP sample was
downloaded and verified again. These are access tests, not complete daily
inputs or a new operational forecast. Run `check-earthdata-downloads.ps1` with authorized
network access to repeat actual sample downloads. Reports are kept under
`data/root-zone/download-checks` and the latest status under `data/root-zone/access`.

SMAP root-zone moisture remains a separate planned model comparison; one
successful download is not model validation. It includes modeled information and is not independent ground
truth. Calibrated farm sensors at known depths, soil properties, crop rooting
depth, and irrigation records are needed to assess farm accuracy. A future
gridded/farm-specific version must be revalidated; these watershed coefficients
must not simply be applied to a farm or SMAP pixel. Archived weather forecasts
could improve responses to upcoming rain and evaporation in a subsequent version.

CPC legacy values and temporary copies were deleted at the user's request. The
removal inventory is `audit/cpc-cmi-removal.json`. Its metadata contains no soil
values; the former CPC downloader was also deleted.
