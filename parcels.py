"""
Real farm locations, from satellite cropland plus legal parcel boundaries.

THE PROBLEM THIS SOLVES
-----------------------
Every result in this project so far rests on twelve invented coordinates. The soil
survey then reported that one of them is Urban land in downtown Hartford and
another is open water. They also sit close enough together to share weather, so
26,000 training rows collapse to roughly 311 genuinely independent label-weeks -
far too few for a hundred-odd features. That, not the model, is the binding
constraint on whether this ever beats persistence.

WHY NOT JUST USE THE ASSESSOR'S "FARM" CODE?
--------------------------------------------
Connecticut publishes a statewide parcel layer with assessor land-use codes, and
filtering it for "FARM" looks like the obvious answer. It is a trap, for two
reasons we measured rather than assumed:

  1. Only 40 of Connecticut's 169 towns populate that field at all. The matches
     cluster hard in the northwest hills - Bethlehem, Morris, Salisbury, Cornwall,
     Sharon - not because that is where farming happens, but because those
     assessors fill in the column. A model trained on that sample would learn the
     Litchfield hills and be tested on the Litchfield hills.

  2. The matches include "TANK FARM", "SOLAR FARM" and "Solar Farm Site". None of
     those grow anything.

So the assessor code is used for LABELLING what we found, never for choosing it.

HOW LOCATIONS ARE CHOSEN INSTEAD
--------------------------------
    1. Satellite decides WHERE farmland is. The USDA Cropland Data Layer classifies
       every 30 m pixel in the state from Landsat and Sentinel imagery. It is
       statewide, uniform, and owes nothing to who filled in a form.

    2. Sampling is spatially stratified. Connecticut is divided into a grid of
       blocks and we take cropland points from each, so the sample spans the state
       instead of piling into whichever county has the most corn.

    3. Parcels turn cropland into FARMS. A contiguous blob of cropland pixels is
       not a farm; a parcel is. Looking up the legal parcel at each sampled point
       and de-duplicating by parcel id means one row per distinct landholding
       rather than several rows describing one farmer's field.

A LIMIT WORTH STATING
---------------------
Every feature in this project is computed per 1 km grid cell, so two farms inside
the same cell are indistinguishable to the model no matter how distinct they are
legally. We therefore de-duplicate by cell as well as by parcel. The honest
description of the output is "distinct 1 km cells known to contain a working
farm", and getting finer than that would mean shrinking the grid.
"""

from __future__ import annotations

import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PARCEL_SERVICE = (
    "https://services3.arcgis.com/3FL1kr7L4LvwA2Kb/ArcGIS/rest/services/"
    "Connecticut_State_Parcel_Layer_2023/FeatureServer/0/query"
)

SQ_M_PER_ACRE = 4046.86

# Parcels outside this range are not small farms: below it are house lots and
# road strips, above it are institutional holdings, state forest and reservoirs.
MIN_PARCEL_ACRES = 2.0
MAX_PARCEL_ACRES = 2000.0

# Land-use descriptions that contain "farm" but grow nothing.
NOT_REALLY_FARMS = ("TANK FARM", "SOLAR FARM", "SOLAR FARM SITE", "WIND FARM")


