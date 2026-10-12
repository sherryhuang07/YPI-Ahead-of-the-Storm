"""
NOAA GEFS: a real forecast for the first ten days.

WHY THIS IS THE HIGHEST-VALUE THING TO ADD
------------------------------------------
`modeling/rainfall.py` measured where rainfall predictability ends when the only
input is rainfall history:

    1 day  +26.6%    3 days  +8.2%    7 days  -1.5%    30 days  -3.2%

Useful skill stops at three days. But that is not a fact about the atmosphere -
it is a fact about our inputs. That model has no pressure, no wind, no upper-air,
no physics: it is pattern-matching a rain gauge against itself.

NOAA already runs the physics. The Global Ensemble Forecast System integrates the
atmosphere forward with 31 perturbed members and publishes the result free. It
carries genuine skill to roughly 7-10 days, which is exactly the gap between what
rain history gives us (3 days) and where climatology has to take over.

So the operational forecast becomes a relay:

    days 1-10    GEFS         a real physical forecast
    days 11-30   analog years climatology, because nothing better exists

THE TRAP IN THESE FILES, WHICH COST AN HOUR AND WOULD HAVE COST MORE
--------------------------------------------------------------------
GEFS precipitation files interleave TWO overlapping accumulation windows. Reading
the raw GRIB messages in order:

    message 0    startStep 0   endStep 3     0-3h
    message 1    startStep 0   endStep 6     0-6h    <- contains message 0
    message 2    startStep 6   endStep 9     6-9h
    message 3    startStep 6   endStep 12    6-12h   <- contains message 2

cfgrib indexes messages by `endStep`, so it hands back all 80 steps as though
they were a clean 3-hourly series. Summing them double-counts every three-hour
bucket and INFLATES RAINFALL BY 1.53x. Measured at Hartford for 1 August 2017:

    all 80 steps                32.4 mm    wrong
    steps divisible by 6        21.1 mm    correct, 40 non-overlapping windows

Nothing about the wrong number looks wrong. It is the right order of magnitude
and it sits closer to the observed 37 mm than the correct value does, so a
sanity check against observations would have ENDORSED the bug. The only way to
catch it is to read `startStep` and `endStep` and notice the windows overlap.

Hence `SIX_HOUR_ONLY` below, and hence the test that pins it.

TIME ZONES, AGAIN
-----------------
GEFS steps are hours after a 00Z initialisation, so they are UTC. AORC
observations in this project were converted to America/New_York before daily
aggregation. Mixing the two would shift forecast rain by four or five hours
against observed rain - small, but it would smear exactly the storm timing the
wet model cares about. The conversion happens here, at the boundary, for the same
reason the tidy contract pins datetime precision there.

WHAT THE REFORECAST BUYS THAT REAL-TIME CANNOT
----------------------------------------------
Real-time GEFS only lets us BUILD the pipeline. The GEFS v12 reforecast - the
same model rerun over 2000-2019 - lets us MEASURE whether it helps, using the
same walk-forward discipline as everything else here. A forecast system that has
never been scored against outcomes is a demo, not a product.

The reforecast has 5 members where real-time has 31, and is initialised once a
day at 00Z. Fewer members means a coarser probability estimate; it is still
enough to ask whether GEFS beats replayed climatology at day 5.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests

REFORECAST_URL = "https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast"
REALTIME_URL = "https://noaa-gefs-pds.s3.amazonaws.com"

# The reforecast publishes a control run plus four perturbed members.
REFORECAST_MEMBERS = ("c00", "p01", "p02", "p03", "p04")

# ONLY the six-hour accumulation windows. See the module docstring: the files
# also contain three-hour windows nested INSIDE these, and summing both inflates
# rainfall by about half again.
SIX_HOUR_ONLY = 6

# Connecticut, with a margin so the 0.25 degree grid brackets every farm.
CT_BOUNDS = {"lat_min": 40.7, "lat_max": 42.3, "lon_min": -73.9, "lon_max": -71.6}

LOCAL_TZ = "America/New_York"


def _member_url(date: pd.Timestamp, member: str, days: str = "Days:1-10") -> str:
    stamp = f"{date:%Y%m%d}00"
    return f"{REFORECAST_URL}/{date:%Y}/{stamp}/{member}/{days}/apcp_sfc_{stamp}_{member}.grib2"


def fetch_member_grib(
    date: pd.Timestamp, member: str, cache_dir: Path, timeout: int = 900
) -> Path | None:
    """Download one member's day 1-10 precipitation file, cached on disk."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"apcp_{date:%Y%m%d}_{member}.grib2"
    if path.exists() and path.stat().st_size > 1000:
        return path

    url = _member_url(date, member)
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        warnings.warn(f"GEFS {date:%Y-%m-%d} {member} unavailable: {exc}", stacklevel=2)
        return None

    path.write_bytes(resp.content)
    return path


