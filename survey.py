"""
Calibrating the irrigation recommendation against what farmers actually reported.

READ THIS FIRST - THE DATA SITUATION
------------------------------------
You asked to blend in CT Farm Bureau survey responses. Here is the honest status,
checked rather than assumed:

**There is no public, machine-readable Connecticut Farm Bureau drought survey
time series.** What exists is press coverage and narrative summaries from drought
years (2016, 2020, 2022), plus national American Farm Bureau survey write-ups.
Useful for context, not loadable as data.

So this module does two things:
  1. Defines exactly what file to hand it, if and when you obtain the data.
  2. Works correctly WITHOUT that data, applying a calibration factor of 1.0 and
     telling you plainly that it did so.

The machinery is built. The input is a gap you can close, and the code will not
pretend the gap is filled.

HOW TO ACTUALLY GET THIS DATA
-----------------------------
Roughly in order of effort:

1. **Ask.** Connecticut Farm Bureau and UConn Extension have run grower drought
   surveys. Emailing to ask whether anonymized response data can be shared for a
   student research project is cheap and sometimes just works. Explain that you
   need per-farm or per-county irrigation amounts with dates.

2. **USDA NASS Irrigation and Water Management Survey** - real, downloadable, and
   includes Connecticut application depths in acre-inches per acre. It runs only
   every five years, so it cannot calibrate week by week, but it is ideal for a
   one-time sanity check that your mm/week numbers land in the right range. If you
   do only one of these, do this one.

3. **Run your own survey.** A handful of CT small farms logging weekly irrigation
   for one season would be a genuinely novel dataset, and would make the index
   defensible in a way no borrowed data would. It is also the slowest option.

WHAT CALIBRATION ACTUALLY DOES
------------------------------
It fits one number: are we systematically over- or under-recommending water?

    factor = median(reported irrigation) / median(modeled irrigation)

A factor of 1.4 means real farmers applied 40% more than your model suggests, and
every future recommendation gets multiplied by 1.4. This is deliberately a single
scalar rather than a per-stage regression, because with a handful of survey
responses anything fancier would fit noise. When you have hundreds of observations,
revisit `fit_calibration` and consider fitting per drought stage.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# The file you would drop into data/external/ to enable calibration.
SURVEY_SCHEMA = {
    "date": "date the irrigation happened or the week it covers (YYYY-MM-DD)",
    "lat": "farm latitude in degrees (or leave blank and use county)",
    "lon": "farm longitude in degrees",
    "county": "CT county name, used if lat/lon are missing",
    "irrigation_mm_week": "water applied that week, in mm (1 inch = 25.4 mm)",
    "crop": "optional - what was being irrigated",
    "source": "optional - where this response came from",
}

DEFAULT_SURVEY_FILENAME = "ct_farm_survey.csv"


@dataclass
class Calibration:
    """The fitted correction factor, plus enough context to judge whether to trust it."""

    factor: float
    n_observations: int
    median_reported_mm: float
    median_modeled_mm: float
    fitted: bool
    note: str

    def describe(self) -> str:
        if not self.fitted:
            return f"Calibration: NOT FITTED (factor 1.0). {self.note}"
        return (
            f"Calibration factor {self.factor:.3f} from {self.n_observations} responses "
            f"(reported median {self.median_reported_mm:.1f} mm/week vs "
            f"modeled {self.median_modeled_mm:.1f} mm/week). {self.note}"
        )


def survey_template() -> pd.DataFrame:
    """
    An empty table in the required shape, with two example rows.

    Write it out with `ctwater survey-template` and either fill it in yourself or
    hand it to whoever holds the survey responses.
    """
    return pd.DataFrame(
        [
            {
                "date": "2022-08-16",
                "lat": 41.7658,
                "lon": -72.6734,
                "county": "Hartford",
                "irrigation_mm_week": 25.4,
                "crop": "mixed vegetables",
                "source": "example row - delete me",
            },
            {
                "date": "2022-08-23",
                "lat": 41.3080,
                "lon": -72.9280,
                "county": "New Haven",
                "irrigation_mm_week": 31.8,
                "crop": "sweet corn",
                "source": "example row - delete me",
            },
        ]
    )


def load_survey(path: str | Path) -> pd.DataFrame | None:
    """
    Read the survey file if it exists. Returns None (with a warning) if it does not.

    Returning None rather than raising is intentional: a missing optional dataset
    should degrade the model gracefully, not stop your work.
    """
    path = Path(path)
    if not path.exists():
        return None

    df = pd.read_csv(path)

    missing = {"date", "irrigation_mm_week"} - set(df.columns)
    if missing:
        raise ValueError(
            f"Survey file {path.name} is missing required columns: {sorted(missing)}. "
            f"Expected schema: {list(SURVEY_SCHEMA)}"
        )

    df["date"] = pd.to_datetime(df["date"])
    df["irrigation_mm_week"] = pd.to_numeric(df["irrigation_mm_week"], errors="coerce")
    df = df.dropna(subset=["irrigation_mm_week"])

    # Drop the example rows so a half-filled template cannot quietly calibrate anything.
    if "source" in df.columns:
        df = df[~df["source"].astype(str).str.contains("example row", case=False, na=False)]

    return df.reset_index(drop=True)


def fit_calibration(
    survey: pd.DataFrame | None,
    modeled: pd.DataFrame | None = None,
    min_observations: int = 5,
    max_factor: float = 3.0,
) -> Calibration:
    """
    Work out the correction factor between reported and modeled irrigation.

    Parameters
    ----------
    survey : loaded survey responses, or None
    modeled : optional table with date + irrigation_mm_week from the model, matched
        to the same weeks. If omitted, we compare against a nominal peak-season
        demand instead, which is cruder but still catches order-of-magnitude errors.
    min_observations : refuse to calibrate on fewer than this many responses.
        Fitting a factor to three data points is worse than not fitting one at all.
    max_factor : clamp, so one mistyped response cannot triple every recommendation.

    We use MEDIANS rather than means throughout, because survey data is small and
    a single farm reporting a flooded field would drag a mean badly.
    """
    if survey is None or survey.empty:
        return Calibration(
            factor=1.0,
            n_observations=0,
            median_reported_mm=float("nan"),
            median_modeled_mm=float("nan"),
            fitted=False,
            note=(
                "No survey file found. Recommendations are uncalibrated physical "
                "estimates - treat them as approximate. See data/survey.py for how "
                "to obtain this data."
            ),
        )

    if len(survey) < min_observations:
        return Calibration(
            factor=1.0,
            n_observations=len(survey),
            median_reported_mm=float(survey["irrigation_mm_week"].median()),
            median_modeled_mm=float("nan"),
            fitted=False,
            note=(
                f"Only {len(survey)} responses; need at least {min_observations} to "
                "fit a factor without chasing noise."
            ),
        )

    reported = float(survey["irrigation_mm_week"].median())

    if modeled is not None and not modeled.empty and "irrigation_mm_week" in modeled.columns:
        model_median = float(modeled["irrigation_mm_week"].median())
        basis = "matched modeled weeks"
    else:
        from ctwater.features.dry import DEFAULT_PEAK_DEMAND_MM_WEEK

        model_median = DEFAULT_PEAK_DEMAND_MM_WEEK
        basis = "nominal peak demand (no matched model output supplied)"

    if not np.isfinite(model_median) or model_median <= 0:
        return Calibration(
            factor=1.0,
            n_observations=len(survey),
            median_reported_mm=reported,
            median_modeled_mm=model_median,
            fitted=False,
            note="Modeled irrigation median was zero or invalid, so no factor could be fitted.",
        )

    raw = reported / model_median
    factor = float(np.clip(raw, 1.0 / max_factor, max_factor))

    note = f"Fitted against {basis}."
    if factor != raw:
        note += f" Clamped from {raw:.2f} to stay within 1/{max_factor:g}..{max_factor:g}."
        warnings.warn(
            f"Calibration factor {raw:.2f} was extreme and got clamped to {factor:.2f}. "
            "Check the survey file for unit errors - inches entered as mm is the usual cause.",
            stacklevel=2,
        )

    return Calibration(
        factor=factor,
        n_observations=len(survey),
        median_reported_mm=reported,
        median_modeled_mm=model_median,
        fitted=True,
        note=note,
    )


def get_calibration(cfg, modeled: pd.DataFrame | None = None) -> Calibration:
    """Load the survey (if present) and fit the factor. The one call the pipeline makes."""
    path = Path(cfg.paths["data_external"]) / DEFAULT_SURVEY_FILENAME
    survey = load_survey(path)
    return fit_calibration(survey, modeled=modeled)
