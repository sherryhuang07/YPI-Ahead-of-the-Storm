"""
Turning a pinpointed lat/lon into something a model can use.

THE CORE PROBLEM
----------------
A user drops a pin at (41.7658, -72.6734). No dataset on earth has a row for that
exact point. Every dataset is either:
  - a grid of cells (rainfall, satellite imagery, soil moisture), or
  - scattered points (weather stations, wells), or
  - polygons (drought monitor areas, counties, soil map units).

So "location precision" in this project really means three separate jobs:
  1. SNAP  - map the pin to a fixed analysis grid cell, so the same pin always
             produces the same features (reproducibility).
  2. SAMPLE - pull the value of each raster/polygon layer at that point.
  3. CONTEXT - add slowly-changing local traits (soil water capacity, slope,
             land cover) that make one field drier than its neighbor.

This module handles #1 and gives you the tools for #2 and #3.

A NOTE ON COORDINATE SYSTEMS (this trips up everyone)
-----------------------------------------------------
Latitude/longitude (EPSG:4326) are angles, not distances. In Connecticut,
1 degree of latitude is ~111 km but 1 degree of longitude is only ~82 km.
So you can NEVER do distance math directly in lat/lon. We convert to
Connecticut State Plane (EPSG:6433), whose units are meters, do the math there,
and convert back if needed.
"""

from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point, box


@dataclass(frozen=True)
class GridSpec:
    """Definition of the fixed analysis grid that every location snaps onto."""

    resolution_m: float
    crs_projected: str = "EPSG:6433"
    crs_geographic: str = "EPSG:4326"
    # Grid origin in projected meters. Fixed constant so cell IDs never shift
    # between runs, even if you later expand the study area.
    origin_x: float = 0.0
    origin_y: float = 0.0


def snap_to_grid(
    lat: float | np.ndarray,
    lon: float | np.ndarray,
    spec: GridSpec,
) -> pd.DataFrame:
    """
    Convert lat/lon point(s) into stable grid-cell identifiers.

    Returns a DataFrame with, per input point:
      col, row       - integer grid indices
      cell_id        - a string like "1000m_0342_0187", unique and stable forever
      cell_center_x/y - the cell's center in projected meters
      cell_center_lat/lon - the same center back in degrees

    Why snap at all? Two farms 200 m apart should share the same 1 km rainfall
    pixel, and you want the model to see them as the same location so it isn't
    fooled into thinking it has more independent data than it really does.
    """
    lat_arr = np.atleast_1d(np.asarray(lat, dtype=float))
    lon_arr = np.atleast_1d(np.asarray(lon, dtype=float))

    to_proj = Transformer.from_crs(spec.crs_geographic, spec.crs_projected, always_xy=True)
    to_geo = Transformer.from_crs(spec.crs_projected, spec.crs_geographic, always_xy=True)

    # always_xy=True means "give me x=longitude, y=latitude order" - the single
    # most common source of silently-swapped-coordinates bugs in geospatial code.
    x, y = to_proj.transform(lon_arr, lat_arr)

    res = spec.resolution_m
    col = np.floor((x - spec.origin_x) / res).astype(int)
    row = np.floor((y - spec.origin_y) / res).astype(int)

    cx = spec.origin_x + (col + 0.5) * res
    cy = spec.origin_y + (row + 0.5) * res
    clon, clat = to_geo.transform(cx, cy)

    res_tag = f"{int(res)}m"
    cell_id = [f"{res_tag}_{c:05d}_{r:05d}" for c, r in zip(col, row, strict=True)]

    return pd.DataFrame(
        {
            "lat": lat_arr,
            "lon": lon_arr,
            "col": col,
            "row": row,
            "cell_id": cell_id,
            "cell_center_x": cx,
            "cell_center_y": cy,
            "cell_center_lat": clat,
            "cell_center_lon": clon,
        }
    )


def points_to_gdf(df: pd.DataFrame, lat_col: str = "lat", lon_col: str = "lon") -> gpd.GeoDataFrame:
    """
    Attach a real geometry column to a plain table of lat/lon rows.

    A GeoDataFrame is just a pandas DataFrame with one extra 'geometry' column
    and a known CRS. Once you have one you can do spatial joins: "which drought
    polygon contains this point?", "which county is this farm in?".
    """
    geom = [Point(xy) for xy in zip(df[lon_col], df[lat_col], strict=True)]
    return gpd.GeoDataFrame(df.copy(), geometry=geom, crs="EPSG:4326")


def connecticut_bbox(cfg_domain: dict) -> gpd.GeoDataFrame:
    """A single rectangle covering Connecticut - handy for clipping big national files."""
    b = cfg_domain["bbox"]
    geom = box(b["min_lon"], b["min_lat"], b["max_lon"], b["max_lat"])
    return gpd.GeoDataFrame({"name": ["connecticut_bbox"]}, geometry=[geom], crs="EPSG:4326")


def in_domain(lat: float, lon: float, cfg_domain: dict) -> bool:
    """Guard rail: reject pins outside Connecticut before wasting time on them."""
    b = cfg_domain["bbox"]
    return (b["min_lat"] <= lat <= b["max_lat"]) and (b["min_lon"] <= lon <= b["max_lon"])


def locations_fingerprint(locations, length: int = 8) -> str:
    """
    A short hash of which cells a table covers.

    Cache files that are keyed only by DATE are a silent-wrong-data trap: change
    the locations and a stale file happily serves numbers for the old ones, with
    no error and no clue. Putting this fingerprint in the filename means a
    different set of cells simply misses the cache instead of quietly using it.
    """
    import hashlib

    ids = sorted(str(c) for c in locations["cell_id"].unique())
    digest = hashlib.sha256("|".join(ids).encode("utf-8")).hexdigest()
    return digest[:length]
