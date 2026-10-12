"""
The U.S. Drought Monitor loader - your answer key.

WHAT THIS DOES
--------------
Downloads the weekly USDM drought maps, clips them to Connecticut, and works out
which drought class each of your grid cells was in, every week. That table is what
the model learns to predict.

HOW USDM ACTUALLY WORKS (verified against the real files, not assumed)
----------------------------------------------------------------------
- One map per week, valid on a TUESDAY, published the following Thursday.
- Available from 2000-01-04 to present, so ~1,300 maps.
- Each map is a shapefile with a single column that matters: `DM`, valued 0-4.
      DM=0 -> D0 Abnormally Dry        DM=3 -> D3 Extreme
      DM=1 -> D1 Moderate              DM=4 -> D4 Exceptional
      DM=2 -> D2 Severe
- The `_M` ("modified") files we download are DISJOINT: each area appears in
  exactly ONE class polygon. A point either falls inside one polygon or inside
  none at all.
  This matters. The *unmodified* USDM files are NESTED (the D0 polygon also covers
  every worse area), and code written for one shape gives wrong answers on the
  other. We verified the disjoint behavior directly, and `_stage_from_join` below
  takes the MAXIMUM class anyway, so it stays correct either way.

OUR STAGE SCALE
---------------
    stage 0 = no drought (point is inside no polygon)
    stage 1 = D0 ... stage 5 = D4          i.e.  stage = DM + 1

A WARNING ABOUT WHAT USDM IS
----------------------------
USDM is not a measurement. It is a weekly expert judgment, drawn by a human author
who blends rainfall, soil moisture, streamflow, and local reports. That is a
strength - it captures on-the-ground impacts no satellite sees - but it also means:
  - boundaries follow the author's hand and sometimes county lines
  - it can lag a fast-developing "flash drought" by a week or two
  - your model will learn the authors' habits along with the physics

Since your goal is a QUICKER warning system, that lag is the specific weakness you
are trying to beat. Worth measuring directly once you have real data: check whether
your model's stage changes tend to lead USDM's.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

USDM_URL = "https://droughtmonitor.unl.edu/data/shapefiles_m/USDM_{date}_M.zip"
USDM_FIRST_DATE = pd.Timestamp("2000-01-04")

# Connecticut, with a small margin so polygons that only clip the border survive.
CT_BBOX = (-74.0, 40.8, -71.6, 42.2)


def usdm_dates(start: str | pd.Timestamp, end: str | pd.Timestamp) -> list[pd.Timestamp]:
    """
    Every valid USDM map date (Tuesdays) in a range.

    Asking for a Wednesday gets you a 404, so we snap to the real release cadence
    rather than letting you discover that one failed download at a time.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    if start < USDM_FIRST_DATE:
        warnings.warn(
            f"USDM starts {USDM_FIRST_DATE.date()}; clamping your start date to it.",
            stacklevel=2,
        )
        start = USDM_FIRST_DATE
    return list(pd.date_range(start, end, freq="W-TUE"))


