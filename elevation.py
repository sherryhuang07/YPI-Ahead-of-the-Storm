"""
USGS 3DEP elevation: where does this field sit in the landscape?

WHY TERRAIN, WHEN WE ALREADY HAVE SOIL RATINGS
----------------------------------------------
NRCS flood ratings (see `floodfreq.py`) are a soil scientist's judgment, mapped
to polygons. This is a measurement: bare-earth LiDAR, roughly 10 m pixels,
current as of July 2026. They agree often and disagree usefully, and they fail
in different ways - a soil polygon can be decades old and its boundary
generalised, while a DEM cannot tell you that a field is drained.

More importantly, terrain answers a question rainfall cannot:

    Water runs downhill and collects in flat low places. A field ten metres above
    the nearest stream on a 6-degree slope does not flood, in any rainfall. A flat
    field two metres above the same stream floods regularly.

That is a PERMANENT property of the place. Every wet-risk feature so far has been
weather - things that change day to day. These do not change at all, which is
precisely why they carry information the weather features structurally cannot.

WHAT IS COMPUTED, AND WHAT IS HONEST ABOUT IT
---------------------------------------------
For each farm we pull a 4 km tile around the cell and compute, for the central
square kilometre:

    elev_m                  mean elevation
    slope_deg               median slope - how fast water leaves
    flat_fraction           share of the cell flatter than 2 degrees
    hand_m                  metres above the local drainage line
    elev_percentile_local   0 = lowest ground for miles, 1 = the local hilltop
    local_relief_m          how much vertical range is nearby

`hand_m` deserves a caveat. Real Height Above Nearest Drainage requires routing
flow across the surface to find where channels actually are. What is computed
here is the cell's elevation above the 5th percentile of the surrounding 4 km
tile - the low ground nearby, which in Connecticut's dissected terrain is almost
always the valley floor a stream runs along. It is a PROXY, it is named as one,
and it costs one raster read instead of a flow-accumulation library.

TOPOGRAPHIC WETNESS INDEX IS DELIBERATELY ABSENT
------------------------------------------------
TWI = ln(upslope contributing area / tan(slope)) is the standard index for this
job and it would be the natural thing to add. It needs true flow accumulation.
A version computed without that - substituting pixel area for contributing area,
as is sometimes done - is not TWI, it is a rescaling of slope wearing TWI's name,
and it would look authoritative while adding nothing. It is left out rather than
faked. If flow routing gets added later, this is the first thing to compute.

THE TILE SIZE IS A REAL CHOICE
------------------------------
Four kilometres, because the drainage a field actually sheds into has to be
INSIDE the tile for `hand_m` to mean anything. A 1 km tile centred on a
floodplain farm can contain nothing but floodplain, making it look like a
hilltop. Four kilometres reliably reaches a valley in Connecticut, at the cost of
10 m pixels rather than the 1 m LiDAR underneath.
"""

from __future__ import annotations

import io
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ELEVATION_URL = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
)

# Tile side in metres, and pixels per side. 4000/400 = 10 m, matching 3DEP's
# seamless 1/3 arc-second product.
TILE_M = 4000.0
TILE_PX = 400

# Below this, water does not run off meaningfully - it sits.
FLAT_SLOPE_DEG = 2.0

# "The local drainage line" is the MEAN of the lowest this-percent of the tile,
# not the value AT that percentile.
#
# That distinction is not pedantry - it was a real bug, caught by a test on a
# synthetic plateau. `np.nanpercentile(dem, 5)` interpolates, so when the low
# ground occupies almost exactly 5% of the tile the percentile lands ON the
# valley wall rather than the floor. The plateau test returned drainage at 57 m
# for a tile whose floor is 0 m, making a 60 m plateau read as 3 m above
# drainage. Real terrain is smoother than the synthetic case, but a narrow
# valley occupying under 5% of a tile would fail exactly the same way - and
# narrow valleys are precisely where flooding happens.
#
# Averaging the lowest 5% cannot land on a cliff edge. It is the low ground,
# by construction.
DRAINAGE_PERCENTILE = 5.0

# 3DEP's no-data for areas outside coverage.
NODATA_BELOW = -1000.0


def fetch_tile(
    lat: float, lon: float, tile_m: float = TILE_M, px: int = TILE_PX, timeout: int = 300
):
    """
    A bare-earth elevation tile centred on a point, as a numpy array.

    Returns (dem, pixel_metres). Elevation is in metres; no-data becomes NaN.
    """
    import rasterio

    # Degrees per metre varies with latitude for longitude but not for latitude.
    dlat = tile_m / 111_320.0
    dlon = tile_m / (111_320.0 * np.cos(np.radians(lat)))

    west, east = lon - dlon / 2, lon + dlon / 2
    south, north = lat - dlat / 2, lat + dlat / 2

    params = {
        "bbox": f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}",
        "bboxSR": 4326,
        "size": f"{px},{px}",
        "imageSR": 4326,
        "format": "tiff",
        "pixelType": "F32",
        "f": "image",
    }
    resp = requests.get(ELEVATION_URL, params=params, timeout=timeout)
    resp.raise_for_status()

    if resp.content[:4] not in (b"II*\x00", b"MM\x00*"):
        raise RuntimeError(f"3DEP returned no GeoTIFF at ({lat}, {lon}): {resp.content[:200]!r}")

    with rasterio.open(io.BytesIO(resp.content)) as src:
        dem = src.read(1).astype(float)

    dem[dem <= NODATA_BELOW] = np.nan
    return dem, tile_m / px


