"""
The dataset registry: one place that lists every input source and how to read it.

RIGHT NOW THIS IS INTENTIONALLY A SKELETON. You said you would pick the datasets
later - when you do, we fill in the `DataSource` entries below and write one
`load_*` function per source. Nothing else in the project has to change, because
everything downstream only ever asks for the tidy table these produce.

THE CONTRACT EVERY SOURCE MUST HONOR
------------------------------------
Each loader returns a "long/tidy" pandas DataFrame with exactly these columns:

    cell_id   str        which analysis grid cell (from grid.snap_to_grid)
    date      datetime   the observation date, no timezone, midnight
    variable  str        e.g. "precip_mm", "soil_moist_0_10cm", "ndvi"
    value     float      the number

Keeping every source in this one shape is the trick that makes the rest of the
pipeline simple: joining ten different datasets becomes a single concat + pivot
instead of ten bespoke merge scripts.

STATIC (non-time-varying) layers - soil water holding capacity, elevation, slope,
land cover - return columns: cell_id, variable, value (no date).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import rowcol

TIDY_COLUMNS = ["cell_id", "date", "variable", "value"]


@dataclass
class DataSource:
    """Metadata describing one input dataset. Fill these in as you choose sources."""

    key: str  # short name used in filenames and configs
    title: str  # human-readable
    kind: Literal["raster", "point", "polygon", "tabular"]
    cadence: Literal["daily", "weekly", "monthly", "static"]
    native_resolution: str  # e.g. "4 km", "point", "1:24000"
    variables: list[str]  # tidy `variable` names it produces
    url: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Candidate sources for this project. NOTHING here is wired up yet - this is a
# menu for you to choose from. Delete what you do not want, add what you do.
# ---------------------------------------------------------------------------
REGISTRY: dict[str, DataSource] = {
    "usdm": DataSource(
        key="usdm",
        title="U.S. Drought Monitor weekly drought classification",
        kind="polygon",
        cadence="weekly",
        native_resolution="polygons, county-to-subcounty detail",
        variables=["usdm_stage"],
        notes="Primary LABEL source (the answer key). D0-D4 becomes stages 1-5, none is 0.",
    ),
    "precip": DataSource(
        key="precip",
        title="Gridded daily precipitation",
        kind="raster",
        cadence="daily",
        native_resolution="TBD",
        variables=["precip_mm"],
        notes="The single strongest predictor. Needs long history to compute SPI.",
    ),
    "temp": DataSource(
        key="temp",
        title="Gridded daily min/max temperature",
        kind="raster",
        cadence="daily",
        native_resolution="TBD",
        variables=["tmax_c", "tmin_c"],
    ),
    "et": DataSource(
        key="et",
        title="Evapotranspiration / atmospheric water demand",
        kind="raster",
        cadence="daily",
        native_resolution="TBD",
        variables=["et0_mm"],
        notes="Rain minus ET is what actually reaches the crop. Usually a big accuracy win.",
    ),
    "soil_moisture": DataSource(
        key="soil_moisture",
        title="Modeled or satellite soil moisture",
        kind="raster",
        cadence="daily",
        native_resolution="TBD",
        variables=["soil_moist_0_10cm", "soil_moist_10_40cm"],
    ),
    "ndvi": DataSource(
        key="ndvi",
        title="Satellite vegetation greenness",
        kind="raster",
        cadence="weekly",
        native_resolution="TBD",
        variables=["ndvi"],
        notes="Shows stress plants ALREADY feel. Lags rainfall by roughly 2-4 weeks.",
    ),
    "streamflow": DataSource(
        key="streamflow",
        title="USGS stream gauge discharge",
        kind="point",
        cadence="daily",
        native_resolution="point",
        variables=["streamflow_pct"],
    ),
    "groundwater": DataSource(
        key="groundwater",
        title="USGS groundwater well levels",
        kind="point",
        cadence="daily",
        native_resolution="point",
        variables=["gw_depth_ft"],
        notes="Critical for CT small farms irrigating from private wells.",
    ),
    "soils": DataSource(
        key="soils",
        title="Soil properties (available water capacity, drainage class)",
        kind="polygon",
        cadence="static",
        native_resolution="1:12000 to 1:24000",
        variables=["awc_mm", "drainage_class"],
        notes="THE reason two neighboring fields behave differently. High value for you.",
    ),
    "terrain": DataSource(
        key="terrain",
        title="Elevation-derived terrain",
        kind="raster",
        cadence="static",
        native_resolution="TBD",
        variables=["elevation_m", "slope_deg", "aspect_deg", "twi"],
        notes="TWI is the topographic wetness index; predicts where water collects.",
    ),
}


def describe_registry() -> pd.DataFrame:
    """Pretty table of everything in the registry. Used by `ctwater sources`."""
    return pd.DataFrame(
        [
            {
                "key": s.key,
                "kind": s.kind,
                "cadence": s.cadence,
                "variables": ", ".join(s.variables),
                "title": s.title,
            }
            for s in REGISTRY.values()
        ]
    )


# ---------------------------------------------------------------------------
# Generic readers you will reuse for most sources.
# ---------------------------------------------------------------------------
def sample_raster_at_points(
    raster_path: str | Path,
    lons: np.ndarray,
    lats: np.ndarray,
    band: int = 1,
    nodata_to_nan: bool = True,
) -> np.ndarray:
    """
    Read the pixel value of a GeoTIFF raster at each lat/lon point.

    This is the workhorse for turning "a map" into "a number for my farm".

    Parameters
    ----------
    raster_path : the .tif file
    lons, lats  : arrays of the SAME length, in degrees (EPSG:4326)

    Returns an array of values, NaN wherever the point falls outside the raster
    or lands on a nodata pixel.
    """
    lons = np.atleast_1d(np.asarray(lons, dtype=float))
    lats = np.atleast_1d(np.asarray(lats, dtype=float))

    with rasterio.open(raster_path) as src:
        # If the raster is not in lat/lon, reproject our points into its CRS first.
        if src.crs is not None and src.crs.to_string() != "EPSG:4326":
            from pyproj import Transformer

            tf = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            xs, ys = tf.transform(lons, lats)
        else:
            xs, ys = lons, lats

        rows, cols = rowcol(src.transform, xs, ys)
        rows = np.atleast_1d(np.asarray(rows))
        cols = np.atleast_1d(np.asarray(cols))

        data = src.read(band)
        out = np.full(rows.shape, np.nan, dtype=float)

        inside = (rows >= 0) & (rows < src.height) & (cols >= 0) & (cols < src.width)
        out[inside] = data[rows[inside], cols[inside]].astype(float)

        if nodata_to_nan and src.nodata is not None:
            out[out == src.nodata] = np.nan

    return out


def to_tidy(
    df: pd.DataFrame,
    value_cols: list[str],
    id_col: str = "cell_id",
    date_col: str = "date",
) -> pd.DataFrame:
    """
    Reshape a wide table (one column per variable) into the tidy contract shape.

    wide:  cell_id | date | precip_mm | tmax_c
    tidy:  cell_id | date | variable  | value
    """
    out = df.melt(
        id_vars=[id_col, date_col],
        value_vars=value_cols,
        var_name="variable",
        value_name="value",
    )
    out[date_col] = pd.to_datetime(out[date_col])
    return out[TIDY_COLUMNS]


def validate_tidy(df: pd.DataFrame, source_key: str = "unknown") -> pd.DataFrame:
    """
    Fail loudly and early if a loader breaks the contract.

    Beginner tip: checks like this are worth far more than they look. A silent
    schema mistake in step 2 becomes a baffling model failure in step 9.
    """
    missing = set(TIDY_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"[{source_key}] tidy frame is missing columns: {sorted(missing)}")
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        raise TypeError(f"[{source_key}] 'date' must be datetime, got {df['date'].dtype}")
    if not pd.api.types.is_numeric_dtype(df["value"]):
        raise TypeError(f"[{source_key}] 'value' must be numeric, got {df['value'].dtype}")

    # Part of the contract: one time precision for every source. Sources arrive in
    # different resolutions and pandas will not merge across them.
    out = df[TIDY_COLUMNS].copy()
    out["date"] = out["date"].astype("datetime64[ns]")
    return out
