"""
NOAA Storm Events: a REAL flood label, at last.

WHY THIS CHANGES THE WET HALF OF THE PROJECT
--------------------------------------------
Every wet-risk number so far carried the same caveat: the target was DEFINED, not
observed. Drought has the U.S. Drought Monitor - a weekly expert judgment to
predict. Nothing equivalent existed for wetness, so `features/wet.py` invented a
rule from streamflow and rainfall and validated it as best it could against two
known floods.

Storm Events removes that caveat. The National Weather Service records every
flood it responds to: what type, when it began, where, and what it damaged. That
is an OBSERVED label, produced by people whose job is to notice floods, entirely
independent of any rule we wrote.

WHAT IS IN IT
-------------
Connecticut, 2023 alone: 94 flash floods and 15 floods. Each carries

    EVENT_TYPE        Flash Flood, Flood, Heavy Rain, Coastal Flood, Drought...
    BEGIN_DATE_TIME   when it started
    BEGIN_LAT/LON     a point location for most events
    CZ_NAME           the county, always
    DAMAGE_CROPS      dollars of CROP damage - agriculture, specifically
    DAMAGE_PROPERTY   dollars of property damage

`DAMAGE_CROPS` deserves attention. It is the only field anywhere in this project
that measures harm to farming directly, rather than a physical proxy for it.

THE TWO THINGS THIS LETS US DO
------------------------------
1. Train the wet model on observed events instead of a definition.
2. CHECK the definition. If our invented wet-risk rule fires on the days the NWS
   recorded floods, the rule was sound and the earlier results stand. If it does
   not, we learned something important and slightly painful.

Both matter. The second is arguably worth more, because it is the audit the wet
half of this project has been missing since it was built.

A LIMIT WORTH KNOWING
---------------------
Storm Events records what was REPORTED. A flood across empty farmland with nobody
to see it may never enter the database, while the same flood over a road gets
logged immediately. The record is therefore biased toward populated places - it
measures observed impact, not physical occurrence. That is a real bias, and it
argues for keeping the physical wet index alongside this rather than discarding
it: one measures what happened, the other what somebody noticed.
"""

from __future__ import annotations

import gzip
import io
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests

STORM_DIR = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"

# The full event set only begins in 1996; earlier years are tornado-heavy and
# would bias any label built from them.
FIRST_COMPLETE_YEAR = 1996

# Event types that mean "too much water" for a farm.
WET_EVENT_TYPES = ("Flash Flood", "Flood", "Heavy Rain", "Coastal Flood", "Lakeshore Flood")
# Storm Events also logs drought, which gives the dry half an independent check.
DRY_EVENT_TYPES = ("Drought", "Excessive Heat")

# How far from a reported point an event is treated as affecting a cell. Flash
# floods are local but the reported coordinate is a single point within a wider
# affected area, so a radius is more honest than an exact match.
DEFAULT_RADIUS_KM = 20.0

DAMAGE_MULTIPLIERS = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def _parse_damage(value: object) -> float:
    """
    Turn "1.50M" into 1500000.

    Returns 0.0 for blanks. Note that a recorded zero usually means "not
    estimated" rather than "no damage" - the NWS does not always cost an event -
    so treat the totals as a floor, never as a measurement.
    """
    if pd.isna(value):
        return 0.0
    text = str(value).strip().upper()
    if not text or text in {"0", "0.00K", "NAN"}:
        return 0.0

    suffix = text[-1]
    if suffix in DAMAGE_MULTIPLIERS:
        try:
            return float(text[:-1]) * DAMAGE_MULTIPLIERS[suffix]
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _year_file(index_html: str, year: int) -> str | None:
    """NOAA stamps filenames with a processing date, so we look it up rather than guess."""
    token = f"StormEvents_details-ftp_v1.0_d{year}_"
    for part in index_html.split('"'):
        if part.startswith(token) and part.endswith(".csv.gz"):
            return part
    return None


