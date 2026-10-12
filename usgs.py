"""
USGS stream gauges: what the rivers say about how dry it is.

WHY STREAMFLOW IS WORTH HAVING
------------------------------
Rainfall tells you what fell. Streamflow tells you what the landscape did with it,
and it carries a much longer memory. After a wet autumn, soils and shallow
groundwater stay charged, streams run high, and a dry June hurts far less. After a
dry autumn there is nothing in the bank. A river integrates months of that history
into one number every day, which is exactly the slow-moving signal a 30-day drought
forecast needs and daily rainfall cannot supply.

It is also the channel that human Drought Monitor authors watch closely, so it may
carry information about how the LABEL gets drawn as well as about the weather.

THE MISTAKE TO AVOID: BASIN SIZE
--------------------------------
A gauge does not measure the river at that spot. It measures everything upstream.

    Connecticut River at Thompsonville   9,660 sq mi
    Housatonic River at Stevenson        1,544 sq mi
    Bunnell Brook near Burlington            4.1 sq mi
    Fivemile River near New Canaan           1.0 sq mi

The Connecticut River gauge is mostly reporting snowmelt and rainfall in Vermont,
New Hampshire and Massachusetts. Its flow can be high while Connecticut farms are
parched. Using it as a Connecticut drought signal would be close to meaningless -
and worse, it would look reasonable, because the numbers are real and the gauge is
genuinely nearby.

Small headwater basins are the opposite: a 4 sq mi brook responds to rain that fell
within a few miles, over days. That is a local drought signal.

So we filter by drainage area. `max_drainage_sqmi` defaults to 100, which keeps 50
of Connecticut's 71 active gauges and throws away the big rivers whose water comes
from other states.

WHAT WE EMIT, AND WHY IT IS A LOGARITHM
---------------------------------------
Streamflow is roughly log-normal: a river might run at 5 cubic feet per second in
a drought and 5,000 in a flood. On a raw scale, one flood swamps every statistic,
and a z-score is meaningless. On a log scale the distribution is close to symmetric
and the anomalies behave.

We emit `streamflow_log10`, a distance-weighted average across the nearest few
qualifying gauges. The absolute value is not directly meaningful - what matters is
how it compares to normal for that place and week of year, and the existing
climatology machinery computes exactly that, fit on the training period only. So
streamflow gets the same leak-safe treatment as rainfall, with no new code.
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
DISCHARGE_PARAM = "00060"  # discharge in cubic feet per second

# Above this, a gauge is integrating water from too far away to say anything about
# local Connecticut conditions. See the module docstring.
DEFAULT_MAX_DRAINAGE_SQMI = 100.0

# How many nearby gauges to blend per cell, and how far we will reach for them.
DEFAULT_N_GAUGES = 3
DEFAULT_MAX_DISTANCE_KM = 40.0


def fetch_gauge_inventory(state: str = "ct", timeout: int = 180) -> pd.DataFrame:
    """
    Every active stream gauge in a state that reports daily discharge.

    Returns site_no, station_nm, lat, lon, drainage_sqmi.
    """
    params = {
        "format": "rdb",
        "stateCd": state,
        "siteType": "ST",
        "parameterCd": DISCHARGE_PARAM,
        "hasDataTypeCd": "dv",
        "siteStatus": "active",
        "siteOutput": "expanded",
    }
    resp = requests.get(SITE_URL, params=params, timeout=timeout)
    resp.raise_for_status()

    # RDB format: comment lines start with #, then a header row, then a row of
    # column-width codes we have to skip.
    body = "\n".join(line for line in resp.text.splitlines() if not line.startswith("#"))
    raw = pd.read_csv(io.StringIO(body), sep="\t", dtype=str).iloc[1:]

    out = pd.DataFrame(
        {
            "site_no": raw["site_no"].str.strip(),
            "station_nm": raw["station_nm"].str.strip(),
            "lat": pd.to_numeric(raw["dec_lat_va"], errors="coerce"),
            "lon": pd.to_numeric(raw["dec_long_va"], errors="coerce"),
            "drainage_sqmi": pd.to_numeric(raw["drain_area_va"], errors="coerce"),
            # USGS already knows which watershed each gauge drains. Carrying it
            # here is what lets `assign_gauges_to_cells` prefer a gauge on the
            # farm's OWN river rather than merely a nearby one.
            "huc8": raw["huc_cd"].str.strip().str[:8] if "huc_cd" in raw else None,
        }
    )
    return out.dropna(subset=["lat", "lon"]).reset_index(drop=True)


def select_local_gauges(
    inventory: pd.DataFrame, max_drainage_sqmi: float = DEFAULT_MAX_DRAINAGE_SQMI
) -> pd.DataFrame:
    """
    Keep only gauges whose basins are small enough to reflect LOCAL conditions.

    Gauges with no reported drainage area are dropped rather than assumed small -
    an unknown basin could be the Connecticut River, and a wrong guess here
    quietly poisons the feature for every cell that uses it.
    """
    known = inventory.dropna(subset=["drainage_sqmi"])
    dropped_unknown = len(inventory) - len(known)

    keep = known[known["drainage_sqmi"] <= max_drainage_sqmi].copy()

    if dropped_unknown:
        warnings.warn(
            f"{dropped_unknown} gauges have no drainage area on record and were dropped "
            "rather than assumed local.",
            stacklevel=2,
        )
    if keep.empty:
        raise ValueError(
            f"No gauges under {max_drainage_sqmi} sq mi. Raise max_drainage_sqmi, but "
            "understand that large basins carry out-of-state water."
        )
    return keep.sort_values("drainage_sqmi").reset_index(drop=True)


def assign_gauges_to_cells(
    locations: pd.DataFrame,
    gauges: pd.DataFrame,
    n_gauges: int = DEFAULT_N_GAUGES,
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
    crs_projected: str = "EPSG:6433",
    farm_basins: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Match each grid cell to its nearest few qualifying gauges.

    Returns cell_id, site_no, distance_km, weight - one row per cell-gauge pair.
    Weights are inverse-distance, so a gauge two miles away counts for more than
    one twenty miles away.

    Distances are computed in a projected coordinate system, in metres. Never in
    raw degrees - a degree of longitude is not a degree of latitude, and the error
    would be systematic rather than random.
    """
    from pyproj import Transformer

    # PREFER GAUGES ON THE FARM'S OWN RIVER.
    #
    # Choosing by distance alone was wrong from the beginning, and the watershed
    # assignment made it measurable. Of the gauge-farm pairs picked purely by
    # distance, only 73% sat in the same USGS subbasin - and it was wildly uneven:
    #
    #     Long Island Sound     0% in-basin
    #     Thames               28%
    #     Pawcatuck            33%
    #     Shetucket            97%
    #
    # For a Thames-basin farm, nearly three quarters of its streamflow signal was
    # measuring a river it does not drain into. A gauge five kilometres away
    # across a divide is a different water system; one thirty kilometres upstream
    # on your own river is the water about to reach you.
    #
    # When `farm_basins` is supplied, candidates are restricted to the farm's own
    # subbasin. Farms with no in-basin gauge inside `max_distance_km` fall back
    # to nearest-by-distance, because a related-but-imperfect signal beats none -
    # and the fallback is counted so the cost is visible rather than silent.
    basin_of_cell: dict[str, str] = {}
    if farm_basins is not None and "huc8" in gauges.columns:
        basin_of_cell = dict(zip(farm_basins["cell_id"], farm_basins["huc8"], strict=False))

    tf = Transformer.from_crs("EPSG:4326", crs_projected, always_xy=True)
    cx, cy = tf.transform(locations[lon_col].to_numpy(), locations[lat_col].to_numpy())
    gx, gy = tf.transform(gauges["lon"].to_numpy(), gauges["lat"].to_numpy())

    rows = []
    gauge_basins = gauges["huc8"].to_numpy() if "huc8" in gauges.columns else None
    fell_back = 0

    for i, cell_id in enumerate(locations["cell_id"].to_numpy()):
        dist_km = np.hypot(gx - cx[i], gy - cy[i]) / 1000.0

        # Restrict to the farm's own subbasin when we know it. If that leaves
        # nothing within range, fall back to nearest-by-distance and count it -
        # a related-but-imperfect signal beats none, but the cost is recorded
        # rather than hidden.
        candidates = np.arange(len(dist_km))
        home = basin_of_cell.get(cell_id)
        if home is not None and gauge_basins is not None:
            same = np.where((gauge_basins == home) & (dist_km <= max_distance_km))[0]
            if same.size:
                candidates = same
            else:
                fell_back += 1

        order = candidates[np.argsort(dist_km[candidates])][:n_gauges]

        for j in order:
            if dist_km[j] > max_distance_km:
                continue
            rows.append(
                {
                    "cell_id": cell_id,
                    "site_no": gauges.iloc[j]["site_no"],
                    "station_nm": gauges.iloc[j]["station_nm"],
                    "drainage_sqmi": float(gauges.iloc[j]["drainage_sqmi"]),
                    "distance_km": round(float(dist_km[j]), 1),
                }
            )

    pairs = pd.DataFrame(rows)
    if pairs.empty:
        raise ValueError(
            f"No cell found a gauge within {max_distance_km} km. Widen max_distance_km "
            "or relax max_drainage_sqmi."
        )

    # Inverse distance, with a floor so a gauge sitting almost on top of a cell
    # does not get infinite weight.
    pairs["weight"] = 1.0 / pairs["distance_km"].clip(lower=1.0)
    pairs["weight"] = pairs["weight"] / pairs.groupby("cell_id")["weight"].transform("sum")

    missing = set(locations["cell_id"]) - set(pairs["cell_id"])
    if missing:
        warnings.warn(
            f"{len(missing)} cells have no gauge within {max_distance_km} km and will have "
            "no streamflow feature.",
            stacklevel=2,
        )
    if fell_back:
        warnings.warn(
            f"{fell_back} farms had no gauge in their own subbasin within "
            f"{max_distance_km} km and fell back to nearest-by-distance. Their "
            "streamflow signal measures a neighbouring river system.",
            stacklevel=2,
        )
    return pairs