def download_usdm_week(
    date: pd.Timestamp, cache_dir: Path, session: requests.Session | None = None
) -> Path | None:
    """
    Fetch one weekly shapefile zip, skipping the download if it is already cached.

    Caching matters more than it looks: a full history is ~1,300 files and a few GB
    of transfer. You do not want to re-download that every time you tweak a feature.
    Returns None if that week is genuinely unavailable, so one gap cannot kill a run.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.strftime("%Y%m%d")
    dest = cache_dir / f"USDM_{stamp}_M.zip"

    if dest.exists() and dest.stat().st_size > 0:
        return dest

    url = USDM_URL.format(date=stamp)
    getter = session or requests
    try:
        resp = getter.get(url, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        warnings.warn(f"Could not download USDM for {date.date()}: {exc}", stacklevel=2)
        return None

    dest.write_bytes(resp.content)
    return dest


def load_usdm_week(zip_path: Path, clip_to_ct: bool = True) -> gpd.GeoDataFrame:
    """
    Read one weekly zip into a GeoDataFrame of drought polygons.

    We read straight out of the zip (no unzipping to disk) using GDAL's virtual
    filesystem, which geopandas exposes through the "zip://" prefix.
    """
    gdf = gpd.read_file(f"zip://{zip_path.as_posix()}")

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    if clip_to_ct:
        # cx is a bounding-box filter. Far cheaper than a real clip, and enough,
        # because we only ever ask "does this polygon contain my point?".
        minx, miny, maxx, maxy = CT_BBOX
        gdf = gdf.cx[minx:maxx, miny:maxy]

    return gdf[["DM", "geometry"]].copy()


def _stage_from_join(points: gpd.GeoDataFrame, polygons: gpd.GeoDataFrame) -> pd.Series:
    """
    Point-in-polygon lookup: which drought class contains each location?

    Returns stage per point, indexed like `points`. Points in no polygon get 0.

    We group by point and take max(DM) so this is correct whether the polygons are
    disjoint (the `_M` files, where there is only ever one match) or nested (the
    unmodified files, where the worst class is the right answer).
    """
    if polygons.empty:
        return pd.Series(0, index=points.index, dtype=int)

    joined = gpd.sjoin(points, polygons, how="left", predicate="within")
    worst = joined.groupby(joined.index)["DM"].max()

    stage = worst.reindex(points.index)
    # DM 0-4 becomes stage 1-5; no containing polygon (NaN) becomes stage 0.
    return (stage + 1).fillna(0).astype(int)


def build_usdm_labels(
    locations: pd.DataFrame,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    cache_dir: Path,
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
    progress: bool = True,
) -> pd.DataFrame:
    """
    Build the full weekly label table for every location.

    Parameters
    ----------
    locations : must have cell_id plus latitude/longitude columns
    start, end : date range; snapped to USDM Tuesdays automatically
    cache_dir : where zips are stored, normally data/raw/usdm

    Returns a DataFrame: cell_id, date, usdm_stage

    Note this samples at the GRID CELL CENTER, not the original pin. That is
    deliberate and consistent with how features are built - both describe the cell,
    so a farm and its 1 km cell always get the same answer.
    """
    from ctwater.data.grid import points_to_gdf

    pts = points_to_gdf(locations[["cell_id", lat_col, lon_col]], lat_col=lat_col, lon_col=lon_col)
    pts = pts.reset_index(drop=True)

    dates = usdm_dates(start, end)
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    missing = 0

    for i, date in enumerate(dates, 1):
        if progress and (i % 50 == 0 or i == len(dates)):
            print(f"  USDM {i}/{len(dates)} weeks ({date.date()})")

        zip_path = download_usdm_week(date, cache_dir, session=session)
        if zip_path is None:
            missing += 1
            continue

        try:
            polys = load_usdm_week(zip_path)
        except Exception as exc:  # a corrupt cached download should not end the run
            warnings.warn(f"Could not read USDM for {date.date()}: {exc}", stacklevel=2)
            missing += 1
            continue

        frames.append(
            pd.DataFrame(
                {
                    "cell_id": pts["cell_id"].to_numpy(),
                    "date": date,
                    "usdm_stage": _stage_from_join(pts, polys).to_numpy(),
                }
            )
        )

    if not frames:
        raise RuntimeError(
            "No USDM weeks could be downloaded. Check your internet connection, "
            "then try one file by hand: "
            "https://droughtmonitor.unl.edu/data/shapefiles_m/USDM_20220816_M.zip"
        )

    if missing:
        # Never let gaps pass silently - a quietly shortened label record is exactly
        # the kind of thing that makes a model look worse than it is for no reason.
        warnings.warn(f"{missing} of {len(dates)} USDM weeks were unavailable.", stacklevel=2)

    labels = pd.concat(frames, ignore_index=True)
    return labels.sort_values(["cell_id", "date"]).reset_index(drop=True)


def summarize_labels(labels: pd.DataFrame) -> pd.DataFrame:
    """How often each stage occurs. Check this before training - see the note in
    features/targets.py about why class balance decides your metric choice."""
    counts = labels["usdm_stage"].value_counts().sort_index()
    return pd.DataFrame(
        {
            "stage": counts.index,
            "n_weeks": counts.to_numpy(),
            "pct": (100 * counts / len(labels)).round(2).to_numpy(),
        }
    )