def terrain_metrics(dem: np.ndarray, pixel_m: float, cell_m: float = 1000.0) -> dict:
    """
    Landscape position and shape, for the central `cell_m` of a tile.

    Slope is computed on the WHOLE tile so the central cell's edge pixels have
    neighbours; every summary statistic is then taken over the central window
    only, because that is the farm.
    """
    if np.isnan(dem).all():
        return dict.fromkeys(
            [
                "elev_m",
                "slope_deg",
                "flat_fraction",
                "hand_m",
                "elev_percentile_local",
                "local_relief_m",
            ],
            np.nan,
        )

    gy, gx = np.gradient(dem, pixel_m)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))

    half = max(int((cell_m / pixel_m) // 2), 1)
    mid = dem.shape[0] // 2
    sl = slice(max(mid - half, 0), min(mid + half, dem.shape[0]))

    centre, centre_slope = dem[sl, sl], slope[sl, sl]
    finite = dem[np.isfinite(dem)]
    n_low = max(int(finite.size * DRAINAGE_PERCENTILE / 100.0), 1)
    drainage = float(np.mean(np.partition(finite, n_low - 1)[:n_low]))
    centre_elev = float(np.nanmean(centre))

    return {
        "elev_m": centre_elev,
        "slope_deg": float(np.nanmedian(centre_slope)),
        "flat_fraction": float(np.nanmean(centre_slope < FLAT_SLOPE_DEG)),
        # Height above the local drainage line - the proxy described in the
        # module docstring. Clipped at zero: a farm below the 5th percentile of
        # its own surroundings is a rounding artefact, not a hole.
        "hand_m": float(max(centre_elev - drainage, 0.0)),
        # Where this sits in the local landscape, 0 = valley floor, 1 = hilltop.
        "elev_percentile_local": float(np.nanmean(dem < centre_elev)),
        "local_relief_m": float(np.nanmax(dem) - np.nanmin(dem)),
    }


def build_cell_terrain(
    locations: pd.DataFrame,
    cache_dir: Path,
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
    pause_seconds: float = 0.2,
    progress: bool = True,
) -> pd.DataFrame:
    """
    Terrain metrics for every cell, cached so the download happens once.

    Also emits `terrain_flood_prone`: low in the landscape AND flat. Both
    conditions matter - a flat hilltop sheds water off its edges, and a steep
    valley side sheds it downhill. It is the combination that ponds.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / "terrain.parquet"

    done = pd.read_parquet(cache) if cache.exists() else pd.DataFrame(columns=["cell_id"])
    have = set(done["cell_id"])
    todo = locations[~locations["cell_id"].isin(have)]

    if progress and len(todo):
        print(f"  {len(todo)} tiles to fetch ({len(have)} cached)")

    rows = []
    for i, row in enumerate(todo.itertuples(index=False), start=1):
        if progress and i % 20 == 0:
            print(f"    {i}/{len(todo)} ...", flush=True)
        try:
            dem, px = fetch_tile(getattr(row, lat_col), getattr(row, lon_col))
            metrics = terrain_metrics(dem, px)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            warnings.warn(f"3DEP tile failed for {row.cell_id}: {exc}", stacklevel=2)
            continue
        rows.append({"cell_id": row.cell_id, **metrics})
        time.sleep(pause_seconds)

    out = pd.concat([done, pd.DataFrame(rows)], ignore_index=True) if rows else done
    if out.empty:
        raise RuntimeError("No terrain retrieved. Check elevation.nationalmap.gov is reachable.")

    out = out.drop_duplicates(subset=["cell_id"], keep="last")

    # Low in the landscape AND flat. Thresholds are the physical ones, not tuned:
    # 10 m is roughly the height a Connecticut river reaches in a large flood,
    # and half the cell being under 2 degrees is what "flat plain" means.
    out["terrain_flood_prone"] = ((out["hand_m"] <= 10.0) & (out["flat_fraction"] >= 0.5)).astype(
        int
    )

    out.to_parquet(cache, index=False)
    return out.reset_index(drop=True)


def summarize(terrain: pd.DataFrame) -> pd.DataFrame:
    """The spread of landscape positions across the farms we cover."""
    rows = []
    for col, label, unit in [
        ("elev_m", "elevation", "m"),
        ("slope_deg", "slope", "deg"),
        ("hand_m", "height above drainage", "m"),
        ("flat_fraction", "share flatter than 2 deg", ""),
        ("local_relief_m", "local relief", "m"),
    ]:
        s = terrain[col].dropna()
        if s.empty:
            continue
        rows.append(
            {
                "metric": label,
                "min": f"{s.min():.1f}{unit}",
                "median": f"{s.median():.1f}{unit}",
                "max": f"{s.max():.1f}{unit}",
            }
        )
    return pd.DataFrame(rows)
