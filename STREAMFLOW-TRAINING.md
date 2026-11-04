# Streamflow trained on longer histories

The Farmer View now has **option 10**, showing saved forecasts for November 4–17, 2026, issued November 3 using observations through November 2. These are research results, not official USGS forecasts or irrigation advice.

## What was trained

The downloader requested daily mean discharge from January 2000 through November 2, 2026 for the 69 gauges with recent readings in the previous inventory. Shorter station records remain shorter; missing days are never filled with zero. Records with qualifiers, invalid values, or negative flows are excluded from this first training design. Provisional readings without qualifiers are retained. The historical database reflects current revisions, not a reconstruction of information available on every past forecast date.

Each gauge is trained independently. Inputs are its own recent discharge and the day of year. No precipitation, groundwater, nearby-gauge observations, satellite measurements, or future information enters these models. Geography is a separate mapping layer.

The model learns relationships between recent flows and each of the next 14 target days. It uses six recent readings, three recent averages, and seasonal calendar terms. Discharge is transformed with log(1 + flow), and a regularized linear model is fitted. A prediction in this transformed space is a central estimate, **not an unbiased arithmetic expected flow**. Negative predictions are prevented.

- Fit candidate models on 2000–2020 observations.
- Choose regularization, or unchanged-flow persistence, using 2021–2022 errors.
- Estimate daily uncertainty ranges using 2023 errors from a model fitted through 2022.
- Test on 2024–2026, using a fixed model fitted through 2023. Test targets never enter this model's fitting or selection.
- Refit the chosen model on available history for the saved November forecast.

Training labels stop before each subsequent period. Evaluation origins are spaced 14 days apart. As in the current forecast, one unavailable day is skipped before the first target. The model requires at least 730 usable training examples and 12 complete evaluation fortnights in each later period. Missing observations can exclude an entire window, so results describe the usable periods, not every day of the record.

## Results

55 of 69 gauges passed the history and completeness requirements. All 55 selected learned models and beat unchanged-flow persistence in the later-year test. The other 14 have explicit insufficient-history status, not invented forecasts. This comparison is against one simple baseline, not proof of superiority to weather-driven or operational forecasting systems.

For **Mill River near Hamden (USGS-01196620)**, mean absolute error across 59 test fortnights was **23.20 cubic feet per second**, versus **31.44** for unchanged flow. The nominal 90% daily ranges covered **95.5%** of test observations. The forecast central estimate rises from **26.55** on November 4 to **31.15** on November 17. Ranges are wide: November 4 is approximately **2.70–203.99**. These are individual daily ranges, not a 90% guarantee for the entire fortnight. Changing climate, rainfall and reservoir operations can invalidate historical relationships.

## Files and reproducibility

- `data/streamflow/history/`: raw API observations for every requested gauge.
- `outputs/streamflow-trained/results.json`: forecasts, coverage statuses, errors, uncertainty, source hashes and fitted parameters.
- `outputs/streamflow-trained/gauges/`: individual successful model files.
- `outputs/streamflow-trained/summary.json`: counts and methodology.
- `scripts/fetch_river_network.py history`: resumable historical downloader.
- `scripts/train_streamflow_history.py`: training and evaluation.
- `scripts/validate_trained_streamflow.py`: date, range and future-data leakage checks.

The existing short-history experiments under option 1 remain saved separately with their older issue date. Option 10 contains the longer-history streamflow results. Precipitation and groundwater models were not retrained in this task.

Source: [USGS Water Data APIs](https://api.waterdata.usgs.gov/).
