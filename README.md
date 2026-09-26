# ctwater — Connecticut water-risk early warning

A 30-day early warning system for **both** water hazards on a pinpointed Connecticut farm:
**too little** and **too much**.

**Input:** latitude, longitude, date → **Output:** for ~30 days ahead —

| | |
|---|---|
| **Too dry** | drought stage (0–5) and irrigation need in mm/week |
| **Too wet** | probability of a flooding or waterlogging event |

## Why both halves

The project began as a drought forecaster. Two findings changed that.

**Connecticut's recent losses were mostly from too much water.** The state Department of
Agriculture surveyed 2023–24 farm losses at **over $50 million**, and the majority came from
excess moisture and flooding — historic flooding in the Connecticut River Valley in 2023, western
Connecticut in 2024. Drought appears as one of several more localised events. A drought-only
system answers half the question, and lately the smaller half.

**The wet half turned out to be the more predictable one.** Excess moisture reaches AUC 0.84
against a baseline that does not exist — nothing forecasts floods for free — while drought
staging fights a persistence baseline it can only draw with. That is physically sensible: floods
follow identifiable setups, whereas drought deepening depends on rain that simply fails to arrive.

The same rainfall, soil, streamflow and crop data drives both. Nothing extra was downloaded to add
the second hazard.

## The asymmetry that governs everything

| | Too dry | Too wet |
|---|---|---|
| Official label | ✅ U.S. Drought Monitor, weekly, expert-drawn | ❌ **none exists** |
| Target | observed | **defined here** — see `features/wet.py` |
| Free baseline to beat | persistence, and it is strong | none |
| Validation | against the label | against events that really happened |

**Read that second column carefully.** For dryness the model learns to predict an authority's
judgment. For wetness there is no authority, so the target is a rule written in this repo and
applied to real measurements. It is validated against the 2023 and 2024 floods rather than against
a label, and that is the best available — not the same thing as ground truth.


---

## Quick start

Everything runs through `uv`, which manages both Python and the packages for you.

```bash
uv run ctwater demo
```

That one command generates placeholder data, builds features, trains both models,
and prints a sample forecast. It proves the whole machine turns before you have spent
a day hunting for datasets.

The individual steps, if you want to run them one at a time:

```bash
uv run ctwater info
```

```bash
uv run ctwater make-synthetic
```

```bash
uv run ctwater find-farms --target 200
```

```bash
uv run ctwater fetch-usdm --start 2016-01-01 --end 2024-12-31
```

```bash
uv run ctwater fetch-noaa
```

```bash
uv run ctwater fetch-usgs
```

```bash
uv run ctwater fetch-cropland
```

```bash
uv run ctwater fetch-soils
```

```bash
uv run ctwater build
```

```bash
uv run ctwater train
```

```bash
uv run ctwater predict --lat 41.7658 --lon -72.6734 --date 2021-07-15
```

```bash
uv run pytest -v
```

---

## What each folder is for

```
ct-drought-forecast/
├── config/config.yaml      ← every tunable number lives here, not in the code
├── data/
│   ├── raw/                ← downloads exactly as they arrived. NEVER edit by hand.
│   ├── interim/            ← half-cleaned intermediates
│   ├── processed/          ← the final model-ready table
│   └── external/           ← reference layers: county shapes, soils, elevation
├── models/                 ← saved trained models (.joblib)
├── notebooks/              ← exploration and plots
├── reports/figures/        ← charts you want to keep
├── scripts/                ← one-off download / conversion scripts
├── src/ctwater/          ← the actual package
│   ├── config.py           ← loads config.yaml
│   ├── splits.py           ← train/test splitting (read this one twice)
│   ├── data/
│   │   ├── grid.py         ← lat/lon → stable grid cell
│   │   ├── usdm.py         ← real Drought Monitor download + point lookup
│   │   ├── survey.py       ← CT Farm Bureau calibration (+ how to get the data)
│   │   ├── sources.py      ← weather dataset registry  ← YOU FILL THIS IN NEXT
│   │   └── synthetic.py    ← fake weather so the pipeline runs today
│   ├── features/
│   │   ├── build.py        ← rolling windows, anomalies, seasonality
│   │   ├── dry.py          ← TOO DRY: stress index → irrigation mm/week
│   │   ├── wet.py          ← TOO WET: flood/waterlogging risk
│   │   ├── waterbalance.py ← evaporation and soil moisture from real weather
│   │   └── targets.py      ← shifts labels 30 days into the future
│   └── modeling/
│       ├── train.py        ← three models: stage, irrigation, wet risk
│       ├── evaluate.py     ← metrics that are not lies
│       └── predict.py      ← lat/lon/date → forecast
└── tests/                  ← guards against the classic silent failures
```

**The `data/raw` rule:** treat raw files as read-only. Every transformation happens in
code, so you can always trace any number back to its source and re-run from scratch.

---

## The three ideas that decide whether this project works

Most of the difficulty in drought forecasting is not the model. It is these three things,
and the code has been written to keep you on the right side of all of them.

### 1. Time leakage — why you cannot shuffle your data

Normal machine learning shuffles rows and holds out a random 20%. Do that here and your
scores become fiction. Randomly held-out days sit *between* training days, so the model
learns "there was a drought on Aug 3" and is then asked about Aug 4. It looks brilliant
in testing and fails completely in the field, where the future has genuinely not happened.

`splits.py` uses **expanding-window (walk-forward)** validation instead: train on the past,
validate on what came next, repeat as the window grows. That mirrors exactly what a
deployed model faces every week.

### 2. The embargo gap — the leak almost everyone misses

Your features on July 1 predict the label on July 31. If validation begins July 15, then a
training row from July 1 already contains an answer that lives inside your validation
window. The fix is an **embargo**: discard a gap of at least `horizon_days` between the end
of training and the start of validation. `config.yaml` sets `embargo_days: 30`, and
`train()` refuses to run if it is smaller than the forecast horizon.

### 3. Persistence — the baseline you must beat

Drought moves slowly. "Next month will look like this month" is a genuinely strong forecast.
Every fold reports `skill_vs_persistence`, and **any accuracy number without that comparison
is close to meaningless.** If your model cannot beat persistence, it is not yet adding value —
and knowing that early is worth more than a high-looking score.

---

## What the model actually sees

A model cannot forecast from a lat/lon and a date — those numbers say nothing about whether
it has rained. So `features/build.py` turns raw daily observations into a row that answers:

| Feature family | Example columns | Why it matters |
|---|---|---|
| Accumulations | `precip_mm_sum30d`, `precip_mm_sum90d` | Drought is about deficits over time, not any single day |
| **Anomalies** | `precip_mm_sum90d_z` | 40 mm of rain is normal in January, alarming in July. Z-scores against a local, week-of-year normal capture that — this is the core of drought science (the idea behind SPI/SPEI) |
| Trend | `soil_moist_frac_delta30d` | Two farms at the same moisture are in very different situations if one is drying and the other just got rain |
| Seasonality | `doy_sin`, `doy_cos`, `is_growing_season` | Sin/cos wrap the year into a circle so Dec 31 and Jan 1 sit next to each other |
| Site traits | `awc_mm`, `elevation_m`, `slope_deg` | **This is how you beat a county-level forecast.** Two farms in one county on different soils experience the same rainfall very differently |
| Current state | `y_stage_now` | Today's condition, which is also the persistence baseline |

The climatology used for anomalies is fit **only on the training period** — computing normals
over the full record would quietly leak the future into every training row.

---

## Two outputs, two models

| Output | Problem type | Model | Headline metric |
|---|---|---|---|
| Drought stage 0–5 | Ordinal classification | LightGBM classifier | **macro-F1** and **recall on stage 3+** |
| Irrigation need, mm/week | Regression | LightGBM regressor | **MAE in mm/week** |

`mae_reg` reads directly as "we're typically off by N mm per week," which you can
sanity-check against reality: a CT vegetable crop needs roughly 25 mm/week at peak, so an
MAE of 3 mm is useful guidance and an MAE of 15 mm is not. Both models also report skill
against persistence (`skill_vs_persistence`, `reg_skill_vs_persistence`).

**Why not accuracy?** If Connecticut is drought-free 80% of weeks, a model that always says
"no drought" scores 80% accuracy and never warns anyone. Macro-F1 weights every stage
equally, so being useless at rare severe droughts drags the score down where you can see it.

**Why recall on stage 3+ specifically?** For a warning system the costs are asymmetric.
A missed drought can cost a farmer a crop; a false alarm costs one unnecessary irrigation run.
Optimize for the error that actually hurts.

**Why gradient-boosted trees and not deep learning?** For a few hundred engineered columns and
tens of thousands of rows, LightGBM beats neural networks almost every time, trains in seconds
on your laptop, handles missing values natively, and tells you which features mattered. Earn
the complexity of a neural network later, if the data volume ever justifies it.

---

## The labels: U.S. Drought Monitor

`ctwater fetch-usdm` downloads the real weekly USDM maps and works out which drought class
each of your grid cells was in.

```bash
uv run ctwater find-farms --target 200
```

```bash
uv run ctwater fetch-usdm --start 2016-01-01 --end 2024-12-31
```

Downloads are cached in `data/raw/usdm/`, so re-running costs nothing. Details verified
against the actual files rather than assumed:

- One map per week, **valid Tuesdays**, published Thursday. Asking for any other weekday 404s.
- Available from 2000-01-04 to present (~1,300 maps).
- The one column that matters is `DM`, valued 0–4 for D0–D4. We map it to **stage = DM + 1**,
  with **stage 0** for a point inside no polygon.
- The `_M` ("modified") files we use are **disjoint** — each point falls in exactly one class.
  The *unmodified* files are **nested** (the D0 polygon also covers every worse area), and
  code written for one shape gives wrong answers on the other. Our lookup takes the maximum
  class, so it is correct either way.

**Know what USDM is.** It is not a measurement — it is a weekly expert judgment by a human
author blending rainfall, soil moisture, streamflow, and local reports. That is a strength
(it captures impacts no satellite sees) but it also means boundaries sometimes follow county
lines, and it can lag a fast-developing "flash drought" by a week or two. Since your goal is
a *quicker* warning system, that lag is precisely the weakness you're trying to beat — so
it's worth measuring directly whether your model's stage changes tend to *lead* USDM's.

---

## Streamflow: the landscape's memory

`ctwater fetch-usgs` pulls daily discharge from USGS stream gauges.

Rainfall tells you what fell. Streamflow tells you what the landscape did with it, and it carries a
much longer memory — after a wet autumn the ground is charged and a dry June hurts far less. It's
also the channel human Drought Monitor authors watch closely.

### Basin size is the entire design problem

**A gauge doesn't measure the river at that spot — it measures everything upstream.**

| Gauge | Drains |
|---|---:|
| Connecticut River at Thompsonville | 9,660 sq mi |
| Housatonic River at Stevenson | 1,544 sq mi |
| Bunnell Brook near Burlington | 4.1 sq mi |

The Connecticut River gauge mostly reports snowmelt in Vermont and New Hampshire. Its flow can run
high while Connecticut farms are parched — a real number, a nearby gauge, and a completely
misleading signal. So gauges are filtered to **≤ 100 sq mi**, keeping 50 of Connecticut's 71 active
ones. Gauges with no reported basin size are *dropped, not assumed small*.

Each cell blends its 3 nearest qualifying gauges within 40 km, inverse-distance weighted.

### Rivers amplify the drought signal

| August 2022 (D2 drought) vs a normal year | |
|---|---|
| Rainfall | 55% of normal |
| **Streamflow** | **15% of normal** |

Soil absorbs the first rain; only the excess reaches the stream. So a moderate rainfall deficit
becomes a dramatic flow deficit — which is exactly why this feature is worth having.

---

## Crop identity: Connecticut does not grow vegetables

`ctwater fetch-cropland` downloads USDA's **Cropland Data Layer** — a 30 m classification of
every pixel in the country, rebuilt each year from Landsat and Sentinel imagery — and works out
what grows in each 1 km cell.

This matters more than it sounds. The model originally assumed mixed vegetables everywhere. The
crop map says that is wrong for ~95% of Connecticut farmland:

| Crop | Acres (2022) | Threshold `p` |
|---|---:|---:|
| Other hay / non-alfalfa | 78,900 | 0.60 |
| Grassland / pasture | 67,700 | 0.60 |
| Corn | 39,300 | 0.55 |
| Alfalfa | 7,700 | 0.55 |
| Tobacco | 3,400 | 0.35 |
| Sweet corn | 2,000 | 0.50 |
| Apples & orchard | 1,500 | 0.50 |
| Vegetables | ~600 | 0.35 |

`p` is how far the soil may dry before the plant actually minds. Hay copes to 60% depletion;
lettuce is in trouble by 35%. **Both** `p` **and the crop-coefficient curve are now per-cell**,
area-weighted across whatever grows there — they come from the same FAO-56 table and the Kc curve
turns out to matter more.

Holding cells and weather fixed and changing only the crop assumption, the average recommendation
barely moved — but 45% of individual weeks changed, by up to 6 mm. It was a **redistribution, not
a level shift**:

| | assumed vegetables | satellite crops | |
|---|---:|---:|---|
| Irrigation, Apr–May | 1.05 | **1.63 mm/wk** | +55% |
| Irrigation, Jun–Aug | 6.46 | **5.99 mm/wk** | −7% |

Hay in early May is actively transpiring while a vegetable field is still bare ground. The old
assumption under-warned hay farmers in a dry May and over-warned them in August — a meaningful
error for a system whose whole point is timely warning.

**What the satellite can't see:** greenhouses and nursery stock (a large share of CT agriculture
by value) are invisible to it, and small diversified vegetable plots at 30 m routinely read as
"grassland." Treat per-cell crops as a much better default than "assume vegetables," not as truth
about any individual farm. Every cell stores `agricultural_fraction` so you can see how much to
trust it, and a cell needs ≥25 crop pixels (~5.5 acres) before its mix is used at all — without
that rule, three stray pixels in a forest produced a confident "tobacco 100%."

---

## The water-stress index: millimetres of irrigation per week

Three of your four inputs are **stress signals**, each rescaled to 0–1 and blended with
weights you control in `config.yaml`:

```
stress = 0.40 × s_stage  +  0.35 × s_depletion  +  0.25 × s_anomaly
```

| Signal | What it is | Why it's in the blend |
|---|---|---|
| `s_stage` | USDM stage ÷ 5 | The expert-judgment channel — well levels, streamflow, farmer reports that no gridded product contains |
| `s_depletion` | How empty the soil bucket is | Plants pull water freely until ~50% depletion, *then* stress rises sharply — so this is 0 below the threshold, not linear |
| `s_anomaly` | 90-day rainfall z-score | Long memory: a dry spring still hurts in July, which a 7-day balance forgets entirely |

The fourth input, the **survey**, is different in kind — it isn't a weekly signal, it's ground
truth about how much water farmers actually needed. So it enters as a **calibration factor**
on the final number, not another weighted term.

Then the step that makes this actionable:

