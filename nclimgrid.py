"""
nClimGrid-Daily: gridded weather back to 1951, which is the missing middle.

THE GAP THIS FILLS
------------------
The forecast does not predict rainfall - it replays real past years at each farm.
That makes the LENGTH of the record the binding constraint on the ensemble, and
the two sources already in hand each solve only half the problem:

    source           resolution        span        ensemble members
    NOAA AORC        1 km grid         2000-2024   24, at every farm
    GHCN-Daily       point stations    to 122 yr   54 median, only near a gauge
    nClimGrid-Daily  4.6 km grid       1951-2026   75, at every farm

nClimGrid is gridded AND long. Every farm gets 75 analog years rather than 24,
without needing a century-old rain gauge next door.

That matters because end-to-end verification found the forecast OVERCONFIDENT -
it says 99% and is right 82% of the time - and diagnosed ensemble
UNDER-DISPERSION: two dozen past years do not span the weather that can actually
occur. Tripling the members is the direct attack on that, and it requires
predicting nothing.

WHY NOT PRISM
-------------
PRISM is the obvious alternative and is a fine dataset, but it is the wrong shape
for this particular need:

    PRISM daily      1981-present   44 years   shorter than nClimGrid
    PRISM monthly    1895-present   130 years  too coarse for an analog ensemble,
                                               which needs day-by-day sequencing

The analog ensemble lives or dies on SEQUENCING - 25 mm as one storm then three
dry weeks is a different month from 25 mm spread evenly - so monthly data cannot
serve it however long the record. nClimGrid-Daily is chosen because it is the
longest DAILY gridded record available, not because PRISM is worse. PRISM monthly
remains a good independent cross-check on the climatology if one is ever wanted.

DOWNLOADING 53 GB WOULD BE THE WRONG WAY TO DO THIS
---------------------------------------------------
The files are monthly CONUS NetCDF at 58 MB each; 1951-2024 is about 900 of them,
roughly 53 GB. But NCEI serves them over OPeNDAP, which subsets server-side.

Connecticut is roughly 29 x 45 cells of a 596 x 1385 grid - 0.16% of each file.
Fetching only that window turns 53 GB into about 85 MB and makes the whole record
practical to hold locally.

UNITS ARE CHECKED, NOT ASSUMED
------------------------------
Same discipline as the GHCN loader, and for the same reason: this project has
been bitten three times by silent unit and convention errors (groundwater sign,
GEFS overlapping windows, GHCN tenths-of-a-mm). `verify_units` compares annual
totals against the AORC record already held rather than trusting the metadata.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

THREDDS = "https://www.ncei.noaa.gov/thredds/dodsC/nclimgrid-daily"

# nClimGrid-Daily begins in 1951.
FIRST_YEAR = 1951

# Connecticut with a margin, so the 4.6 km grid brackets every farm.
CT_BOUNDS = {"lat_min": 40.7, "lat_max": 42.3, "lon_min": -73.9, "lon_max": -71.6}

VARIABLES = ("prcp", "tmax", "tmin")


def _month_url(year: int, month: int) -> str:
    return f"{THREDDS}/{year}/ncdd-{year}{month:02d}-grd-scaled.nc"


def fetch_month(
    year: int,
    month: int,
    locations: pd.DataFrame,
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
) -> pd.DataFrame | None:
    """
    One month of gridded daily weather, sampled at each farm.

    The spatial subset happens SERVER-SIDE via OPeNDAP - only the Connecticut
    window crosses the network, not the whole of CONUS.
    """
    import xarray as xr

    try:
        ds = xr.open_dataset(_month_url(year, month))
    except (OSError, ValueError, KeyError) as exc:
        warnings.warn(f"nClimGrid {year}-{month:02d} unavailable: {exc}", stacklevel=2)
        return None

    try:
        window = ds.sel(
            lat=slice(CT_BOUNDS["lat_min"], CT_BOUNDS["lat_max"]),
            lon=slice(CT_BOUNDS["lon_min"], CT_BOUNDS["lon_max"]),
        )
        keep = [v for v in VARIABLES if v in window.data_vars]
        if not keep:
            return None
        # Pull the window once; sampling per farm from memory is far cheaper
        # than one remote read per farm.
        block = window[keep].load()
    except (OSError, ValueError, KeyError) as exc:
        warnings.warn(f"nClimGrid {year}-{month:02d} subset failed: {exc}", stacklevel=2)
        return None
    finally:
        ds.close()

    lats = block["lat"].values
    lons = block["lon"].values
    times = pd.to_datetime(block["time"].values)

    rows = []
    for row in locations.itertuples(index=False):
        i = int(np.abs(lats - getattr(row, lat_col)).argmin())
        j = int(np.abs(lons - getattr(row, lon_col)).argmin())
        frame = {"cell_id": row.cell_id, "date": times}
        for v in keep:
            frame[f"{v}_raw"] = block[v].values[:, i, j]
        rows.append(pd.DataFrame(frame))

    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).astype("datetime64[ns]")
    return out


def build_nclimgrid_daily(
    locations: pd.DataFrame,
    start_year: int = FIRST_YEAR,
    end_year: int = 2024,
    cache_dir: Path | None = None,
    progress: bool = True,
) -> pd.DataFrame:
    """
    The whole record at every farm, cached one year at a time.

    Caching per year means an interrupted run resumes where it stopped rather
    than starting the 900-request loop again.
    """
    frames = []
    for year in range(max(start_year, FIRST_YEAR), end_year + 1):
        cached = cache_dir / f"nclimgrid_{year}.parquet" if cache_dir else None
        if cached is not None and cached.exists():
            frames.append(pd.read_parquet(cached))
            continue

        months = []
        for month in range(1, 13):
            part = fetch_month(year, month, locations)
            if part is not None:
                months.append(part)

        if not months:
            warnings.warn(f"nClimGrid {year} produced no data.", stacklevel=2)
            continue

        year_df = pd.concat(months, ignore_index=True)
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            year_df.to_parquet(cached, index=False)
        frames.append(year_df)

        if progress:
            print(f"  {year}: {len(year_df):,} farm-days", flush=True)

    if not frames:
        raise RuntimeError(f"No nClimGrid data retrieved. Check {THREDDS} is reachable.")
    return pd.concat(frames, ignore_index=True)


def verify_units(gridded: pd.DataFrame, aorc: pd.DataFrame) -> tuple[float, str]:
    """
    Confirm the precipitation scale against rainfall we already trust.

    The file name says "grd-scaled", which is a standing invitation to guess
    wrong. Annual totals per farm are compared against AORC over the overlapping
    years, and the divisor that makes them agree is the one used.
    """
    g = gridded.dropna(subset=["prcp_raw"]).copy()
    g["year"] = g["date"].dt.year
    per = g.groupby(["cell_id", "year"])["prcp_raw"].agg(["sum", "size"])
    per = per[per["size"] >= 330]
    if per.empty:
        return 1.0, "no complete farm-years to compare; assuming millimetres"
    grid_annual = per.groupby("year")["sum"].mean()

    a = aorc.copy()
    a["date"] = pd.to_datetime(a["date"])
    a["year"] = a["date"].dt.year
    aorc_annual = a.groupby(["cell_id", "year"])["precip_mm"].sum().groupby("year").mean()

    shared = grid_annual.index.intersection(aorc_annual.index)
    if len(shared) < 3:
        return 1.0, "too few overlapping years; assuming millimetres"

    ratio = float(grid_annual.loc[shared].mean() / aorc_annual.loc[shared].mean())
    if 0.5 < ratio < 2:
        return 1.0, f"totals are {ratio:.2f}x AORC - already millimetres"
    if 5 < ratio < 20:
        return 10.0, f"totals are {ratio:.1f}x AORC - tenths of a millimetre"

    warnings.warn(
        f"nClimGrid totals are {ratio:.2f}x AORC, matching neither scale. Units are NOT confirmed.",
        stacklevel=2,
    )
    return 1.0, f"UNRESOLVED: totals are {ratio:.2f}x AORC"


def to_si(gridded: pd.DataFrame, divisor: float = 1.0) -> pd.DataFrame:
    """Apply the confirmed divisor and name the columns as the rest of the project does."""
    out = gridded.copy()
    out["precip_mm"] = out["prcp_raw"] / divisor
    for raw, name in (("tmax_raw", "tmax_c"), ("tmin_raw", "tmin_c")):
        if raw in out.columns:
            out[name] = out[raw]  # temperature is already Celsius
    cols = ["cell_id", "date", "precip_mm"] + [c for c in ("tmax_c", "tmin_c") if c in out.columns]
    return out[cols]


def ensemble_gain(gridded_si: pd.DataFrame, min_days: int = 330) -> pd.DataFrame:
    """
    How many usable analog years this actually delivers, per farm.

    Counted the same way as the GHCN loader: a year missing three months is not
    a usable analog, so completeness is measured rather than record length
    quoted.
    """
    g = gridded_si.dropna(subset=["precip_mm"]).copy()
    g["year"] = g["date"].dt.year
    counts = g.groupby(["cell_id", "year"]).size().rename("days").reset_index()
    usable = counts[counts["days"] >= min_days]

    per_farm = usable.groupby("cell_id")["year"].agg(["size", "min", "max"])
    per_farm.columns = ["usable_years", "first", "last"]
    return per_farm.reset_index()


def compare_with_aorc(gridded_si: pd.DataFrame, aorc: pd.DataFrame) -> pd.DataFrame:
    """
    Do the two gridded products agree where they overlap?

    AORC is 1 km and nClimGrid is 4.6 km, built by different methods from
    overlapping but not identical station networks. Broad agreement is the check;
    the disagreement is worth seeing before either is trusted alone.
    """
    g = gridded_si.copy()
    g["year"] = g["date"].dt.year
    a = aorc.copy()
    a["date"] = pd.to_datetime(a["date"])
    a["year"] = a["date"].dt.year

    ga = g.groupby(["cell_id", "year"])["precip_mm"].sum().groupby("year").mean()
    aa = a.groupby(["cell_id", "year"])["precip_mm"].sum().groupby("year").mean()

    shared = sorted(set(ga.index) & set(aa.index))
    if not shared:
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "year": shared,
            "nclimgrid_mm": ga.loc[shared].to_numpy(),
            "aorc_mm": aa.loc[shared].to_numpy(),
        }
    )
    out["difference_pct"] = (100 * (out["nclimgrid_mm"] - out["aorc_mm"]) / out["aorc_mm"]).round(1)
    return out.round(0)
