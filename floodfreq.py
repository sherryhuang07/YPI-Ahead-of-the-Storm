"""
NRCS flood and ponding frequency: how susceptible is this GROUND?

THE MISSING HALF OF THE FLOOD QUESTION
--------------------------------------
Atlas 14 answers "how rare is this rain here". It says nothing about whether the
land it falls on is a river terrace or a hillside. Those are not the same field:

    a 2-year storm on Connecticut River floodplain silt   ->  water over the crop
    the same storm on a Hinckley gravelly outwash slope   ->  gone by evening

Every flood signal in this project so far has been about WEATHER. This one is
about PLACE, and it is permanent - it does not change day to day, which is
exactly why it adds information the weather features cannot.

NRCS rates every soil map unit for how often it floods and how often it ponds,
from field observation and landform position. Across Connecticut's 633 map units:

    None            467      most of the state, as you would expect
    Very frequent   121      floodplains and low terraces
    Rare             20
    Frequent         17
    Occasional        6

So about a quarter of Connecticut's mapped soils flood at some rate. A model that
treats a floodplain farm and a hillside farm identically is throwing that away.

FLOODING AND PONDING ARE DIFFERENT THINGS
-----------------------------------------
    FLOODING  water arrives from somewhere else - a river leaves its channel and
              covers the field. A landform property: you are low, near a channel.

    PONDING   water collects where it fell and cannot leave, because the
              depression has no outlet. This is the WATERLOGGING mechanism, the
              one that rots roots.

Ponding matters especially here. `features/wet.py` had to drop waterlogging from
the event definition because our soil moisture is a bucket model with no drainage
delay, so it reported saturation on 27% of growing-season days. Ponding frequency
is a real, observed, per-soil statement about where water actually stands - it is
the honest version of the signal we had to remove.

WHAT THE CLASSES MEAN, AS RETURN PERIODS
----------------------------------------
NRCS defines these as annual chances, which converts directly onto the Atlas 14
scale and lets storm rarity and site susceptibility be compared in one unit:

    class            NRCS definition                approx. return period
    None             no reasonable possibility              -
    Very rare        < 1 time in 100 years              ~200 years
    Rare             1 to 5 times in 100 years           ~40 years
    Occasional       5 to 50 times in 100 years           ~7 years
    Frequent         > 50 times in 100 years              ~1.5 years
    Very frequent    more than once per year              ~0.5 years

A "Very frequent" soil floods on ordinary rain, by definition. A "None" soil
needs something exceptional. That is the location specificity a statewide
rainfall threshold cannot express.

THE MONTHLY TABLE TURNED OUT NOT TO BE WORTH IT
-----------------------------------------------
SSURGO's `comonth` table carries flood and ponding class per MONTH, which looked
like the seasonality Atlas 14 lacks. Measured on Connecticut, it is nearly flat -
558 "Very frequent" component-months in every month of the year, with only a
slight summer dip in the "Rare" class. The seasonal detail does not exist in the
data for this state, so this module uses the annual dominant condition and says
so, rather than carrying a 12x join that encodes nothing.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import requests

from ctwater.data.ssurgo import _point_literal, _sda_query

# NRCS frequency class -> approximate return period in years. Midpoints of the
# published ranges, on a log scale, because these ranges are geometric.
#
# `None` becomes a large finite number rather than infinity: it keeps the column
# numeric and orderable, and no Connecticut farm is truly incapable of flooding.
FLOOD_CLASS_ARI = {
    "None": 500.0,
    "Very rare": 200.0,
    "Rare": 40.0,
    "Occasional": 7.0,
    "Frequent": 1.5,
    "Very frequent": 0.5,
}

# Ponding uses a shorter list in practice - Connecticut has only None,
# Occasional and Frequent.
POND_CLASS_ARI = {
    "None": 500.0,
    "Rare": 40.0,
    "Occasional": 7.0,
    "Frequent": 1.5,
    "Very frequent": 0.5,
}


# MINIMUM EVIDENCE, the same rule the cropland loader uses.
#
# A map unit is a mixture. Without this threshold the worst-case rule picks up
# tiny wet inclusions - a 5% depression inside an 85% well-drained component -
# and rates the whole farm as frequently ponded. Measured, that produced 72% of
# farms rated "Frequent" ponding, which is not credible for land people chose to
# farm. A component must occupy at least this share of the map unit before its
# ponding counts.
MIN_COMPONENT_PCT = 15


def fetch_flood_ponding_at_points(points: pd.DataFrame, batch_size: int = 100) -> pd.DataFrame:
    """
    Flood and ponding ratings at each sample point.

    Flooding comes from `muaggatt.flodfreqdcd`, which is already the dominant
    condition for the map unit. Ponding is not in that table, so it is aggregated
    from `component` weighted by `comppct_r` - the share of the map unit each
    component occupies.

    Returns pid, mukey, flood_class, pond_class.
    """
    frames: list[pd.DataFrame] = []
    failures: list[str] = []

    for i in range(0, len(points), batch_size):
        batch = points.iloc[i : i + batch_size]
        values = ", ".join(_point_literal(r.pid, r.lon, r.lat) for r in batch.itertuples())

        # Same B608 reasoning as ssurgo.fetch_soil_at_points: Soil Data Access is
        # a REST endpoint that accepts a SQL string, so bound parameters do not
        # exist. Safety comes from `_point_literal`, which forces every value
        # through int()/float() and rejects non-finite numbers, so nothing
        # string-shaped can reach the query. Everything else here is a literal.
        # Ponding is NOT on `component` - the column is `comonth.pondfreqcl`, one
        # row per component per month. It is collapsed to a single worst-case
        # number in SQL with a CASE, because SDA rejects TOP/ORDER BY inside a
        # correlated subquery, and because pulling 12 rows per component and
        # aggregating in pandas would multiply the payload for no gain.
        sql = (
            "SELECT p.pid, m.mukey, m.flodfreqdcd, "  # nosec B608
            "  (SELECT MIN(CASE cm.pondfreqcl "
            "     WHEN 'Very frequent' THEN 0.5 WHEN 'Frequent' THEN 1.5 "
            "     WHEN 'Occasional' THEN 7 WHEN 'Rare' THEN 40 ELSE 500 END) "
            "   FROM comonth cm INNER JOIN component c2 ON c2.cokey = cm.cokey "
            f"   WHERE c2.mukey = m.mukey AND c2.comppct_r >= {MIN_COMPONENT_PCT}) AS pond_ari "
            f"FROM (VALUES {values}) AS p(pid, wkt) "
            "CROSS APPLY SDA_Get_Mukey_from_intersection_with_WktWgs84(p.wkt) AS k "
            "INNER JOIN muaggatt m ON m.mukey = k.mukey"
        )

        try:
            table = _sda_query(sql)
        except (requests.RequestException, ValueError) as exc:
            detail = f"points {i}-{i + len(batch)}: {type(exc).__name__}: {exc}"
            failures.append(detail)
            warnings.warn(f"Flood/ponding query failed - {detail}", stacklevel=2)
            continue

        if table.empty:
            continue
        table.columns = ["pid", "mukey", "flood_class", "pond_ari"]
        frames.append(table)

    if not frames:
        cause = "\n  ".join(failures) if failures else "queries succeeded but returned nothing"
        raise RuntimeError(
            f"No flood/ponding ratings returned for {len(points)} points.\n"
            f"What actually went wrong:\n  {cause}\n"
            "Test by hand at https://sdmdataaccess.sc.egov.usda.gov/"
        )

    out = pd.concat(frames, ignore_index=True)
    out["pid"] = pd.to_numeric(out["pid"], errors="coerce").astype("Int64")
    out["pond_ari"] = pd.to_numeric(out["pond_ari"], errors="coerce")
    return out


def build_cell_flood_ratings(
    locations: pd.DataFrame,
    n_side: int = 3,
    batch_size: int = 100,
    progress: bool = True,
) -> pd.DataFrame:
    """
    One flood and ponding rating per cell.

    Sampled on the same 3x3 grid as the soil water properties, because a farm
    cell is a square kilometre and can easily straddle a terrace edge - which is
    exactly where flood rating changes. The cell takes the WORST rating found
    rather than the average: if part of your field is on the floodplain, your
    field floods, and averaging that away would be the wrong kind of tidy.

    Returns cell_id, flood_class, pond_class, site_flood_ari_years,
    site_pond_ari_years, flood_prone.
    """
    from ctwater.data.ssurgo import sample_points_for_cells

    points = sample_points_for_cells(locations, n_per_side=n_side)
    if progress:
        print(f"  {len(points)} sample points across {len(locations)} cells")

    raw = fetch_flood_ponding_at_points(points, batch_size=batch_size)
    merged = points.merge(raw, on="pid", how="left")

    merged["flood_ari"] = merged["flood_class"].map(FLOOD_CLASS_ARI)

    unknown = set(merged["flood_class"].dropna().unique()) - set(FLOOD_CLASS_ARI)
    if unknown:
        warnings.warn(
            f"Unmapped flood frequency classes, treated as missing: {unknown}", stacklevel=2
        )

    # WORST case wins: the smallest return period found anywhere in the cell.
    grouped = merged.groupby("cell_id")
    out = pd.DataFrame(
        {
            "site_flood_ari_years": grouped["flood_ari"].min(),
            "site_pond_ari_years": grouped["pond_ari"].min(),
        }
    ).reset_index()

    inverse = {v: k for k, v in FLOOD_CLASS_ARI.items()}
    out["flood_class"] = out["site_flood_ari_years"].map(inverse)
    inverse_p = {v: k for k, v in POND_CLASS_ARI.items()}
    out["pond_class"] = out["site_pond_ari_years"].map(inverse_p)

    # A single flag for the common question: is this farm on flood-prone ground?
    out["flood_prone"] = (out["site_flood_ari_years"] <= 10.0).astype(int)
    return out


def add_site_susceptibility(
    wide: pd.DataFrame,
    ratings: pd.DataFrame,
    rain_col: str = "rain_ari_years",
) -> pd.DataFrame:
    """
    Attach the site's susceptibility, and the interaction that matters.

    `flood_pressure` is the ratio of storm rarity to what the ground tolerates.
    Both are return periods in years, so the ratio is dimensionless and means
    something concrete: above 1, the storm is rarer than the site's own flooding
    interval, i.e. rare enough to matter HERE.

    This is the term that makes a 2-year storm an event on a floodplain and a
    non-event on a hillside - which is the whole point of pulling these ratings.
    """
    cols = ["cell_id", "site_flood_ari_years", "site_pond_ari_years", "flood_prone"]
    out = wide.merge(ratings[cols], on="cell_id", how="left")

    if rain_col in out.columns:
        out["flood_pressure"] = out[rain_col] / out["site_flood_ari_years"].replace(0, np.nan)
        out["pond_pressure"] = out[rain_col] / out["site_pond_ari_years"].replace(0, np.nan)
    return out


def summarize(ratings: pd.DataFrame) -> pd.DataFrame:
    """How the farms we actually cover are distributed across the ratings."""
    rows = []
    for label, col in [("flooding", "flood_class"), ("ponding", "pond_class")]:
        counts = ratings[col].fillna("(not rated)").value_counts()
        for name, n in counts.items():
            rows.append(
                {
                    "rating": label,
                    "class": name,
                    "farms": int(n),
                    "share": f"{100 * n / len(ratings):.0f}%",
                }
            )
    return pd.DataFrame(rows)
