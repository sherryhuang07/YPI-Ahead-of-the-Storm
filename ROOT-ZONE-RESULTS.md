# First root-zone soil moisture historical test

Separate model only. No connection to overall drought scoring.

Data: USGS aggregation of NLDAS-2 Noah, 1980-2020, 69 watersheds with
Connecticut outlets. All 14,976 daily records per watershed have valid combined
0-100 cm moisture. Numeric source files match publisher checksums. Metadata
checksum and daily-time-boundary issues are documented in ROOT-ZONE-SOIL-MOISTURE.md.

Training ends in 2009; model selection and interval calibration use 2010-2014.
The held-out period is 2015-2020. Predictions were sealed before the separate
scorer ran. Inputs stop six source days before each simulated issue date.

| Lead | Mean absolute error, soil-water percentage points | Unchanged-moisture baseline | Relative error reduction | Distinct completed target dates | Missing targets |
|---|---:|---:|---:|---:|---:|
| 1 day | 1.154 | 1.184 | 2.5% | 2,191 | 0 |
| 7 days | 1.435 | 1.580 | 9.1% | 2,185 | 0 |
| 14 days | 1.637 | 1.890 | 13.4% | 2,178 | 0 |

The 14-day comparison contains 150,282 watershed/target cases. These are not
independent trials. Results pool watersheds equally per case; they are not
weighted by farm area. Nominal 90% bands contained 92.7% of the 14-day held-out
NLDAS values. At 14 days, mean signed error was +0.376 percentage points
(overprediction of moisture). Individual watershed scores are also retained.

Errors compare to **modeled soil moisture**, not independent field observations.
This later-release archive cannot reproduce historical data vintages; the
availability delay is simulated. Exact Connecticut local-day alignment remains
unverified. The improvement is descriptive, not a statistical significance claim.

Five software tests passed, including invariance to changing future/unavailable
inputs, no missing-value filling, and depth conversion. Source and sealed
prediction hashes passed verification during scoring.

Live inputs are now connected: recent NASA NLDAS-2 days are rebuilt per
watershed (UTC-5 day, 0.017-point mean difference from this archive in a 2020
check) and fed to the frozen model; see ROOT-ZONE-SOIL-MOISTURE.md. Live accuracy,
the SMAP comparison, and farm sensor validation remain pending.
See Farmer View option 14 and ROOT-ZONE-SOIL-MOISTURE.md for next requirements.
