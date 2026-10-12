"""
The long record: 130 years of Connecticut drought, monthly.

WHY THIS EXISTS
---------------
The main model is limited by events, not by method. Twenty-five years of Drought
Monitor labels contain roughly 4 moderate drought episodes and 3 severe ones, and
two of them dominate everything the model learns. No algorithm can extract more
than a handful of examples contain.

NOAA's climate-division record goes back to 1895. Measured on Connecticut:

    drought episodes (3+ months)   1895-2024   2000-2024
      moderate  PDSI <= -2              19           7     2.7x more
      severe    PDSI <= -3               7           4     1.8x more

And the worst droughts in the record sit OUTSIDE the modern window entirely:

    1966  -4.48   <- the benchmark New England drought, and the main model has
    1931  -2.58      never seen it
    1950  -2.52
    1957  -2.26

1966 is roughly 20% worse than anything since 2000. A model that has never seen
it has no idea that severity is possible - which is exactly how the 2015-2018
fold failed when it met a drought larger than its training data.

WHAT IT COSTS
-------------
This is a genuinely different product from the main pipeline, not a drop-in
extension, and the trade is real:

                  Drought Monitor (main)      Climate division (this)
    cadence       weekly                      monthly
    resolution    ~2 km polygons              3 divisions statewide
    nature        expert judgment, includes   a formula from rainfall and
                  wells, streams, reports     temperature
    record        25 years                    130 years

So: nearly three times the events, at far coarser resolution, from a computed index
rather than a human read. For the specific problem of too few events, that is a
good trade - but it is a companion model, not a replacement. Use it to learn what
deep drought looks like and to sanity-check severity the main model has never
seen.

WHAT COMES WITH IT
------------------
NOAA publishes the whole drought toolkit for every division, monthly, since 1895:

    pdsi   Palmer Drought Severity Index - the headline number
    phdi   Palmer HYDROLOGICAL index - slower, tracks reservoirs and groundwater
    pmdi   Palmer Modified - a smoothed variant
    zndx   Palmer Z-index - THIS month's moisture anomaly, no memory
    sp01 .. sp24   Standardised Precipitation Index at 1,2,3,6,9,12,24 months

That SPI ladder is the multi-scale deficit signal drought forecasting wants, and
it is already computed. The Z-index paired with PDSI is particularly useful: one
is the shock, the other is the accumulated state.
"""

from __future__ import annotations

import warnings

import pandas as pd
import requests

CLIMDIV_DIR = "https://www.ncei.noaa.gov/monitoring-content/data/us/climdiv/monthly/current/"

# climdiv uses its OWN state numbering, alphabetical by state name, NOT FIPS.
# Connecticut is 06 here and 09 in FIPS - a genuinely easy mistake to make.
CLIMDIV_STATE_CT = "06"

# Which files to pull, and what each contributes.
ELEMENTS = {
    "pdsi": "climdiv-pdsidv",  # the headline drought index
    "phdi": "climdiv-phdidv",  # hydrological - slow, reservoirs and groundwater
    "pmdi": "climdiv-pmdidv",  # modified Palmer, smoother
    "zndx": "climdiv-zndxdv",  # this month's anomaly, no memory - the shock term
    "sp01": "climdiv-sp01dv",  # standardised precipitation, 1 month
    "sp03": "climdiv-sp03dv",  # 3 months  - the agricultural drought scale
    "sp06": "climdiv-sp06dv",
    "sp12": "climdiv-sp12dv",  # 12 months - hydrological drought scale
    "sp24": "climdiv-sp24dv",
    "pcpn": "climdiv-pcpndv",  # precipitation, inches
    "tmpc": "climdiv-tmpcdv",  # mean temperature, F
}

MISSING = -99.99


def _list_current_files(timeout: int = 180) -> dict[str, str]:
    """Find today's filename for each element - NOAA stamps them with a date."""
    resp = requests.get(CLIMDIV_DIR, timeout=timeout)
    resp.raise_for_status()

    found = {}
    for token in resp.text.split('"'):
        for key, prefix in ELEMENTS.items():
            if token.startswith(prefix) and key not in found:
                found[key] = token
    return found


def _parse_climdiv(text: str, state: str, want_element: str | None = None) -> pd.DataFrame:
    """
    Parse the fixed-width climate-division format.

    Layout of the 10-character key, which is easy to get wrong and silently
    produces nonsense years if you do:

        chars 0-1   state code (climdiv numbering, not FIPS)
        chars 2-3   division number
        chars 4-5   element code
        chars 6-9   year

    Then twelve 7-character monthly values.
    """
    rows = []
    for line in text.splitlines():
        if len(line) < 20 or line[:2] != state:
            continue

        division = line[2:4]
        element = line[4:6]
        year = int(line[6:10])
        if want_element and element != want_element:
            continue

        for m in range(12):
            raw = line[10 + 7 * m : 17 + 7 * m].strip()
            if not raw:
                continue
            value = float(raw)
            if value <= MISSING:
                continue
            rows.append({"division": division, "year": year, "month": m + 1, "value": value})

    return pd.DataFrame(rows)