```
shortfall          = max(0, ETc − effective_rain)     ← what the sky didn't cover
irrigation_mm_week = survey_factor × stress × shortfall
```

`s_depletion` uses **this cell's** crop threshold, and `ETc` uses **this cell's** blended crop
coefficient — both from the satellite crop map above.

**Order matters here, and getting it wrong is subtle.** `stress × ETc − rain` would subtract
full rainfall from an already stress-reduced number, double-counting the dryness and
collapsing the target to zero almost everywhere. (It did exactly that on the first run — the
90th percentile came out at 0.0 mm/week.) The correct reading: the shortfall is what the crop
needs beyond rainfall, and *stress decides how much of that shortfall you must supply* rather
than let the crop draw from soil storage. Full profile → draw from storage. Empty profile →
you supply all of it.

Multiplying by **crop demand** (`ETc = Kc × ET0`) is what makes the output physically
sensible. A stress of 0.8 in January and 0.8 in July are agronomically nothing alike: in
January the crop needs almost nothing, in July the same stress means ~25 mm/week. A bare
index cannot say that. You get both numbers back — `water_stress_index` (0–1, comparable
across seasons) and `irrigation_mm_week` (the recommendation).

### Two things to be straight about

**The weights are assumptions, not measurements.** They sit in `config.yaml` in the open so
you can change them and watch what moves. Survey calibration is how you eventually replace
guesswork with evidence.

**The two model outputs are correlated by construction.** The stress index contains drought
stage, and we also predict stage separately. So if both say "bad month coming," that is
substantially *one* prediction expressed two ways — not two agreeing predictions. Set
`stress_index.weights.stage: 0` if you ever want a genuinely independent second opinion.

---

## ⚠️ The survey data doesn't exist yet — here's how to get it

I checked: **there is no public, machine-readable Connecticut Farm Bureau drought survey time
series.** What exists is press coverage and narrative summaries from drought years (2016,
2020, 2022) plus national AFBF write-ups — useful context, not loadable data.

So the calibration machinery is built and tested, and it runs correctly *without* the data:
factor 1.0, and it tells you plainly that it wasn't fitted. Nothing pretends the gap is filled.

```bash
uv run ctwater survey-template
```

That writes `data/external/ct_farm_survey.csv` with the required columns (`date`, `lat`,
`lon`, `county`, `irrigation_mm_week`, `crop`, `source`). Fill it in, re-run `build`, and the
recommendation gets calibrated. Three ways to obtain it, in order of effort:

1. **Ask.** CT Farm Bureau and UConn Extension have run grower drought surveys. Emailing to
   ask whether anonymized responses can be shared for a student project is cheap and
   sometimes just works.
2. **USDA NASS Irrigation and Water Management Survey** — real, downloadable, includes
   Connecticut application depths. Only runs every five years so it can't calibrate weekly,
   but it's ideal for a one-time check that your mm/week numbers land in the right range.
   **If you do only one of these, do this one.**
3. **Run your own.** A handful of CT farms logging weekly irrigation for one season would be
   a genuinely novel dataset and would make the index defensible in a way borrowed data
   wouldn't. Also the slowest option.

