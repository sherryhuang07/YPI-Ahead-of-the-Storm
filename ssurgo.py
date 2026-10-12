"""
USDA soil survey: how much water each field can actually hold.

WHY THIS IS THE MOST IMPORTANT REMAINING DATASET
------------------------------------------------
Your project's claim is location precision - that a forecast for one farm should
differ from the forecast for a farm five miles away. Rainfall cannot deliver that,
because it is interpolated from a few dozen gauges and barely varies over 1 km.
Soil can, and does.

Two fields receiving identical rain behave completely differently if one holds
60 mm of plant-available water and the other holds 180 mm. The sandy one is in
trouble after ten dry days; the loamy one coasts for a month. That difference is
mapped, at a scale far finer than 1 km, and it has been sitting unused while
`awc_mm` was an invented random number between 60 and 180.

THE SOURCE
----------
SSURGO - the Soil Survey Geographic Database, the detailed county-level soil
survey NRCS has been building since the 1890s. Mapped at 1:12,000 to 1:24,000,
so polygons are often just a few acres.

We query it through Soil Data Access (SDA), a public SQL endpoint. No login.

WHAT WE TAKE
------------
NRCS has already done the hard aggregation for us. The `muaggatt` table carries
"available water storage" summed over a depth range and weighted across the soil
components in each map unit:

    aws050wta    water held in the top 50 cm,  in cm
    aws0100wta   water held in the top 100 cm, in cm
    aws0150wta   water held in the top 150 cm, in cm

Multiply by 10 for millimetres. Doing this ourselves from the horizon tables would
mean depth-weighting every layer and component percentage by hand, and getting the
same answer with more chances to be wrong.

WHICH DEPTH? THE CROP DECIDES
-----------------------------
A lettuce root system cannot reach water at 120 cm, so counting it would overstate
what the plant can actually use. Rooting depths come from FAO-56 and are set per
crop in config.yaml, and because we already know each cell's crop mix from the
satellite map, the depth is blended the same way:

    vegetables, tobacco, turf   50 cm
    hay, pasture, corn, grain   100 cm
    alfalfa, orchard            150 cm

So a hay field and a lettuce field on the *same soil* get different usable water.
That is correct, and it is the kind of distinction this project exists to make.

SAMPLING: WHY NINE POINTS PER CELL
----------------------------------
SSURGO polygons are much smaller than a 1 km cell, so a single reading at the
centre could land on an unrepresentative patch - a road verge, a wet hollow. We
sample a 3x3 grid across each cell and average. Sampling more points would be
better still; nine is the point where the improvement stops being worth the query
time.

A CAVEAT WORTH READING
----------------------
Some of the invented farm locations in this project sit on urban land, where the
survey reports almost no water storage because the soil is buried under buildings.
That is a true statement about the coordinate and a useless one about farming. The
loader flags cells whose water storage is implausibly low for agriculture rather
than silently feeding the model a soil that dries out in two days.
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path

import pandas as pd
import requests

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"

# Depth columns SSURGO publishes, and the rooting depth each one represents.
DEPTH_COLUMNS = {50: "aws050wta", 100: "aws0100wta", 150: "aws0150wta"}

# Below this, the "soil" is pavement, open water, or a survey gap - not farmland.
MIN_PLAUSIBLE_AWC_MM = 25.0

# Used when a cell has no usable soil reading at all. A middling Connecticut loam.
FALLBACK_AWC_MM = 120.0


def _point_literal(pid: object, lon: object, lat: object) -> str:
    """
    Build one `(id, 'point(lon lat)')` row for the query, safely.

    Every value is forced through int() or float() and checked for finiteness, so
    no string a caller supplies can survive into the SQL. This is what lets the
    query below be built by formatting at all - see the note there.
    """
    pid_i = int(pid)
    lon_f, lat_f = float(lon), float(lat)

    if not (math.isfinite(lon_f) and math.isfinite(lat_f)):
        raise ValueError(f"Non-finite coordinate for point {pid_i}: ({lon_f}, {lat_f})")
    if not (-180.0 <= lon_f <= 180.0 and -90.0 <= lat_f <= 90.0):
        raise ValueError(f"Coordinate out of range for point {pid_i}: ({lon_f}, {lat_f})")

    return f"({pid_i},'point({lon_f:.6f} {lat_f:.6f})')"


def _sda_query(sql: str, timeout: int = 300) -> pd.DataFrame:
    """Run one SQL statement against Soil Data Access and return it as a table."""
    resp = requests.post(SDA_URL, json={"format": "JSON", "query": sql}, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()

    rows = payload.get("Table", [])
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def sample_points_for_cells(
    locations: pd.DataFrame,
    cell_size_m: float = 1000.0,
    n_per_side: int = 3,
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
    crs_projected: str = "EPSG:6433",
) -> pd.DataFrame:
    """
    Lay a small grid of sample points inside each cell.

    Offsets are computed in projected metres and converted back to degrees, so the
    spacing is genuinely even on the ground rather than stretched east-west.
    """
    from pyproj import Transformer

    to_proj = Transformer.from_crs("EPSG:4326", crs_projected, always_xy=True)
    to_geo = Transformer.from_crs(crs_projected, "EPSG:4326", always_xy=True)

    # Evenly spaced inside the cell, avoiding the very edges.
    step = cell_size_m / (n_per_side + 1)
    offsets = [(i + 1) * step - cell_size_m / 2 for i in range(n_per_side)]

    rows = []
    for _, loc in locations.iterrows():
        cx, cy = to_proj.transform(loc[lon_col], loc[lat_col])
        for dx in offsets:
            for dy in offsets:
                lon, lat = to_geo.transform(cx + dx, cy + dy)
                rows.append({"cell_id": loc["cell_id"], "lat": lat, "lon": lon})

    out = pd.DataFrame(rows).reset_index(drop=True)
    out["pid"] = out.index
    return out


def fetch_soil_at_points(points: pd.DataFrame, batch_size: int = 100) -> pd.DataFrame:
    """
    Look up soil properties at each sample point.

    Uses a single SQL statement per batch: a table of points, CROSS APPLYed
    through SSURGO's point-in-polygon function and joined to the aggregated soil
    attributes. That keeps per-point attribution, which a MULTIPOINT query loses.
    """
    frames: list[pd.DataFrame] = []
    failures: list[str] = []

    depth_cols = ", ".join(f"m.{c}" for c in DEPTH_COLUMNS.values())

    for i in range(0, len(points), batch_size):
        batch = points.iloc[i : i + batch_size]
        values = ", ".join(_point_literal(r.pid, r.lon, r.lat) for r in batch.itertuples())

        # A security linter flags SQL built by string formatting (B608), and it is
        # right to. Soil Data Access is a REST endpoint that takes a SQL string, so
        # bound parameters are not available - we cannot use the normal fix.
        #
        # What makes this safe is that NOTHING string-shaped reaches the query.
        # `_point_literal` forces every value through int() and float() and rejects
        # anything non-finite, so the only characters that can appear are digits,
        # signs, dots and the punctuation we write ourselves. `depth_cols` is built
        # from a module constant, not from input.
        sql = (
            f"SELECT p.pid, m.mukey, m.muname, {depth_cols}, m.drclassdcd "  # nosec B608
            f"FROM (VALUES {values}) AS p(pid, wkt) "
            "CROSS APPLY SDA_Get_Mukey_from_intersection_with_WktWgs84(p.wkt) AS k "
            "INNER JOIN muaggatt m ON m.mukey = k.mukey"
        )

        try:
            table = _sda_query(sql)
        except (requests.RequestException, ValueError) as exc:
            detail = f"points {i}-{i + len(batch)}: {type(exc).__name__}: {exc}"
            failures.append(detail)
            warnings.warn(f"SSURGO query failed - {detail}", stacklevel=2)
            continue

        if table.empty:
            continue

        table.columns = ["pid", "mukey", "muname", *DEPTH_COLUMNS.values(), "drainage_class"]
        frames.append(table)

    if not frames:
        cause = "\n  ".join(failures) if failures else "queries succeeded but returned no soil"
        raise RuntimeError(
            f"No soil data returned for {len(points)} sample points.\n"
            f"What actually went wrong:\n  {cause}\n"
            "Test by hand at https://sdmdataaccess.sc.egov.usda.gov/"
        )

    out = pd.concat(frames, ignore_index=True)
    out["pid"] = pd.to_numeric(out["pid"], errors="coerce").astype("Int64")
    for col in DEPTH_COLUMNS.values():
        # Water storage arrives in centimetres; the rest of the project uses mm.
        out[col] = pd.to_numeric(out[col], errors="coerce") * 10.0
    return out


def blended_root_depth_cm(
    composition: pd.DataFrame | None, crop_params: dict, fallback_group: str = "hay_grass"
) -> pd.Series:
    """
    How deep each cell's crops actually root, area-weighted by the crop mix.

    Returns a Series indexed by cell_id. Cells with no crop data fall back to the
    default group's depth.
    """
    fallback_depth = float(crop_params[fallback_group].get("root_depth_cm", 100))

    if composition is None or composition.empty:
        return pd.Series(dtype=float)

    depths, weights = {}, {}
    for _, row in composition.iterrows():
        cell = row["cell_id"]
        total = 0.0
        depth = 0.0
        for group, params in crop_params.items():
            frac = float(row.get(f"frac_{group}", 0) or 0)
            if frac <= 0:
                continue
            depth += frac * float(params.get("root_depth_cm", 100))
            total += frac
        depths[cell] = depth / total if total > 0 else fallback_depth
        weights[cell] = total

    return pd.Series(depths, dtype=float)


def _pick_depth_column(depth_cm: float) -> str:
    """Snap a rooting depth to the nearest depth range SSURGO publishes."""
    nearest = min(DEPTH_COLUMNS, key=lambda d: abs(d - depth_cm))
    return DEPTH_COLUMNS[nearest]


def build_cell_soils(
    locations: pd.DataFrame,
    cache_dir: Path,
    crop_composition: pd.DataFrame | None = None,
    crop_params: dict | None = None,
    fallback_crop: str = "hay_grass",
    cell_size_m: float = 1000.0,
    n_per_side: int = 3,
    progress: bool = True,
) -> pd.DataFrame:
    """
    The one call the pipeline makes: per-cell available water capacity, in mm.

    Returns cell_id, awc_mm, root_depth_cm, drainage_class, dominant_soil,
    n_samples, soil_note.
    """
    from ctwater.data.grid import locations_fingerprint

    cache_dir.mkdir(parents=True, exist_ok=True)
    raw_path = cache_dir / f"ssurgo_points_{locations_fingerprint(locations)}.parquet"

    points = sample_points_for_cells(locations, cell_size_m=cell_size_m, n_per_side=n_per_side)

    if raw_path.exists():
        sampled = pd.read_parquet(raw_path)
        if progress:
            print(f"  {len(sampled):,} soil samples (cached)")
    else:
        if progress:
            print(f"  querying SSURGO at {len(points)} points ...")
        sampled = fetch_soil_at_points(points)
        sampled.to_parquet(raw_path, index=False)

    merged = points.merge(sampled, on="pid", how="left")

    # Rooting depth per cell, from the crop mix.
    depths = pd.Series(dtype=float)
    if crop_composition is not None and crop_params is not None:
        depths = blended_root_depth_cm(crop_composition, crop_params, fallback_crop)
    default_depth = (
        float(crop_params[fallback_crop].get("root_depth_cm", 100)) if crop_params else 100.0
    )

    rows = []
    for cell_id, grp in merged.groupby("cell_id"):
        depth_cm = float(depths.get(cell_id, default_depth))
        col = _pick_depth_column(depth_cm)

        values = grp[col].dropna()
        n = len(values)

        if n == 0:
            awc, note = FALLBACK_AWC_MM, "no soil survey coverage; using a default loam"
        else:
            awc = float(values.mean())
            if awc < MIN_PLAUSIBLE_AWC_MM:
                note = (
                    f"survey reports only {awc:.0f} mm - this cell is likely pavement or "
                    "open water, not farmland"
                )
            else:
                note = ""

        names = grp["muname"].dropna()
        drainage = grp["drainage_class"].dropna()

        rows.append(
            {
                "cell_id": cell_id,
                "awc_mm": round(awc, 1),
                "root_depth_cm": round(depth_cm),
                "n_samples": n,
                "dominant_soil": names.mode().iloc[0] if len(names) else "unknown",
                "drainage_class": drainage.mode().iloc[0] if len(drainage) else "unknown",
                "soil_note": note,
            }
        )

    out = pd.DataFrame(rows)

    flagged = out[out["soil_note"] != ""]
    if len(flagged):
        warnings.warn(
            f"{len(flagged)} of {len(out)} cells have implausible soil for farming "
            "(urban land, water, or no survey coverage). Their awc_mm is real but not "
            "agriculturally meaningful - check the soil_note column.",
            stacklevel=2,
        )
    return out


def summarize(soils: pd.DataFrame) -> pd.DataFrame:
    """Readable per-cell summary of what the survey found."""
    return pd.DataFrame(
        {
            "cell_id": soils["cell_id"],
            "water mm": soils["awc_mm"],
            "root cm": soils["root_depth_cm"],
            "drainage": soils["drainage_class"].str.slice(0, 18),
            "dominant soil": soils["dominant_soil"].str.slice(0, 34),
        }
    )


def compare_with_invented(soils: pd.DataFrame, locations: pd.DataFrame) -> str:
    """
    How wrong was the invented soil data?

    `awc_mm` used to be a uniform random draw between 60 and 180 mm. This says how
    far that guess was from the surveyed truth, which is worth knowing before
    trusting any earlier result that depended on it.
    """
    if "awc_mm" not in locations.columns:
        return "No previous awc_mm to compare against."

    merged = soils[["cell_id", "awc_mm"]].merge(
        locations[["cell_id", "awc_mm"]], on="cell_id", suffixes=("_real", "_invented")
    )
    if merged.empty:
        return "No overlapping cells to compare."

    diff = (merged["awc_mm_real"] - merged["awc_mm_invented"]).abs()
    corr = merged["awc_mm_real"].corr(merged["awc_mm_invented"])

    return (
        f"Invented mean {merged['awc_mm_invented'].mean():.0f} mm vs surveyed "
        f"{merged['awc_mm_real'].mean():.0f} mm.\n"
        f"Mean absolute error of the invented values: {diff.mean():.0f} mm "
        f"(worst {diff.max():.0f} mm).\n"
        f"Correlation between invented and real: {corr:+.2f} "
        f"({'as expected for random numbers' if abs(corr) < 0.4 else 'suspiciously high'})."
    )
