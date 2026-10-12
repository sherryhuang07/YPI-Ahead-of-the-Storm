"""
NOAA Atlas 14: how rare is this rain, here?

THE PROBLEM THIS SOLVES
-----------------------
Every rainfall threshold in this project has been a number in millimetres that I
picked and then tuned - 80 mm, then 60, then 65/80/55/85 by season. Two things
are wrong with that, and both are the kind of wrong that survives good scores.

FIRST, MILLIMETRES ARE NOT SEVERITY. Eighty millimetres of rain is not the same
event everywhere. Measured from Atlas 14, the 24-hour storm you expect once every
two years is:

    southwest coast    92 mm
    southeast shore    87 mm
    Hartford           79 mm
    northwest hills    78 mm

An 18% spread. A flat 80 mm threshold flags a genuine 2-year storm in the hills
and a routine 1.3-year storm on the coast. For a project whose entire claim is
location precision, applying one number statewide quietly discards it.

SECOND, MY THRESHOLDS WERE TUNED TO "COMMON". Compare what the calibration
against reported floods landed on with what Atlas 14 says those depths mean at
Hartford:

    winter  65 mm  ~  the 1-year storm  (63 mm)
    spring  80 mm  ~  the 2-year storm  (79 mm)
    summer  55 mm  <  the 1-year storm
    fall    85 mm  ~  the 2-year storm

A storm you get every single year is, by definition, not cause for concern. It is
normal weather. The rule was calibrated to fire on ordinary rain because ordinary
rain is what generates most Weather Service flood reports - a road underwater for
an hour is a report, and it happens every year.

WHAT ATLAS 14 GIVES INSTEAD
---------------------------
NOAA's Precipitation Frequency Data Server publishes, for any point, the rainfall
depth expected at each average recurrence interval (ARI):

    duration   1yr   2yr   5yr  10yr  25yr  50yr  100yr
    24-hr       63    79   104   125   154   175    199     <- Hartford, mm

Read backwards, this converts a measured depth into a RETURN PERIOD. 125 mm at
Hartford is a 10-year storm; the same 125 mm on the southwest coast is closer to
a 5-year storm. That single number - "this is a 1-in-N year event here" - is
comparable across locations, physically meaningful, standard in engineering and
NRCS conservation practice, and derived by NOAA statisticians from long records
with no knowledge of this project.

It replaces four tuned constants with one interpretable parameter: how rare must
a storm be before we call it cause for concern?

WHAT IT DOES NOT GIVE
---------------------
Atlas 14 is built from annual and partial-duration series, so it carries NO
SEASONALITY. A 2-year storm is a 2-year storm whether it falls on frozen February
ground or dry August ground - and those are not equally dangerous. Return period
answers "how rare", season answers "how much damage it does". Both are needed, so
the seasonal adjustment stays; it now scales a physically meaningful quantity
instead of standing in for one.

A NOTE ON VINTAGE
-----------------
Volume 10 (Northeastern States) is based on records through roughly 2012. It is
the current official standard and it is what drainage in Connecticut is designed
against, but a warming climate has been loading the extreme tail since, so these
return periods are, if anything, conservative - today's "10-year storm" likely
arrives more often than every ten years. NOAA Atlas 15 is intended to address
exactly this. Treat these as the engineering baseline, not as a forecast of
future frequency.
"""

from __future__ import annotations

import io
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PFDS_URL = "https://hdsc.nws.noaa.gov/cgi-bin/new/fe_text_mean.csv"

# Average recurrence intervals, in years, as published.
ARI_YEARS = (1, 2, 5, 10, 25, 50, 100, 200, 500, 1000)

# Durations we keep. 24-hr pairs with `max_1day_mm`; the multi-day rows matter
# for the slower, saturating kind of flooding that a single downpour misses.
KEEP_DURATIONS = ("60-min", "6-hr", "24-hr", "2-day", "3-day", "7-day")

# PFDS returns the same grid cell for nearby points, so rounding coordinates
# before lookup collapses 200 farms onto far fewer requests. This is the same
# lesson as the parcel geocoding: deduplicate BEFORE the expensive call, not
# after. Two decimals is about 1 km.
COORD_PRECISION = 2


def fetch_point_estimates(lat: float, lon: float, timeout: int = 120) -> pd.DataFrame:
    """
    Precipitation frequency estimates for one point, in millimetres.

    Returns a table indexed by duration with one column per ARI.
    """
    params = {
        "lat": f"{lat:.4f}",
        "lon": f"{lon:.4f}",
        "data": "depth",
        "units": "metric",
        "series": "pds",  # partial duration series - the standard for this use
    }
    resp = requests.get(PFDS_URL, params=params, timeout=timeout)
    resp.raise_for_status()

    text = resp.text
    if "PRECIPITATION FREQUENCY ESTIMATES" not in text:
        raise RuntimeError(
            f"PFDS returned no estimate block for ({lat}, {lon}). "
            "The point may be outside Atlas 14 Volume 10 coverage."
        )

    # The estimate block runs from the header line until the first blank line.
    body = text.split("PRECIPITATION FREQUENCY ESTIMATES", 1)[1]
    body = body.split("by duration for ARI (years):", 1)[1]
    lines = []
    for line in body.splitlines()[1:]:
        if not line.strip():
            break
        lines.append(line)

    frame = pd.read_csv(
        io.StringIO("\n".join(lines)),
        header=None,
        names=["duration", *[f"ari_{a}" for a in ARI_YEARS]],
    )
    frame["duration"] = frame["duration"].str.rstrip(":").str.strip()
    return frame.set_index("duration")


