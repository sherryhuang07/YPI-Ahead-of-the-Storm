"""
Groundwater: the slowest and longest-memory reservoir in the system.

WHY THIS MATTERS FOR DROUGHT
----------------------------
Water sits in three places, and they empty at very different speeds:

    the soil        days to weeks    - already have it, from the bucket model
    the streams     weeks to months  - already have it, from USGS gauges
    the aquifer     months to YEARS  - this file

Drought is a cumulative deficit, and groundwater is the most cumulative thing we
can measure. A single wet week barely moves a water table; two dry summers move
it a long way and it stays moved. That makes it the closest thing to a direct
reading of the deficit the drought model is trying to anticipate.

It is also what farmers actually experience. Connecticut's 2022 drought had
growers reporting ponds two feet low and neighbours out of water entirely, and
dairy farms trucking water in. Those are aquifer problems, not rainfall problems.

WHETHER IT HELPS FLOODS IS AN OPEN QUESTION
-------------------------------------------
Physically it should help far less: an aquifer cannot respond to a three-hour
downpour, and flooding is intensity and timing. But a full aquifer means a
saturated landscape with nowhere to put new rain, which is a real flood
precondition. So it is offered to the wet model too and judged on results rather
than on the argument.

THE SIGN CONVENTION - GET THIS WRONG AND EVERYTHING INVERTS
-----------------------------------------------------------
USGS reports "depth to water level": how far DOWN from the land surface the water
table sits, in feet. So a BIGGER number means a LOWER water table, which means
DRIER. That is the opposite direction from every other signal in this project,
where bigger means wetter.

We therefore flip it on the way in and emit `gw_level_ft = -depth`, so that:

    higher value  =  higher water table  =  wetter
    negative z    =  unusually low water =  drought

matching rainfall, streamflow and soil moisture. Leaving it unflipped would still
train - trees do not care about sign - but every anomaly would read backwards to a
human, and the dry/wet feature split would be reasoning about the wrong direction.

WELLS ARE NOT COMPARABLE RAW
----------------------------
One well sits 4 feet below the surface, another 40. Averaging those raw numbers
is meaningless. Each well is standardised against its OWN history first - median
and inter-quartile range, computed strictly before `climatology_end` so no future
information sets the scale - and only then blended across wells.
"""

from __future__ import annotations

import io
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests

SITE_URL = "https://waterservices.usgs.gov/nwis/site/"
DV_URL = "https://waterservices.usgs.gov/nwis/dv/"

# Depth to water level below land surface, in feet.
DEPTH_PARAM = "72019"
# USGS publishes max/min/mean as separate series; we want the daily mean.
MEAN_STAT = "00003"

DEFAULT_N_WELLS = 3
DEFAULT_MAX_DISTANCE_KM = 60.0  # wider than streamflow: only 12 wells statewide


def fetch_well_inventory(state: str = "ct", timeout: int = 180) -> pd.DataFrame:
    """Every groundwater well in a state that publishes a DAILY record."""
    params = {
        "format": "rdb",
        "stateCd": state,
        "siteType": "GW",
        "hasDataTypeCd": "dv",
        "siteStatus": "active",
        "siteOutput": "expanded",
    }
    resp = requests.get(SITE_URL, params=params, timeout=timeout)
    resp.raise_for_status()

    body = "\n".join(line for line in resp.text.splitlines() if not line.startswith("#"))
    raw = pd.read_csv(io.StringIO(body), sep="\t", dtype=str).iloc[1:]

    out = pd.DataFrame(
        {
            "site_no": raw["site_no"].str.strip(),
            "station_nm": raw["station_nm"].str.strip(),
            "lat": pd.to_numeric(raw["dec_lat_va"], errors="coerce"),
            "lon": pd.to_numeric(raw["dec_long_va"], errors="coerce"),
        }
    )
    return out.dropna(subset=["lat", "lon"]).reset_index(drop=True)


