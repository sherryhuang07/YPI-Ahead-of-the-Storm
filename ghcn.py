"""
GHCN-Daily: a century of real rain gauges, instead of predicting rain ourselves.

WHY THIS, AND WHY NOW
---------------------
The forecast does not predict rainfall. It replays what actually happened at each
farm in the same week of past years and runs every one through that farm's soil.
That design is sound, and it has one hard limit: the AORC record we pull covers
2000-2024, so the ensemble is capped at 24 members.

End-to-end verification found the specific consequence. The forecast beats
climatology (Brier skill +0.267) and is OVERCONFIDENT at every level - it says
99% and is right 82% of the time. The diagnosis was ensemble UNDER-DISPERSION:
two dozen past years at one location do not span the range of weather that could
actually occur, so the members agree with each other more than reality warrants.

GHCN-Daily is the fix that does not require predicting anything. Connecticut has
454 stations, and the longest daily precipitation records run:

    142 years   USC00065445  Norfolk 2 SW      1884-present
    138 years   USC00068138
    129 years   USC00064767
    121 years   USC00068065

A century of real gauge observations means an ensemble of a hundred members
rather than twenty-four - drawn from actual weather, including droughts and
floods nobody alive has planned around.

THE UNIT TRAP, CHECKED RATHER THAN ASSUMED
------------------------------------------
GHCN stores precipitation in TENTHS OF A MILLIMETRE and temperature in tenths of
a degree Celsius. A day with 25 mm of rain is stored as 250.

Getting that wrong inflates rainfall tenfold, and a tenfold error is actually
easier to catch than a subtle one. The dangerous version is the opposite: NCEI's
CSV service sometimes serves already-converted values, so blindly dividing by ten
would make every storm a drizzle and every drought look permanent. This project
has been bitten by exactly this shape of error twice - the groundwater sign
convention and the GEFS accumulation windows - so `verify_units` checks against
the AORC record we already hold rather than trusting either assumption.

WHAT IT IS AND IS NOT GOOD FOR
------------------------------
  GOOD    Long records at fixed points. Real instruments, not a model. The
          natural way to extend the analog ensemble backwards.

  NOT     Spatial coverage. A station measures one point; AORC estimates every
          square kilometre. Stations also move, close, and change instruments,
          and a "142-year record" usually has gaps - Norfolk's 142 years hold
          31,226 daily observations where a complete record would hold ~51,800.

So GHCN does not replace AORC. It extends it in time at the places where
somebody has been holding a rain gauge for a century.
"""

from __future__ import annotations

import io
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests

GHCN_ROOT = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
STATION_CSV = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access"

# New England plus the edges of neighbouring states that drain into it.
NEW_ENGLAND_STATES = ("CT", "MA", "RI", "NY")

# A station needs at least this many years of precipitation to be worth pulling
# for the analog ensemble - fewer and it adds little the AORC record lacks.
MIN_RECORD_YEARS = 60

# GHCN stores PRCP in tenths of a millimetre and TMAX/TMIN in tenths of a degree.
TENTHS = 10.0


def fetch_station_inventory(
    states: tuple[str, ...] = NEW_ENGLAND_STATES,
    element: str = "PRCP",
    min_years: int = MIN_RECORD_YEARS,
    timeout: int = 600,
) -> pd.DataFrame:
    """
    Stations in the region with a long record of one element.

    Two files, joined: `ghcnd-stations.txt` has the coordinates,
    `ghcnd-inventory.txt` has which elements each station recorded and between
    which years.
    """
    stations = requests.get(f"{GHCN_ROOT}/ghcnd-stations.txt", timeout=timeout).text
    inventory = requests.get(f"{GHCN_ROOT}/ghcnd-inventory.txt", timeout=timeout).text

    # Both are fixed-width. The layouts are published and stable.
    srows = []
    for line in stations.splitlines():
        if len(line) < 72:
            continue
        state = line[38:40].strip()
        if state not in states:
            continue
        srows.append(
            {
                "station": line[0:11].strip(),
                "lat": float(line[12:20]),
                "lon": float(line[21:30]),
                "elev_m": float(line[31:37]),
                "state": state,
                "name": line[41:71].strip(),
            }
        )
    site = pd.DataFrame(srows)

    irows = []
    for line in inventory.splitlines():
        if len(line) < 45 or line[31:35].strip() != element:
            continue
        irows.append(
            {
                "station": line[0:11].strip(),
                "first_year": int(line[36:40]),
                "last_year": int(line[41:45]),
            }
        )
    inv = pd.DataFrame(irows)

    if site.empty or inv.empty:
        raise RuntimeError(
            f"No {element} stations found for {states}. Check {GHCN_ROOT} is reachable."
        )

    out = site.merge(inv, on="station", how="inner")
    out["record_years"] = out["last_year"] - out["first_year"]
    out = out[out["record_years"] >= min_years]
    return out.sort_values("record_years", ascending=False).reset_index(drop=True)


