"""
What is actually growing on each square kilometre - from satellite imagery.

WHY THIS EXISTS
---------------
Everything in this project used to assume "mixed vegetables" everywhere. That is
wrong for Connecticut, and the real crop map says so plainly. The 2022 satellite
classification of the state gives roughly:

    Other hay / non-alfalfa   78,900 acres
    Grassland / pasture       67,700 acres
    Corn                      39,300 acres
    Alfalfa                    7,700 acres
    Tobacco                    3,400 acres
    Sweet corn                 2,000 acres
    Apples                     1,500 acres
    Pumpkins                     600 acres

Hay, pasture and corn are about 95% of it. Vegetables are a rounding error.

This matters because two crop-specific numbers drive the irrigation figure, and
both differ a lot between hay and lettuce:

  p  - how far the soil can dry before the plant feels it. Deep-rooted grass hay
       copes to 60% depletion; shallow-rooted vegetables struggle past 35%.
  Kc - how thirsty the crop is relative to a reference grass surface, through the
       year. Bare ground in April and full-canopy corn in July are nothing alike.

Using vegetable values statewide made the model too twitchy on hay ground (warning
of stress that grass would shrug off) and mistimed on corn (whose water use peaks
later and harder than a vegetable field's).

THE DATA
--------
USDA's Cropland Data Layer (CDL): a 30 m classification of every pixel in the
country, produced annually from Landsat and Sentinel imagery combined with ground
truth from farmer-reported acreage. Free, no login.

HOW GOOD IS IT, HONESTLY?
-------------------------
Good for big, distinctive crops - corn and hay in the Northeast classify reliably.
Weak for exactly the farms you care most about: a 2-acre mixed vegetable plot is a
handful of 30 m pixels, and CDL routinely misreads small diversified fields as
"grassland" or as whatever surrounds them. It also cannot see greenhouses or
nursery stock, which is a large share of Connecticut agriculture by value.

So treat the per-cell crop mix as a better default than "assume vegetables," not as
ground truth about any individual farm. `agricultural_fraction` is returned with
every cell so you can see how much of it is farmland at all, and a farmer who knows
their own field should always be able to override it.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Transformer
from rasterio.windows import from_bounds

CDL_FILE_URL = "https://nassgeodata.gmu.edu/webservice/nass_data_cache/byfips/CDL_{year}_{fips}.tif"
CT_FIPS = "09"

# ---------------------------------------------------------------------------
# CDL class code -> the crop group we model.
# Only agricultural classes appear here; anything absent (forest, developed,
# water, wetland) is treated as non-agricultural and ignored when blending.
# ---------------------------------------------------------------------------
CDL_TO_GROUP: dict[int, str] = {
    1: "corn",
    12: "sweet_corn",
    5: "soybeans",
    21: "small_grain",
    22: "small_grain",
    23: "small_grain",
    24: "small_grain",
    27: "small_grain",
    28: "small_grain",
    29: "small_grain",
    36: "alfalfa",
    37: "hay_grass",
    59: "turf_sod",
    60: "turf_sod",
    61: "fallow",
    11: "tobacco",
    68: "orchard",
    69: "orchard",
    66: "orchard",
    67: "orchard",
    70: "orchard",
    71: "orchard",
    72: "orchard",
    74: "orchard",
    75: "orchard",
    76: "orchard",
    77: "orchard",
    204: "vegetables",
    206: "vegetables",
    207: "vegetables",
    208: "vegetables",
    209: "vegetables",
    213: "vegetables",
    214: "vegetables",
    216: "vegetables",
    219: "vegetables",
    221: "vegetables",
    222: "vegetables",
    227: "vegetables",
    229: "vegetables",
    242: "vegetables",
    243: "vegetables",
    244: "vegetables",
    245: "vegetables",
    246: "vegetables",
    247: "vegetables",
    248: "vegetables",
    249: "vegetables",
    250: "vegetables",
    176: "pasture",
}

NON_AG_NOTE = "cell contains no classified cropland; using the fallback crop mix"


def download_cdl(year: int, dest_dir: Path, fips: str = CT_FIPS) -> Path:
    """
    Fetch one year of the Cropland Data Layer for a state, caching the result.

    The file is ~25 MB for Connecticut and never changes once published, so it is
    downloaded once and kept.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"CDL_{year}_{fips}.tif"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    url = CDL_FILE_URL.format(year=year, fips=fips)
    resp = requests.get(url, timeout=600)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def cell_crop_composition(
    locations: pd.DataFrame,
    cdl_path: Path,
    cell_size_m: float = 1000.0,
    lat_col: str = "cell_center_lat",
    lon_col: str = "cell_center_lon",
    min_ag_pixels: int = 25,
    min_ag_fraction: float = 0.02,
) -> pd.DataFrame:
    """
    For each grid cell, what fraction of its farmland is each crop group?

    We deliberately do NOT just take the single most common crop. A square
    kilometre of Connecticut is a patchwork - a corn field, a hay meadow, some
    woods, a road - so we count every pixel and return the mix. The irrigation
    figure then blends crop parameters by area, which is both more honest and more
    stable than flipping between crops as a pin moves a few hundred metres.

    MINIMUM EVIDENCE RULE
    ---------------------
    A cell needs at least `min_ag_pixels` farmland pixels AND `min_ag_fraction` of
    its area as farmland before we trust its crop mix. Without this, a cell that is
    99.8% forest with two stray tobacco pixels reports "tobacco 100%" and gets
    tobacco's shallow-rooted threshold - a confident-looking answer built on almost
    nothing. Below the thresholds we say so and fall back to the default crop.

    25 pixels at 30 m is about 5.5 acres, a plausible small field.

    Returns one row per cell with:
        cell_id
        frac_<group>          fraction of the cell's AGRICULTURAL area, sums to 1
        agricultural_fraction fraction of the whole cell that is farmland at all
        dominant_crop         the largest group, for reporting
        crop_evidence         "ok" or why the cell was not trusted
    """
    with rasterio.open(cdl_path) as src:
        # Grid cells are defined in a Connecticut-specific projection; the CDL is in
        # a national one. Convert each cell's corners into the raster's coordinates
        # so we read the right patch of pixels.
        to_cdl = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
        half = cell_size_m / 2.0

        rows = []
        for _, loc in locations.iterrows():
            cx, cy = to_cdl.transform(loc[lon_col], loc[lat_col])
            try:
                window = from_bounds(
                    cx - half, cy - half, cx + half, cy + half, transform=src.transform
                )
                patch = src.read(1, window=window, boundless=True, fill_value=0)
            except (ValueError, rasterio.errors.RasterioError):
                patch = np.zeros((1, 1), dtype=np.uint8)

            rows.append(_summarize_patch(loc["cell_id"], patch, min_ag_pixels, min_ag_fraction))

    comp = pd.DataFrame(rows).fillna(0.0)

    frac_cols = [c for c in comp.columns if c.startswith("frac_")]
    if not frac_cols:
        raise RuntimeError("No crop classes found anywhere - is the CDL file valid?")

    return comp