def fetch_climate_divisions(state: str = CLIMDIV_STATE_CT, timeout: int = 300) -> pd.DataFrame:
    """
    Every monthly drought index for one state's climate divisions, 1895 to now.

    Returns a wide table: division, date, then one column per element.
    """
    files = _list_current_files(timeout=timeout)

    frames = []
    for key, filename in files.items():
        try:
            resp = requests.get(CLIMDIV_DIR + filename, timeout=timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            warnings.warn(f"Could not fetch {key} ({filename}): {exc}", stacklevel=2)
            continue

        part = _parse_climdiv(resp.text, state)
        if part.empty:
            warnings.warn(f"No rows for state {state} in {filename}", stacklevel=2)
            continue

        part = part.rename(columns={"value": key})
        frames.append(part.set_index(["division", "year", "month"])[key])

    if not frames:
        raise RuntimeError(
            f"No climate-division data retrieved for state {state}. "
            f"Check {CLIMDIV_DIR} is reachable."
        )

    wide = pd.concat(frames, axis=1).reset_index()
    wide["date"] = pd.to_datetime(dict(year=wide["year"], month=wide["month"], day=1)).astype(
        "datetime64[ns]"
    )

    return wide.sort_values(["division", "date"]).reset_index(drop=True)


def build_longterm_features(
    wide: pd.DataFrame, horizon_months: int = 1, lags: tuple[int, ...] = (1, 2, 3, 6, 12)
) -> pd.DataFrame:
    """
    Turn the monthly record into a modelling table.

    Features are the indices themselves plus their recent history and direction.
    Everything is backward-looking; the target is shifted forward.

    Targets produced:
        y_pdsi        PDSI `horizon_months` ahead - the value to regress
        y_pdsi_now    today's PDSI, which is also the persistence baseline
        y_worsens     will PDSI fall by at least half a point? The warning question.
        y_drought     will PDSI be at or below -2 (moderate drought or worse)?
    """
    out = wide.sort_values(["division", "date"]).copy()
    grouped = out.groupby("division", sort=False)

    index_cols = [c for c in ELEMENTS if c in out.columns]

    new: dict[str, pd.Series] = {}
    for col in index_cols:
        for lag in lags:
            new[f"{col}_lag{lag}"] = grouped[col].shift(lag)
        # Direction matters as much as level: a PDSI of -1 heading down is a
        # different situation from a PDSI of -1 recovering.
        new[f"{col}_delta3"] = out[col] - grouped[col].shift(3)
        new[f"{col}_delta12"] = out[col] - grouped[col].shift(12)

    out = pd.concat([out, pd.DataFrame(new, index=out.index)], axis=1)

    # Seasonality: drought in February matters far less than drought in July.
    out["month_sin"] = (out["month"] * 3.14159 / 6).apply(lambda x: __import__("math").sin(x))
    out["month_cos"] = (out["month"] * 3.14159 / 6).apply(lambda x: __import__("math").cos(x))

    # --- targets, shifted FORWARD ------------------------------------------
    out["y_pdsi_now"] = out["pdsi"]
    out["y_pdsi"] = grouped["pdsi"].shift(-horizon_months)
    out["y_worsens"] = ((out["y_pdsi"] - out["y_pdsi_now"]) <= -0.5).astype(float)
    out["y_drought"] = (out["y_pdsi"] <= -2.0).astype(float)
    out.loc[out["y_pdsi"].isna(), ["y_worsens", "y_drought"]] = float("nan")

    return out.dropna(subset=["y_pdsi"]).reset_index(drop=True)


def describe_record(wide: pd.DataFrame) -> pd.DataFrame:
    """What the long record actually contains, and how it compares to the modern slice."""
    st = wide.groupby("date")["pdsi"].mean().sort_index()

    def episodes(series: pd.Series, threshold: float) -> int:
        bad = series <= threshold
        grp = (bad != bad.shift()).cumsum()
        return sum(1 for _, g in bad.groupby(grp) if bool(g.iloc[0]) and len(g) >= 3)

    modern = st[st.index.year >= 2000]
    rows = []
    for label, thresh in [
        ("moderate (PDSI <= -2)", -2.0),
        ("severe (PDSI <= -3)", -3.0),
        ("extreme (PDSI <= -4)", -4.0),
    ]:
        full, recent = episodes(st, thresh), episodes(modern, thresh)
        rows.append(
            {
                "drought episodes": label,
                "1895-2024": full,
                "2000-2024": recent,
                "gain": f"{full / max(recent, 1):.1f}x",
            }
        )
    return pd.DataFrame(rows)


def worst_droughts(wide: pd.DataFrame, n: int = 8) -> pd.DataFrame:
    """The deepest droughts on record, as distinct episodes rather than adjacent months."""
    st = wide.groupby("date")["pdsi"].mean().sort_index()
    rolling = st.rolling(12).mean().sort_values()

    seen: list[int] = []
    rows = []
    for date, value in rolling.items():
        if any(abs(date.year - y) < 3 for y in seen):
            continue
        seen.append(date.year)
        rows.append({"year": date.year, "12-month mean PDSI": round(float(value), 2)})
        if len(rows) >= n:
            break
    return pd.DataFrame(rows)
