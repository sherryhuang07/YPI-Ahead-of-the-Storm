"""
MRMS: the sub-daily rainfall this project has never had.

THE GAP
-------
Every flood judgement here rests on DAILY rainfall. `rain_ari_years` asks how
rare a farm's 24-hour total is against its Atlas 14 curve, and the wet event
fires when that crosses a threshold.

Atlas 14 itself says why that is not enough. At these farms, 34% of a 10-year
day's rain can fall in a single HOUR and 65% within six. A flash flood is an
hourly phenomenon measured here with a daily instrument - 60 mm spread evenly
over a day is nothing, and 60 mm in ninety minutes closes roads.

MRMS closes that gap. NOAA's Multi-Radar Multi-Sensor system publishes
quantitative precipitation estimates on a 1.1 km grid every two minutes, and -
usefully for this project - publishes them already converted to AVERAGE
RECURRENCE INTERVALS at 30 minutes, 1, 3, 6, 12 and 24 hours, plus ARIMAX, the
worst of those durations at each pixel.

ARIMAX is exactly the quantity `atlas14.rain_ari_years` computes, except it does
not assume the storm lasted a day.

WHAT IT IS NOT GOOD FOR
-----------------------
The archive begins 2020-10-15. Six years is far too short to extend the analog
ensemble - nClimGrid gives 74 - and too short to retrain a flood model on, since
Connecticut's flood events are already scarce.

So MRMS is not another ensemble source. It is a MEASURING INSTRUMENT for a
specific question: how much does using daily rainfall cost us on the flood side?
If sub-daily rarity separates real flood days from ordinary wet days better than
daily rarity does, that difference is the price of the resolution we have been
working at, and it can be quantified rather than assumed.

VOLUME FORCES A TARGETED PULL
-----------------------------
720 files a day at 83 KB each is about 60 MB per day, or 130 GB for the archive.
Downloading it would be absurd for a question that only needs specific days. So
this module pulls a chosen cadence (hourly by default) on chosen dates - the days
the Weather Service recorded floods, plus controls - and nothing else.

UNITS ARE CHECKED, NOT ASSUMED
------------------------------
cfgrib reports the variable name and units as "unknown" because MRMS uses local
GRIB tables. The product name says recurrence interval in years, but this project
has been bitten four times by trusting metadata (groundwater sign, GEFS
overlapping windows, GHCN tenths-of-a-mm, a swapped Hargreaves argument), so
`verify_scale` checks the distribution against what a return period must look
like rather than taking the name at face value.
"""

from __future__ import annotations

import gzip
import os
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests

MRMS_BUCKET = "https://noaa-mrms-pds.s3.amazonaws.com"

# The archive on AWS begins here. Earlier MRMS exists but not in this bucket.
FIRST_DATE = pd.Timestamp("2020-10-15")

# ARIMAX: the worst recurrence interval across all durations at each pixel. The
# per-duration products are also available if a specific timescale is ever
# wanted.
PRODUCT = "FLASH_QPE_ARIMAX_00.00"

# Connecticut, with a margin.
CT_BOUNDS = {"lat_min": 40.8, "lat_max": 42.2, "lon_min": -73.9, "lon_max": -71.6}

# MRMS marks no-coverage with large negatives.
NODATA_BELOW = -1.0


def _key(date: pd.Timestamp, hour: int, minute: int = 0) -> str:
    stamp = f"{date:%Y%m%d}-{hour:02d}{minute:02d}00"
    return f"CONUS/{PRODUCT}/{date:%Y%m%d}/MRMS_{PRODUCT}_{stamp}.grib2.gz"


def fetch_frame(date: pd.Timestamp, hour: int, timeout: int = 300) -> tuple | None:
    """
    One 2-minute frame, subset to Connecticut.

    Returns (lats, lons, values) or None. Values are the recurrence interval in
    years at each 1.1 km pixel.
    """
    import cfgrib

    url = f"{MRMS_BUCKET}/{_key(date, hour)}"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        raw = gzip.decompress(resp.content)
    except (requests.RequestException, OSError, ValueError) as exc:
        warnings.warn(f"MRMS {date:%Y-%m-%d} {hour:02d}Z unavailable: {exc}", stacklevel=2)
        return None

    fd, path = tempfile.mkstemp(suffix=".grib2")
    try:
        os.write(fd, raw)
        os.close(fd)
        datasets = cfgrib.open_datasets(path, backend_kwargs={"indexpath": ""})
        if not datasets:
            return None
        ds = datasets[0]
        var = next(iter(ds.data_vars))

        lats = ds["latitude"].values
        lons = ds["longitude"].values - 360.0  # MRMS uses 0-360
        li = np.where((lats >= CT_BOUNDS["lat_min"]) & (lats <= CT_BOUNDS["lat_max"]))[0]
        lj = np.where((lons >= CT_BOUNDS["lon_min"]) & (lons <= CT_BOUNDS["lon_max"]))[0]
        if li.size == 0 or lj.size == 0:
            return None

        block = np.asarray(ds[var].values)[np.ix_(li, lj)].astype(float)
        block[block < NODATA_BELOW] = np.nan
        return lats[li], lons[lj], block
    finally:
        if os.path.exists(path):
            os.unlink(path)