def _summarize_patch(
    cell_id: str, patch: np.ndarray, min_ag_pixels: int, min_ag_fraction: float
) -> dict:
    """Turn one cell's block of CDL pixels into crop-group fractions."""
    codes, counts = np.unique(patch, return_counts=True)
    total_px = int(counts.sum())

    group_counts: dict[str, int] = {}
    ag_px = 0
    for code, n in zip(codes.tolist(), counts.tolist(), strict=True):
        group = CDL_TO_GROUP.get(int(code))
        if group is None:
            continue
        group_counts[group] = group_counts.get(group, 0) + n
        ag_px += n

    ag_frac = ag_px / max(total_px, 1)
    out: dict = {"cell_id": cell_id, "agricultural_fraction": ag_frac}

    if ag_px == 0:
        out["dominant_crop"] = "none"
        out["crop_evidence"] = "no cropland detected"
        return out

    if ag_px < min_ag_pixels or ag_frac < min_ag_fraction:
        # Too little farmland to say anything trustworthy about what grows here.
        out["dominant_crop"] = "insufficient"
        out["crop_evidence"] = (
            f"only {ag_px} cropland pixels ({100 * ag_frac:.1f}% of cell) — below the "
            f"{min_ag_pixels}-pixel / {100 * min_ag_fraction:.0f}% minimum"
        )
        return out

    for group, n in group_counts.items():
        out[f"frac_{group}"] = n / ag_px
    out["dominant_crop"] = max(group_counts, key=group_counts.get)
    out["crop_evidence"] = "ok"
    return out