def fetch_storm_events(
    start_year: int,
    end_year: int,
    cache_dir: Path,
    state: str = "CONNECTICUT",
    timeout: int = 300,
    progress: bool = True,
) -> pd.DataFrame:
    """
    Download and cache the Storm Events record for one state.

    Each national year file is ~10-20 MB; we keep only the state's rows, so the
    cache stays tiny.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    index_html = requests.get(STORM_DIR, timeout=timeout).text

    frames: list[pd.DataFrame] = []
    for year in range(max(start_year, FIRST_COMPLETE_YEAR), end_year + 1):
        cached = cache_dir / f"storm_{state.lower()}_{year}.parquet"
        if cached.exists():
            frames.append(pd.read_parquet(cached))
            continue

        filename = _year_file(index_html, year)
        if filename is None:
            warnings.warn(f"No Storm Events file published for {year}.", stacklevel=2)
            continue

        if progress:
            print(f"  {year} ...", flush=True)
        try:
            raw = requests.get(STORM_DIR + filename, timeout=timeout).content
            national = pd.read_csv(
                io.BytesIO(gzip.decompress(raw)), low_memory=False, encoding_errors="replace"
            )
        except (requests.RequestException, OSError, ValueError) as exc:
            warnings.warn(f"Could not read Storm Events {year}: {exc}", stacklevel=2)
            continue

        keep = national[national["STATE"].astype(str).str.upper() == state.upper()].copy()
        if keep.empty:
            continue

        cols = [
            c
            for c in [
                "EVENT_ID",
                "EVENT_TYPE",
                "BEGIN_DATE_TIME",
                "END_DATE_TIME",
                "CZ_NAME",
                "BEGIN_LAT",
                "BEGIN_LON",
                "DAMAGE_PROPERTY",
                "DAMAGE_CROPS",
                "EVENT_NARRATIVE",
            ]
            if c in keep.columns
        ]
        keep = keep[cols]
        keep.to_parquet(cached, index=False)
        frames.append(keep)

    if not frames:
        raise RuntimeError(
            f"No Storm Events data retrieved for {state}. Check {STORM_DIR} is reachable."
        )

    events = pd.concat(frames, ignore_index=True)
    events["date"] = (
        pd.to_datetime(events["BEGIN_DATE_TIME"], format="%d-%b-%y %H:%M:%S", errors="coerce")
        .dt.normalize()
        .astype("datetime64[ns]")
    )
    events["damage_crops_usd"] = events["DAMAGE_CROPS"].map(_parse_damage)
    events["damage_property_usd"] = events["DAMAGE_PROPERTY"].map(_parse_damage)

    return events.dropna(subset=["date"]).reset_index(drop=True)


def select_wet_events(events: pd.DataFrame) -> pd.DataFrame:
    """Keep the events that mean too much water, and that have a usable location."""
    wet = events[events["EVENT_TYPE"].isin(WET_EVENT_TYPES)].copy()

    located = wet.dropna(subset=["BEGIN_LAT", "BEGIN_LON"])
    if len(located) < len(wet):
        warnings.warn(
            f"{len(wet) - len(located)} of {len(wet)} wet events have no coordinates and "
            "cannot be matched to a cell. They are dropped, which biases the label toward "
            "events the NWS pinpointed.",
            stacklevel=2,
        )
    return located.reset_index(drop=True)


def events_to_cell_days(
    events: pd.DataFrame,
    locations: pd.DataFrame,
    radius_km: float = DEFAULT_RADIUS_KM,
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
    crs_projected: str = "EPSG:6433",
) -> pd.DataFrame:
    """
    Turn point-located events into per-cell daily flags.

    An event is attributed to every cell within `radius_km`. Distances are
    computed in projected metres, never in degrees.

    Returns cell_id, date, storm_wet_event, storm_crop_damage_usd.
    """
    from pyproj import Transformer

    if events.empty:
        return pd.DataFrame(columns=["cell_id", "date", "storm_wet_event", "storm_crop_damage_usd"])

    tf = Transformer.from_crs("EPSG:4326", crs_projected, always_xy=True)
    cx, cy = tf.transform(locations[lon_col].to_numpy(), locations[lat_col].to_numpy())
    ex, ey = tf.transform(events["BEGIN_LON"].to_numpy(), events["BEGIN_LAT"].to_numpy())

    cells = locations["cell_id"].to_numpy()
    radius_m = radius_km * 1000.0

    rows = []
    for i in range(len(events)):
        dist = np.hypot(cx - ex[i], cy - ey[i])
        hit = dist <= radius_m
        if not hit.any():
            continue
        rows.append(
            pd.DataFrame(
                {
                    "cell_id": cells[hit],
                    "date": events["date"].iloc[i],
                    "storm_wet_event": 1,
                    "storm_crop_damage_usd": float(events["damage_crops_usd"].iloc[i]),
                }
            )
        )

    if not rows:
        return pd.DataFrame(columns=["cell_id", "date", "storm_wet_event", "storm_crop_damage_usd"])

    out = pd.concat(rows, ignore_index=True)
    # Several reports can describe one storm over one cell; collapse to a day.
    return (
        out.groupby(["cell_id", "date"], as_index=False)
        .agg(
            storm_wet_event=("storm_wet_event", "max"),
            storm_crop_damage_usd=("storm_crop_damage_usd", "sum"),
        )
        .sort_values(["cell_id", "date"])
        .reset_index(drop=True)
    )


def summarize(events: pd.DataFrame) -> pd.DataFrame:
    """What the record contains, by type."""
    wet = events[events["EVENT_TYPE"].isin(WET_EVENT_TYPES)]
    rows = []
    for etype, grp in wet.groupby("EVENT_TYPE"):
        rows.append(
            {
                "event type": etype,
                "count": len(grp),
                "with coordinates": int(grp["BEGIN_LAT"].notna().sum()),
                "crop damage $": f"{grp['damage_crops_usd'].sum():,.0f}",
            }
        )
    return pd.DataFrame(rows).sort_values("count", ascending=False)


def compare_with_defined_target(
    storm_days: pd.DataFrame, features: pd.DataFrame, window_days: int = 3
) -> str:
    """
    The audit: does our INVENTED wet rule fire when the NWS recorded a flood?

    This is the check the wet half of this project has never had. We built a
    definition from streamflow and rainfall and validated it against two known
    floods; here we test it against every flood the Weather Service logged.

    A day counts as agreeing if our `wet_event` flag is set within `window_days`
    of the reported event - storms cross midnight, and streamflow peaks a day
    late, so demanding an exact date match would understate agreement.
    """
    if "wet_event" not in features.columns:
        return "features have no `wet_event` column - run build first."

    f = features[["cell_id", "date", "wet_event"]].copy()
    f["date"] = pd.to_datetime(f["date"])

    # Widen our flag by +/- window days so near-misses in timing still count.
    f = f.sort_values(["cell_id", "date"])
    widened = (
        f.groupby("cell_id", sort=False)["wet_event"]
        .rolling(2 * window_days + 1, center=True, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
    )
    f["ours_nearby"] = widened

    merged = storm_days.merge(f, on=["cell_id", "date"], how="left")
    caught = float(merged["ours_nearby"].fillna(0).mean())

    base = float(f["wet_event"].mean())
    lift = caught / max(base, 1e-9)

    return (
        f"NWS recorded {len(storm_days):,} cell-days of flooding.\n"
        f"Our invented rule flags {100 * caught:.0f}% of them (within +/-{window_days} days).\n"
        f"It fires on {100 * base:.1f}% of all cell-days, so that is a {lift:.1f}x lift over "
        f"chance.\n"
        + (
            "The definition is picking up real floods."
            if lift > 3
            else "WEAK agreement - the definition may not be measuring what the NWS sees."
        )
    )
