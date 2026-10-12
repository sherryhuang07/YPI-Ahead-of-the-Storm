"""
Fake-but-plausible data, so the whole pipeline runs TODAY.

WHY THIS EXISTS
---------------
Real environmental data takes days to find, download, and clean. Meanwhile you
learn nothing about modeling while you wait. So this module invents a Connecticut
that behaves roughly like the real one: it rains seasonally, summers dry out soil
faster than winters, sandy sites drain quicker than loamy ones, and drought stage
follows accumulated water deficit.

Then, when your real datasets arrive, you delete NOTHING except the call to
`make_synthetic_dataset()` - you swap in real loaders that emit the same tidy
shape, and every feature, split, model, and metric keeps working.

IMPORTANT HONESTY NOTE
----------------------
A model trained on this data proves your CODE works. It proves nothing about
whether you can forecast real drought. Never report a score from synthetic data
as a result.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ctwater.data.grid import GridSpec, snap_to_grid

# A handful of real-ish Connecticut farm locations spread across the state,
# so the synthetic set has genuine geographic spread.
SEED_LOCATIONS: list[tuple[str, float, float]] = [
    ("litchfield_hills", 41.7470, -73.1890),
    ("farmington_valley", 41.7190, -72.8320),
    ("hartford_area", 41.7658, -72.6734),
    ("storrs_tolland", 41.8084, -72.2495),
    ("northeast_hills", 41.9060, -71.9720),
    ("middlesex_ct_river", 41.5620, -72.6510),
    ("new_haven_shore", 41.3080, -72.9280),
    ("naugatuck_valley", 41.4900, -73.0450),
    ("southwest_coast", 41.1500, -73.2600),
    ("southeast_shore", 41.3560, -72.0990),
    ("windham", 41.7000, -72.1600),
    ("northwest_corner", 41.9500, -73.3300),
]


def make_synthetic_dataset(
    start: str = "2005-01-01",
    end: str = "2024-12-31",
    grid_resolution_m: float = 1000,
    seed: int = 42,
) -> dict[str, pd.DataFrame]:
    """
    Build a synthetic daily weather panel plus weekly drought labels.

    Returns a dict with three DataFrames:
      "locations" - one row per site: cell_id, lat, lon, static soil traits
      "observations" - tidy daily weather: cell_id, date, variable, value
      "labels" - weekly stand-in for USDM: cell_id, date, usdm_stage

    The physics is a deliberately simple "bucket" model:
        soil_water[t] = clip(soil_water[t-1] + rain[t] - et[t], 0, capacity)
    Drought stage is then a function of how depleted that bucket has been.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start, end, freq="D")
    n_days = len(dates)

    # --- locations and their permanent traits ---------------------------------
    lats = np.array([lat for _, lat, _ in SEED_LOCATIONS])
    lons = np.array([lon for _, _, lon in SEED_LOCATIONS])
    grid = snap_to_grid(lats, lons, GridSpec(resolution_m=grid_resolution_m))
    grid["site_name"] = [name for name, _, _ in SEED_LOCATIONS]

    # Available water capacity: how much water the soil can hold, in mm.
    # Sandy sites (low awc) hit drought stress much faster after the same dry spell.
    grid["awc_mm"] = rng.uniform(60, 180, size=len(grid)).round(1)
    grid["elevation_m"] = rng.uniform(5, 350, size=len(grid)).round(1)
    grid["slope_deg"] = rng.uniform(0, 12, size=len(grid)).round(2)

    doy = dates.dayofyear.to_numpy()
    # Seasonal cycle: one full sine wave over the year, peaking mid-summer.
    season = np.sin(2 * np.pi * (doy - 100) / 365.25)

    obs_frames: list[pd.DataFrame] = []
    label_frames: list[pd.DataFrame] = []

    for _idx, row in grid.iterrows():
        # --- daily weather -----------------------------------------------------
        # Rain: happens on ~30% of days; amount is a skewed (gamma) draw, which is
        # how real daily rainfall behaves - lots of small events, rare big ones.
        wet = rng.random(n_days) < 0.30
        amount = rng.gamma(shape=0.9, scale=9.0, size=n_days)
        precip = np.where(wet, amount, 0.0)

        # Multi-year wet/dry regimes, so real droughts of realistic LENGTH appear
        # instead of pure day-to-day noise. This is what makes the task learnable.
        regime = _slow_wave(n_days, rng, period_days=900) + _slow_wave(n_days, rng, period_days=270)
        precip = precip * np.clip(1.0 + 0.55 * regime, 0.15, 2.2)

        tmax = 14.0 + 13.0 * season + rng.normal(0, 3.5, n_days) - row["elevation_m"] * 0.004
        tmin = tmax - rng.uniform(6, 13, n_days)

        # Reference evapotranspiration, via the Hargreaves equation:
        #     ET0 = 0.0023 x Ra x sqrt(Tmax - Tmin) x (Tmean + 17.8)
        #
        # Ra is extraterrestrial radiation - how much sunlight reaches the top of the
        # atmosphere. It is NOT constant: at Connecticut's latitude it swings from
        # about 13 MJ/m2/day in January to 41 in July. Using a fixed value (an
        # earlier version of this file did) makes summer ET roughly three times too
        # small, the soil never dries out, and the irrigation target collapses to
        # zero - which is exactly the kind of quiet physical error that produces a
        # model that trains fine and means nothing.
        ra = 27.0 + 14.0 * np.sin(2 * np.pi * (doy - 81) / 365.25)  # MJ/m2/day
        ra_mm = ra * 0.408  # convert to mm/day
        tmean = (tmax + tmin) / 2.0
        et0 = np.clip(
            0.0023 * ra_mm * np.sqrt(np.clip(tmax - tmin, 0, None)) * (tmean + 17.8), 0, None
        )

        # --- the soil-water bucket --------------------------------------------
        capacity = float(row["awc_mm"])
        soil = np.empty(n_days)
        level = capacity * 0.7
        for t in range(n_days):
            level = min(max(level + precip[t] - et0[t], 0.0), capacity)
            soil[t] = level

        # Fraction of capacity remaining: 1.0 = field capacity, 0.0 = bone dry.
        frac = soil / capacity

        # --- turn physics into the two targets ---------------------------------
        # Stress index: 30-day average dryness, smoothed to 0-1.
        frac_s = pd.Series(frac, index=dates)
        stress = (1.0 - frac_s.rolling(30, min_periods=1).mean()).clip(0, 1)

        # Stage: bucket the stress into 6 ordinal classes, mirroring USDM D0-D4.
        # Real USDM percentile cutoffs are 30/20/10/5/2; these thresholds are the
        # same idea applied to our synthetic index.
        stage = pd.cut(
            stress,
            bins=[-0.01, 0.45, 0.55, 0.65, 0.75, 0.85, 1.01],
            labels=[0, 1, 2, 3, 4, 5],
        ).astype(int)

        cell_id = row["cell_id"]

        wide = pd.DataFrame(
            {
                "cell_id": cell_id,
                "date": dates,
                "precip_mm": precip.round(2),
                "tmax_c": tmax.round(2),
                "tmin_c": tmin.round(2),
                "et0_mm": et0.round(3),
                "soil_moist_frac": frac.round(4),
            }
        )
        obs_frames.append(
            wide.melt(
                id_vars=["cell_id", "date"],
                value_vars=["precip_mm", "tmax_c", "tmin_c", "et0_mm", "soil_moist_frac"],
                var_name="variable",
                value_name="value",
            )
        )

        # Labels only on Tuesdays, matching the U.S. Drought Monitor release cadence.
        #
        # We emit ONLY the stage here. The water-stress index and irrigation figure
        # are computed later by features/irrigation.py, from the same code path the
        # real USDM data uses - so there is exactly one definition of the target,
        # not a synthetic one and a real one that quietly drift apart.
        weekly = pd.DataFrame({"cell_id": cell_id, "date": dates, "usdm_stage": stage.to_numpy()})
        label_frames.append(weekly[weekly["date"].dt.dayofweek == 1].reset_index(drop=True))

    observations = pd.concat(obs_frames, ignore_index=True)
    labels = pd.concat(label_frames, ignore_index=True)

    locations = grid[
        [
            "cell_id",
            "site_name",
            "lat",
            "lon",
            "cell_center_lat",
            "cell_center_lon",
            "awc_mm",
            "elevation_m",
            "slope_deg",
        ]
    ].copy()

    return {"locations": locations, "observations": observations, "labels": labels}


def _slow_wave(n: int, rng: np.random.Generator, period_days: int) -> np.ndarray:
    """A smooth random oscillation - stands in for multi-year climate variability."""
    phase = rng.uniform(0, 2 * np.pi)
    t = np.arange(n)
    return np.sin(2 * np.pi * t / period_days + phase)
