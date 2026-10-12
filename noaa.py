"""
Real NOAA weather, at 1 km, daily. The end of the synthetic data.

THE SOURCE
----------
NOAA's Analysis of Record for Calibration (AORC): a gridded reconstruction of
near-surface weather for the whole continental US, hourly, 1979 to present.

  spacing   0.00833 degrees = about 0.92 km      <- genuinely 1 km, as you asked
  cadence   hourly (we sum/aggregate to daily)
  variables precipitation, temperature, humidity, wind, radiation, pressure
  format    Zarr on AWS, free, no login
  cost      about half a second per month for Connecticut

We take three variables:
    APCP_surface       hourly precipitation, kg/m^2 (which is the same as mm)
    TMP_2maboveground  hourly air temperature at 2 m, in Kelvin

and turn them into daily `precip_mm`, `tmax_c` and `tmin_c`.

READ THIS BEFORE YOU BELIEVE THE "1 KM"
---------------------------------------
The grid is 1 km. The *information* is not.

AORC is built by taking real gauge and radar observations and spreading them onto
a fine grid using terrain-aware interpolation. Connecticut has on the order of a
few dozen daily reporting rain gauges. Interpolation cannot invent rainfall detail
between them, so two farms 1 km apart will get nearly identical values from this
product - not because their rainfall is identical, but because nothing measured
the difference.

This matters directly for your project's central claim. If the selling point is
location precision, that precision cannot come from the rainfall field. It has to
come from the things that genuinely do vary at 1 km and that we DO know per cell:

    soil water capacity   sandy vs loamy, next field over
    terrain               slope, aspect, where water collects
    crop                  hay copes with a dry spell; lettuce does not

Rainfall tells you the regional weather. Those three tell you what it does to a
particular field. Be precise about that distinction when you write this up - it is
a strength of the design, not a weakness, but only if you state it accurately.

TIME ZONES
----------
AORC timestamps are UTC. A "day" of rainfall in UTC is shifted five hours from a
day in Connecticut, which would smear an evening thunderstorm into the wrong date.
We convert to America/New_York before aggregating, so a daily total means what a
farmer would mean by it.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

AORC_BUCKET = "noaa-nws-aorc-v1-1-1km"
AORC_FIRST_YEAR = 1979
LOCAL_TZ = "America/New_York"

# Variables we pull from AORC and what they become.
PRECIP_VAR = "APCP_surface"
TEMP_VAR = "TMP_2maboveground"


def _open_year(year: int):
    """Open one year of AORC straight from AWS, without downloading the whole thing."""
    import s3fs
    import xarray as xr

    fs = s3fs.S3FileSystem(anon=True)
    store = s3fs.S3Map(f"{AORC_BUCKET}/{year}.zarr", s3=fs)
    return xr.open_zarr(store, consolidated=True)


def extract_year(
    year: int,
    locations: pd.DataFrame,
    bbox: tuple[float, float, float, float],
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
) -> pd.DataFrame:
    """
    Pull one year of daily weather for every grid cell.

    Returns wide daily data: cell_id, date, precip_mm, tmax_c, tmin_c.

    The trick that makes this fast is slicing to Connecticut *before* asking for
    any numbers. Zarr only fetches the blocks that overlap the region, so we move
    a few megabytes instead of the whole continent.
    """
    import xarray as xr

    ds = _open_year(year)

    min_lon, min_lat, max_lon, max_lat = bbox
    region = ds.sel(latitude=slice(min_lat, max_lat), longitude=slice(min_lon, max_lon))

    # Nearest grid cell to each of our cell centres.
    pt_lat = xr.DataArray(locations[lat_col].to_numpy(), dims="point")
    pt_lon = xr.DataArray(locations[lon_col].to_numpy(), dims="point")
    picked = region[[PRECIP_VAR, TEMP_VAR]].sel(latitude=pt_lat, longitude=pt_lon, method="nearest")

    hourly = picked.compute()

    # UTC -> local, so a "day" means a Connecticut day.
    times = pd.to_datetime(hourly["time"].values).tz_localize("UTC").tz_convert(LOCAL_TZ)
    local_day = pd.DatetimeIndex(times).tz_localize(None).normalize()

    precip = pd.DataFrame(hourly[PRECIP_VAR].values, index=local_day)
    temp_c = pd.DataFrame(hourly[TEMP_VAR].values, index=local_day) - 273.15

    daily_precip = precip.groupby(level=0).sum()
    daily_tmax = temp_c.groupby(level=0).max()
    daily_tmin = temp_c.groupby(level=0).min()

    frames = []
    for i, cell_id in enumerate(locations["cell_id"].to_numpy()):
        frames.append(
            pd.DataFrame(
                {
                    "cell_id": cell_id,
                    "date": daily_precip.index,
                    "precip_mm": daily_precip[i].to_numpy().round(2),
                    "tmax_c": daily_tmax[i].to_numpy().round(2),
                    "tmin_c": daily_tmin[i].to_numpy().round(2),
                }
            )
        )

    out = pd.concat(frames, ignore_index=True)

    # The first and last local day of a year are incomplete, because the UTC file
    # does not cover the full local day. Dropping them avoids fake dry days at
    # every year boundary - a subtle error that would show up as an annual cycle
    # in the anomalies.
    edges = {out["date"].min(), out["date"].max()}
    return out[~out["date"].isin(edges)].reset_index(drop=True)


def fetch_aorc(
    locations: pd.DataFrame,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    bbox: tuple[float, float, float, float],
    cache_dir: Path,
    progress: bool = True,
) -> pd.DataFrame:
    """
    Daily precipitation and temperature for every cell, across a range of years.

    Each year is cached as a parquet file, so re-running costs nothing. Returns
    wide daily data: cell_id, date, precip_mm, tmax_c, tmin_c.
    """
    from ctwater.data.grid import locations_fingerprint

    start, end = pd.Timestamp(start), pd.Timestamp(end)
    cache_dir.mkdir(parents=True, exist_ok=True)
    fp = locations_fingerprint(locations)

    frames: list[pd.DataFrame] = []
    for year in range(start.year, end.year + 1):
        if year < AORC_FIRST_YEAR:
            warnings.warn(f"AORC begins in {AORC_FIRST_YEAR}; skipping {year}.", stacklevel=2)
            continue

        cached = cache_dir / f"aorc_{year}_{fp}.parquet"
        if cached.exists():
            frames.append(pd.read_parquet(cached))
            if progress:
                print(f"  {year}  (cached)")
            continue

        if progress:
            print(f"  {year}  downloading ...", flush=True)
        try:
            year_df = extract_year(year, locations, bbox)
        except Exception as exc:  # a missing year should not kill a long run
            warnings.warn(f"Could not fetch AORC {year}: {exc}", stacklevel=2)
            continue

        year_df.to_parquet(cached, index=False)
        frames.append(year_df)

    if not frames:
        raise RuntimeError(
            "No AORC data could be fetched. Check your internet connection, then try "
            "one year by hand in a notebook to see the underlying error."
        )

    obs = pd.concat(frames, ignore_index=True)
    obs = obs[(obs["date"] >= start) & (obs["date"] <= end)]
    return obs.sort_values(["cell_id", "date"]).reset_index(drop=True)


def to_tidy(wide: pd.DataFrame) -> pd.DataFrame:
    """
    Reshape to the four-column contract every loader in this project honours.

    Note the explicit `datetime64[ns]` cast. Pandas keeps whatever time precision a
    source happened to use, and AORC arrives in microseconds while the Drought
    Monitor arrives in nanoseconds. Merging across two precisions fails with a
    genuinely baffling error about "incompatible merge keys". Pinning the precision
    here, at the point data enters the project, means no downstream code has to
    know or care - which is the whole purpose of having a contract.
    """
    value_cols = [c for c in wide.columns if c not in ("cell_id", "date")]
    tidy = wide.melt(
        id_vars=["cell_id", "date"],
        value_vars=value_cols,
        var_name="variable",
        value_name="value",
    )
    tidy["date"] = pd.to_datetime(tidy["date"]).astype("datetime64[ns]")
    return tidy[["cell_id", "date", "variable", "value"]]


def summarize(wide: pd.DataFrame) -> pd.DataFrame:
    """
    A sanity table you should actually read before trusting a download.

    Connecticut reality to check against: roughly 1,100-1,300 mm of precipitation
    a year, fairly evenly spread across months, with summer highs near 28 C and
    winter lows below freezing. If the numbers below are far from that, something
    is wrong with the extraction, not with Connecticut.
    """
    wide = wide.copy()
    wide["year"] = pd.to_datetime(wide["date"]).dt.year

    annual = wide.groupby(["cell_id", "year"])["precip_mm"].sum().groupby("cell_id").mean()
    rows = []
    for cell_id, mean_annual in annual.items():
        cell = wide[wide["cell_id"] == cell_id]
        rows.append(
            {
                "cell_id": cell_id,
                "mean annual precip mm": round(float(mean_annual)),
                "wettest day mm": round(float(cell["precip_mm"].max()), 1),
                "dry days %": round(100 * float((cell["precip_mm"] < 0.2).mean()), 1),
                "tmax high C": round(float(cell["tmax_c"].max()), 1),
                "tmin low C": round(float(cell["tmin_c"].min()), 1),
            }
        )
    return pd.DataFrame(rows)


def gridded_precision_warning(locations: pd.DataFrame, obs: pd.DataFrame) -> str:
    """
    Measure how different the rainfall actually is between your cells.

    This quantifies the caveat in this module's docstring. If the average
    difference between two cells' daily rainfall is tiny, then the 1 km grid is
    carrying regional weather, not field-scale weather, and your location
    precision must come from soil, terrain and crop instead.
    """
    wide = obs.pivot_table(index="date", columns="cell_id", values="precip_mm")
    if wide.shape[1] < 2:
        return "Only one cell - nothing to compare."

    corr = wide.corr().to_numpy()
    off_diag = corr[~np.eye(corr.shape[0], dtype=bool)]

    annual = wide.resample("YE").sum().mean()
    spread = float(annual.max() - annual.min())

    return (
        f"Between-cell daily rainfall correlation: {off_diag.mean():.2f} "
        f"(1.00 would mean every cell gets identical rain).\n"
        f"Spread in mean annual total across your {wide.shape[1]} cells: {spread:.0f} mm."
    )
