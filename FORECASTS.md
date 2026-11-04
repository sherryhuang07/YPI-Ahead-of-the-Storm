# Three isolated 14-day forecast experiments

Choose **1** in Farmer View. These are research baselines, not validated operational forecasts. Only precipitation, groundwater level and streamflow are predicted. There are no crop, drought, excess-moisture, irrigation or strategy predictions.

The saved experiment is dated **November 2, 2026**, with source observations ending **November 1** and target date labels **November 3–16**. A one-day observation gap is accounted for: water models forecast 15 steps from the last reading, skip November 2, and retain the following 14. PRISM's dates denote periods ending at 12 UTC, not local-midnight days; USGS daily records follow station reporting days. Thus the variables are not aligned to identical wall-clock intervals, and the first PRISM target period begins November 2 at 12 UTC. This is a dated experiment, not a live forecast feed.

## What is and is not available

| Variable | Output | Unsupported scope |
|---|---|---|
| Precipitation | Expected daily amounts and 14-day total for all 11,759 mapped farm candidates, plus Yale pilot | Storm timing, a calibrated rainfall probability/range, confirmed field-scale accuracy |
| Groundwater | Daily projections at 8 monitored wells with enough usable daily data | Groundwater beneath every farm: all candidate farm-level values remain null because aquifer connections and farm wells are unconfirmed |
| Streamflow | Daily discharge projections at 65 supported Connecticut stream gauges | Every water body: ungauged reaches, lakes, ponds, reservoir inflows/outflows, and cross-border rivers are not modeled |

Groundwater coverage records exist for every mapped farm candidate, but they explicitly say **unavailable**, rather than substituting a nearby well's level. Eight well projections are monitoring context only. Similarly, a gauge is a measurement point, not a forecast for every reach of a named river. A lake does not have a single unambiguous streamflow value without defining an inlet or outlet. A complete statewide waterbody inventory and river routing have not been added.

## Input isolation

- **Precipitation:** only the saved PRISM precipitation grids enter the predictive calculation. Farm geometries and saved cell-area overlaps attach the grid predictions to candidate footprints.
- **Groundwater:** each model uses only that well's own unqualified daily mean depths below land surface. No PRISM, streamflow, soil, or neighboring-well values enter the model. Monthly manual readings are too sparse for the declared daily model and are not interpolated.
- **Streamflow:** each model uses only that gauge's own unqualified daily mean discharge. No rainfall, groundwater, weather-model output, neighboring gauges, or historical percentile tables enter its predictive calculation.

Metadata and geographic links organize outputs, not predictive features. Input files and hashes are recorded in each variable's summary. The independent scripts can be run separately. Their outputs are combined only for display.

## Methods

Precipitation uses the mean daily amount over a candidate trailing window of 14, 28, or 42 days. A single window is selected using statewide grid-cell errors over two earlier test periods. The selected window is **42 days**. Each cell's expected daily amount is repeated for 14 dates, so this does **not** claim that rain will fall evenly or identify a storm's arrival. Farm values use the existing area weights. This is not a seasonal climatology: only 90 days of history are available.

Groundwater and streamflow each compare three univariate methods independently at every monitoring location:

1. Hold the last observation (persistence).
2. Fit a recent 14-day trend and reduce its future influence by a fixed factor of 0.8 each step.
3. Fit a one-step autoregression to at most 42 recent days, with its coefficient constrained to 0–0.98, then project forward.

Streamflow uses a log(1 + discharge) transformation and nonnegative output. Reverse-flow series are not handled by this model. Groundwater remains in feet below local land surface, so values above land surface can be negative and increasing depth means a falling level. No direct comparisons of absolute groundwater depth between wells are implied.

At least 70 usable daily observations out of 90, a cutoff-date observation, adequate tuning data, and at least 12 held-out target observations are required. Qualified values are excluded rather than silently treated as clean. Southbury's well fails the declared tuning-data requirements; four recent stream gauges fail usable-history or test requirements. Exclusion reasons remain in the output, rather than replacing failed predictions with zeros.

## Evaluation and actual results

Models are chosen using two 14-day forecast windows after training cutoffs September 14 and September 28, each including the same one-day gap as the issued experiment. A final, untouched target period **October 19–November 1** tests the chosen method using only observations through **October 17**. This held-out result is not used to reselect the model. The final selected model is then fit using all available observations through November 1.

This is one held-out fortnight, not evidence of year-round performance. All data are downloaded snapshots and may include later revisions, so the test is retrospective rather than a reconstruction of exactly what was available on past issue dates. Spatially correlated grid cells do not create thousands of independent weather tests.

**The precipitation baseline failed its benchmark.** Mean absolute error in the held-out 14-day total was **67.81 mm (2.67 inches)** across Connecticut-centered grid cells, versus **62.02 mm (2.44 inches)** from repeating the preceding fortnight. The model did not anticipate the dry spell. Yale Farm's experimental expected amount for November 3–16 is about **1.84 inches**, but it is not a reliable weather forecast and is shown with its test error.

Four of eight well models and 56 of 65 streamflow models beat the hold-last-reading baseline in this single held-out fortnight. This does not establish calibrated skill, especially during storms, reservoir operations, pumping changes or other seasons. Results, absolute errors, benchmark errors and methods are retained for each monitoring location. The code does not switch to whichever model looks best on the final test.

No calibrated prediction intervals are published. A test error is not a confidence interval, and the limited record cannot justify assigning a 90% or 95% uncertainty range. Operational use would require longer, seasonally representative evaluation, forecast uncertainty calibration, and—in particular for precipitation—information about future weather. Those inputs were not added because this request keeps the three datasets isolated.

## Files and rerunning

`outputs/forecasts/precipitation/` contains grid and farm predictions, a town lookup and evaluation results. `outputs/forecasts/groundwater/` contains well forecasts and explicit farm coverage gaps. `outputs/forecasts/streamflow/` contains supported gauge projections and exclusions.

Run these with `.venv\Scripts\python.exe`:

```
scripts/forecast_precipitation.py
scripts/forecast_water.py groundwater
scripts/forecast_water.py streamflow
scripts/validate_forecasts.py
```

Validation checks source hashes and allowed variable declarations, all farm IDs, dates and units, zero versus missing values, finite outputs, and null unsupported farm groundwater. A synthetic test changes only held-out outcomes and confirms that neither model selection nor held-out predictions change, protecting against future-data leakage.

The available datasets are described in `PRECIPITATION.md`, `GROUNDWATER.md` and `STREAMFLOW.md`. These experiments are independently implemented baselines, not official PRISM or USGS forecasts.