def fetch_daily_levels(
    site_nos: list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    timeout: int = 300,
) -> pd.DataFrame:
    """
    Daily water-table level for a list of wells.

    Returns site_no, date, gw_level_ft - already flipped so higher means wetter.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    params = {
        "format": "json",
        "sites": ",".join(site_nos),
        "parameterCd": DEPTH_PARAM,
        "statCd": MEAN_STAT,
        "startDT": start.strftime("%Y-%m-%d"),
        "endDT": end.strftime("%Y-%m-%d"),
        "siteStatus": "all",
    }
    try:
        resp = requests.get(DV_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(
            f"Groundwater request failed for {len(site_nos)} wells: {type(exc).__name__}: {exc}"
        ) from exc

    frames = []
    for series in payload.get("value", {}).get("timeSeries", []):
        site = series["sourceInfo"]["siteCode"][0]["value"]
        values = series.get("values", [{}])[0].get("value", [])
        if not values:
            continue

        df = pd.DataFrame(values)
        depth = pd.to_numeric(df["value"], errors="coerce")
        depth[depth <= -100] = np.nan  # USGS no-data sentinel

        frames.append(
            pd.DataFrame(
                {
                    "site_no": site,
                    "date": pd.to_datetime(df["dateTime"]).dt.tz_localize(None).dt.normalize(),
                    # THE FLIP. Depth is measured downward; we want higher = wetter.
                    "gw_level_ft": -depth.to_numpy(),
                }
            )
        )

    if not frames:
        raise RuntimeError(
            "No groundwater levels returned. Test by hand: "
            "https://waterservices.usgs.gov/nwis/dv/?format=json&sites=411832072325501"
            "&parameterCd=72019&startDT=2022-08-01&endDT=2022-08-05"
        )

    out = pd.concat(frames, ignore_index=True).dropna(subset=["gw_level_ft"])
    return out.sort_values(["site_no", "date"]).reset_index(drop=True)


def standardize_per_well(levels: pd.DataFrame, climatology_end: str | pd.Timestamp) -> pd.DataFrame:
    """
    Put every well on a common scale before blending.

    One well swings four feet a year and another forty; their raw numbers cannot
    be averaged. Each is centred on its own median and divided by its own
    inter-quartile range - robust statistics, so a single stuck reading cannot
    distort the scale.

    Both constants come from data strictly BEFORE `climatology_end`, so nothing
    from the evaluation period sets the scale. Wells with no usable history are
    dropped rather than standardised against the future.
    """
    end = pd.Timestamp(climatology_end)
    hist = levels[levels["date"] < end]

    stats = hist.groupby("site_no")["gw_level_ft"].agg(
        med="median", q25=lambda s: s.quantile(0.25), q75=lambda s: s.quantile(0.75)
    )
    stats["iqr"] = (stats["q75"] - stats["q25"]).replace(0, np.nan)

    usable = stats.dropna(subset=["iqr"])
    dropped = set(levels["site_no"].unique()) - set(usable.index)
    if dropped:
        warnings.warn(
            f"{len(dropped)} wells have no usable pre-{end.date()} history and were dropped.",
            stacklevel=2,
        )

    out = levels[levels["site_no"].isin(usable.index)].merge(
        usable[["med", "iqr"]], left_on="site_no", right_index=True, how="left"
    )
    out["gw_standardized"] = (out["gw_level_ft"] - out["med"]) / out["iqr"]
    return out.drop(columns=["med", "iqr"])


def build_groundwater_observations(
    locations: pd.DataFrame,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    cache_dir: Path,
    climatology_end: str | pd.Timestamp,
    n_wells: int = DEFAULT_N_WELLS,
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    state: str = "ct",
    progress: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    The one call the pipeline makes. Returns (tidy observations, well assignment).

    Emits a single variable, `groundwater_z` - the distance-weighted blend of the
    nearest wells' standardised levels. Negative means an unusually low water
    table for that well: the deepest and slowest drought signal available.
    """
    from ctwater.data.usgs import assign_gauges_to_cells

    cache_dir.mkdir(parents=True, exist_ok=True)
    inv_path = cache_dir / "well_inventory.parquet"

    if inv_path.exists():
        inventory = pd.read_parquet(inv_path)
    else:
        if progress:
            print("  fetching well inventory ...")
        inventory = fetch_well_inventory(state)
        inventory.to_parquet(inv_path, index=False)

    # Reuse the streamflow matcher: same problem, same inverse-distance answer.
    # It expects a drainage column, which wells do not have, so we supply a
    # constant - basin size is meaningless for a well.
    wells = inventory.copy()
    wells["drainage_sqmi"] = 0.0

    pairs = assign_gauges_to_cells(
        locations, wells, n_gauges=n_wells, max_distance_km=max_distance_km
    )

    site_nos = sorted(pairs["site_no"].unique())
    lvl_path = cache_dir / f"levels_{pd.Timestamp(start).year}_{pd.Timestamp(end).year}.parquet"

    if lvl_path.exists():
        levels = pd.read_parquet(lvl_path)
        if progress:
            print(f"  {len(site_nos)} wells (cached)")
    else:
        if progress:
            print(f"  downloading daily levels for {len(site_nos)} wells ...")
        levels = fetch_daily_levels(site_nos, start, end)
        levels.to_parquet(lvl_path, index=False)

    levels = standardize_per_well(levels, climatology_end)

    merged = pairs[["cell_id", "site_no", "weight"]].merge(levels, on="site_no", how="inner")
    merged["weighted"] = merged["gw_standardized"] * merged["weight"]

    grp = merged.groupby(["cell_id", "date"])
    composite = (grp["weighted"].sum() / grp["weight"].sum()).reset_index(name="value")

    composite["variable"] = "groundwater_z"
    composite["date"] = pd.to_datetime(composite["date"]).astype("datetime64[ns]")
    tidy = composite[["cell_id", "date", "variable", "value"]].sort_values(["cell_id", "date"])

    return tidy.reset_index(drop=True), pairs


def drought_response_check(tidy: pd.DataFrame) -> str:
    """
    Does the water table actually fall during droughts that really happened?

    A groundwater signal that does not drop in 2016 and 2022 - Connecticut's two
    worst recent droughts - would be measuring something other than drought.
    """
    s = tidy.pivot_table(index="date", columns="cell_id", values="value")

    def mean_for(period: str) -> float:
        try:
            return float(s.loc[period].mean().mean())
        except KeyError:
            return float("nan")

    rows = []
    for label, period in [
        ("Sep 2016 — severe drought", "2016-09"),
        ("Sep 2022 — severe drought", "2022-09"),
        ("Sep 2021 — wet year", "2021-09"),
        ("Sep 2023 — flood year", "2023-09"),
    ]:
        v = mean_for(period)
        if np.isfinite(v):
            rows.append(f"  {label:28s} {v:+.2f}")

    return "Standardised water table (negative = unusually low):\n" + "\n".join(rows)