def sample_cropland_points(
    cdl_path: Path,
    bbox: tuple[float, float, float, float],
    n_strata: int = 12,
    per_stratum: int = 24,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Draw candidate points from land the satellite says is cropland.

    Connecticut is split into `n_strata` x `n_strata` blocks and up to
    `per_stratum` cropland points are taken from each, so the sample spreads
    across the state rather than concentrating wherever crops are densest.

    Returns lat, lon, cdl_code, stratum.
    """
    import rasterio
    from pyproj import Transformer
    from rasterio.windows import from_bounds

    from ctwater.data.cropland import CDL_TO_GROUP

    rng = np.random.default_rng(seed)
    min_lon, min_lat, max_lon, max_lat = bbox

    lon_edges = np.linspace(min_lon, max_lon, n_strata + 1)
    lat_edges = np.linspace(min_lat, max_lat, n_strata + 1)

    ag_codes = np.array(sorted(CDL_TO_GROUP), dtype=np.int32)
    rows = []

    with rasterio.open(cdl_path) as src:
        to_cdl = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        to_geo = Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)

        for i in range(n_strata):
            for j in range(n_strata):
                x0, y0 = to_cdl.transform(lon_edges[i], lat_edges[j])
                x1, y1 = to_cdl.transform(lon_edges[i + 1], lat_edges[j + 1])

                try:
                    window = from_bounds(
                        min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), src.transform
                    )
                    block = src.read(1, window=window, boundless=True, fill_value=0)
                    win_transform = src.window_transform(window)
                except (ValueError, rasterio.errors.RasterioError):
                    continue

                ag_mask = np.isin(block, ag_codes)
                found = np.argwhere(ag_mask)
                if len(found) == 0:
                    continue

                take = min(per_stratum, len(found))
                picks = found[rng.choice(len(found), size=take, replace=False)]

                for r, c in picks:
                    # Pixel centre in the raster's own coordinates, then to lat/lon.
                    x = win_transform.c + (c + 0.5) * win_transform.a
                    y = win_transform.f + (r + 0.5) * win_transform.e
                    lon, lat = to_geo.transform(x, y)
                    rows.append(
                        {
                            "lat": float(lat),
                            "lon": float(lon),
                            "cdl_code": int(block[r, c]),
                            "stratum": f"{i:02d}_{j:02d}",
                        }
                    )

    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("No cropland found in the CDL raster for this bounding box.")
    return out.reset_index(drop=True)


def parcel_at_point(lat: float, lon: float, timeout: int = 120) -> dict | None:
    """
    Which legal parcel contains this point?

    Returns the parcel id, town, assessor land-use description and area, or None
    if the point falls outside any mapped parcel.
    """
    params = {
        "geometry": f"{float(lon):.6f},{float(lat):.6f}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "OBJECTID,Town_Name,State_Use_Description,Shape__Area",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        resp = requests.get(PARCEL_SERVICE, params=params, timeout=timeout)
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except (requests.RequestException, ValueError) as exc:
        warnings.warn(f"Parcel lookup failed at ({lat:.4f}, {lon:.4f}): {exc}", stacklevel=2)
        return None

    if not features:
        return None

    attrs = features[0]["attributes"]
    return {
        "parcel_id": int(attrs["OBJECTID"]),
        "town": attrs.get("Town_Name"),
        "parcel_use": attrs.get("State_Use_Description"),
        "parcel_acres": round(float(attrs.get("Shape__Area") or 0) / SQ_M_PER_ACRE, 2),
    }


def build_farm_locations(
    cdl_path: Path,
    bbox: tuple[float, float, float, float],
    cache_dir: Path,
    grid_resolution_m: float = 1000.0,
    n_strata: int = 12,
    per_stratum: int = 24,
    target_farms: int = 200,
    seed: int = 42,
    request_pause: float = 0.15,
    progress: bool = True,
) -> pd.DataFrame:
    """
    The one call the pipeline makes: a table of real farm locations.

    Returns the same columns `make-synthetic` produced, so everything downstream
    works unchanged: cell_id, site_name, lat, lon, cell_center_lat/lon, plus the
    parcel provenance. `awc_mm` is deliberately absent - the soil survey supplies
    it now, and inventing a placeholder would reintroduce exactly the fake number
    this project just removed.
    """
    from ctwater.data.grid import GridSpec, snap_to_grid

    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / "farm_parcels.parquet"

    if cached.exists():
        found = pd.read_parquet(cached)
        if progress:
            print(f"  {len(found):,} parcel lookups (cached)")
    else:
        candidates = sample_cropland_points(
            cdl_path, bbox, n_strata=n_strata, per_stratum=per_stratum, seed=seed
        )

        # DEDUPLICATE BEFORE THE EXPENSIVE STEP. The parcel service takes one HTTP
        # request per point, and an earlier version looked up all ~2,600 sampled
        # points before collapsing them to cells - which both wasted most of the
        # work and got the public service to throttle us into a stall.
        #
        # Since features are computed per cell, several cropland points inside one
        # cell can only ever produce one location. Collapsing first cuts the
        # request count by roughly five, and trimming to the target cuts it again.
        spec_pre = GridSpec(resolution_m=grid_resolution_m)
        pre = snap_to_grid(candidates["lat"].to_numpy(), candidates["lon"].to_numpy(), spec_pre)
        candidates = pd.concat(
            [candidates.reset_index(drop=True), pre[["cell_id"]]], axis=1
        ).drop_duplicates(subset=["cell_id"])

        # Leave headroom, because some points fall outside any mapped parcel and
        # some parcels get filtered out below.
        budget = min(len(candidates), int(target_farms * 2.5))
        candidates = candidates.sample(n=budget, random_state=seed).reset_index(drop=True)

        if progress:
            print(f"  {len(candidates):,} distinct cells to look up (deduplicated first)")

        records = []
        for n, row in enumerate(candidates.itertuples(), 1):
            if progress and n % 25 == 0:
                print(f"    {n}/{len(candidates)}", flush=True)

            parcel = parcel_at_point(row.lat, row.lon)
            time.sleep(request_pause)  # be a polite client of a free public service
            if parcel is None:
                continue
            records.append({"lat": row.lat, "lon": row.lon, "cdl_code": row.cdl_code, **parcel})

        found = pd.DataFrame(records)
        if found.empty:
            raise RuntimeError("No parcels matched any sampled cropland point.")
        found.to_parquet(cached, index=False)

    # --- filter to things that are plausibly working farms --------------------
    before = len(found)
    keep = found[found["parcel_acres"].between(MIN_PARCEL_ACRES, MAX_PARCEL_ACRES)].copy()

    use = keep["parcel_use"].fillna("").str.upper()
    keep = keep[~use.apply(lambda u: any(bad in u for bad in NOT_REALLY_FARMS))]

    # --- one row per distinct farm, then per distinct grid cell ---------------
    keep = keep.drop_duplicates(subset=["parcel_id"])
    n_parcels = len(keep)

    spec = GridSpec(resolution_m=grid_resolution_m)
    snapped = snap_to_grid(keep["lat"].to_numpy(), keep["lon"].to_numpy(), spec)
    keep = pd.concat([keep.reset_index(drop=True), snapped.drop(columns=["lat", "lon"])], axis=1)
    keep = keep.drop_duplicates(subset=["cell_id"]).reset_index(drop=True)

    if len(keep) > target_farms:
        # Keep the geographic spread when trimming: sample rather than take the
        # first N, which would be ordered by stratum and so clip a whole region.
        keep = keep.sample(n=target_farms, random_state=seed).reset_index(drop=True)

    keep["site_name"] = [
        f"{str(t).lower().replace(' ', '_')}_{p}"
        for t, p in zip(keep["town"], keep["parcel_id"], strict=True)
    ]

    if progress:
        print(
            f"  {before:,} lookups -> {n_parcels:,} distinct parcels -> "
            f"{len(keep):,} distinct 1 km cells"
        )

    cols = [
        "cell_id",
        "site_name",
        "lat",
        "lon",
        "cell_center_lat",
        "cell_center_lon",
        "town",
        "parcel_id",
        "parcel_acres",
        "parcel_use",
        "cdl_code",
    ]
    return keep[cols]


def summarize(farms: pd.DataFrame) -> pd.DataFrame:
    """Geographic spread of the farms we found - the thing that was wrong before."""
    from ctwater.data.cropland import CDL_TO_GROUP

    crops = farms["cdl_code"].map(CDL_TO_GROUP).fillna("other")
    return pd.DataFrame(
        [
            {"measure": "farms (distinct 1 km cells)", "value": f"{len(farms):,}"},
            {"measure": "towns covered", "value": f"{farms['town'].nunique()} of 169"},
            {
                "measure": "latitude span",
                "value": f"{farms['lat'].min():.2f} to {farms['lat'].max():.2f}",
            },
            {
                "measure": "longitude span",
                "value": f"{farms['lon'].min():.2f} to {farms['lon'].max():.2f}",
            },
            {
                "measure": "median parcel size",
                "value": f"{farms['parcel_acres'].median():.0f} acres",
            },
            {"measure": "most common crop", "value": crops.value_counts().index[0]},
            {
                "measure": "crop mix",
                "value": ", ".join(f"{k} {v}" for k, v in crops.value_counts().head(4).items()),
            },
        ]
    )