def fetch_station_daily(station: str, cache_dir: Path, timeout: int = 600) -> pd.DataFrame | None:
    """
    One station's full daily record, in SI units.

    Returns station, date, precip_mm, tmax_c, tmin_c. Values are divided by ten
    only after `verify_units` has confirmed the raw file really is in tenths.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{station}.parquet"
    if cached.exists():
        return pd.read_parquet(cached)

    try:
        resp = requests.get(f"{STATION_CSV}/{station}.csv", timeout=timeout)
        resp.raise_for_status()
        raw = pd.read_csv(io.BytesIO(resp.content), low_memory=False)
    except (requests.RequestException, ValueError) as exc:
        warnings.warn(f"GHCN station {station} unavailable: {exc}", stacklevel=2)
        return None

    # GHCN QUALITY FLAGS ARE NOT OPTIONAL.
    #
    # `PRCP_ATTRIBUTES` is "measurement,quality,source,time". A NON-BLANK quality
    # flag means NOAA's own checks rejected that value, and ingesting it anyway
    # is taking data the publisher has already disowned.
    #
    # It matters at the tail, which is the part this dataset exists to supply. A
    # single station reported 736 mm in one day - roughly 2.5x Connecticut's
    # record - with no corroboration from any neighbour. By contrast the
    # 1955-08-19 cluster (461, 336, 324, 291, 273 mm at five separate stations)
    # is Hurricane Diane and is entirely real. Flags separate the two; magnitude
    # alone does not.
    keep = {"DATE": "date", "PRCP": "precip_raw", "TMAX": "tmax_raw", "TMIN": "tmin_raw"}
    present = {k: v for k, v in keep.items() if k in raw.columns}
    if "DATE" not in present or "PRCP" not in present:
        warnings.warn(f"GHCN station {station} has no PRCP column.", stacklevel=2)
        return None

    out = raw[list(present)].rename(columns=present)
    out["station"] = station
    out["date"] = pd.to_datetime(out["date"], errors="coerce").astype("datetime64[ns]")
    for col in ("precip_raw", "tmax_raw", "tmin_raw"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    # Drop anything NOAA's quality assurance rejected, element by element.
    for elem, col in (("PRCP", "precip_raw"), ("TMAX", "tmax_raw"), ("TMIN", "tmin_raw")):
        attr = f"{elem}_ATTRIBUTES"
        if col not in out.columns or attr not in raw.columns:
            continue
        qflag = raw[attr].astype(str).str.split(",").str[1].fillna("").str.strip()
        rejected = qflag.ne("") & out[col].notna()
        if rejected.any():
            out.loc[rejected, col] = np.nan

    out = out.dropna(subset=["date"]).reset_index(drop=True)
    out.to_parquet(cached, index=False)
    return out


def verify_units(station_daily: pd.DataFrame, aorc: pd.DataFrame) -> tuple[float, str]:
    """
    Work out the divisor by COMPARING to rainfall we already trust.

    GHCN documents tenths of a millimetre, but NCEI's CSV service sometimes
    serves converted values, and guessing wrong changes every storm by a factor
    of ten in one direction or the other. Rather than trust the documentation or
    the service, this compares annual totals against the AORC record over their
    overlapping years and picks the divisor that agrees.

    Returns (divisor, explanation).
    """
    s = station_daily.dropna(subset=["precip_raw"]).copy()
    s["year"] = s["date"].dt.year
    a = aorc.copy()
    a["year"] = pd.to_datetime(a["date"]).dt.year

    # Only station-years with most days recorded, so gaps do not masquerade as a
    # dry climate. Note the grouping is by STATION AND YEAR: an earlier version
    # grouped by year alone, which silently summed every station together and
    # reported totals 220x AORC when 46 stations were passed in. It gave the
    # right answer for a single station and the wrong one for many - which is
    # why the ratio guard below exists rather than a bare assumption.
    per = s.groupby(["station", "year"])["precip_raw"].agg(["sum", "size"])
    per = per[per["size"] >= 330]
    if per.empty:
        return TENTHS, "no complete station-years to compare; defaulting to tenths of a mm"
    station_annual = per.groupby("year")["sum"].mean()

    aorc_annual = a.groupby("year")["precip_mm"].sum() / max(a["cell_id"].nunique(), 1)
    shared = station_annual.index.intersection(aorc_annual.index)
    if len(shared) < 3:
        return TENTHS, "too few overlapping complete years; defaulting to tenths of a mm"

    raw_ratio = float(station_annual.loc[shared].mean() / aorc_annual.loc[shared].mean())

    # Connecticut averages roughly 1200 mm a year. If the raw totals are ~10x
    # that, the file is in tenths; if they are about right, it is already mm.
    if 5 < raw_ratio < 20:
        return TENTHS, f"raw totals are {raw_ratio:.1f}x AORC — the file is in tenths of a mm"
    if 0.5 < raw_ratio < 2:
        return 1.0, f"raw totals are {raw_ratio:.2f}x AORC — the file is already in mm"

    warnings.warn(
        f"GHCN totals are {raw_ratio:.2f}x AORC, which matches neither tenths nor "
        "millimetres. Units are NOT confirmed; treat the values with suspicion.",
        stacklevel=2,
    )
    return TENTHS, f"UNRESOLVED: raw totals are {raw_ratio:.2f}x AORC"


def to_si(station_daily: pd.DataFrame, divisor: float = TENTHS) -> pd.DataFrame:
    """Apply the confirmed divisor and drop the raw columns."""
    out = station_daily.copy()
    out["precip_mm"] = out["precip_raw"] / divisor
    if "tmax_raw" in out.columns:
        out["tmax_c"] = out["tmax_raw"] / divisor
    if "tmin_raw" in out.columns:
        out["tmin_c"] = out["tmin_raw"] / divisor

    cols = ["station", "date", "precip_mm"] + [c for c in ("tmax_c", "tmin_c") if c in out.columns]
    return out[cols]


def assign_stations_to_farms(
    locations: pd.DataFrame,
    stations: pd.DataFrame,
    n_stations: int = 3,
    max_distance_km: float = 40.0,
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
    crs_projected: str = "EPSG:6433",
) -> pd.DataFrame:
    """
    Nearest long-record stations for each farm, with inverse-distance weights.

    Unlike stream gauges, rain gauges do NOT need to share a watershed - rain
    falls across drainage divides, and a station five kilometres away over a
    ridge is measuring much the same storms. The watershed constraint that
    matters for streamflow would be wrong here.
    """
    from pyproj import Transformer

    tf = Transformer.from_crs("EPSG:4326", crs_projected, always_xy=True)
    cx, cy = tf.transform(locations[lon_col].to_numpy(), locations[lat_col].to_numpy())
    sx, sy = tf.transform(stations["lon"].to_numpy(), stations["lat"].to_numpy())

    rows = []
    for i, cell_id in enumerate(locations["cell_id"].to_numpy()):
        dist_km = np.hypot(sx - cx[i], sy - cy[i]) / 1000.0
        order = np.argsort(dist_km)[:n_stations]
        for j in order:
            if dist_km[j] > max_distance_km:
                continue
            rows.append(
                {
                    "cell_id": cell_id,
                    "station": stations.iloc[j]["station"],
                    "name": stations.iloc[j]["name"],
                    "record_years": int(stations.iloc[j]["record_years"]),
                    "distance_km": round(float(dist_km[j]), 1),
                }
            )

    pairs = pd.DataFrame(rows)
    if pairs.empty:
        raise ValueError(f"No farm found a station within {max_distance_km} km.")

    pairs["weight"] = 1.0 / pairs["distance_km"].clip(lower=1.0)
    pairs["weight"] = pairs["weight"] / pairs.groupby("cell_id")["weight"].transform("sum")
    return pairs


def compare_with_aorc(station_si: pd.DataFrame, aorc: pd.DataFrame) -> pd.DataFrame:
    """
    Do the gauges and the gridded product agree where they overlap?

    AORC is a model-based reanalysis; GHCN is an instrument in a field. Where
    both exist they should broadly agree, and where they do not, the disagreement
    is worth knowing before either is trusted alone.
    """
    s = station_si.copy()
    s["year"] = s["date"].dt.year
    a = aorc.copy()
    a["date"] = pd.to_datetime(a["date"])
    a["year"] = a["date"].dt.year

    counts = s.groupby("year")["precip_mm"].size()
    full = counts[counts >= 330].index
    sa = s[s["year"].isin(full)].groupby("year")["precip_mm"].sum()
    aa = a.groupby("year")["precip_mm"].sum() / max(a["cell_id"].nunique(), 1)

    shared = sorted(set(sa.index) & set(aa.index))
    if not shared:
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "year": shared,
            "station_mm": sa.loc[shared].to_numpy(),
            "aorc_mm": aa.loc[shared].to_numpy(),
        }
    )
    out["difference_%"] = (100 * (out["station_mm"] - out["aorc_mm"]) / out["aorc_mm"]).round(1)
    return out.round(0)


def ensemble_years_available(station_si: pd.DataFrame, min_days: int = 330) -> pd.DataFrame:
    """
    How many past years can actually serve as ensemble members?

    A year missing three months is not a usable analog, so completeness is
    counted rather than assumed. This is the number that decides whether the
    ensemble grows from 24 members to something that fixes its under-dispersion.
    """
    s = station_si.dropna(subset=["precip_mm"]).copy()
    s["year"] = s["date"].dt.year
    counts = s.groupby(["station", "year"]).size().rename("days").reset_index()
    usable = counts[counts["days"] >= min_days]

    return (
        usable.groupby("station")
        .agg(usable_years=("year", "size"), first=("year", "min"), last=("year", "max"))
        .sort_values("usable_years", ascending=False)
        .reset_index()
    )