def read_member_daily(
    grib_path: Path,
    locations: pd.DataFrame,
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
) -> pd.DataFrame:
    """
    Turn one member's GRIB into daily rainfall per farm, in local time.

    Returns cell_id, valid_date, precip_mm.
    """
    import cfgrib

    # cfgrib does NOT return one dataset per file. The control member comes back
    # as a single dataset of 80 steps; the perturbed members come back as TWO -
    # a stray single-step dataset with no `step` dimension at all, plus the
    # remaining 79. Taking `datasets[0]` silently worked for c00 and dropped
    # every perturbed member, leaving a "5-member ensemble" with one member in
    # it. So we gather steps from EVERY dataset instead of trusting the layout.
    datasets = cfgrib.open_datasets(str(grib_path), backend_kwargs={"indexpath": ""})
    if not datasets:
        raise RuntimeError(f"cfgrib returned no datasets for {grib_path.name}")

    lat_grid = datasets[0]["latitude"].values
    lon_grid = datasets[0]["longitude"].values
    lat_mask = (lat_grid >= CT_BOUNDS["lat_min"] - 0.5) & (lat_grid <= CT_BOUNDS["lat_max"] + 0.5)
    lon_mask = (lon_grid >= CT_BOUNDS["lon_min"] % 360 - 0.5) & (
        lon_grid <= CT_BOUNDS["lon_max"] % 360 + 0.5
    )
    lat_idx, lon_idx = np.where(lat_mask)[0], np.where(lon_mask)[0]

    # step-hours -> (valid_time, Connecticut slab). Keyed by step so a step that
    # appears in more than one dataset cannot be counted twice.
    slabs: dict[int, tuple[pd.Timestamp, np.ndarray]] = {}
    for ds in datasets:
        da = ds["tp"]
        steps = np.atleast_1d(ds["step"].values)
        valid = np.atleast_1d(ds["valid_time"].values)
        block = da.values
        if "step" not in da.dims:
            block = block[np.newaxis, ...]

        for k, raw_step in enumerate(steps):
            hours = int(raw_step / 3.6e12)
            # ONLY the six-hour windows - the three-hour ones are nested inside
            # them and summing both inflates rainfall by 1.53x.
            if hours % SIX_HOUR_ONLY != 0 or hours in slabs:
                continue
            slab = np.nan_to_num(block[k])[np.ix_(lat_idx, lon_idx)]
            slabs[hours] = (pd.Timestamp(valid[k]), slab)

    if not slabs:
        raise RuntimeError(
            f"{grib_path.name} has no 6-hour accumulation windows - the file layout "
            "has changed and the overlap logic must be re-checked."
        )

    hours_sorted = sorted(slabs)
    valid = pd.DatetimeIndex([slabs[h][0] for h in hours_sorted])
    values = np.stack([slabs[h][1] for h in hours_sorted])  # (step, lat, lon)

    # UTC -> local, so forecast days line up with observed days.
    local = valid.tz_localize("UTC").tz_convert(LOCAL_TZ).tz_localize(None)
    local_date = pd.Series(local).dt.normalize().to_numpy()

    grid_lat = lat_grid[lat_idx]
    grid_lon = lon_grid[lon_idx]

    rows = []
    for row in locations.itertuples(index=False):
        lat = getattr(row, lat_col)
        lon = getattr(row, lon_col) % 360
        i = int(np.abs(grid_lat - lat).argmin())
        j = int(np.abs(grid_lon - lon).argmin())

        series = pd.Series(values[:, i, j], index=local_date)
        daily = series.groupby(level=0).sum()
        rows.append(
            pd.DataFrame(
                {"cell_id": row.cell_id, "valid_date": daily.index, "precip_mm": daily.to_numpy()}
            )
        )

    out = pd.concat(rows, ignore_index=True)
    out["valid_date"] = pd.to_datetime(out["valid_date"]).astype("datetime64[ns]")
    return out