def blend_crop_parameters(
    composition: pd.DataFrame,
    crop_params: dict,
    fallback_group: str = "hay_grass",
) -> pd.DataFrame:
    """
    Turn each cell's crop mix into the two numbers the irrigation model needs.

    p is area-weighted across whatever grows there. Kc is handled per-row later
    (it depends on the date as well as the crop), so here we just carry the
    fractions forward and resolve the depletion threshold.

    Cells with no detected cropland fall back to `fallback_group` - grass hay,
    since that is Connecticut's most common agricultural cover and a far safer
    default than vegetables.
    """
    comp = composition.copy()
    groups = [g for g in crop_params if f"frac_{g}" in comp.columns]

    p_vals = np.zeros(len(comp), dtype=float)
    weight = np.zeros(len(comp), dtype=float)
    for g in groups:
        f = comp[f"frac_{g}"].to_numpy(dtype=float)
        p_vals += f * float(crop_params[g]["p"])
        weight += f

    fallback_p = float(crop_params[fallback_group]["p"])
    no_crop = weight <= 1e-9
    p_vals = np.where(no_crop, fallback_p, p_vals / np.where(no_crop, 1.0, weight))

    comp["depletion_threshold"] = np.round(p_vals, 4)
    comp["crop_note"] = np.where(no_crop, NON_AG_NOTE, "")

    if no_crop.any():
        warnings.warn(
            f"{int(no_crop.sum())} of {len(comp)} cells have no usable crop data (no cropland, "
            f"or too few pixels to trust); they fall back to '{fallback_group}' parameters.",
            stacklevel=2,
        )
    return comp


def blended_kc(
    day_of_year: pd.Series,
    composition_row_fracs: pd.DataFrame,
    crop_params: dict,
    fallback_group: str = "hay_grass",
) -> np.ndarray:
    """
    Area-weighted crop coefficient for each row, given its date and its cell's mix.

    Kc has to be computed per row rather than per cell because it changes through
    the year: corn peaks in late July, hay stays moderately thirsty from May to
    September, an orchard holds a high Kc all summer.
    """
    from ctwater.features.dry import crop_coefficient

    doy = pd.to_numeric(day_of_year).to_numpy(dtype=float)
    kc = np.zeros(len(doy), dtype=float)
    weight = np.zeros(len(doy), dtype=float)

    for g, params in crop_params.items():
        col = f"frac_{g}"
        if col not in composition_row_fracs.columns:
            continue
        f = composition_row_fracs[col].to_numpy(dtype=float)
        kc += f * crop_coefficient(doy, params["kc_curve"])
        weight += f

    no_crop = weight <= 1e-9
    fallback = crop_coefficient(doy, crop_params[fallback_group]["kc_curve"])
    return np.where(no_crop, fallback, kc / np.where(no_crop, 1.0, weight))


def summarize_composition(composition: pd.DataFrame) -> pd.DataFrame:
    """Readable per-cell summary: what grows here, and how much of it is farmland."""
    frac_cols = sorted(c for c in composition.columns if c.startswith("frac_"))
    rows = []
    for _, r in composition.iterrows():
        parts = [
            f"{c.replace('frac_', '')} {100 * r[c]:.0f}%"
            for c in frac_cols
            if float(r.get(c, 0) or 0) >= 0.10
        ]
        if parts:
            mix = ", ".join(parts)
        elif str(r.get("dominant_crop")) == "insufficient":
            mix = "too little farmland to tell"
        else:
            mix = "none detected"

        rows.append(
            {
                "cell_id": r["cell_id"],
                "farmland": f"{100 * r['agricultural_fraction']:.1f}%",
                "crop mix": mix,
                "p": round(float(r.get("depletion_threshold", float("nan"))), 3),
            }
        )
    return pd.DataFrame(rows)