Calibration fits exactly one number — `median(reported) / median(modeled)` — deliberately a
scalar rather than anything fancier, because with a handful of responses a regression would
just fit noise. It refuses to fit below 5 responses and clamps extreme factors (a mistyped
inches-as-mm entry shouldn't triple every recommendation).

---

## Report the mature folds separately — the average was hiding everything

Walk-forward validation trains each fold on everything before its cutoff, so fold 1 has 9 years of
history and fold 5 has 21. Averaging them answers a question nobody asked: *how well does this model
do, averaged over versions of itself that had far less data than the one you would deploy?*

On this project that average was actively misleading:

| Test period | Trained on | Model error | Persistence | |
|---|---:|---:|---:|---|
| 2009–2012 | 9 yr | 0.63 | 0.24 | |
| 2012–2015 | 12 yr | 1.39 | 0.36 | |
| **2015–2018** | 15 yr | **2.12** | 0.40 | **5.4× worse** |
| 2018–2021 | 18 yr | **0.29** | 0.26 | nearly tied |
| 2021–2024 | 21 yr | **0.37** | 0.31 | nearly tied |

One fold moved the headline error from 0.33 to 0.96 by itself.

**Why that fold failed:** it trained on 2000–2015, which contains exactly *one* major drought (2002),
then was asked to predict **2016 — the largest drought in the record**. Severe Connecticut drought is
clumped into about 8 years out of 25, and 2002 and 2016 dominate. In 17 of 25 years D2-or-worse never
occurred at all. Teaching a model about hurricanes with one hurricane, then testing on a bigger one.

### What the numbers become

`config.yaml` now carries `split.min_train_years: 18`, and every training run prints both columns:

| Metric | All folds | **Mature (≥18 yr)** | Change |
|---|---:|---:|---:|
| MAE, drought stage | 0.960 | **0.330** | −0.63 |
| macro-F1 | 0.249 | **0.323** | +0.07 |
| `skill_vs_persistence` | −0.647 | **−0.046** | **+0.60** |
| Within 1 stage | 0.764 | **0.961** | +0.20 |
| Accuracy | 0.506 | **0.711** | +0.21 |
| recall on stage 3+ | 0.355 | **0.173** | −0.18 |
| `reg_skill_vs_persistence` | 0.310 | **0.078** | −0.23 |

**The drought model is nearly tied with persistence** once judged on folds with real history: error
0.330 against 0.284, macro-F1 0.323 against 0.334, and 96% of forecasts within one stage. That is by
far the best drought result in the project — it was buried under two folds that never had a chance.

### Two honest corrections in the other direction

**The irrigation win is smaller than I reported.** `reg_skill_vs_persistence` falls from +0.310 to
**+0.078**. It still beats the baseline, but the headline was inflated by the early folds. The
mature number is the real one.

**Severe-drought recall drops, 0.355 → 0.173.** The early folds' apparent recall came from
over-predicting drought constantly, which catches events by accident. The mature model is properly
calibrated and consequently more conservative — better on every error measure, worse at catching the
rare severe cases. That trade is worth making deliberately, not by accident.

### This is not cherry-picking

Reporting only the good half of a random split would be. This is a *time* split, and folds differ in
how much history they had — a property of the method, not of the data. The model you would deploy has
all 24 years. Both columns are printed every run so the comparison stays visible.

---

## 25 years of data: what it fixed, and what it did not

The record was extended from 9 years to **2000–2024** (1.8M model rows, 261,000 label-weeks) and
`final_test_start` moved to 2024, so the 2023 flood year enters development while 2024 stays held
out. Three results, and they do not all point the same way.

### 1. The irrigation forecast now beats persistence — the first time anything has

| | 9-year run | **25-year run** |
|---|---:|---:|
| MAE, irrigation (mm/wk) | 2.07 | **1.85** |
| Persistence | 2.04 | 2.16 |
| `reg_skill_vs_persistence` | −0.14 | **+0.31** |
| R² | −8.9 | **+0.21** |

The actionable output — millimetres of water per week — is now better than the free baseline, and
R² is positive for the first time in the project. More history is what did it.

### 2. The excess-moisture model works now. The diagnosis was right.

With the flood years held out it never fired at any threshold. With 2023 in development:

| Threshold | Warnings/yr | Correct | False | Precision | Recall |
|---:|---:|---:|---:|---:|---:|
| 0.50 | 11.1 | 4.1 | 7.0 | 0.37 | 0.57 |
| 0.90 | 4.7 | 2.7 | 1.9 | 0.59 | 0.38 |
| **0.98** | **2.4** | **1.8** | **0.6** | **0.76** | 0.26 |

Precision climbs steadily with the threshold, 0.37 → 0.76 — the mark of a well-behaved model.
Cross-validated AUC **0.839**, up from 0.681. And unlike drought, there is no free baseline here:
nothing predicts floods for you.

**But a large share of that is near-term detection, not forecasting.** The 30-day window includes
days right after today, when an event is largely determined by conditions already visible. Testing
a window that starts two weeks out:

| Forward window | AUC | Precision @0.90 |
|---|---:|---:|
| T+1 … T+30 (includes near term) | 0.811 | 0.59 |
| **T+15 … T+30 (genuine lead time)** | **0.717** | **0.34** |

Real skill survives at genuine lead time — 0.717 is well above chance — but it is much weaker than
the headline. Quote the second row, not the first.

### 3. Drought got harder, not easier

Stage classification degraded badly (`skill_vs_persistence` −0.65, MAE 0.96 against persistence's
0.31), and the worsening model's precision went **flat**: 0.32 at every threshold from 0.50 to 0.95.
A flat precision curve means the model's confident predictions are no more reliable than its
uncertain ones — the opposite of the wetness model's behaviour.

The likely cause is that 2.9-year validation windows now span wildly different drought regimes, and
balanced class weighting on 1.75M rows over-predicts drought throughout. This is worth diagnosing
before adding anything else.

### The honest summary

More data made **wetness and irrigation** work and made **drought staging** worse. Excess moisture
turns out to be more predictable than drought intensification at a month's lead — which is
physically sensible, since floods follow identifiable setups while drought deepening depends on rain
that simply fails to arrive.

---

## Predicting the CHANGE instead of the level — this is the one that works

Every model above predicted the drought *level* in 30 days, and lost to "assume nothing changes"
because the level genuinely does not change 76% of the time. Asking **"will it get worse?"** competes
only on the part that is actually uncertain.

**Persistence cannot answer this question at all.** By construction it predicts no change, so it
catches zero worsening events, ever. Any recall above zero is capability the free baseline does not
have.

### The decision threshold is the whole game

A classifier outputs a probability; 0.5 is an arbitrary place to cut it. For a warning system that
cut *is* the product decision:

| Threshold | Warnings/yr | Correct | False | Precision | Recall |
|---:|---:|---:|---:|---:|---:|
| 0.50 | 6.5 | 2.4 | 4.1 | 0.37 | 0.27 |
| 0.70 | 5.4 | 2.3 | 3.1 | 0.43 | 0.27 |
| 0.90 | 4.1 | 2.2 | 1.9 | 0.54 | 0.25 |
| **0.95** | **3.4** | **2.1** | **1.4** | **0.60** | 0.24 |

Recall barely moves as the threshold rises — the false alarms fall away and the correct warnings
stay. That is the shape you want.

### Compared with predicting the level

| Per farm, per year | Level model | **Change model @0.95** | Persistence |
|---|---:|---:|---:|
| Warnings given | 8.4 | **3.4** | 3.0 |
| Correct | 1.9 | **2.1** | 2.1 |
| **False alarms** | 6.5 | **1.4** | 0.9 |
| Precision | 0.23 | **0.60** | 0.71 |

**More correct warnings than the level model, with a quarter of the false alarms.** And unlike
persistence — which only ever says "same as now" — this one actually anticipates deterioration.
Cross-validated AUC is 0.736, so the ranking carries real signal.

This is the first configuration in the project that is arguably worth putting in front of a farmer.

---

## Excess moisture: the model is blocked by the split, not by the data

Connecticut lost more to flooding than drought in 2023–24, so the same inputs were used to forecast
**"will there be excess moisture in the next 30 days?"** The target validates well (see the data
dictionary). The model does not — and the reason is structural rather than a modelling failure.

```
excess-moisture events by year
  2016 [dev]  0.0%      2021 [dev]  5.9%
  2017 [dev]  3.4%      2022 [TEST] 2.2%
  2018 [dev]  0.4%      2023 [TEST] 6.3%
  2019 [dev]  0.1%      2024 [TEST] 6.8%
  2020 [dev]  0.1%
```

**The flood years are the held-out years.** Development runs 2016–2021 at 1.64% events; the test
period runs 5.09%. The model is being asked to learn floods from years that mostly did not have any,
and at every decision threshold it never fires.

Cross-validated AUC is 0.681, so there *is* signal in the ranking — it simply cannot be calibrated
into a usable warning when the training period holds so few positive examples.

**The fix is not a better model.** Either move `split.final_test_start` later so 2023–24 enter
development, or extend the record back before 2016 — AORC reaches 1979 and USGS further still. Until
then, treat the wetness forecast as untested rather than as failed.

---

## Locations: real farms, not invented coordinates

Everything used to rest on twelve made-up coordinates. The soil survey then reported that one was
**Urban land** in downtown Hartford and another was **open water** — and they sat close enough
together to share weather, collapsing 26,000 training rows into roughly 311 genuinely independent
label-weeks. That was the binding constraint, not the model.

`ctwater find-farms` replaces them using two independent public sources.

### Why not just filter the parcel layer for "FARM"?

It's the obvious move and it's a trap, for two reasons I measured rather than assumed:

1. **Only 40 of Connecticut's 169 towns populate the assessor's land-use field.** Matches cluster
   hard in the northwest hills — Bethlehem, Morris, Salisbury, Cornwall, Sharon — not because
   that's where farming happens, but because those assessors fill in the column. A model trained
   on that sample would learn the Litchfield hills and be tested on the Litchfield hills.
2. **The matches include "TANK FARM", "SOLAR FARM" and "Solar Farm Site".** None grow anything.

So the assessor code labels what we found; it never chooses it.

### What actually picks the locations

| Step | Source | Job |
|---|---|---|
| 1 | USDA Cropland Data Layer | Satellite decides **where farmland is** — statewide and uniform |
| 2 | Stratified sampling | 12×12 blocks, so the sample spans the state |
| 3 | CT State Parcel Layer | Parcels turn cropland into **distinct farms** |
| 4 | De-duplication | One row per parcel, then one per 1 km cell |

Result: **200 farms across 99 of 169 towns**, median parcel 54 acres, crop mix pasture 81 / hay 73
/ corn 25 — which matches Connecticut's actual statewide acreage.

### Two things worth knowing

**The honest name for the output is "distinct 1 km cells known to contain a working farm."** Every
feature is computed per cell, so two farms in one cell are indistinguishable to the model however
distinct they are legally. Going finer means shrinking the grid.

**Deduplicate before the expensive step.** The first version looked up all ~2,600 sampled points
against the parcel service before collapsing them to cells — wasting most of the work and getting
throttled into a stall. Collapsing first cut it to 500 lookups that finish in about two minutes.

---

## Soil: where location precision actually comes from

`ctwater fetch-soils` queries USDA's SSURGO soil survey and replaces the invented `awc_mm`.

Two fields getting identical rain behave completely differently if one holds 60 mm of
plant-available water and the other 180 mm. Rainfall barely varies over 1 km; **soil does.** So
this, not the weather, is where a location-precise forecast gets its precision.

**The crop picks the rooting depth.** Lettuce cannot reach water at 120 cm, so counting it would
overstate what the plant can use. FAO-56 depths live per crop in `config.yaml` and blend by each
cell's satellite crop mix:

| Crops | Depth read |
|---|---|
| vegetables, tobacco, turf | 0–50 cm |
| hay, pasture, corn, grain | 0–100 cm |
| alfalfa, orchard | 0–150 cm |

A hay field and a lettuce field on the *same soil* therefore get different usable water.

### How wrong was the invented data?

| | |
|---|---|
| Invented mean | 133 mm |
| **Surveyed mean** | **88 mm** |
| Mean absolute error | **59 mm** (worst 138 mm) |
| Correlation invented vs real | **−0.25** — none, as expected of random numbers |

Every result before this depended on a number wrong by 59 mm on average and uncorrelated with
reality.

### ⚠️ Several of your locations are not farms

The survey reports **Urban land** for Hartford (35.9 mm), another urban cell at 12.9 mm, and one
cell that is literally **Water** (64.9 mm). Those are true statements about the coordinate and
useless ones about farming. Cells below 25 mm get flagged with a `soil_note`.

**The locations are the problem, not the soil data** — another reason to replace the 12 invented
sites with real farms.

---

## Results: four data upgrades, tracked honestly

Every input is now real. Here is `skill_vs_persistence` after each change — positive means
beating the "next month looks like this month" baseline:

| Stage of the project | cells | `skill_vs_persistence` | recall on stage 3+ |
|---|---:|---:|---:|
| Synthetic weather | 12 | −0.066 | 0.41 |
| + real NOAA weather | 12 | −0.016 | 0.23 |
| + USGS streamflow | 12 | −0.012 | 0.26 |
| + USDA soil survey | 12 | **−0.0008** | 0.34 |
| **+ 200 real farm parcels** | **200** | **−0.206** | **0.60** |

### More data made the headline number worse. Here is why.

That last row looks like a failure and is not one — but the naive reading ("more data hurt") is
wrong, so it is worth being precise.

**What actually changed is the precision/recall balance.** Severe-drought recall nearly doubled,
0.34 → **0.60**. The model now catches three fifths of serious droughts instead of a third. It pays
for that by crying wolf, and MAE punishes false alarms hard.

The cause is measurable. Class weighting scales rare stages up sharply — stage 0 gets weight 0.3,
stage 4 gets **7.1**, a 24× ratio — which deliberately makes the model trigger-happy. Then look at
what a validation fold actually contains:

```
fold 5 validation window: 46,800 rows, 100% stage 0 — no drought at all
  persistence  MAE 0.006   (it just says "same as now", and is right)
  model        MAE 0.227   (predicts drought on 17% of rows)
```

In a drought-free window, any false alarm is pure loss and persistence is nearly perfect. So the
metric is dominated by whether that particular stretch of calendar happened to be quiet.

**And that is the deeper finding: adding cells did not add as much independence as the row count
suggests.** Between-cell drought-stage correlation is **0.84** — Connecticut is small and drought
is regional. Going from 12 to 200 cells multiplied rows *within the same weather*, so a quiet
validation window now contains 46,800 easy rows instead of 3,000. Walk-forward CV here has an
effective sample size closer to the number of independent *time windows* than the number of rows.

### What this means for the project

- **`mae_stage` may be the wrong headline metric for a warning system.** It rewards silence. You
  said the costs are asymmetric — a missed drought can cost a crop, a false alarm costs one
  irrigation run — and `recall_d2plus` at 0.60 is the number that reflects that.
- **The class weighting is a lever, not a bug.** `class_weight: balanced` in `config.yaml` is what
  buys the recall. Turning it off should recover MAE and lose severe-drought detection. Worth
  running both and deciding deliberately rather than by default.
- **37% of weeks have cells genuinely disagreeing on stage**, with spreads up to 1.35 stages. That
  disagreement is the real signal 200 locations bought, and it is not what MAE measures.

**Two things still explain the remaining gap, and both are measurable:**

**1. Persistence is an unusually strong opponent here.** The Drought Monitor is drawn each week by
a human author who updates last week's map incrementally. Measured on your own labels:

| Horizon | Stage unchanged |
|---|---|
| 7 days | 92% |
| 14 days | 85% |
| **30 days** | **76%** |

Three quarters of the time, "next month looks like this month" is simply correct. Beating that at
30 days is a hard open problem, not a beginner's oversight.

**2. There is far less independent data than the row count suggests.** 26,172 development rows look
substantial, but they are 12 cells sharing near-identical weather (rainfall correlation 0.82) over
~311 independent label-weeks. Fitting 94 features to that is heavily over-parameterised — and
the model's top feature is `doy_sin`, meaning it leans on *what time of year it is* more than on
drought physics.

### What would actually move the needle

- **More locations.** 12 → several hundred cells across Connecticut is the single biggest lever,
  and the pipeline already supports any number. More cells means genuinely more label variation.
- **Fewer features, or stronger regularisation.** 94 columns against ~311 independent observations
  is the wrong ratio.
- **Real soil data.** `awc_mm` is still invented, and it is the main thing that makes neighbouring
  fields differ — the exact effect this project claims to capture.
- **Predict *change*, not level.** Persistence wins because the level barely moves. A model that
  forecasts "will it get worse?" competes on the part that is actually uncertain.

The harness is working correctly throughout: it refuses to flatter a model that has not yet earned
it, which is what lets you trust it on the day the number finally goes positive.

---

## The flood label stopped being something I made up

Every wet-risk number in this project used to carry the same asterisk, and I put
it there myself: **the target was defined, not observed.** Drought has the U.S.
Drought Monitor — a human expert drawing a map every week — and the model learns
to predict that. Nothing equivalent publishes a weekly map of which fields are
too wet, so I wrote a rule from streamflow and rainfall and validated it against
the two floods I knew about.

That is a weak position, and it was the weakest thing in the project.

**NOAA's Storm Events Database fixes it.** The National Weather Service records
every flood it responds to: what type, when it began, where, and what it damaged.
For Connecticut, 1996–2024:

| event type | count | with usable coordinates |
| --- | --- | --- |
| Flash Flood | 615 | 485 |
| Flood | 346 | 219 |
| Heavy Rain | 126 | 12 |
| Coastal Flood | 67 | 0 |

That is a label somebody else produced, for their own reasons, with no knowledge
of this project. Which is exactly what makes it worth having.

```bash
uv run ctwater fetch-storm-events
```

### First thing it did was grade my homework

Before training anything, the obvious question: does the rule I invented fire on
the days the Weather Service actually recorded floods?

```
NWS recorded 5,350 cell-days of flooding.
Our invented rule flags 25% of them (within ±3 days).
It fires on 3.2% of all cell-days, so that is a 8.0x lift over chance.
```

**Eight times better than chance, and still missing three floods in four.** Both
halves of that sentence are true and both matter. The rule was not noise — it
found real floods at eight times the base rate. It was also nowhere near a
complete account of flooding in Connecticut.

The month-by-month breakdown shows exactly where it went wrong:

| month | our rule fires | NWS recorded | ratio |
| --- | --- | --- | --- |
| Jan | 0.00% | 0.19% | **0×** |
| Feb | 0.00% | 0.07% | **0×** |
| Mar | 0.00% | 0.33% | **0×** |
| Apr | 3.73% | 0.11% | 33× |
| May | 4.39% | 0.07% | 66× |
| Jun | 6.99% | 0.30% | 24× |
| Jul | 5.04% | 0.73% | 7× |
| Aug | 4.56% | 0.55% | 8× |
| Sep | 9.15% | 0.65% | 14× |
| Oct | 4.51% | 0.32% | 14× |
| Nov | 0.00% | 0.03% | **0×** |
| Dec | 0.00% | 0.16% | **0×** |

Two failures, in opposite directions:

**I turned it off for half the year.** My rule only fires April–October, because
Connecticut soil is saturated most of the winter and I decided a wet January
damages nothing. The NWS recorded floods in every winter month — March is its
third-worst month of the year. Snowmelt and winter rain flood fields; my rule is
structurally blind to it. That was my assumption, and it was wrong.

**I cried wolf in spring.** In May my rule fires 66 times more often than the NWS
records anything. A physical threshold crossed on 4.4% of May days is not a
flood, it is a wet spring. The threshold was tuned on July and August events and
does not transfer.

This is the single most useful thing the storm database has done, and it cost
nothing but the download. **A definition you cannot check is a definition you
should not trust** — and I could not check this one until now.

## Fixing it: what the observed label actually changed

Having found the two faults, I fixed them against the record rather than by eye.
Thresholds were fitted per season on **2000–2019**, the *scheme* was chosen on
**2020–2023**, and **2024 was never used for either** — so it is a genuine test.

### Per-month thresholds looked better and were worse

The obvious move is a threshold for every month. It fit beautifully and failed
out of sample:

| scheme | F1 on 2020–23 |
| --- | --- |
| old flat 80 mm, Apr–Oct only | 0.198 |
| **per-season, all year** | **0.252** |
| per-month, all year | 0.205 |

The per-month numbers were visibly jagged — July 35 mm, August 80 mm, September
105 mm — which is not a physical pattern, it is noise being memorised. Twelve
thresholds fitted to a few hundred events is more knobs than the data supports.
**Per season, not per month.** That is overfitting caught in the act, and it is
the same failure mode that makes a model look brilliant in testing and useless in
a field.

### The spring problem was my fix, not the original rule

This is the part I got backwards. My first correction *lowered* the spring
threshold to 60 mm, on the theory that spring floods easily. Measured, that made
April fire on 5.7% of days — worse than before.

**Spring's original 80 mm was right.** The final thresholds:

| season | threshold | why |
| --- | --- | --- |
| winter | 65 mm | frozen or saturated ground sheds rain instead of absorbing it |
| spring | **80 mm** | unchanged — this was never the problem |
| summer | 55 mm | convective storms, intense, onto warm ground |
| fall | 85 mm | summer has dried the profile, so more rain is needed |

The winter blind spot was real. The spring over-firing was mostly an artifact of
comparing a 14-day window against single-day events — and my first attempt to fix
it made it genuinely worse.

### Streamflow lost its vote entirely

`peak_flow_z` carried the **heaviest weight in the index (0.45)**, on the sound-
sounding reasoning that a river in flood is carrying water off the land. Against
the record it is the worst signal available:

| season | flow z≥2.45 | rain≥80 mm |
| --- | --- | --- |
| winter | 1.7× | 4.8× |
| spring | 2.5× | 8.5× |
| summer | 2.2× | 5.2× |
| fall | 4.7× | 6.6× |

Adding flow to the rain trigger *lowered* F1 in all four seasons. I moved it to
z≥3.2, where it looked neutral, and kept it on the argument that riverine
flooding damages farmland even when under-reported. Then 2024 settled it:

> **flow ≥ 3.2 fired on 1.36% of cell-days and caught zero reported floods.**

So the argument lost to the measurement. The cause is subtle and worth
remembering: these z-scores are computed against *week-of-year* normals, so by
construction they clear a fixed threshold at roughly the same rate every week of
the year — about 3–4%. **"Unusual for early May" is not "a flood."** I had
normalised away the very seasonality that decides whether high water is dangerous.

Flow is not deleted. It stays in the index and stays available to the models as a
feature, where a tree can combine it with season and rainfall. It is only
disqualified from deciding *on its own* that a flood happened.

### Where it ended up

| | 2020–2023 | | 2024 (held out) | |
| --- | --- | --- | --- | --- |
| | **F1** | recall | **F1** | recall |
| old: 80 mm, Apr–Oct only | 0.198 | 15.6% | **0.144** | 10.6% |
| new: seasonal, all year | **0.265** | **29.2%** | 0.118 | **14.6%** |

**Recall nearly doubles, and the system can warn in winter at all.** Note the
honest wart: on 2024 the old rule still scores higher on F1. It does that by
firing on 0.9% of days — too rarely to be very wrong, and too rarely to be much
use. Agreement with the NWS record across the whole period went from **25% to
40%** of reported floods caught.

## What is actually cause for concern: NOAA Atlas 14

Everything above tuned a number in millimetres. Atlas 14 asks the better
question — **how rare is this rain, at this exact farm?** — and the answer was
uncomfortable.

```bash
uv run ctwater fetch-atlas14
```

NOAA publishes, for any point, the rainfall depth expected at each **average
recurrence interval**. At Hartford, 24-hour depths:

| 1 yr | 2 yr | 5 yr | 10 yr | 25 yr | 100 yr |
|---|---|---|---|---|---|
| 63mm | 79mm | 104mm | 125mm | 154mm | 199mm |

### My thresholds had been calibrated to "normal weather"

A typical Connecticut farm sees a ~71mm 24-hour storm **once a year**. So my
carefully tuned seasonal thresholds meant:

| my threshold | what it actually is |
| --- | --- |
| summer 55mm | a **0.6-year** storm — arrives twice a year |
| winter 65mm | a 0.9-year storm |
| spring 80mm | a 1.3-year storm |

I had tuned the rule to fire on rain that falls every single year. It scored well
because **most NWS flood reports are ordinary storms** — a road underwater for an
hour is a report — so optimising agreement with the report count optimises toward
the commonplace. That is precisely the trap of calibrating against a label
without asking what the label counts.

### Millimetres also aren't comparable across the state

Across these 200 farms the 2-year 24-hour storm ranges **78mm to 93mm**. One flat
number is a 2.1-year event at one farm and a 1.1-year event at another — throwing
away the location precision this project exists to provide.

### Where concern actually begins

Calibrated against floods that caused **recorded property damage** (148 events,
$52M):

| threshold | fires on | recall, damaging | recall, major | lift |
| --- | --- | --- | --- | --- |
| ARI ≥ 0.5 yr | 19.8% of days | 61.4% | 78.8% | 3.1× |
| **ARI ≥ 1 yr** | **2.6%** | **25.6%** | **48.3%** | **9.9×** |
| ARI ≥ 2 yr | 1.1% | 14.0% | 34.8% | 12.4× |
| ARI ≥ 5 yr | 0.3% | 5.4% | 11.7% | 19.8× |

**The jump from 3.1× to 9.9× between half a year and one year is the line between
"wet" and "worth acting on."** Below it the rule fires on a fifth of all days,
which is not a warning, it is a season. The trigger is now `ARI ≥ 1 year`, with
tiers at 1 / 2 / 5 years for *watch* / *concern* / *severe*.

### The seasonal thresholds turned out to be a workaround

Median return period of a **damaging** flood by season: winter 0.66, spring 0.76,
summer 0.50, fall 0.82 — a narrow spread. Adding seasonal multipliers to the ARI
threshold moved F1 from 0.081 to 0.083, i.e. nothing.

**Four tuned constants collapsed into one interpretable parameter**, because the
seasonal millimetre thresholds were mostly compensating for millimetres not being
severity. Once severity is measured properly, most of the seasonality they stood
in for disappears.

### One caveat on vintage

Volume 10 is built from records through ~2012. It is the current official
standard and what Connecticut drainage is designed against, but a warming climate
has been loading the extreme tail since — today's "10-year storm" likely arrives
more often than every ten years. NOAA Atlas 15 is meant to address this. These
are the engineering baseline, not a forecast of future frequency.

## Can floods be forecast at all? Mostly not

Trained on the observed NWS label across four horizons:

| horizon | model AUC | climatology AUC | model AP | climatology AP |
| --- | --- | --- | --- | --- |
| 3 days | 0.748 | 0.755 | 0.042 | 0.028 |
| 7 days | 0.758 | 0.768 | 0.106 | 0.058 |
| 14 days | 0.776 | 0.779 | 0.207 | 0.107 |
| 30 days | 0.779 | 0.795 | 0.307 | 0.220 |

**On AUC the model loses to the calendar at every horizon**, including three days.
On average precision — the right metric for rare events — it runs roughly
1.4–1.9× ahead. Read together: the model does not reorder the bulk of days better
than "floods happen in July," but it does rank its *top* predictions better.

Treat that as weak and unstable, not as a win. The full 200-cell run put the AP
edge at only +0.016; this 50-cell run puts it at +0.087. **An effect that swings
that much with the sample is not one to build a warning system on yet.**

The underlying reason is physical: a flood is one storm, and storm timing is not
predictable beyond about ten days. Drought is a slow accumulating deficit, so
today genuinely constrains next month. That asymmetry is why the dry side gets
within 0.046 of persistence and the wet side cannot beat a calendar.

## Whose ground is it? NRCS flood and ponding frequency

Atlas 14 says how rare the *rain* is. It says nothing about whether that rain
lands on a river terrace or a hillside — and those are not the same field:

> a 2-year storm on Connecticut River floodplain silt → **water over the crop**
> the same storm on Hinckley outwash gravel → **gone by evening**

NRCS rates every soil map unit for how often it floods and ponds, from field
observation and landform position.

```bash
uv run ctwater fetch-flood-ratings
```

### These 200 farms are not on uniform ground

| flooding | farms | | ponding | farms |
| --- | --- | --- | --- | --- |
| None | 127 (64%) | | None | 99 (50%) |
| Frequent | 35 (18%) | | Frequent | 101 (50%) |
| Rare | 25 (12%) | | | |
| Very frequent | 8 (4%) | | | |
| Occasional | 3 (2%) | | | |

**46 of 200 farms sit on ground that floods at least once a decade.** A model
treating a floodplain farm and a hillside farm identically throws that away.

Ponding matters especially: it is the **waterlogging** mechanism — water
collecting where it fell, in a depression with no outlet. `features/wet.py` had
to drop waterlogging from the event definition because our bucket soil model
reported saturation on 27% of growing-season days. This is the honest,
field-observed version of the signal we had to remove.

### The classes convert straight onto the Atlas 14 scale

| class | NRCS definition | ≈ return period |
| --- | --- | --- |
| Very frequent | more than once per year | 0.5 yr |
| Frequent | > 50 times in 100 years | 1.5 yr |
| Occasional | 5–50 times in 100 years | 7 yr |
| Rare | 1–5 times in 100 years | 40 yr |
| None | no reasonable possibility | — |

Both are return periods, so `flood_pressure = rain_ari / site_flood_ari` is
dimensionless and means something concrete: **is this storm rarer than the
interval at which this ground floods anyway?**

### The validation failed, and the failure was mine

Tested against damaging floods, flood-prone farms showed **no more** damaging
floods than the rest — 0.40% vs 0.44%. Every combined rule scored *worse* than
rain rarity alone.

That looked like a dead end until I checked the obvious suspect — my own
attribution radius:

| radius | flood-prone | not prone | ratio |
| --- | --- | --- | --- |
| 20 km | 0.404% | 0.441% | 0.92 |
| 10 km | 0.126% | 0.147% | 0.86 |
| 5 km | 0.038% | 0.036% | 1.05 |
| 3 km | 0.015% | 0.011% | 1.37 |
| **2 km** | 0.008% | 0.003% | **2.39** |

**I attribute every NWS flood report to all cells within 20 km — an area 400×
larger than the 1 km scale at which soil flood rating varies.** The test could
not have detected the effect. As the radius tightens the signal emerges cleanly
and monotonically, reaching 2.4× at 2 km.

⚠️ **But at 2 km only 84 cell-days are flagged**, so that ratio is underpowered
and I am not claiming it as a result. The honest statement is: *the storm-events
label cannot validate a sub-20 km spatial feature, and this is a limitation of
the label, not evidence against the soil ratings.*

So the ratings go in as **model features**, not as a trigger — static, cheap,
physically real, and carrying information no weather feature can see. Whether
they earn their place is for the model to show, not for me to assert.

### A methodological warning this raises for everything else

The 20 km radius is baked into every spatial claim on the wet side of this
project. Any effect operating below that scale is invisible to the current
validation. That is worth remembering before trusting any location-precision
claim the wet model makes.

## Terrain: USGS 3DEP LiDAR

NRCS is a soil scientist's judgment on polygons. 3DEP is a **measurement** —
bare-earth LiDAR, ~10m pixels, current to July 2026. They fail differently, which
is why both are worth having: a soil polygon can be decades old and generalised,
while a DEM cannot tell you a field has been drained.

```bash
uv run ctwater fetch-elevation
```

Per farm, a 4km tile, summarised over the central square kilometre. The tile size
is a real constraint: **the valley a field drains into has to be inside the tile**
for height-above-drainage to mean anything. A 1km tile centred on a floodplain
farm contains nothing but floodplain and reads as a hilltop.

### Connecticut farmland is mostly high ground

| metric | min | median | max |
| --- | --- | --- | --- |
| elevation | −1.2m | 129.6m | 465.8m |
| slope | 0° | 4.3° | 13.4° |
| height above drainage | 0.1m | **42.8m** | 173.5m |
| share flatter than 2° | 0.0 | **0.2** | 1.0 |
| local relief | 18.5m | 131.7m | 502.1m |

**Only 11 of 198 farms are both low (within 10m of drainage) and flat.** Far more
selective than NRCS's 46. Farms sit where farming works, which in glacial
Connecticut is mostly not the floodplain.

### Two independent sources agree

| | NRCS: not prone | NRCS: prone |
| --- | --- | --- |
| terrain: not low/flat | 148 | 39 |
| terrain: low + flat | 5 | 6 |

More telling than the crosstab: **NRCS flood-prone farms sit at a median 25.7m
above local drainage; everyone else at 50.8m — exactly half.** A soil survey drawn
from field observation and a LiDAR calculation, neither knowing about the other,
agree on which farms sit low. That is the closest thing to independent
verification this project has produced.

### The flood signal, once the radius is tight enough

Damaging-flood rate, lowest vs highest quartile of height-above-drainage:

| radius | lowest HAND 25% | highest 25% | ratio |
| --- | --- | --- | --- |
| 20 km | 0.406% | 0.459% | 0.88 |
| 10 km | 0.151% | 0.154% | 0.98 |
| 5 km | 0.054% | 0.028% | **1.94** |
| 3 km | 0.017% | 0.009% | **1.83** |
| 2 km | 0.006% | 0.003% | **2.00** |

Same pattern as NRCS, from an entirely different measurement: **invisible at
20km, roughly 2× at 2–5km.** Two independent site-susceptibility datasets, both
showing the same signal at the same scales, is much harder to dismiss as noise
than either alone.

The binary `terrain_flood_prone` flag reads 0.00% at 2–3km — but that is 11 farms
with too few events, a small-sample zero rather than evidence of no effect.
**Continuous `hand_m` is the usable signal; the binary flag cannot be validated
at this sample size.**

### Topographic Wetness Index is deliberately absent

TWI = ln(upslope area / tan slope) is the standard index for this job and needs
true flow accumulation. The shortcut version — substituting pixel area for
contributing area — is not TWI, it is a rescaling of slope wearing TWI's name. It
would look authoritative and add nothing. Left out rather than faked; it is the
first thing to compute if flow routing is ever added.

### A bug a test caught, worth recording

`hand_m` originally used `nanpercentile(dem, 5)` as the local low ground. On a
synthetic plateau it returned **57m for a tile whose floor is 0m** — when low
ground occupies almost exactly 5% of a tile, the percentile interpolates onto the
valley *wall* rather than the floor, and a 60m plateau read as 3m above drainage.

Real terrain is smoother, but **a narrow valley occupying under 5% of a tile
fails identically — and narrow valleys are exactly where flooding happens.** Now
the mean of the lowest 5% of pixels, which cannot land on a cliff edge.

## The product: stop competing with climatology, start delivering it better

A long stretch of this project measured whether the model could beat climatology
and persistence. It mostly cannot, and those results stand. But that was never
what makes this system worth building.

**The U.S. Drought Monitor is what a Connecticut farmer has today.** Its limits
have nothing to do with forecast skill:

| | U.S. Drought Monitor | this system |
| --- | --- | --- |
| updates | once a week | **every day** |
| latency | Tuesday data, Thursday map | same day |
| spatial unit | hand-drawn polygons, county-scale | **1 km², at the farm** |
| soil | not represented | measured capacity per farm |
| crop | not represented | FAO-56 curve per crop |
| horizon | current conditions | **30 days ahead** |
| uncertainty | one category | an explicit range |

Not one of those requires beating climatology.

```bash
uv run ctwater forecast --date 2022-06-15
```

### How the forecast is built

Rainfall is **not predicted**. For each farm we replay what actually happened at
that location in that calendar window in each of the past ~24 years, and run
every one of them through that farm's own soil capacity and crop demand.

Whole past years rather than random draws, because water stress depends on
**sequencing**, not totals — 25 mm as one storm then three dry weeks is a
different month from 25 mm spread evenly, and sampling days independently
destroys exactly that structure.

The output is a range and a probability, never a single number. Emitting a point
forecast would contradict our own measurement that 30-day rainfall is
unpredictable.

### Where rainfall predictability actually ends

All 200 farms, rainfall history only, against the seasonal normal:

| days ahead | model MAE | climatology MAE | vs climatology |
| --- | --- | --- | --- |
| 1 | 3.70 mm | 5.05 mm | **+26.6%** |
| 3 | 10.33 | 11.26 | **+8.2%** |
| 7 | 18.66 | 18.37 | −1.5% |
| 14 | 28.13 | 27.57 | −1.7% |
| 30 | 43.93 | 42.44 | −3.2% |

**Useful skill ends at three days.** Beyond that the model is *worse* than
knowing what month it is — because with no real signal left, a flexible model
fits noise while a seasonal average cannot.

⚠️ **This model has no atmospheric inputs.** No pressure, wind, upper-air, or
numerical weather prediction — only rainfall history. Three days is what rainfall
history alone buys. Ingesting NOAA's actual forecast products (GEFS) would extend
useful skill to roughly 7–10 days, and that is the single highest-value thing
left to add.

### The finding that justifies the whole system

Does per-farm soil capacity actually change the answer? Yes — **but only while
there is water in the bank**, and that timing is the product thesis:

| forecast issued | soil now | irrigation need across farms | corr(capacity, need) |
| --- | --- | --- | --- |
| **15 May** | 0.54 | 0.0–18.0 mm/wk | **−0.688** |
| 15 Jun | 0.34 | 0.0–29.7 | −0.245 |
| 1 Jul | 0.04 | 5.7–32.3 | +0.009 |
| 1 Aug | 0.03 | 8.7–32.1 | +0.710 |

In May, with profiles half full, one farm needs 18 mm/week while its neighbour
needs nothing — driven almost entirely by soil. By August every farm is scraped
down to the same stress line, a deep profile is no help because it is empty to
that same line, and the correlation flips positive purely from geography (deep
alluvial soils sit in the hot, dry Connecticut River valley).

**The location-specific advantage is largest in May and June — exactly when 30
days' notice is still actionable.** By August everyone is in trouble and the map
hardly matters.

### Two arithmetic errors that had to be fixed to see it

The first irrigation formula was `ETc − rain`, which **never touches soil
capacity**. Farms with 98 mm and 151 mm of available water both returned
24.9 mm/week — the entire case for per-farm forecasting vanished into the
algebra. The second attempt refilled to field capacity, which made *large*
buckets need the most water: an artifact of the refill rule, not a property of
soil. Applying only enough to clear the stress line fixed both.

## NOAA GEFS: a real forecast for the first week

Rainfall history alone runs out of skill at three days. That is a fact about our
inputs, not about the atmosphere - that model has no pressure, no wind, no
upper-air, no physics. **NOAA already runs the physics**, and publishes it free.

```bash
uv run ctwater fetch-gefs --date 2018-06-15
uv run ctwater forecast   --date 2018-06-15
```

### Measured, not assumed: GEFS earns 7 days, not 10

GEFS v12 reforecast against a climatology fitted only on prior years. 15 forecast
dates across three growing seasons, 200 farms:

| lead day | GEFS MAE | climatology MAE | GEFS better by | correlation |
| --- | --- | --- | --- | --- |
| 1 | 2.00 mm | 3.66 mm | **+45.3%** | 0.35 |
| 2 | 4.04 | 6.36 | **+36.4%** | 0.77 |
| 3 | 5.60 | 6.84 | **+18.0%** | 0.56 |
| 4 | 4.06 | 4.65 | **+12.8%** | 0.48 |
| 5 | 3.10 | 3.36 | **+7.8%** | 0.29 |
| 6 | 3.31 | 3.73 | **+11.4%** | 0.24 |
| 7 | 5.55 | 6.00 | **+7.4%** | 0.10 |
| **8** | 5.78 | 4.10 | **-40.9%** | 0.05 |
| 9 | 5.43 | 4.73 | **-14.7%** | -0.11 |

The files are published as `Days:1-10` and the obvious move is to use all ten.
**Day 8 is where it stops paying** - and past it GEFS is not merely useless but
*actively worse* than the seasonal normal, because a five-member ensemble mean at
long lead is noise with a physical pedigree. The relay switches at 7.

So the forecast is now three sources, each doing what it is best at:

| days | source | why |
| --- | --- | --- |
| 1-7 | **NOAA GEFS** | real atmospheric physics, +7% to +45% over climatology |
| 8-30 | replayed past years | nothing beats climatology out here |
| throughout | per-farm soil & crop | what neither of the above can see |

### Two silent bugs, both worth recording

**The accumulation-window trap.** GEFS precipitation files interleave overlapping
windows: message 0 is 0-3h, message 1 is **0-6h**, message 2 is 6-9h, message 3
is **6-12h**. cfgrib indexes by `endStep`, so all 80 steps look like a clean
3-hourly series. Summing them **inflates rainfall by 1.53x** - 32.4 mm against a
correct 21.1 mm at Hartford.

What makes it dangerous is that the wrong number is the right order of magnitude
*and lands closer to the observed 37 mm than the correct one does*. **A sanity
check against observations would have endorsed the bug.** Only reading
`startStep`/`endStep` catches it.

**The one-member ensemble.** cfgrib does not return one dataset per file. The
control member comes back as one dataset of 80 steps; the perturbed members come
back as *two*, with a stray single-step dataset that has no `step` dimension.
Taking `datasets[0]` worked perfectly for `c00` and silently discarded p01-p04 -
producing a "5-member ensemble" containing one member. It still yields a mean and
percentiles. It just has no spread, and spread is the entire product.

WARNING on the 7-day boundary: 15 dates is a small sample, growing season only,
and the reforecast carries 5 members where operational GEFS carries 31. A fuller
ensemble would likely push the boundary out a day or two. Re-measure before
moving it.

## Scoring the forecast end to end

The check that separates "well-built" from "known to work". 6,000 farm-forecasts,
30 issue dates, six years.

```bash
uv run ctwater verify --years 2012,2014,2016,2018,2020,2022 --months 5,6,7,8,9
```

Nobody records "this farm needed 15 mm/week in June 2018", so the forecast is
scored against the same water balance driven by the weather that *actually
happened*. Truth and forecast share identical physics, so every difference
between them is weather uncertainty - which is exactly what the ensemble claims
to quantify.

### It beats climatology on both counts

| | forecast | climatology | persistence |
| --- | --- | --- | --- |
| **Brier score** (lower better) | **0.1546** | 0.2110 | 0.2593 |
| **irrigation MAE** | **4.76 mm/wk** | 6.32 mm/wk | - |

**Brier skill +0.267. Irrigation skill +24.7%.** The p10-p90 range contained the
outcome on **79.9%** of forecasts against an 80% target.

### But the probability is overconfident, and it cannot be calibrated away

| when it says | it happens |
| --- | --- |
| 3% | 0.4% |
| 38% | 27% |
| **59%** | **40%** |
| 81% | 73% |
| **99%** | **82%** |

Every gap negative. The obvious fix is isotonic calibration on prior years. It
**made things worse** - Brier 0.1546 to 0.1593, worst gap 0.155 to 0.220.

The reason is the useful part. The bias is not stable:

| year | actual rate | mean forecast | gap | |
| --- | --- | --- | --- | --- |
| 2012 | 0.576 | 0.576 | -0.000 | |
| 2014 | 0.686 | 0.556 | **+0.130** | |
| 2016 | 0.905 | 0.690 | **+0.215** | drought |
| 2018 | 0.370 | 0.467 | **-0.097** | wet |
| 2020 | 0.881 | 0.638 | **+0.243** | drought |
| 2022 | 0.589 | 0.619 | -0.030 | |

**In drought years the ensemble under-predicts stress; in wet years it
over-predicts.** That is not miscalibration - it is the ensemble hedging toward
the climatological middle because it cannot know which kind of year this is. The
correction needed depends on knowing the season ahead, which is precisely the
unpredictable thing. A mapping fitted on other years imports the wrong
correction.

### So the product leads with the range, not the probability

The continuous p10-p90 band is calibrated (79.9% against 80%) and stable in every
individual year (0.70 to 0.91). The binary probability beats climatology on
average but its errors are year-dependent and irreducible.

**"You will need 8 to 24 mm/week" is trustworthy in a way that "94% chance of
stress" is not.** Show the range.

### What this does NOT prove

Truth and forecast share the same soil model. If the FAO-56 bucket misjudges when
a real Connecticut field runs dry, both are wrong together and this verification
reports success anyway. Closing that gap needs field soil-moisture sensors, which
this project does not have. **This validates the handling of weather uncertainty,
not the soil physics.**

## Splitting drought into two questions

Every model above asked one question: what will the drought stage be in 30 days?
That forces one set of features to answer two things that are not alike.

| | depends on | how predictable |
| --- | --- | --- |
| **will there be a drought?** | future rainfall | poor - skill ends at 3 days |
| **how bad will it be?** | current storage | good - we measure it today |

So estimate them separately and combine.

```bash
uv run ctwater factored
```

### Both halves work

**Stage 1 - occurrence, from rainfall alone:**

| | AUC | Brier | skill |
| --- | --- | --- | --- |
| model | **0.889** | 0.0687 | **+0.128** |
| climatology | 0.503 | 0.0788 | - |

**Stage 2 - severity, from soil, streamflow, aquifer and terrain alone:**

| record | drought episodes | months in training | skill vs predict-the-mean |
| --- | --- | --- | --- |
| 25-year Drought Monitor | 6 | ~50 | **+11.6%** |
| **130-year climate divisions** | **18** | **392** | **+42.7%** |

**The 25-year result was not a weak signal, it was a starved one.** Severity
given drought is strongly predictable from accumulated storage once there are
enough droughts to learn from - and it holds across all six folds spanning
different eras.

On the long record the storage variables are Palmer PHDI (which tracks
reservoirs and groundwater rather than topsoil) and the SPI 6/12/24-month
deficit ladder - the century-scale equivalents of soil moisture, streamflow and
aquifer level.

### The combination rule was wrong, and it cost 35 points

| | MAE |
| --- | --- |
| factored, **mean rule** | 0.4242 |
| factored, **median rule** | **0.3163** |
| monolithic | 0.3089 |
| persistence | 0.2837 |

`P x severity + (1-P) x calm` is an expected VALUE. **MAE is minimised by the
MEDIAN.** With 92% of rows drought-free that product spread probability mass
onto intermediate values like 0.6 that are nobody's actual outcome.

The hurdle model implies a real two-part distribution, and its median has a
closed form:

    F(m) = (1-P) F_calm(m) + P F_drought(m) = 0.5

    P < 0.5   ->  calm quantile 0.5/(1-P)          slides up as P grows
    P >= 0.5  ->  severity estimate offset to drought quantile (P-0.5)/P

Both agree at P = 0.5, so the prediction stays continuous. Fixing this took the
gap from **-37.3% to -2.4%**.

This is the third appearance of the same mistake in this project - optimising or
combining for the mean while scoring the median. It cost the rainfall model 11%
against climatology until its objective was switched to L1.

### The verdict: right analysis, not a better score

The factored model ties the monolithic one and neither beats persistence. But
splitting was still worth it for two reasons that are not accuracy:

**The output is actually usable.** "Expected stage 0.6" means nothing to a
farmer. "70% chance of drought, and D2 if it arrives" is a decision.

**Each stage can use the best data for its own question.** Occurrence needs farm
resolution and gets it from 25 years of daily rainfall. Severity needs droughts
and gets 18 of them from 130 years. A single model cannot draw on both records
at once; a factored one can.

## The same split on the wet side: drought severity is in the ground, flood severity is in the sky

The median rule was applied to the wet side too. The wet CLASSIFIER does not have
a mean-versus-median problem - it emits a probability, and a probability has no
median to get wrong. But storm rarity does, and worse than anything on the dry
side:

| target | skew |
| --- | --- |
| dry: `y_stage` | 2.0 |
| **wet: storm return period** | **58.5** |

So the same question was asked: *how rare will the worst storm in the next 30
days be, at this farm?* - split into occurrence and severity exactly as drought
was.

### The median rule transfers, but the objective matters more

| combination rule | MAE |
| --- | --- |
| **median of the mixture** | **0.3482** |
| expected value | 0.3670 |

**+5.1% for the median** - real, but far short of the 35 points it was worth on
the dry side.

| monolithic objective | MAE |
| --- | --- |
| **L1 (median)** | **0.3292** |
| L2 (mean) | 0.3945 |

**+16.6% for L1.** With a skew of 39, simply telling the model to optimise
absolute error beat every structural change.

### The wet decomposition fails, and that is the finding

| stage | dry | wet |
| --- | --- | --- |
| occurrence AUC | **0.889** | 0.737 |
| **severity vs predict-the-median** | **+42.7%** | **-13.3%** |

Wet severity is *worse* than predicting the median. Soil moisture, streamflow,
groundwater, height above drainage and flood rating carry essentially nothing
about how rare the worst storm of the next month will be.

That is not a modelling failure. It is the clearest statement of the asymmetry
this project keeps meeting:

> **Drought severity is written in the ground. Flood severity is written in the
> sky.**

How bad a drought gets depends on what is left in storage - aquifer, subsoil,
streamflow - all measured today. How bad a flood gets depends on how large the
next storm happens to be, which is atmospheric chance. No amount of ground
measurement anticipates it.

The decomposition is right for both hazards; it simply has opposite answers.

### And on the wet side nothing beats climatology

| | MAE |
| --- | --- |
| **climatology** | **0.3239** |
| monolithic L1 | 0.3292 |
| factored, median rule | 0.3482 |
| persistence | 0.5308 |

Persistence is dramatically worse - **storms do not cluster the way droughts
persist**, the same asymmetry arriving from the other direction.

## Stop predicting rainfall. Use the records that already exist.

The forecast never predicted rain - it replays real past years. That makes the
LENGTH of the record the binding constraint, and three sources were pulled to
attack it.

| source | resolution | span | ensemble members |
| --- | --- | --- | --- |
| NOAA AORC | 1 km grid | 2000-2024 | 24, at every farm |
| GHCN-Daily | point stations | up to 122 yr | 54 median, only near a gauge |
| nClimGrid-Daily | 4.6 km grid | 1951-2026 | 74, at every farm |

nClimGrid is gridded AND long, so it is the one that scales. PRISM was considered
and rejected on fit, not quality: PRISM daily starts in 1981 (30 fewer years) and
PRISM monthly cannot serve an analog ensemble at all, because the ensemble lives
on day-by-day SEQUENCING.

### Subsetting server-side turned 53 GB into 85 MB

The monthly CONUS files are 58 MB each and 1951-2024 is about 900 of them. NCEI
serves them over OPeNDAP, and Connecticut is 0.16% of each grid, so only that
window crosses the network. 2.9 seconds per month.

### What the depth buys: different weather, not more of the same

| driest reachable year | modern record only | with nClimGrid |
| --- | --- | --- |
| 1st | 2016, 918 mm | 1965, 754 mm |
| 2nd | 2001, 981 mm | 1964, 855 mm |

1965 is 18% drier than anything since 2000. An earlier diagnosis in this project
was that the 2015-2018 fold failed exactly when it met a drought larger than its
training data. The ensemble now contains one.

### A caveat I got backwards

I flagged that the early gridded years would rest on a thinner station network.
The opposite is true - the cooperative observer network peaked mid-century:

| era | stations reporting |
| --- | --- |
| 1950s | 36 |
| 1970s | 33 |
| 1990s | 29 |
| 2020s | 20 |

### Result: better Brier, slightly over-wide range

| | Brier | p10-p90 coverage | says 90%+ happens |
| --- | --- | --- | --- |
| 24-member | 0.1546 | 80.0% | 91% |
| 74-member | 0.1453 | 86.4% | 91% |

Brier improves 6%. But 80.0% coverage was already essentially perfect against an
80% target, and 86.4% means the range is now WIDER than it needs to be. The
deeper ensemble traded slight over-confidence for slight over-hedging. Safer for
a warning system, but no longer optimally calibrated, and worth saying rather
than calling 86.4% an improvement on 80%.

### The obvious fix for that over-width does not work

The ensemble replays 74 past years and, until now, counted every one equally -
treating 1965 and 2019 as equally informative about the month ahead. The
atmospheric reanalysis makes it possible to weight them: score each past year by
how closely its atmosphere over the preceding fortnight resembled today's, and
let similar years count for more. Concentrating the ensemble that way should pull
the too-wide range back toward 80%.

It was worth expecting to work, because the same atmospheric predictors DO
improve a rainfall regression - they carry 18% of that model's gain over
climatology at 7 days. Scored across six years of real outcomes:

| weighting | effective members | Brier | p10-p90 coverage |
| --- | --- | --- | --- |
| **none** | 66.0 | **0.1453** | 87.5% |
| gentle (1.0) | 64.0 | 0.1455 | 87.5% |
| sharper (0.3) | 50.3 | 0.1465 | 87.2% |
| aggressive (0.1) | 17.5 | 0.1550 | 84.7% |

**Brier degrades monotonically as the weighting sharpens**, and the coverage it
buys is negligible - 87.5% to 84.7%, still well above target - at the cost of
collapsing the effective ensemble from 66 members to 17.5.

The negative result is more interesting than a win would have been. Predicting
*how much rain falls* and choosing *which past year to replay* are different
problems. The first asks the atmosphere to nudge an amount; the second asks it to
match a whole 30-day sequence at one farm, which is a far stronger claim - and
the atmosphere cannot support it. Weighting is implemented, measured, and off by
default; `member_weights` still accepts weights if a future predictor set earns
them.

The over-width therefore stands unfixed. Erring wide is the safer direction for a
warning system, but it is a known miscalibration, not a design choice.

## Watersheds: right idea, wrong place to apply it

Farms were assigned to USGS watersheds - 10 HUC8 subbasins hold the 200 farms -
and the pipeline reordered to partition first, then train.

Measured before fitting anything, basins separate CLIMATE but not LAND:

| variable | between-basin / within-basin |
| --- | --- |
| soil capacity | 0.26 |
| slope | 0.34 |
| 2-year storm depth | 1.10 |
| annual rainfall | 1.02 |

A subbasin holds both floodplain and hillside, so partitioning gives homogeneous
weather, not homogeneous ground.

Per-basin drought training lost: 1 of 8 basins helped, overall -5.3%, and the
loss tracked basin size almost monotonically (Outlet Connecticut River, 40 farms:
+1.3%; Farmington, 13 farms: -13.2%). The same statewide droughts hit every
basin, so splitting divides the farms without creating a single new event.
Watershed belongs as a feature, not a partition.

### But it exposed a real bug

Stream gauges were assigned by DISTANCE, which is hydrologically wrong - a gauge
across a drainage divide measures a different river system however close it is.

| | in-basin gauge pairs | farms with no in-basin gauge |
| --- | --- | --- |
| before | 66% | 10% |
| after | 98% | 2% |

By basin it was worse than the average suggests: 0% in-basin for Long Island
Sound farms, 28% for the Thames. Nearly three quarters of those farms streamflow
signal was measuring a river they do not drain into.

## MRMS: measuring what the daily approximation costs

Every flood judgement here rests on DAILY rainfall, while Atlas 14 says 34% of a
10-year day's rain can fall in a single hour. NOAA's MRMS publishes recurrence
intervals on a 1.1 km grid every two minutes, at 30-minute through 24-hour
durations - so it can measure that gap rather than leaving it assumed.

It is not another ensemble source: the archive starts 2020-10-15, six years
against nClimGrid's 74, and 720 files a day is 130 GB. So it was pulled for the
37 Connecticut flood days inside the archive plus 40 month-matched controls.

### The result was negative, and the reason is the useful part

| measure | AUC | median on flood days | on other days |
| --- | --- | --- | --- |
| daily (Atlas 14) | 0.787 | 0.82 | 0.39 |
| sub-daily (MRMS) | 0.680 | 0.00 | 0.00 |

My first explanation was that the label's 20 km attribution radius cannot resolve
a 1.1 km signal. Tightening it confirmed the radius matters and did NOT explain
the gap:

| radius | daily AUC | MRMS AUC | flood cell-days |
| --- | --- | --- | --- |
| 20 km | 0.787 | 0.680 | 1,437 |
| 10 km | 0.843 | 0.764 | 530 |
| 5 km | 0.879 | 0.800 | 154 |
| 3 km | 0.889 | 0.802 | 60 |
| 2 km | 0.876 | 0.741 | 26 |

Both improve as the radius tightens - the **third** confirmation that 20 km is
the binding constraint on every fine-resolution flood feature, after it hid the
NRCS flood ratings and the 3DEP terrain. But MRMS trails at every radius.

### The actual cause: our "daily" measure is a fortnight

`rain_ari_years` is built from `max_1day_mm`, which is a **14-day rolling
maximum**. It stays elevated for two weeks after any storm - above zero on 93% of
days against MRMS's 7%, and correlated only 0.29 with same-day rainfall.

So the comparison was *"was there a rare storm in the last two weeks"* against
*"was today's storm rare"*, and the first won. That is not sub-daily losing to
daily; it is a windowed measure beating an instantaneous one at a task that
rewards windows, because flood reports cluster around stormy periods.

A fair test needs MRMS as a 14-day rolling maximum, which requires continuous
coverage rather than 77 targeted days - a different undertaking that wants a
clearer reason first.

**What this delivers:** a measured answer that the daily approximation is
defensible for the label we have. The cost of daily resolution is not
demonstrable at 20 km attribution, and even at 2 km only 26 flood cell-days
remain to test on.

## Atmospheric reanalysis: it helps, and I cannot explain why

The rainfall model's skill ended at 3 days, and its own docstring said why that
was not a fact about the atmosphere - it had no pressure, no wind, no upper-air.
NCEP/NCAR Reanalysis 1 supplies those: daily 500 hPa height and precipitable
water on a 2.5 degree grid, 1948-2026, matching nClimGrid's era.

Three regions, kept separate because a ridge over Connecticut and a ridge over
the Atlantic mean opposite things for rainfall:

| region | box | what it is |
| --- | --- | --- |
| local | 38-45N, 75-65W | over the farms |
| upstream | 35-50N, 100-80W | where tomorrow's weather is now |
| atlantic | 28-40N, 70-55W | the Bermuda High |

ERA5 would be better - 0.25 degrees against 2.5 - but Copernicus requires a
registered API key that cannot be created here. For synoptic features at
thousand-kilometre scale, 2.5 degrees resolves them fine and NCEP's 1948 start is
worth more than ERA5's finer grid. The NCAR AWS mirror is the upgrade path.

### It works

| horizon | features | MAE vs climatology | AUC wet/dry |
| --- | --- | --- | --- |
| 7 day | rain only | +1.2% | 0.552 |
| 7 day | **rain + atmospheric** | **+4.4%** | **0.589** |
| 30 day | rain only | -6.1% | 0.571 |
| 30 day | **rain + atmospheric** | **-3.0%** | **0.583** |

At 7 days the model stops tying climatology and beats it. At 30 days it still
loses, but the deficit halves. The atmospheric predictors carry **18.2% of the
model's gain**.

### And the physical story failed its own test

The module includes a check on the obvious mechanism - ridging over Connecticut
means sinking air and no rain. On the four summers that matter:

| predictor | 2016 dry | 2022 dry | 2021 wet | 2023 flood |
| --- | --- | --- | --- | --- |
| `hgt500_local` | +9.3 | +7.3 | **+34.2** | -17.8 |
| `hgt500_upstream` | +20.3 | +13.5 | **+25.1** | -1.5 |
| `hgt500_atlantic` | +10.4 | +14.7 | **+26.8** | -0.0 |

**The wet summer has the strongest ridging on every measure.** Not one predictor
separates droughts from wet years on its own.

So these features improve prediction and the reason is not established. The
likely explanation is that ridge POSITION matters rather than amplitude - a ridge
whose western flank sits over Connecticut brings southerly flow and moisture,
which a regional average cannot express - but that is a hypothesis, not a
demonstration.

Four summers cannot disprove a mechanism, so this is *unexplained* rather than
*refuted*. But an 18% contribution nobody can account for deserves suspicion
rather than satisfaction, given this project has four times found that an
unexplained-yet-plausible result was a bug.

## Train on New England, predict Connecticut - the first thing to beat persistence

Persistence - "next month's drought stage equals this month's" - has been the
unbeatable baseline throughout this project. The farm model lost to it by 0.046,
the 130-year Connecticut model by 0.127, the factored model by more. Every
architectural change failed against it.

Training on the surrounding region beats it.

| training set | rows | MAE on CT | vs persistence | folds won | AUC |
| --- | --- | --- | --- | --- | --- |
| CT only | 4,239 | 0.7589 | -0.0495 | 1/6 | 0.943 |
| + MA, RI | 9,891 | 0.7267 | -0.0174 | 3/6 | 0.947 |
| **+ NY, NH** | 26,847 | **0.6897** | **+0.0196** | **5/6** | **0.956** |
| all New England | 35,325 | 0.6918 | +0.0176 | 5/6 | 0.953 |

Always **evaluated on Connecticut**, in identical folds. Only the training set
changes, so a larger region cannot be flattered by being scored on easier rows.
Folds won climbs 1 to 3 to 5, and the best tier's worst fold is essentially a tie
(-0.0064) where CT-only's worst is a rout (-0.1389).

### Why this works where partitioning by watershed did not

The two are mirror images, and the difference is EVENTS.

Splitting Connecticut by watershed lost - 1 of 8 basins helped, -5.3% overall -
because it subdivided the same droughts among fewer farms. Rows down, events
constant.

Expanding outward adds droughts Connecticut never had:

| state | correlation with CT | drought months not shared with CT |
| --- | --- | --- |
| MA | 0.88 | 30% |
| RI | 0.81 | 41% |
| NY | 0.67 | 46% |
| NH | 0.64 | **68%** |
| VT | 0.60 | **71%** |
| ME | 0.55 | 63% |

**Pooled New England holds 394 drought months against Connecticut's 147 - 2.7x
the events.** Events have constrained every drought result in this project; rows
never were the constraint.

### The gain saturates rather than reversing

The obvious worry is domain shift - a Maine drought need not behave like a
Connecticut one, so at some radius extra events should start hurting. They do
not: `+NY,NH` and all-New England are indistinguishable (4 of 6 folds apart, mean
difference 0.0021).

So there is no similarity/quantity frontier to find. The default stops at NY and
NH because that is the smallest set achieving the full gain, not because Vermont
and Maine were shown to hurt.

### Scope

This expands the **climate-division** model - the 130-year monthly PDSI record
that exists for every New England state. It does **not** expand the per-farm
forecast, because only Connecticut has parcels, soil surveys and terrain here.

It transfers the way the factored model already does: train the drought stage
where the events are, apply it at Connecticut farm resolution. Extending the farm
product itself would mean pulling parcels, SSURGO and cropland for five more
states.

## Connecticut's own drought rule - the target we should have had

Sources: the [CT Drought Preparedness and Response Plan (2022)](https://portal.ct.gov/-/media/water/drought/ct_state_drought_plan_2022-09-06.pdf),
the [CT Interagency Drought Workgroup](https://portal.ct.gov/Water/Drought/Interagency-Drought-Workgroup),
[NIDIS Connecticut](https://www.drought.gov/states/connecticut),
the [U.S. Drought Monitor](https://droughtmonitor.unl.edu/), and the
[Northeast DEWS dashboard](https://nedews.nrcc.cornell.edu/).

**This project has been predicting the wrong thing.**

The U.S. Drought Monitor's own documentation says *"the map is made by people, not
computers"* - four agencies rotate authorship, blending indices with local
reports and expert judgement. It is a considered human product.

Connecticut does not act on it. Connecticut acts on its **own declarations**, and
those are what reach a farmer: the Governor declares a stage, and restrictions
follow. Unlike the Drought Monitor, that rule is written down and is arithmetic.

| stage | precipitation | groundwater | streamflow | reservoirs | PDSI | USDM |
| --- | --- | --- | --- | --- | --- | --- |
| 2 | 2-month total < 65% of avg | 2 of 3 months < 25th pct | 2 of 3 months < 25th pct | < 80% | -2.0 to -2.99 | D1-D2 |
| 3 | 3-month < 65% | 4 consecutive < 25th | 4 of 5 < 25th | < 70% | -3.0 to -3.99 | D2-D3 |
| 4 | 5-month < 65% | 6 consecutive < 25th | 6 of 7 < 25th | < 60% | -4 or less | D3-D4 |
| 5 | 7-month < 65% | 8 consecutive < 25th | 7 consecutive < 25th | < 50% or < 50 days | -4 or less | D4 |

**We already hold five of the eight indicators** - precipitation, groundwater,
streamflow, PDSI, and the Drought Monitor itself. Missing are reservoir storage
(utility-held), Crop Moisture Index / VegDRI, and fire danger.

### It reproduces what the state actually declared

| period | the rule computes | Connecticut declared |
| --- | --- | --- |
| 2016 drought | Stage 2, 3 of 6 months | Stage 2 |
| 2020 drought | Stage 2, 1 of 5 months | Stage 2, four counties |
| 2022 drought | Stage 2, 2 of 5 months | Stage 2, all eight counties |

Six Stage-2 months since 2016 and never Stage 3+, matching the record.

### Why this target suits what the models are actually good at

Every criterion is **persistence of a low percentile** - "N of M months below the
25th". Persistence has been the unbeatable baseline throughout this project
precisely because drought state persists. The official rule is built on the one
thing the models do best, rather than on a stage level they have never beaten
persistence at predicting.

It is also **county-resolved** - June 2026's Stage 2 covered Fairfield, Middlesex
and New Haven only - a resolution the per-farm data already exceeds.

⚠️ The plan says a declaration is "guided by" these thresholds "as well as any
other ancillary data", and the workgroup votes. This is evidence a committee
weighs, not a formula that fires by itself.

### Trained on it, and the hypothesis was wrong

The claim above - that a rule built on persistence suits models that are good at
persistence - was testable, so it was tested. Both targets, identical folds,
identical features, each against its own baselines.

FIRST ATTEMPT, AS A NUMBER TO REGRESS. The Connecticut target looked better:
MAE 0.1115 against USDM's 0.3085. That number is void. The CT stage sits at 0
for 96% of farm-months, and a constant zero scores 0.0658 - beating both the
model and persistence. Absolute error was rewarding rarity, not skill.

SECOND ATTEMPT, AS AN EVENT. P(stage >= 2 within 30 days), scored three ways:

| target | base | Brier | vs climatology | vs persistence 0/1 | **vs calibrated persistence** | AUC | lift |
| --- | --- | --- | --- | --- | --- | --- | --- |
| USDM >= 2 | 0.081 | 0.0500 | +34.4% | +14.1% | **-5.8%** | 0.930 | 7.3x |
| CT >= 2 | 0.032 | 0.0390 | **-25.5%** | +9.4% | **-36.7%** | 0.864 | 4.5x |

The third baseline decides everything, and it is the one that is easy to leave
out. Scoring persistence as a hard 0/1 makes it maximally confident, so Brier
punishes it fully whenever it is wrong. Against that strawman BOTH targets look
like wins (+14.1%, +9.4%). Against persistence expressed honestly - the historical
P(event in 30 days | today's stage), fit on training folds only - BOTH LOSE.

And the Connecticut target loses to a plain constant by 25.5%. Under the correct
loss function, on the correct framing, the model is worse than announcing "3.2%,
every farm, every month, forever."

### Why the reasoning was backwards

The rates the calibrated baseline learned explain it:

| target | P(event \| at stage now) | P(event \| below now) | ratio |
| --- | --- | --- | --- |
| USDM | 0.690 | 0.046 | 15x |
| Connecticut | 0.425 | 0.022 | **19x** |

Persistence discriminates the Connecticut target MORE sharply, not less. The
earlier AUC reading that suggested otherwise - persistence at 0.649 on CT versus
0.899 on USDM - was an artifact of the same 0/1 encoding: a binary forecast can
only produce a two-level ranking, which mechanically caps AUC on a rare event. It
never showed that persistence was uninformative there.

The mechanism was inverted from the start. Connecticut's criteria are windows of
two to seven months. **Most of the window that decides next month's stage has
already happened.** A rule built out of long persistence windows is therefore
maximally predictable BY PERSISTENCE and minimally improvable by a model - the
only thing left to forecast is the marginal new month, which is future rainfall,
the least predictable input there is. "Built on persistence" advantages the
BASELINE, not the model.

This was flagged as a risk before the run - "if it is more predictable for that
reason, persistence should also predict it better, so the margin might not
improve even as raw accuracy does." It did not merely fail to improve. It got
worse.

### What this changes

**USDM stays the modelling target.** It is the only one of the two the model is
competitive on (-5.8% is near parity, with AUC 0.930 and 7.3x precision lift over
the base rate).

**Connecticut's rule stays, as a translation layer rather than a target.** It is
still the thing that reaches a farmer, and it is still computable per farm rather
than per county. The right architecture is the one the state already uses:
compute the stage from indicators rather than predicting the stage directly. That
means forecasting the INPUTS - precipitation percentiles, groundwater, streamflow
- and running Connecticut's arithmetic on the forecast inputs. Regressing a
discontinuous threshold directly was the error.

## Forecasting the inputs instead of the stage

`ct_relay.py` does what the state does: compute the stage from indicators rather
than predict it. Precipitation for the target month comes from an ensemble - the
same calendar month replayed from each of 74 past years of nClimGrid - and
Connecticut's arithmetic runs on every member, so the output is the FRACTION of
replayed years that would have triggered Stage 2. That is a probability with an
explanation attached: "31 of 74 past Julys would have put you in Stage 2."

Forecasts are issued at month end for the next full calendar month, because a
30-day window starting mid-month covers no calendar month completely.

32,592 farm-months, 2010-2023, scored against the same baselines as the direct
model:

| | Brier | vs climatology | vs persistence 0/1 | **vs calibrated persistence** | AUC |
| --- | --- | --- | --- | --- | --- |
| relay, 10 members | 0.0420 | +8.9% | +27.1% | -6.0% | 0.767 |
| relay, 25 members | 0.0395 | +14.4% | +31.5% | **+0.4%** | 0.787 |
| relay, 74 members | 0.0397 | +13.9% | +31.1% | **-0.2%** | 0.795 |
| calibrated persistence | 0.0397 | +14.0% | +31.2% | 0.0% | 0.682 |
| direct regression | 0.0390 | -25.5% | +9.4% | -36.7% | 0.864 |

⚠️ The direct-regression row is from a DIFFERENT evaluation set - model-table dev
folds, base rate 0.032 - so the exact deltas are not comparable. The qualitative
gap, catastrophic loss versus parity, is.

**The architecture change fixed the failure and did not create a win.** The
direct model lost to calibrated persistence by 36.7% and lost to a plain constant
by 25.5%. The relay is level with calibrated persistence and beats the constant.
It recovers the skill the direct model threw away. It does not add skill beyond
persistence.

**74 members buys nothing over 25.** Ten is clearly too few (-6.0%), 25 is the
whole gain, and 74 is fractionally worse. The deep record matters for the
same-month NORMALS, not for ensemble depth. (Available members averaged 65.6, not
74, because the reference period consumes years.)

### The sensitivity check fired, and it is the real finding

Groundwater and streamflow are persisted rather than forecast. `persistence_sensitivity`
exists to measure what that assumption is worth instead of asserting it is small:

| last observed supply value shifted | mean P(Stage 2) |
| --- | --- |
| -1.0 sd | 0.083 |
| -0.5 sd | 0.083 |
| unchanged | 0.078 |
| **+0.5 sd** | **0.000** |
| +1.0 sd | 0.000 |

Not a gradient - a cliff. Nudge groundwater and streamflow up by half a standard
deviation and the stage probability collapses to zero for every farm tested,
because Connecticut's rule requires ALL available indicators to agree. If the
supply indicators are not below their 25th percentile, no amount of forecast
rainfall can trigger a stage. **The rainfall ensemble only matters once the
supply gate is already open.**

Two things amplify this. The conjunction is a hard gate by design. And the last
observed value counts TWICE in every window - once as the most recent observation
and again as the assumed value for the target month - so the persistence
assumption has double leverage over the outcome.

That explains the parity result mechanically. The relay ties calibrated
persistence because, structurally, it largely IS a persistence forecast: today's
groundwater decides whether a stage is possible at all, and the rainfall ensemble
only modulates the probability inside that gate. This is the failure mode the
check was written to detect, and it detected it.

### Calibration is off at both ends

| forecast | n | predicted | observed |
| --- | --- | --- | --- |
| 0.00-0.05 | 28,408 | 0.001 | **0.020** |
| 0.05-0.15 | 1,159 | 0.096 | 0.115 |
| 0.15-0.30 | 1,297 | 0.221 | 0.180 |
| 0.30-0.50 | 1,034 | 0.392 | 0.331 |
| 0.50-1.01 | 694 | 0.585 | **0.403** |

Overconfident at the top - "58%" happens 40% of the time - and far too absolute at
the bottom, where 87% of all forecasts live: it says essentially zero and the
event occurs 2% of the time. For a warning system the bottom bin is the dangerous
one, because that is the bin a farmer would read as "nothing to prepare for".

### Forecasting the supply indicators instead of persisting them

`supply.py` fits `next = alpha * current + beta * rain_share + gamma` for each
indicator, pooled across farms, on months strictly before the evaluation period.
Each ensemble member then drives its own groundwater and streamflow from its own
rainfall, so the gate opens and closes member by member.

| indicator | alpha | beta | residual sd | R2 | persisting |
| --- | --- | --- | --- | --- | --- |
| groundwater | 0.814 | 0.234 | 0.376 | 0.665 | 0.576 |
| streamflow | 0.810 | 0.295 | 0.257 | 0.748 | 0.606 |

Both beat persisting, and rainfall earns its place - it adds R2 beyond what this
month's level already explains (+0.043 and +0.104).

**And feeding those fits into the rule made the forecast WORSE.**

| | Brier | vs climatology | vs calibrated persistence | AUC | mean P |
| --- | --- | --- | --- | --- | --- |
| supply persisted | **0.0395** | +14.4% | +0.4% | 0.787 | 0.0344 |
| supply forecast (point) | 0.0412 | +10.7% | -3.9% | 0.731 | 0.0314 |
| supply forecast + spread | 0.0399 | +13.6% | -0.6% | **0.801** | 0.0311 |
| calibrated persistence | 0.0397 | +14.0% | 0.0% | 0.682 | 0.0304 |
| OBSERVED | | | | | **0.0477** |

Least squares returns the CONDITIONAL MEAN, and alpha below 1 shrinks it toward
normal. That is the right answer for the level and the wrong input to a
percentile threshold: a shrunken estimate crosses the line less often than
reality does. Persisting never hit this because persisting never shrinks. Good R2
bought nothing, because fitting better in the middle is irrelevant to a question
that only asks about the tail.

### The fix worked. The reason given for it was wrong.

Carrying the residual spread - expanding each rainfall member across nine
residual quantiles - recovered nearly all the loss (0.0412 to 0.0399) and gave
the best discrimination of anything tried (AUC 0.801, against 0.787 persisted and
0.682 for calibrated persistence).

But the prediction made for WHY it would work was that spread would fix the
under-calling. **It did not.** Mean P went 0.0314 to 0.0311 - if anything slightly
lower. Symmetric spread around a shrunken centre adds variance without removing
the bias in that centre. It helped through a different route: more spread means
finer gradations between farms, which is discrimination, not calibration.

### Every method under-calls, which is not a model problem

Mean predicted P(Stage 2) is 0.0344 persisted, 0.0311 with spread, 0.0304 for
calibrated persistence - against an observed **0.0477**. Everything under-calls by
30-40%, INCLUDING the baselines.

The cause is the reference period. Percentiles and normals are fit before 2010 as
a leakage guard, and the pre-2010 event rate is 0.0205 against 0.0477 in
2010-2023. The evaluation era is more than twice as droughty as the era the
thresholds were calibrated on, so a "25th percentile" fixed on 2000-2010 fires
too rarely afterwards. That is climate non-stationarity meeting a fixed-baseline
rule, and it would affect Connecticut's own declarations the same way.

VERDICT: forecasting the supply indicators is a wash on Brier and a real if
modest win on ranking. Keep persisting as the default; use the spread variant
where the job is deciding WHICH farms to warn rather than stating an absolute
probability.

### The under-warning was one year, not a broken baseline

The claim that a fixed pre-2010 reference caused systematic under-warning was
wrong, and checking it before acting is what caught it. **2016 is 84% of the
entire shortfall on 7% of the rows.** Excluding it, the relay predicts 0.0247
against an observed 0.0275 - calibrated across the other thirteen years. Widening
the reference window would have moved every threshold to chase a problem living
in one year.

⚠️ The stated reason was also backwards. If the reference era were WETTER than the
evaluation era, evaluation months would fall below a stale 25th percentile MORE
often, not less - that over-fires. "Stale baseline" never explained under-warning.

### What the diagnostic actually found: a lag

| storage trend | error from persisting |
| --- | --- |
| falling fast | **+0.229 sd too wet** |
| falling | +0.091 |
| flat | -0.006 |
| rising | -0.113 |
| rising fast | -0.193 sd too dry |

Monotone. Persisting does not report today's water - it reports LAST month's,
which during a fall is more water than will actually be there. In 2016 May-Sep,
momentum was -0.414 and the persistence error +0.394: Connecticut's gate stayed
shut through the drought's onset because the indicator feeding it was reporting
water that had already drained.

That also explains why forecasting made things worse. Alpha of 0.81 shrinks
toward normal, so a fitted model lags HARDER than persistence exactly when
storage falls - replacing a lagging input with a more-lagging one.

Adding last month's change fixes the fit. Both terms are observed, so it is known
at forecast time:

| indicator | alpha | beta | **delta** | R2 | persisting | without momentum |
| --- | --- | --- | --- | --- | --- | --- |
| groundwater | 0.705 | 0.204 | **0.508** | **0.761** | 0.574 | 0.664 |
| streamflow | 0.777 | 0.288 | 0.163 | 0.757 | 0.605 | 0.748 |

| | Brier | vs calibrated persistence | AUC | mean P |
| --- | --- | --- | --- | --- |
| supply persisted | **0.0395** | +0.4% | 0.787 | 0.0344 |
| supply forecast | 0.0409 | -3.1% | 0.754 | 0.0334 |
| forecast + spread + momentum | 0.0397 | -0.0% | **0.809** | 0.0325 |
| calibrated persistence | 0.0397 | 0.0% | 0.682 | 0.0304 |
| OBSERVED | | | | **0.0477** |

### And it did not fix 2016, for a reason worth knowing

2016 moved from 0.1140 to 0.1158 against an observed 0.3097. A large fit
improvement bought 0.0018 of forecast. Counting how many members passed each
criterion separately says why:

| 2016 growing season | pass rate |
| --- | --- |
| **precipitation test** | **21.1%** |
| supply gate | 55.7% |
| both, i.e. Stage 2 | 12.1% |
| observed | **31.0%** |

**The supply gate was never binding.** It passed on 55.7% of farm-months while
precipitation passed on 21.1%, so momentum improved the constraint that was
already loose. Only a fifth of replayed years were dry enough to satisfy the
precipitation criterion, because 2016 was drier than roughly 79% of the historical
record for those months.

That is not a fixable modelling gap. The ensemble replays real past months, and
this project already measured that rainfall skill decays to nothing by day 8. A
30-day rainfall forecast can only be climatological, and a climatological ensemble
under-calls a record drought BY CONSTRUCTION - it cannot concentrate on an outcome
history barely contains.

⚠️ **For a warning system this is the worst failure mode to have**, because it
means the system is least reliable exactly when it matters most. It should be
stated to farmers plainly rather than buried: this forecast under-warns in record
droughts.

VERDICT: keep persisting for absolute probabilities (best Brier, 0.0395); use
forecast + spread + momentum for RANKING which farms to warn (best AUC, 0.809,
against 0.682 for calibrated persistence). Neither fixes 2016.

### What this says to build next

The binding constraint is not rainfall. It is groundwater and streamflow, which
are currently persisted. Forecasting THOSE - they are slow, autocorrelated, and
therefore the most forecastable things in the system - is what would move the
result, and it is the opposite of where the effort has gone so far.

### A corroboration worth noting

The Northeast DEWS operates over **New England plus New York** - exactly the
region just measured to beat persistence on Connecticut drought. The official
early-warning system already works at the scale the data says is right.

## Two stages: the drought, then the farm

The old design ran weather and soil through ONE calculation, so a farm that
happened to start wet returned a low probability even while a drought built. The
verification caught it precisely: 489 forecasts said 19%, stress arrived 41% of
the time, and they were the WETTEST farms - soil at 63% of capacity against 28%
elsewhere - in the three drought years. The buffer was hiding the hazard.

They are different questions:

    HAZARD  will the atmosphere deliver a drought?   regional, farm-free
    IMPACT  what does that drought do to THIS farm?  soil, crop, current wetness

`hazard.py` answers the first from temperature, humidity, wind and rainfall and
never sees a farm. `impact.py` meters that answer through one farm's soil bucket.
Wetness can now change HOW LONG a farm holds out, never WHETHER a drought is
coming.

### It fixes the failure it was built for

| version | says | happens | gap |
| --- | --- | --- | --- |
| old, one stage | 0.194 | 0.405 | **+0.211** |
| **split, two stages** | **0.360** | 0.405 | **+0.045** |

**The gap closed by 79%.** And the headline metric improves rather than trading
against it:

| | Brier | vs old | irrigation MAE | mean P |
| --- | --- | --- | --- | --- |
| old, one stage | 0.1464 | - | 5.05 | 0.661 |
| **split, two stages** | **0.1415** | **+3.3%** | **4.95** | 0.683 |
| observed | | | | 0.704 |

By year the split moves toward the truth in every drought year - 2015 0.752 to
0.774 against an observed 0.900, 2016 0.733 to 0.756 against 0.905, 2020 0.660 to
0.679 against 0.882 - at the cost of slightly more over-warning in the calm ones
(2018 0.517 to 0.536 against 0.370). That trade is worth taking for a warning
system, and the Brier says it is a net gain rather than a wash.

⚠️ It does NOT fix the drought years outright. 2015 still forecasts 0.774 against
an observed 0.900. The remaining shortfall is the 30-day rainfall limit
documented above, which no architecture reaches.

### Humidity and wind: fetched, correct, and the mechanism does not operate here

74 years of near-surface relative humidity and 10 m wind now sit in
`reanalysis_surface.parquet` (27,029 days, no gaps), enabling FAO-56
Penman-Monteith demand instead of the temperature-only Hargreaves estimate.

The expectation was that thirsty air would reveal drought-year stress temperature
alone cannot see. **It does not, in this climate.**

| year | temp-only | Penman-Monteith | difference | RH% |
| --- | --- | --- | --- | --- |
| 2016 (drought) | 4.59 | 3.69 | -0.89 | 80.9 |
| 2018 (wet) | 4.46 | 3.51 | -0.94 | 83.5 |
| all years | 4.42 | 3.46 | -0.96 | |

Penman-Monteith is uniformly LOWER, by a near-constant amount, and the two
correlate at 0.949. Connecticut averages 81-83% humidity and even 2016 only fell
to 80.9%; the parched, windy conditions where the two methods diverge sharply
(25% RH, 8 m/s gives 10.4 mm/day against 4.8 for humid and still) essentially do
not occur here at regional scale - the driest daily mean in 74 years was 49%.
Hargreaves is known to over-predict in humid climates, and this is that.

⚠️ **Whether Penman-Monteith is more ACCURATE cannot be settled here.** Neither
method is observed; both estimate. Deciding between them needs lysimeter or
flux-tower measurements this project does not have. The scored `split + PM` row
(-19.4%) is NOT evidence against it - those forecasts were graded against a
Hargreaves-based truth, so the row measures a units mismatch, not skill.

CONNECTICUT DROUGHTS ARE RAIN-DEFICIT DROUGHTS, NOT EVAPORATIVE-DEMAND DROUGHTS.
That is the finding, and it was worth the fetch to establish rather than assume.

## The headline metric: will this farm run short of water?

`ctwater verify` is the command that matters. It scores the question a farmer
actually asks - will my soil dry past the point the crop starts losing yield, and
how much irrigation would prevent it - computed from each farm's OWN observed
weather, soil capacity and crop.

This is the headline because it is the only target that is both farm-resolution
and independent of any warning product. USDM is blurred to one value for the whole
state on 61.8% of dates; the Connecticut-stage reconstruction is a rule we wrote
ourselves. Neither can grade a per-farm claim. (This target is still a
computation - FAO-56 water balance - not a measurement.)

30 issue dates (May-September of 2012, 2015, 2016, 2018, 2020, 2022) x 200 farms,
30 days ahead, ensemble members drawn from the 74-year record:

| | forecast | climatology | persistence |
| --- | --- | --- | --- |
| **will this farm hit stress** (Brier, lower better) | **0.1465** | 0.2024 | 0.2268 |
| **how much water** (mm/week, mean absolute error) | **5.05** | 6.62 | - |

**+27.6% skill against climatology on the stress question, +23.7% on the amount.**

⚠️ Note the reversal: PERSISTENCE IS THE WORST BASELINE HERE (0.2268, worse than
climatology's 0.2024). On drought stage persistence was unbeatable, because slow
storage persists. Water stress is driven by the next few weeks of weather, so
"same as today" is actively misleading. Different physics, different baseline to
beat - and a reminder that "beat persistence" is not a universal bar.

### The range is honest

The outcome fell inside the p10-p90 band on **81.9%** of forecasts, against a
target of ~80%. That is close to properly calibrated, and notably better than the
87.5% the Connecticut-stage relay produced, which was too wide.

### It genuinely knows which farms are worst

This is the measurement that supports a per-farm claim, and the official labels
cannot produce it:

| question | rank correlation | dates it could rank | share positive |
| --- | --- | --- | --- |
| will this farm hit stress | **+0.293** | 22/30 | 86% |
| **how much water it needs** | **+0.724** | **30/30** | **100%** |
| persistence baseline | could not rank farms on ANY date | 0/30 | - |

**+0.724 on the irrigation amount, on every single date, always positive.**
Compare that with the +0.03 to +0.13 the Connecticut-stage forecast managed
against USDM. The spatial precision IS real - it was the drought-STAGE target
that could not show it.

That makes physical sense. Irrigation need depends on each farm's soil water
capacity from SSURGO, its crop's rooting depth and water demand, and its local
weather - genuine per-farm physical variation. A drought stage is a coarse
threshold on regional conditions, so most farms share an answer by construction.

⚠️ **This does NOT retract the earlier finding.** On the drought-stage target,
USDM ranks farms as well as we do. Both are true: the extra precision is real on
the water-balance question and unproven on the stage question. Which one is
claimed depends on which is reported, so report this one.

### The "overconfidence" was a bug in this repo, not in the forecast

`reliability()` defaulted to `prob_col="prob_stress"` while always comparing
against `actual_stressed`. Those are DIFFERENT EVENTS: `prob_stress` is the chance
of stress on any single day, `actual_stressed` is whether the farm hit seven or
more stressed days. P(any day) is far higher than P(a full week), so the pairing
manufactured a systematic gap and this README reported it as "overconfident at
every level, the most valuable thing left to fix".

Graded against its own event, the picture reverses:

| P(>=7 stressed days) | n | forecast | observed | gap |
| --- | --- | --- | --- | --- |
| [0.0, 0.1) | 536 | 0.027 | 0.045 | +0.018 |
| **[0.1, 0.3)** | 489 | 0.194 | **0.405** | **+0.211** |
| [0.3, 0.5) | 470 | 0.427 | 0.468 | +0.041 |
| [0.5, 0.7) | 1,007 | 0.569 | 0.700 | +0.131 |
| [0.7, 0.9) | 1,849 | 0.837 | 0.862 | +0.025 |
| [0.9, 1.01) | 1,649 | 0.932 | 0.898 | -0.034 |

It is mildly UNDER-confident, not over. `PROB_TRUTH_PAIRS` now maps each
probability to its own outcome and `truth_for` raises on anything unregistered,
so the pairing cannot be defaulted wrongly again. A test pins it. Brier scores
were never affected - those were matched all along.

### No recalibration transfers, so none is applied

Five corrections, every one fitted on five years and graded on the sixth, because
the previous isotonic failure was a TRANSFER failure and only a held-out test can
detect that:

| method | Brier | vs raw | worst gap | years it beat raw |
| --- | --- | --- | --- | --- |
| **raw** | **0.1465** | - | 0.441 | - |
| scale (1 parameter) | 0.1488 | -1.6% | 0.405 | 4/6 |
| Platt (2 parameters) | 0.1535 | -4.8% | 0.430 | 3/6 |
| isotonic (unlimited) | 0.1602 | -9.3% | 0.401 | 3/6 |
| scale by starting wetness | 0.1586 | -8.2% | 0.420 | 4/6 |
| scale by month | 0.1518 | -3.6% | 0.390 | 3/6 |

**Every method makes the forecast worse on unseen years.** The earlier diagnosis
blamed isotonic's flexibility, but a ONE-parameter correction fails too, and so
does conditioning on antecedent wetness or season - the two things that would
make "year-type dependent" actionable. Flexibility was not the problem.

### The one weak bin, chased to the end

The [0.1, 0.3) bin says 19% and stress happens 41% - a gap of +0.211, which at
n=489 is 9.5 standard errors, so it is real and not noise. It holds 8.2% of all
forecasts. Four questions, asked in order:

**Is it everywhere, or a few years?** A few.

| year | says | happens | gap |
| --- | --- | --- | --- |
| 2012 | 0.187 | 0.219 | +0.032 |
| **2015** | 0.196 | **0.913** | **+0.717** |
| **2016** | 0.195 | 0.614 | **+0.419** |
| 2018 | 0.189 | 0.196 | +0.007 |
| **2020** | 0.191 | 0.660 | **+0.469** |
| 2022 | 0.214 | 0.254 | +0.039 |

Three years are near-perfect and three are badly wrong. By month it is June
(+0.662) and July (+0.570) against August (+0.063) and September (+0.043).

**What are these farms?** The WET ones - soil at 0.627 of capacity against 0.283
elsewhere. The forecast expects 3.2 stressed days and reality delivers 6.4.

**Is that a water-balance bug?** No, because the error FLIPS SIGN:

| wet-starting farms | stress-day error |
| --- | --- |
| calm years (2012/18/22) | **-0.70** (over-predicts) |
| dry years (2015/16/20) | **+2.92** (under-predicts) |

Per year: 2018 -3.24, 2012 -1.93, 2022 +0.03, 2015 +2.30, 2020 +2.68, 2016 +3.60.
There is no monotone bias by wetness decile. This is the ensemble pulling toward
climatology - over-warning when the year turns out calm, under-warning when it
turns out dry. It is also exactly why no recalibration transferred: the
correction needed has OPPOSITE SIGNS in different years.

**Can the sign be known at forecast time?** No, and this was the last hope. The
farm's own wetness fails as a conditioner (-8.2%), month fails (-3.6%), and the
REGIONAL state - the average condition across all 200 farms on the issue date -
carries nothing at all:

    correlation with the error   -0.008
    rank correlation             -0.046
    median split                 8/15 dates under-predicted in the drier half,
                                 8/15 in the wetter half

⚠️ **This bin is not fixable, and it is not a defect to fix.** It is the 30-day
rainfall predictability limit made visible. The ensemble replays real past years,
history is mostly normal years, so it cannot concentrate on an outcome history
barely contains - and nothing observable on the issue date says which kind of year
is starting. Closing it would require skillful 30-day rainfall forecasting, which
this project measured decaying to nothing by day 8.

What CAN be done is refuse to hide it: the reliability table ships beside the
forecast, and a farmer reading "20%" should know that in a drought-developing year
that has historically meant closer to 60%.

### And it is already calibrated where it matters

| starting soil | n | mean forecast | observed | bias |
| --- | --- | --- | --- | --- |
| **dry** | 2,000 | 0.806 | 0.806 | **+0.000** |
| mid | 2,001 | 0.801 | 0.880 | +0.079 |
| wet | 1,999 | 0.376 | 0.424 | +0.047 |

When the ground is already dry - the regime a drought warning exists for - the
forecast says 80.6% and stress happens 80.6% of the time. The residual bias lives
in the middle bucket, where the stakes are lowest.

DECISION: ship raw probabilities, publish the reliability table beside them, and
do not apply a correction that measurement says would make forecasts worse.

## Is the per-farm precision real? Measured, and the answer is no

The project's central claim is that this is MORE LOCATION-PRECISE than existing
systems. Nothing in the label set can check that, which is the problem:

| label | resolution it actually carries |
| --- | --- |
| USDM | changes only on **Thursdays** (100% of changes); all 200 farms identical on **61.8%** of dates; **15.8%** of variance is between farms |
| CT rule per farm | monthly; **59.5%** of variance between farms - but it is OUR reconstruction, not an observation |

Scoring a per-farm daily forecast against USDM cannot detect farm-level skill. If
two neighbouring farms genuinely differ, USDM records them identically, so being
right is scored as being wrong on one of them.

### The test: rank farms, and let independent physical observations arbitrate

Use NEXT MONTH'S observed rainfall, groundwater and streamflow - never seen by
the forecast, out of sample by construction. Correlate WITHIN DATE, across the
200 farms, because a pooled correlation would mostly measure that droughty months
are droughty everywhere and would look like spatial skill without any.

**Head-to-head on the 39 dates where both can rank farms:**

| | next-month rain | next-month groundwater | next-month streamflow |
| --- | --- | --- | --- |
| relay forecast | +0.029 | +0.110 | **+0.096** |
| USDM stage | **+0.173** | **+0.130** | +0.085 |

**USDM ranks Connecticut farms as well as our per-farm forecast, and better on
rainfall.** The hypothesis that a coarse county product must carry less spatial
information than a per-farm model is refuted. Disagreements between this forecast
and the official warning are NOT evidence that this one is more precise.

### What IS defensible

| | relay | USDM | persistence |
| --- | --- | --- | --- |
| dates it can rank farms at all | **94/168 (56%)** | 44/168 (26%) | **0/168 (0%)** |
| within-date rho vs groundwater, drought underway | **+0.131** | +0.127 | - |
| within-date rho vs groundwater, quiet | +0.090 | **+0.194** | - |

Three honest claims survive:

1. **Availability, not accuracy.** The relay produces a farm-level signal on more
   than twice as many dates, including quiet periods before any declaration
   exists. That is the early-warning value, and it is real.
2. **In drought conditions it ties USDM** (+0.131 vs +0.127) - the regime that
   matters. USDM's overall edge comes from quiet periods.
3. **Persistence cannot rank farms at all**, on any of 168 dates, because the CT
   stage is 0 almost everywhere almost always. Any spatial discrimination beats
   the baseline that has otherwise been unbeatable.

⚠️ **All of these correlations are weak** - 0.03 to 0.19. Farm-level ranking skill
is modest for every method tested, including the operational one.

⚠️ The arbiters are farm-resolved (groundwater and streamflow take 196-198
distinct values across 200 farms, so shared-gauge attribution is not capping the
test) but distinct is not independent: they are interpolated from a sparser gauge
network, so the effective resolution is coarser than 200 and these correlations
are likely floors rather than ceilings.

### What this changes about how results are reported

**The "more location-precise" claim is currently unsupported and should not be
made.** What can be said is that the system issues farm-level guidance twice as
often as the official product and matches it during drought.

Reporting should also stop quoting daily-resolution skill against a Thursday-only
label. The defensible headline metric is the soil-water-balance target - water
stress and irrigation need computed from observed weather at each farm - because
it is the only one that is both farm-resolution and independent of any warning
product. (It is still a computation, FAO-56, not a measurement.)

**What would settle it:** observed farm-level outcomes - irrigation logs, soil
moisture probes, or the grower survey already listed below as pending. Until
then, extra spatial precision is asserted, not validated.

## Where you are, and what comes next

- [x] Project scaffold, virtual environment, dependency management
- [x] Config system, grid snapping, feature engineering, leak-safe splits
- [x] Both models training end-to-end with honest metrics
- [x] `predict --lat --lon --date` interface
- [x] **Real USDM labels** — download, cache, point-in-polygon lookup
- [x] **Water-stress index** defined as mm of irrigation per week
- [x] **Per-cell crop identity** from satellite; crop-specific `p` and Kc
- [x] Survey calibration hook (works uncalibrated, says so plainly)
- [x] **Real NOAA weather** — AORC at 0.92 km, rainfall and temperature, validated
      against Connecticut climatology and cross-checked against the 2022 drought
- [x] Refit on real weather and compare honestly against persistence
- [x] **USGS streamflow** — small headwater basins only; the landscape's memory
- [x] **Real soil water capacity** from USDA SSURGO, with crop-aware rooting depth
- [x] **Real farm locations** — 200 farms across 99 towns, from satellite cropland
      individuated by legal parcel
- [ ] Obtain survey responses and calibrate (see above)
- [ ] Spatial holdout test: does it work at a farm it has never seen?
- [ ] Measure whether your stage changes *lead* USDM's — that's the "quicker
      warning" claim, and it needs its own evidence
- [ ] Deployment: live data fetch, then a map interface for farmers

---

## Keeping the docs honest

Two documents are maintained alongside the code, and both are meant to stay true at every commit:

| File | What it covers |
|---|---|
| `README.md` | Why the project is shaped this way; what is real vs. still assumed; where you are |
| [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md) | Every table, every column, units, provenance, and whether the data is real |

**The rule: if a commit changes a column, a unit, a threshold, or where data comes from, it
updates these in the same commit.** A data dictionary that lags the code is worse than none,
because people trust it. When you add a dataset, its rows go in the dictionary before you start
modelling with it.

Two things worth re-checking whenever you touch the index:

- The **provenance table** at the bottom of the data dictionary — it is the fastest way to see
  what is still invented.
- The **status strip** at the top of this README's architecture page, which says the same thing
  visually: <https://claude.ai/code/artifact/6754327b-4682-4f2b-a9bb-61ccf698069f>

**Adding a real dataset changes nothing downstream.** Every loader returns the same four
columns — `cell_id, date, variable, value` — so features, splits, models, and metrics all
keep working untouched. That is the whole point of the structure.

---

## Working with this project day to day

`uv run <command>` automatically uses the project's virtual environment — you never need to
"activate" anything.

Add a package:

```bash
uv add statsmodels
```

Re-install everything from scratch (e.g. on a new computer):

```bash
uv sync --extra dev
```

Format and lint:

```bash
uv run ruff check --fix . ; uv run ruff format .
```

### Automatic checks on every commit

Ten checks run whenever you `git commit`, and the commit is refused if any fail. Set this up once
on a new machine:

```bash
uv run pre-commit install
```

Run them over the whole project any time:

```bash
uv run pre-commit run --all-files
```

| Check | What it does |
|---|---|
| `ruff` | Finds sloppy or suspicious code |
| `ruff-format` | Applies one consistent layout |
| `bandit` | Security linter — looks for unsafe patterns |
| hygiene hooks | Trailing whitespace, missing newlines, invalid YAML/TOML, merge markers, private keys, files over 2 MB |

**The test suite is deliberately not in there.** Slow checks make you resent committing and start
skipping them. Run `uv run pytest` yourself, or wire it into CI once this project has a remote.

If a hook rewrites a file, the commit fails on purpose — review the change, `git add` it, and
commit again. In a genuine emergency `git commit --no-verify` skips everything, but treat that as
a decision you will have to explain later.

**Bandit skips `tests/`** (see `[tool.bandit]` in `pyproject.toml`). Pytest's whole mechanism *is*
the `assert` statement, so scanning tests would produce hundreds of correct-usage warnings. We
exclude the directory rather than disabling the rule globally — because that rule caught a real
problem in library code, described next.

### Why there are no `assert`s in `src/`

`python -O` **deletes every `assert` statement** from a program, silently. The guard in
`features/targets.py` that checks your forecast targets point *forwards* in time used to be an
assert — so under that flag it vanished, and a reversed shift would have trained the model on the
past while scoring beautifully.

It is now an explicit `raise`, which nothing can remove, and three tests hold the line: one that a
backwards shift raises, one that runs a real subprocess under `-O` to confirm the guard still
fires, and one that fails if any `assert` reappears anywhere in `src/`.

The rule: **`assert` is for catching your own mistakes while developing. Anything that must always
hold — especially something protecting the honesty of your results — gets an explicit raise.**

For notebooks, select the `.venv` interpreter in VS Code or run `uv run jupyter lab`.

**Secrets:** copy `.env.example` to `.env` for API keys. `.env` is gitignored, so keys never
get committed.

---

## A note on the synthetic data

`ctwater make-synthetic` invents a Connecticut where rain falls seasonally, sandy soils dry
faster than loamy ones, and drought follows accumulated water deficit. It exists so you can
learn the modeling workflow without waiting on downloads.

**A model trained on it proves your code works. It proves nothing about forecasting real
drought.** Never report a score from synthetic data as a result.
