"""
Atmospheric reanalysis: the physics the rainfall model has never had.

THE CAVEAT THIS ADDRESSES
-------------------------
`modeling/rainfall.py` measured where rainfall predictability ends using rainfall
history alone: useful skill to 3 days, nothing after. The docstring there says
plainly why that number is not a fact about the atmosphere:

    "That model has no pressure, no wind, no upper-air, no physics: it is
     pattern-matching a rain gauge against itself."

Reanalysis is those missing inputs. NCEP/NCAR Reanalysis 1 gives daily
geopotential height, precipitable water and winds on a 2.5 degree global grid
from 1948 to the present - the same era nClimGrid covers, so the two line up.

WHY ERA5 IS NOT USED HERE
-------------------------
ERA5 is the better reanalysis - 0.25 degrees against 2.5, and a far more modern
assimilation system. It is not used because the Copernicus Data Store requires a
registered account and API key, which cannot be created from here. The NCAR
mirror on AWS is reachable without credentials and would be the upgrade path if
higher resolution ever mattered.

For this purpose it very likely does not. The predictors below are SYNOPTIC -
the position of a ridge, the strength of the Bermuda High, how much moisture the
column holds. Those are thousand-kilometre features, well resolved at 2.5
degrees, and NCEP's longer record (1948) is worth more here than ERA5's finer
grid.

WHAT MIGHT AND MIGHT NOT WORK
-----------------------------
Being explicit before measuring, because this is the kind of question where a
model will always find SOMETHING.

  UNLIKELY TO HELP: deterministic rainfall past ~10 days. Reanalysis describes
  the atmosphere's state TODAY. The atmosphere forgets its initial conditions,
  which is why GEFS skill died at day 7 in this project's own measurements. No
  amount of upper-air data escapes chaos.

  PLAUSIBLE: the 30-day ANOMALY - wetter or drier than normal. Some atmospheric
  patterns are slow. A blocking ridge parked over the Northeast persists for
  weeks, and a westward-displaced Bermuda High is the classic driver of New
  England drought. If those are readable today they say something about the
  month ahead in a way tomorrow's rain does not.

That distinction is the whole test. The 30-day above/below-normal question
currently scores AUC 0.565 from rainfall history alone, and that is the number to
beat.

THE THREE REGIONS, AND WHY THEY ARE NOT ONE
-------------------------------------------
    local      38-45N, 75-65W    over Connecticut
    upstream   35-50N, 100-80W   where tomorrow's weather is now
    atlantic   28-40N, 70-55W    the Bermuda High

One regional average would blur these together, and the derived gradients matter
because absolute 500 hPa height is dominated by season while the DIFFERENCE
between regions is what steers storms.

WHAT WAS MEASURED, AND WHAT WAS NOT EXPLAINED
---------------------------------------------
These predictors help. Added to the rainfall-only model, on identical folds:

    horizon   features        MAE vs climatology   AUC wet/dry
      7 day   rain only            +1.2%              0.552
      7 day   rain + atmos         +4.4%              0.589
     30 day   rain only            -6.1%              0.571
     30 day   rain + atmos         -3.0%              0.583

At 7 days the model stops tying climatology and beats it. At 30 days it still
loses, but the deficit halves. They carry 18.2% of the model's gain.

AND THE PHYSICAL STORY FAILED ITS OWN TEST.

`drought_signature` checks the obvious mechanism - ridging over Connecticut means
sinking air and no rain. On the four summers that matter:

                          2016 dry   2022 dry   2021 wet   2023 flood
    hgt500_local             +9.3       +7.3      +34.2      -17.8
    hgt500_upstream         +20.3      +13.5      +25.1       -1.5
    hgt500_atlantic         +10.4      +14.7      +26.8       -0.0

The WET summer has the strongest ridging on every measure. Ridge POSITION was
then computed directly - the area-weighted centroid of the positive 500 hPa
anomaly - to test whether a regional mean was hiding it:

    season        ridge lat   ridge lon   strength
    2016 dry         40.7       -80.8      116.5 m
    2022 dry         42.3       -79.1      132.5 m
    2021 wet         43.1       -79.8      162.1 m
    2023 flood       42.0       -80.3      159.2 m

Position is essentially identical - every centre within 1.7 degrees - and
strength runs BACKWARDS, with the wet summers about 30 m stronger. Ridging is not
the mechanism, on amplitude, position or regional average.

BUT THE SIGNAL ITSELF IS REAL, AND HERE IS WHAT IT IS MADE OF
-------------------------------------------------------------
The decisive test is permutation: keep the same eight columns and the same
distributions, destroy the link to the date. If the gain survives, the features
were only giving the model room to memorise noise.

    feature set                  7-day vs clim   30-day vs clim
    rain only                        +1.2%           -6.1%
    rain + atmospheric               +4.4%           -3.0%
    rain + atmospheric SHUFFLED      +1.3%           -5.5%   <- collapses
    rain + heights only              +2.7%           -5.6%
    rain + gradients only            +1.8%           -5.3%
    rain + moisture only             +2.6%           -4.5%

Shuffling returns the model to baseline at both horizons, so the information is
genuinely tied to the date.

IT IS DISTRIBUTED, NOT CONCENTRATED. Individual gains sum to roughly the combined
gain (7-day: 1.5 + 1.4 + 0.6 = 3.5 against 3.2 combined; 30-day: 0.5 + 0.8 + 1.6
= 2.9 against 3.1), so the three families contribute largely independently. That
is why no single predictor separated the drought summers - none of them is
supposed to alone.

AND MOISTURE LEADS AT LONG RANGE. Column precipitable water is the strongest
single family at 30 days (-4.5% against heights' -5.6%), while at 7 days heights
and moisture are level. At 7 days a moisture signal could be dismissed as
air-mass persistence - today's column water is tomorrow's rain. At 30 days it
cannot be, so it is describing a persistent moisture REGIME, which is the kind of
slowly-varying signal subseasonal forecasting is meant to exploit.

What remains unknown is the causal chain. "Moisture regime" names the family, not
the physics. That is a far better position than an unexplained 18%, and enough to
justify using these predictors - but not enough to tell a story about why they
work.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

PSL = "https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis/Dailies"

FIRST_YEAR = 1948

# Longitudes are 0-360 in this dataset, latitudes descend from 90.
REGIONS = {
    "local": {"lat": (45, 38), "lon": (285, 295)},
    "upstream": {"lat": (50, 35), "lon": (260, 280)},
    "atlantic": {"lat": (40, 28), "lon": (290, 305)},
}

# 500 hPa is the standard steering level: it sits above the friction and weather
# of the lower atmosphere and below the jet, so it shows where systems will go.
STEERING_LEVEL = 500


def _open(url: str):
    import xarray as xr

    return xr.open_dataset(url)


def fetch_year(year: int) -> pd.DataFrame | None:
    """
    One year of regional atmospheric predictors, daily.

    Returns date plus hgt500_<region> and pwat_<region> for each region. The
    spatial averaging happens after a server-side subset, so only the windows
    cross the network.
    """
    frames = {}
    try:
        hgt = _open(f"{PSL}/pressure/hgt.{year}.nc")
        pwat = _open(f"{PSL}/surface/pr_wtr.eatm.{year}.nc")
    except (OSError, ValueError, KeyError) as exc:
        warnings.warn(f"Reanalysis {year} unavailable: {exc}", stacklevel=2)
        return None

    try:
        for name, box in REGIONS.items():
            lat = slice(*box["lat"])
            lon = slice(*box["lon"])

            h = hgt["hgt"].sel(level=STEERING_LEVEL).sel(lat=lat, lon=lon)
            frames[f"hgt500_{name}"] = h.mean(dim=["lat", "lon"]).load()

            p = pwat["pr_wtr"].sel(lat=lat, lon=lon)
            frames[f"pwat_{name}"] = p.mean(dim=["lat", "lon"]).load()
    except (OSError, ValueError, KeyError) as exc:
        warnings.warn(f"Reanalysis {year} subset failed: {exc}", stacklevel=2)
        return None
    finally:
        hgt.close()
        pwat.close()

    first = next(iter(frames.values()))
    out = pd.DataFrame({"date": pd.to_datetime(first["time"].values).normalize()})
    for col, series in frames.items():
        out[col] = np.asarray(series.values, dtype=float)

    # THE GRADIENT IS THE SIGNAL, NOT THE LEVEL.
    #
    # Absolute 500 hPa height is dominated by season - it is simply higher in
    # summer everywhere. What steers storms is the DIFFERENCE between regions:
    # a high over the Atlantic against a low over the Great Lakes is a
    # storm-track pattern, and the same two heights in the opposite arrangement
    # is not.
    out["hgt500_atl_minus_local"] = out["hgt500_atlantic"] - out["hgt500_local"]
    out["hgt500_local_minus_upstream"] = out["hgt500_local"] - out["hgt500_upstream"]
    out["date"] = out["date"].astype("datetime64[ns]")
    return out


# SURFACE VARIABLES, FETCHED SEPARATELY AND ON PURPOSE.
#
# The variables above describe where storms will GO - steering heights and the
# moisture available to them. These describe how hard the atmosphere PULLS water
# out of the ground, which is the other half of a drought and the half this
# project has been missing. Temperature alone (Hargreaves) cannot see it: the
# same 30C afternoon dries a field far faster when the air is parched and moving
# than when it is humid and still.
#
# Only the local box is fetched. Humidity and wind matter at the farm, whereas
# steering patterns matter upstream - a different question needing a different
# footprint.
#
# Written to its own file rather than merged into the existing one, so a failed
# or partial fetch cannot damage a dataset that took hours to build.
SURFACE_SOURCES = {
    "rhum": ("surface", "rhum.sig995", "rhum"),
    "uwnd": ("surface_gauss", "uwnd.10m.gauss", "uwnd"),
    "vwnd": ("surface_gauss", "vwnd.10m.gauss", "vwnd"),
}


def fetch_surface_year(year: int) -> pd.DataFrame | None:
    """
    One year of near-surface humidity and wind over the local box, daily.

    Any variable that fails to load is dropped with a warning rather than losing
    the year, because a partial record is still worth having and a silent zero
    is not.
    """
    frames: dict[str, np.ndarray] = {}
    times = None
    box = REGIONS["local"]
    lat, lon = slice(*box["lat"]), slice(*box["lon"])

    for name, (folder, stem, var) in SURFACE_SOURCES.items():
        try:
            ds = _open(f"{PSL}/{folder}/{stem}.{year}.nc")
        except (OSError, ValueError, KeyError) as exc:
            warnings.warn(f"Surface {name} {year} unavailable: {exc}", stacklevel=2)
            continue
        try:
            sub = ds[var].sel(lat=lat, lon=lon).mean(dim=["lat", "lon"]).load()
            frames[name] = np.asarray(sub.values, dtype=float)
            if times is None:
                times = pd.to_datetime(sub["time"].values).normalize()
        except (OSError, ValueError, KeyError) as exc:
            warnings.warn(f"Surface {name} {year} subset failed: {exc}", stacklevel=2)
        finally:
            ds.close()

    if times is None or not frames:
        return None

    out = pd.DataFrame({"date": times})
    for col, values in frames.items():
        if len(values) != len(out):
            warnings.warn(f"Surface {col} {year} length mismatch; dropped", stacklevel=2)
            continue
        out[col] = values

    if "uwnd" in out.columns and "vwnd" in out.columns:
        # Direction does not matter for evaporation - only how fast the air moves.
        out["wind_ms"] = np.sqrt(out["uwnd"] ** 2 + out["vwnd"] ** 2)
    out["date"] = out["date"].astype("datetime64[ns]")
    return out


def build_surface(
    start_year: int = FIRST_YEAR,
    end_year: int | None = None,
    progress: bool = False,
) -> pd.DataFrame:
    """Fetch the surface record year by year, skipping years that fail."""
    end_year = end_year or pd.Timestamp.today().year
    frames = []
    for year in range(start_year, end_year + 1):
        got = fetch_surface_year(year)
        if got is not None and not got.empty:
            frames.append(got)
            if progress:
                print(f"  {year}: {len(got)} days", flush=True)
        elif progress:
            print(f"  {year}: unavailable", flush=True)
    if not frames:
        raise RuntimeError("No surface reanalysis years could be fetched.")
    return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)


def build_reanalysis(
    start_year: int = 1951,
    end_year: int = 2024,
    cache_dir: Path | None = None,
    progress: bool = True,
) -> pd.DataFrame:
    """Every year of predictors, cached per year so an interrupted run resumes."""
    frames = []
    for year in range(max(start_year, FIRST_YEAR), end_year + 1):
        cached = cache_dir / f"reanalysis_{year}.parquet" if cache_dir else None
        if cached is not None and cached.exists():
            frames.append(pd.read_parquet(cached))
            continue

        part = fetch_year(year)
        if part is None:
            continue
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            part.to_parquet(cached, index=False)
        frames.append(part)

        if progress and year % 10 == 0:
            print(f"  {year}", flush=True)

    if not frames:
        raise RuntimeError(f"No reanalysis retrieved. Check {PSL} is reachable.")
    return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)


def add_anomalies(
    reanalysis: pd.DataFrame, train_end: pd.Timestamp, smooth_days: int = 15
) -> pd.DataFrame:
    """
    Turn absolute values into departures from the seasonal normal.

    A 500 hPa height of 5800 m means nothing on its own - it is ordinary in July
    and extraordinary in January. The anomaly is the informative quantity.

    The climatology is fitted STRICTLY BEFORE `train_end`, the same guard used
    for every other anomaly in this project. Fitting it on the whole record would
    let each row peek at its own answer.
    """
    out = reanalysis.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["doy"] = out["date"].dt.dayofyear

    hist = out[out["date"] < pd.Timestamp(train_end)]
    if hist.empty:
        raise ValueError("No reanalysis rows before train_end; cannot fit a climatology.")

    value_cols = [c for c in out.columns if c not in ("date", "doy")]
    for col in value_cols:
        clim = hist.groupby("doy")[col].mean()
        # Smooth around the calendar so 31 December and 1 January agree.
        wrapped = pd.concat([clim, clim, clim])
        smoothed = wrapped.rolling(smooth_days, center=True, min_periods=1).mean()
        clim_s = smoothed.iloc[len(clim) : 2 * len(clim)]
        clim_s.index = clim.index

        out[f"{col}_anom"] = out[col] - out["doy"].map(clim_s)

    return out.drop(columns=["doy"])


def summarize(reanalysis: pd.DataFrame) -> pd.DataFrame:
    """What the predictors look like, and whether they move sensibly."""
    cols = [c for c in reanalysis.columns if c.endswith("_anom")]
    if not cols:
        cols = [c for c in reanalysis.columns if c != "date"]

    return (
        reanalysis[cols]
        .agg(["mean", "std", "min", "max"])
        .T.round(2)
        .reset_index()
        .rename(columns={"index": "predictor"})
    )


def drought_signature(reanalysis: pd.DataFrame) -> str:
    """
    Do these predictors actually mark Connecticut's known droughts?

    If a 500 hPa ridging index does not stand out in the summers of 2016 and
    2022 - the two worst recent droughts - then it is not measuring what it is
    supposed to and no model will rescue it.
    """
    r = reanalysis.copy()
    r["date"] = pd.to_datetime(r["date"])
    col = "hgt500_local_anom" if "hgt500_local_anom" in r.columns else "hgt500_local"

    rows = []
    for label, period in [
        ("Jun-Aug 2016 (severe drought)", ("2016-06-01", "2016-08-31")),
        ("Jun-Aug 2022 (severe drought)", ("2022-06-01", "2022-08-31")),
        ("Jun-Aug 2021 (wet)", ("2021-06-01", "2021-08-31")),
        ("Jun-Aug 2023 (flood year)", ("2023-06-01", "2023-08-31")),
    ]:
        sel = r[(r["date"] >= period[0]) & (r["date"] <= period[1])]
        if sel.empty:
            continue
        rows.append(f"  {label:32s} {sel[col].mean():+7.1f} m")

    return "500 hPa height anomaly over Connecticut (positive = ridging = dry):\n" + "\n".join(rows)