def build_atlas14_table(
    locations: pd.DataFrame,
    cache_dir: Path,
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
    pause_seconds: float = 0.3,
    progress: bool = True,
) -> pd.DataFrame:
    """
    Precipitation frequency estimates for every cell.

    Coordinates are rounded and deduplicated first, so a few hundred farms cost a
    few dozen requests rather than a few hundred. `pause_seconds` keeps us from
    hammering a public NOAA service.

    Returns cell_id, duration, and one column per ARI.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / "atlas14_points.parquet"

    locs = locations[["cell_id", lat_col, lon_col]].copy()
    locs["klat"] = locs[lat_col].round(COORD_PRECISION)
    locs["klon"] = locs[lon_col].round(COORD_PRECISION)

    unique = locs[["klat", "klon"]].drop_duplicates().reset_index(drop=True)
    if progress:
        print(f"  {len(locs)} cells collapse to {len(unique)} Atlas 14 points")

    if cache.exists():
        points = pd.read_parquet(cache)
        have = set(zip(points["klat"], points["klon"], strict=True))
        todo = unique[~unique.apply(lambda r: (r["klat"], r["klon"]) in have, axis=1)]
    else:
        points, todo = pd.DataFrame(), unique

    frames = [points] if len(points) else []
    for i, row in enumerate(todo.itertuples(index=False), start=1):
        if progress and i % 10 == 0:
            print(f"    {i}/{len(todo)} ...", flush=True)
        try:
            est = fetch_point_estimates(row.klat, row.klon)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            warnings.warn(
                f"Atlas 14 lookup failed at ({row.klat}, {row.klon}): {exc}", stacklevel=2
            )
            continue

        est = est.loc[[d for d in KEEP_DURATIONS if d in est.index]].reset_index()
        est["klat"], est["klon"] = row.klat, row.klon
        frames.append(est)
        time.sleep(pause_seconds)

    if not frames:
        raise RuntimeError("No Atlas 14 estimates retrieved. Check hdsc.nws.noaa.gov is reachable.")

    points = pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=["klat", "klon", "duration"], keep="last"
    )
    points.to_parquet(cache, index=False)

    return locs[["cell_id", "klat", "klon"]].merge(points, on=["klat", "klon"], how="left")


def depth_to_return_period(
    depth_mm: np.ndarray | pd.Series,
    curve: np.ndarray,
    ari_years: tuple[int, ...] = ARI_YEARS,
) -> np.ndarray:
    """
    Convert an observed rainfall depth into "this is a 1-in-N year storm here".

    Interpolation is linear in LOG return period, because recurrence intervals
    are geometric - the gap from 1 to 2 years is the same kind of step as 50 to
    100, and interpolating linearly in years would badly distort the middle.

    Depths below the 1-year value return a return period below 1, which is the
    honest answer: rain that common is not an event. Depths above the 1000-year
    value are capped there rather than extrapolated, because the tail beyond the
    published range is not something this table can support.
    """
    depth = np.asarray(pd.to_numeric(depth_mm, errors="coerce"), dtype=float)
    curve = np.asarray(curve, dtype=float)

    if np.isnan(curve).any():
        return np.full_like(depth, np.nan)

    log_ari = np.log(np.asarray(ari_years, dtype=float))
    out = np.interp(depth, curve, log_ari, left=np.nan, right=log_ari[-1])

    # Below the 1-year depth: scale down proportionally so the measure stays
    # continuous and monotonic instead of jumping to missing.
    below = depth < curve[0]
    out[below] = np.log(np.maximum(depth[below] / max(curve[0], 1e-9), 1e-3))

    return np.exp(out)


def add_return_period(
    wide: pd.DataFrame,
    atlas: pd.DataFrame,
    depth_col: str = "max_1day_mm",
    duration: str = "24-hr",
    out_col: str = "rain_ari_years",
) -> pd.DataFrame:
    """
    Add "how rare is this rain, here" to a wide feature table.

    This is the column that replaces tuned millimetre thresholds. It is directly
    comparable between a coastal farm and a hillside one, which raw depth is not.
    """
    ari_cols = [f"ari_{a}" for a in ARI_YEARS]
    curves = atlas[atlas["duration"] == duration].set_index("cell_id")[ari_cols]

    out = wide.copy()
    values = np.full(len(out), np.nan)

    for cell_id, idx in out.groupby("cell_id", sort=False).indices.items():
        if cell_id not in curves.index:
            continue
        values[idx] = depth_to_return_period(
            out[depth_col].to_numpy()[idx], curves.loc[cell_id].to_numpy()
        )

    out[out_col] = values
    return out


def summarize(atlas: pd.DataFrame, duration: str = "24-hr") -> pd.DataFrame:
    """How much the design storm varies across the farms we actually cover."""
    sel = atlas[atlas["duration"] == duration]
    rows = []
    for ari in (1, 2, 5, 10, 25, 100):
        col = f"ari_{ari}"
        if col not in sel.columns:
            continue
        rows.append(
            {
                "storm": f"{ari}-year {duration}",
                "min mm": round(float(sel[col].min()), 1),
                "median mm": round(float(sel[col].median()), 1),
                "max mm": round(float(sel[col].max()), 1),
                "spread": f"{100 * (sel[col].max() / max(sel[col].min(), 1e-9) - 1):.0f}%",
            }
        )
    return pd.DataFrame(rows)
