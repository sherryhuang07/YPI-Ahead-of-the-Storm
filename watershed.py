"""
Watersheds: the unit water actually moves in.

WHY THIS REORDERS THE WHOLE PIPELINE
------------------------------------
Everything in this project so far has treated location as a COORDINATE - a
latitude and longitude handed to the model as two more numbers, from which it is
expected to work out that some farms behave alike. That is backwards. Water does
not care about latitude. It runs downhill into a drainage network, and every
farm in that network shares the same rivers, the same underlying geology, the
same response time to a storm.

The natural unit is the watershed, and the correct order is:

    partition by watershed  ->  analyse each one  ->  train per watershed

rather than pooling every farm into one model and hoping `lat` and `lon` stand in
for hydrology. Pooling averages away exactly the differences that make a farm in
the Farmington River basin behave unlike one draining to Long Island Sound.

THE SCALE IS A REAL CHOICE, AND IT IS FORCED
--------------------------------------------
USGS nests watersheds inside each other, coarse to fine:

    HUC2   region        New England is 01
    HUC4   subregion
    HUC6   basin
    HUC8   subbasin      28 intersect Connecticut
    HUC10  watershed     124
    HUC12  subwatershed  497

Finer is more hydrologically honest and less trainable. With 200 farms, HUC12
would leave well under one farm per unit - not a model, a lookup table. HUC8
leaves enough farms per basin to fit something and still separates the
Connecticut River valley from the Thames, the Housatonic and the coastal
drainages, which are genuinely different systems.

So HUC8 is the modelling unit. HUC10 and HUC12 are still attached, because
knowing which subwatershed a farm sits in is useful as a feature even when it is
too fine to train on.

THE BUG THIS IS EXPECTED TO EXPOSE
----------------------------------
`usgs.assign_gauges_to_cells` picks the nearest stream gauges BY DISTANCE. That
is hydrologically wrong and it has been wrong from the beginning: a gauge five
kilometres away on the other side of a drainage divide is measuring a different
river system, while one thirty kilometres upstream on your own river is measuring
the water that is about to reach you.

Distance is a proxy for "same water". Watershed membership is the real thing.
This module makes the difference measurable rather than assumed.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import requests

WBD_URL = "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer"

# ArcGIS layer id -> (column name, human label). The layer ids are not the digit
# counts, which is an easy and silent mistake to make.
HUC_LAYERS = {
    8: (4, "huc8", "subbasin"),
    10: (5, "huc10", "watershed"),
    12: (6, "huc12", "subwatershed"),
}

# New England, generous enough to bracket every Connecticut farm and the basins
# that reach into neighbouring states.
NEW_ENGLAND_BBOX = (-74.0, 40.7, -70.4, 42.5)

# HUC2 region 01 is New England. Region 02 (Mid-Atlantic) also touches southwest
# Connecticut via Long Island Sound, so both are kept.
NEW_ENGLAND_REGIONS = ("01", "02")


def fetch_huc_polygons(
    level: int = 8,
    bbox: tuple[float, float, float, float] = NEW_ENGLAND_BBOX,
    timeout: int = 300,
):
    """
    Watershed polygons for a bounding box, as a GeoDataFrame.

    One request for the whole region rather than a point query per farm - the
    same deduplicate-before-the-expensive-call lesson as the parcel geocoding and
    the Atlas 14 lookups.
    """
    import geopandas as gpd
    from shapely.geometry import shape

    if level not in HUC_LAYERS:
        raise ValueError(f"HUC level must be one of {sorted(HUC_LAYERS)}, got {level}")
    layer_id, field, _label = HUC_LAYERS[level]

    # PAGINATE. Asking for all 497 HUC12 polygons with geometry in one call
    # returns a 500 from the server - the payload is simply too large. The
    # coarser levels fit in one request and the finer ones do not, so every level
    # goes through the same page loop rather than only the ones that broke.
    page, offset, feats = 250, 0, []
    while True:
        params = {
            "geometry": ",".join(str(v) for v in bbox),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "outSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": f"{field},name,areasqkm",
            "returnGeometry": "true",
            "f": "geojson",
            "resultRecordCount": page,
            "resultOffset": offset,
        }
        resp = requests.get(f"{WBD_URL}/{layer_id}/query", params=params, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()

        batch = payload.get("features", [])
        feats.extend(batch)
        if len(batch) < page:
            break
        offset += page
        if offset > 20_000:  # a runaway guard, far above any real region
            warnings.warn(f"HUC{level} paging exceeded 20,000 features; stopping.", stacklevel=2)
            break

    rows = []
    for f in feats:
        attrs = f.get("properties") or f.get("attributes") or {}
        geom = f.get("geometry")
        if geom is None:
            continue
        rows.append(
            {
                "huc": str(attrs.get(field) or attrs.get(field.upper()) or ""),
                "huc_name": attrs.get("name") or attrs.get("NAME"),
                "area_sqkm": attrs.get("areasqkm") or attrs.get("AREASQKM"),
                "geometry": shape(geom),
            }
        )

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    gdf = gdf[gdf["huc"].str.len() == level].reset_index(drop=True)
    return gdf


def assign_farms(
    locations: pd.DataFrame,
    levels: tuple[int, ...] = (8, 10, 12),
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
    cache_dir: Path | None = None,
    progress: bool = True,
) -> pd.DataFrame:
    """
    Put every farm in its watershed, at each requested scale.

    Returns cell_id plus huc8 / huc8_name / huc10 / huc12 etc. A farm that falls
    outside every polygon keeps a null rather than being snapped to the nearest -
    silently assigning a farm to the wrong basin is exactly the error this module
    exists to prevent.
    """
    import geopandas as gpd

    farms = gpd.GeoDataFrame(
        locations[["cell_id"]].copy(),
        geometry=gpd.points_from_xy(locations[lon_col], locations[lat_col]),
        crs="EPSG:4326",
    )

    out = locations[["cell_id"]].copy()
    for level in levels:
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached = cache_dir / f"huc{level}.parquet"
        else:
            cached = None

        if cached is not None and cached.exists():
            polys = gpd.read_parquet(cached)
        else:
            if progress:
                print(f"  fetching HUC{level} polygons ...", flush=True)
            try:
                polys = fetch_huc_polygons(level)
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                # One scale failing must not cost the others. HUC8 is the
                # modelling unit; the finer levels are features.
                warnings.warn(f"HUC{level} unavailable, skipping: {exc}", stacklevel=2)
                out[f"huc{level}"] = pd.NA
                continue
            if cached is not None:
                polys.to_parquet(cached)

        joined = gpd.sjoin(
            farms, polys[["huc", "huc_name", "geometry"]], how="left", predicate="within"
        )
        # A point on a shared boundary can match two polygons; keep the first.
        joined = joined[~joined.index.duplicated(keep="first")]

        out[f"huc{level}"] = joined["huc"].to_numpy()
        if level == 8:
            out["huc8_name"] = joined["huc_name"].to_numpy()

        missing = out[f"huc{level}"].isna().sum()
        if missing:
            warnings.warn(
                f"{missing} farms fall outside every HUC{level} polygon and were left "
                "unassigned rather than snapped to the nearest basin.",
                stacklevel=2,
            )

    return out


def summarize(assigned: pd.DataFrame, level: int = 8) -> pd.DataFrame:
    """How the farms distribute across basins, and whether each can be trained on."""
    col = f"huc{level}"
    name_col = "huc8_name" if level == 8 else None

    grouped = assigned.groupby(col, dropna=False)
    rows = []
    for huc, grp in grouped:
        rows.append(
            {
                "huc": huc,
                "name": grp[name_col].iloc[0] if name_col and name_col in grp else "",
                "farms": len(grp),
            }
        )
    out = pd.DataFrame(rows).sort_values("farms", ascending=False).reset_index(drop=True)
    out["share"] = (100 * out["farms"] / out["farms"].sum()).round(1)
    return out


def gauges_crossing_divides(pairs: pd.DataFrame, assigned: pd.DataFrame) -> pd.DataFrame:
    """
    How often does a farm's nearest stream gauge sit in a DIFFERENT watershed?

    `usgs.assign_gauges_to_cells` chooses by distance. A gauge across a drainage
    divide measures a different river system however close it is, so this counts
    how much of the streamflow signal is hydrologically unrelated to the farm it
    is attached to.

    `pairs` needs cell_id, site_no and the gauge's own huc8 as `gauge_huc8`.
    """
    merged = pairs.merge(assigned[["cell_id", "huc8"]], on="cell_id", how="left")
    merged = merged.dropna(subset=["huc8", "gauge_huc8"])
    if merged.empty:
        return pd.DataFrame()

    merged["same_basin"] = merged["huc8"] == merged["gauge_huc8"]
    by_cell = merged.groupby("cell_id")["same_basin"].agg(["sum", "size"])

    return pd.DataFrame(
        {
            "metric": [
                "gauge-farm pairs in the same subbasin",
                "farms whose nearest gauge is out-of-basin",
                "farms with NO in-basin gauge at all",
            ],
            "value": [
                f"{100 * merged['same_basin'].mean():.0f}%",
                f"{100 * (by_cell['sum'] < by_cell['size']).mean():.0f}%",
                f"{100 * (by_cell['sum'] == 0).mean():.0f}%",
            ],
        }
    )