def fetch_daily_flow(
    site_nos: list[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    batch_size: int = 20,
    timeout: int = 300,
) -> pd.DataFrame:
    """
    Daily mean discharge for a list of gauges.

    Returns site_no, date, discharge_cfs. USGS accepts many sites per request, so
    we batch rather than making one call per gauge.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    frames: list[pd.DataFrame] = []
    failures: list[str] = []

    for i in range(0, len(site_nos), batch_size):
        batch = site_nos[i : i + batch_size]
        params = {
            "format": "json",
            "sites": ",".join(batch),
            "parameterCd": DISCHARGE_PARAM,
            "startDT": start.strftime("%Y-%m-%d"),
            "endDT": end.strftime("%Y-%m-%d"),
            "siteStatus": "all",
        }
        try:
            resp = requests.get(DV_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            # Keep the real cause. An earlier version only warned and then raised a
            # generic "no data returned", which sent us hunting a parsing bug when
            # the actual problem was a transient network failure. An error message
            # that hides its cause costs more time than the failure itself.
            detail = f"sites {batch[0]}..{batch[-1]}: {type(exc).__name__}: {exc}"
            failures.append(detail)
            warnings.warn(f"USGS request failed for {len(batch)} sites - {detail}", stacklevel=2)
            continue

        for series in payload.get("value", {}).get("timeSeries", []):
            site = series["sourceInfo"]["siteCode"][0]["value"]
            values = series.get("values", [{}])[0].get("value", [])
            if not values:
                continue

            df = pd.DataFrame(values)
            flow = pd.to_numeric(df["value"], errors="coerce")
            # USGS uses -999999 for "ice affected" and similar no-data conditions.
            flow[flow <= -100] = np.nan

            frames.append(
                pd.DataFrame(
                    {
                        "site_no": site,
                        "date": pd.to_datetime(df["dateTime"]).dt.tz_localize(None).dt.normalize(),
                        "discharge_cfs": flow.to_numpy(),
                    }
                )
            )

    if not frames:
        cause = (
            "\n  ".join(failures) if failures else "no request failed, but every series was empty"
        )
        raise RuntimeError(
            f"No streamflow data returned for {len(site_nos)} gauges.\n"
            f"What actually went wrong:\n  {cause}\n"
            "USGS occasionally returns transient errors on long multi-year requests; "
            "re-running usually works, and finished years stay cached. To test by hand: "
            "https://waterservices.usgs.gov/nwis/dv/?format=json&sites=01188000"
            "&parameterCd=00060&startDT=2022-08-01&endDT=2022-08-05"
        )

    out = pd.concat(frames, ignore_index=True).dropna(subset=["discharge_cfs"])
    return out.sort_values(["site_no", "date"]).reset_index(drop=True)


def build_streamflow_observations(
    locations: pd.DataFrame,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    cache_dir: Path,
    max_drainage_sqmi: float = DEFAULT_MAX_DRAINAGE_SQMI,
    n_gauges: int = DEFAULT_N_GAUGES,
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    state: str = "ct",
    farm_basins: pd.DataFrame | None = None,
    progress: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    The one call the pipeline makes. Returns (tidy observations, gauge assignment).

    Tidy observations carry a single variable, `streamflow_log10` - the
    distance-weighted average of log10 discharge across each cell's nearby small
    basins. See the module docstring for why it is a logarithm and why basin size
    is filtered.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    inv_path = cache_dir / "gauge_inventory.parquet"

    if inv_path.exists():
        inventory = pd.read_parquet(inv_path)
    else:
        if progress:
            print("  fetching gauge inventory ...")
        inventory = fetch_gauge_inventory(state)
        inventory.to_parquet(inv_path, index=False)

    gauges = select_local_gauges(inventory, max_drainage_sqmi)
    pairs = assign_gauges_to_cells(
        locations,
        gauges,
        n_gauges=n_gauges,
        max_distance_km=max_distance_km,
        farm_basins=farm_basins,
    )

    site_nos = sorted(pairs["site_no"].unique())
    import hashlib

    gauge_fp = hashlib.sha256("|".join(site_nos).encode("utf-8")).hexdigest()[:8]
    flow_path = (
        cache_dir / f"flow_{pd.Timestamp(start).year}_{pd.Timestamp(end).year}_{gauge_fp}.parquet"
    )

    if flow_path.exists():
        flow = pd.read_parquet(flow_path)
        if progress:
            print(f"  {len(site_nos)} gauges (cached)")
    else:
        if progress:
            print(f"  downloading daily flow for {len(site_nos)} gauges ...")
        flow = fetch_daily_flow(site_nos, start, end)
        flow.to_parquet(flow_path, index=False)

    # log10 handles the huge dynamic range; the small offset keeps zero flow finite.
    flow = flow.copy()
    flow["log_flow"] = np.log10(flow["discharge_cfs"].clip(lower=0) + 0.01)

    merged = pairs[["cell_id", "site_no", "weight"]].merge(flow, on="site_no", how="inner")
    merged["weighted"] = merged["log_flow"] * merged["weight"]

    # Renormalise per cell-day, so a gauge missing on some days does not drag the
    # average down as if its river had stopped flowing.
    grp = merged.groupby(["cell_id", "date"])
    composite = (grp["weighted"].sum() / grp["weight"].sum()).reset_index(name="value")

    composite["variable"] = "streamflow_log10"
    composite["date"] = pd.to_datetime(composite["date"]).astype("datetime64[ns]")
    tidy = composite[["cell_id", "date", "variable", "value"]].sort_values(["cell_id", "date"])

    return tidy.reset_index(drop=True), pairs


def summarize_assignment(pairs: pd.DataFrame) -> pd.DataFrame:
    """Which gauges each cell ended up using, and how far away they are."""
    rows = []
    for cell_id, grp in pairs.groupby("cell_id"):
        grp = grp.sort_values("distance_km")
        rows.append(
            {
                "cell_id": cell_id,
                "gauges": len(grp),
                "nearest km": grp["distance_km"].min(),
                "basin sq mi": ", ".join(f"{a:.0f}" for a in grp["drainage_sqmi"]),
                "nearest station": grp.iloc[0]["station_nm"][:38],
            }
        )
    return pd.DataFrame(rows)


def drought_response_check(tidy: pd.DataFrame) -> str:
    """
    Does the streamflow signal actually drop during a known drought?

    A feature that does not move when the thing it is supposed to measure happens
    is worse than no feature, because it adds noise while looking informative.
    August 2022 was a D2 severe drought across Connecticut, so flows then should
    sit clearly below the same month in a normal year.
    """
    s = tidy.pivot_table(index="date", columns="cell_id", values="value")

    def month_mean(period: str) -> float:
        try:
            return float(s.loc[period].mean().mean())
        except KeyError:
            return float("nan")

    normal, drought = month_mean("2021-08"), month_mean("2022-08")
    if not np.isfinite(normal) or not np.isfinite(drought):
        return "Not enough data spanning August 2021 and August 2022 to check."

    ratio = 10 ** (drought - normal)
    return (
        f"Aug 2021 (normal) mean log10 flow {normal:.2f}; "
        f"Aug 2022 (D2 drought) {drought:.2f}.\n"
        f"Drought-month flow was {100 * ratio:.0f}% of the normal year - "
        f"{'as expected' if ratio < 0.8 else 'NOT the expected drop, investigate'}."
    )