def fetch_day_max(
    date: pd.Timestamp,
    locations: pd.DataFrame,
    hours: tuple[int, ...] = tuple(range(0, 24, 1)),
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
    cache_dir: Path | None = None,
) -> pd.DataFrame | None:
    """
    The worst recurrence interval each farm saw during one day.

    ARIMAX is already a running maximum across durations, so sampling hourly
    rather than every two minutes captures the peak of a storm while pulling a
    thirtieth of the data.
    """
    date = pd.Timestamp(date).normalize()
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / f"mrms_{date:%Y%m%d}.parquet"
        if cached.exists():
            return pd.read_parquet(cached)
    else:
        cached = None

    peak = None
    lats = lons = None
    for hour in hours:
        frame = fetch_frame(date, hour)
        if frame is None:
            continue
        lats, lons, block = frame
        peak = block if peak is None else np.fmax(peak, block)

    if peak is None:
        return None

    rows = []
    for row in locations.itertuples(index=False):
        i = int(np.abs(lats - getattr(row, lat_col)).argmin())
        j = int(np.abs(lons - getattr(row, lon_col)).argmin())
        rows.append({"cell_id": row.cell_id, "date": date, "mrms_ari_max": float(peak[i, j])})

    out = pd.DataFrame(rows)
    if cached is not None:
        out.to_parquet(cached, index=False)
    return out


def verify_scale(mrms: pd.DataFrame) -> str:
    """
    Does this look like a recurrence interval in years?

    cfgrib reports MRMS variables as "unknown" because the product uses local
    GRIB tables, so the units come from the product name and nothing else. A
    return period has a shape that can be checked: mostly at or near zero
    (ordinary weather is not rare), strictly non-negative, and with a long thin
    upper tail reaching tens of years on genuine storms.

    If the values were millimetres instead, the median would sit in single
    figures rather than at zero and the maximum would be in the hundreds.
    """
    v = mrms["mrms_ari_max"].dropna()
    if v.empty:
        return "no values to check"

    zero_ish = float((v < 0.1).mean())
    return "\n".join(
        [
            f"  n={len(v):,}  min {v.min():.2f}  median {v.median():.2f}  "
            f"p99 {v.quantile(0.99):.1f}  max {v.max():.1f}",
            f"  {100 * zero_ish:.0f}% of farm-days below 0.1 - ordinary weather is not rare",
            (
                "  shape is consistent with a recurrence interval in years"
                if v.min() >= 0 and zero_ish > 0.5 and v.max() > 5
                else "  SHAPE DOES NOT MATCH a return period - check the units"
            ),
        ]
    )


def compare_with_daily(
    mrms: pd.DataFrame, features: pd.DataFrame, storm_days: pd.DataFrame
) -> pd.DataFrame:
    """
    The question this module exists for.

    On the days the Weather Service recorded a flood, does sub-daily rarity
    separate them from ordinary days better than the daily rarity we have been
    using? Both are recurrence intervals in years, so they are directly
    comparable.
    """
    m = mrms.copy()
    m["date"] = pd.to_datetime(m["date"])

    f = features[["cell_id", "date", "rain_ari_years"]].copy()
    f["date"] = pd.to_datetime(f["date"])

    s = storm_days[["cell_id", "date"]].copy()
    s["date"] = pd.to_datetime(s["date"])
    s["flood"] = 1

    joined = m.merge(f, on=["cell_id", "date"], how="inner").merge(
        s, on=["cell_id", "date"], how="left"
    )
    joined["flood"] = joined["flood"].fillna(0)
    if joined.empty or joined["flood"].nunique() < 2:
        return pd.DataFrame()

    from sklearn.metrics import roc_auc_score

    rows = []
    for label, col in (
        ("daily (Atlas 14)", "rain_ari_years"),
        ("sub-daily (MRMS)", "mrms_ari_max"),
    ):
        sub = joined.dropna(subset=[col])
        if sub["flood"].nunique() < 2:
            continue
        flood = sub.loc[sub["flood"] == 1, col]
        calm = sub.loc[sub["flood"] == 0, col]
        rows.append(
            {
                "measure": label,
                "auc": round(float(roc_auc_score(sub["flood"], sub[col])), 3),
                "median on flood days": round(float(flood.median()), 2),
                "median on other days": round(float(calm.median()), 2),
                "separation": round(float(flood.median() - calm.median()), 2),
            }
        )
    return pd.DataFrame(rows)