def fetch_gefs_ensemble(
    date: pd.Timestamp,
    locations: pd.DataFrame,
    cache_dir: Path,
    members: tuple[str, ...] = REFORECAST_MEMBERS,
    keep_grib: bool = False,
    progress: bool = True,
) -> pd.DataFrame:
    """
    All members for one initialisation, as daily rainfall per farm.

    Returns cell_id, forecast_date, valid_date, member, precip_mm. The per-farm
    result is cached as parquet - a few kilobytes against 27 MB of GRIB per
    member - so re-running is free and the raw files can be discarded.
    """
    date = pd.Timestamp(date).normalize()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"gefs_farms_{date:%Y%m%d}.parquet"
    if cached.exists():
        return pd.read_parquet(cached)

    frames = []
    for member in members:
        if progress:
            print(f"    {date:%Y-%m-%d} {member} ...", flush=True)
        path = fetch_member_grib(date, member, cache_dir / "grib")
        if path is None:
            continue
        try:
            daily = read_member_daily(path, locations)
        except (RuntimeError, OSError, ValueError) as exc:
            warnings.warn(f"Could not read {path.name}: {exc}", stacklevel=2)
            continue
        finally:
            if not keep_grib and path.exists():
                path.unlink(missing_ok=True)

        daily["member"] = member
        frames.append(daily)

    if not frames:
        raise RuntimeError(
            f"No GEFS members retrieved for {date:%Y-%m-%d}. "
            f"Check {_member_url(date, 'c00')} by hand."
        )

    out = pd.concat(frames, ignore_index=True)
    out["forecast_date"] = date
    out["lead_days"] = (out["valid_date"] - date).dt.days
    out = out[["cell_id", "forecast_date", "valid_date", "lead_days", "member", "precip_mm"]]
    out.to_parquet(cached, index=False)
    return out


def summarize(ensemble: pd.DataFrame) -> pd.DataFrame:
    """Ensemble spread by lead day - how confident is the forecast, and when?"""
    g = ensemble.groupby("lead_days")["precip_mm"]
    out = pd.DataFrame(
        {
            "mean_mm": g.mean(),
            "min_member": g.min(),
            "max_member": g.max(),
            "spread": g.std(),
        }
    ).round(2)
    return out.reset_index()


def score_against_observed(
    ensemble: pd.DataFrame, observed: pd.DataFrame, max_lead: int = 10
) -> pd.DataFrame:
    """
    Did GEFS actually beat replayed climatology at each lead day?

    This is the question the reforecast exists to answer. `observed` needs
    cell_id, date, precip_mm - the AORC record this project already holds.
    """
    obs = observed.rename(columns={"date": "valid_date"})[
        ["cell_id", "valid_date", "precip_mm"]
    ].rename(columns={"precip_mm": "observed_mm"})
    obs["valid_date"] = pd.to_datetime(obs["valid_date"]).astype("datetime64[ns]")

    mean_fc = (
        ensemble[ensemble["lead_days"].between(1, max_lead)]
        .groupby(["cell_id", "forecast_date", "valid_date", "lead_days"], as_index=False)[
            "precip_mm"
        ]
        .mean()
        .rename(columns={"precip_mm": "forecast_mm"})
    )
    merged = mean_fc.merge(obs, on=["cell_id", "valid_date"], how="inner")
    if merged.empty:
        return pd.DataFrame()

    merged["abs_error"] = (merged["forecast_mm"] - merged["observed_mm"]).abs()

    rows = []
    for lead, grp in merged.groupby("lead_days"):
        rows.append(
            {
                "lead_days": int(lead),
                "n": len(grp),
                "observed_mean_mm": grp["observed_mm"].mean(),
                "forecast_mean_mm": grp["forecast_mm"].mean(),
                "mae": grp["abs_error"].mean(),
                "corr": grp["forecast_mm"].corr(grp["observed_mm"]),
            }
        )
    return pd.DataFrame(rows).round(3)
