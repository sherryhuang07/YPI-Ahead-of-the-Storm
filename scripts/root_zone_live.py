"""Shared pieces for assembling recent daily root-zone inputs from NASA NLDAS-2.

The historical model was trained on the USGS watershed aggregation of NLDAS-2
Noah (0-10 + 10-40 + 40-100 cm storage, kg m-2 = mm, divided by 1000 mm).
Current data come from GES DISC NLDAS_NOAH0125_H v2.0, variable SoilM_0_100cm,
which is the same 0-100 cm column storage in kg m-2. Hourly grids are fetched as
small OPeNDAP subsets over the watershed box, never as whole CONUS files.
"""
import contextlib
import io
import json
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RZ = ROOT / 'data/root-zone'
HOURLY = RZ / 'nldas-hourly'
BASINS = RZ / 'basins'
INPUTS = RZ / 'daily-inputs'
COLLECTION = 'C2069246977-GES_DISC'
VARIABLE = 'SoilM_0_100cm'
LON0, LAT0, STEP, NX, NY = -124.9375, 25.0625, 0.125, 464, 224
# Hours (UTC) that make up a source "day". Default: the UTC calendar day.
# The archive alignment check decides which offset matches the USGS archive.
DEFAULT_DAY_START_UTC_HOUR = 0
# netCDF4/HDF5 is not thread-safe: downloads run in parallel, decoding does not.
DECODE_LOCK = threading.Lock()


def cell_lon(i): return LON0 + STEP * i
def cell_lat(j): return LAT0 + STEP * j


def login_session():
    """Earthdata session from environment credentials set by the PowerShell launcher."""
    if not (os.getenv('EARTHDATA_USERNAME') and os.getenv('EARTHDATA_PASSWORD')):
        raise RuntimeError('NASA sign-in not provided. Run root-zone-update.ps1 (uses the saved Windows-encrypted sign-in).')
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import earthaccess
        auth = earthaccess.login(strategy='environment', persist=False)
        if not auth.authenticated:
            raise RuntimeError('NASA sign-in failed')
        return earthaccess.get_requests_https_session()


def granule_url(hour, box):
    """OPeNDAP DAP4 subset URL for one hourly NLDAS granule. box=(j0,j1,i0,i1) inclusive."""
    j0, j1, i0, i1 = box
    name = 'NLDAS_NOAH0125_H.2.0:NLDAS_NOAH0125_H.A%s.%s.020.nc' % (hour.strftime('%Y%m%d'), hour.strftime('%H00'))
    ce = '/%s[0:1:0][%d:1:%d][%d:1:%d];/lat[%d:1:%d];/lon[%d:1:%d]' % (VARIABLE, j0, j1, i0, i1, j0, j1, i0, i1)
    return ('https://opendap.earthdata.nasa.gov/collections/%s/granules/%s.dap.nc4' % (COLLECTION, name)), ce


def hourly_path(hour):
    return HOURLY / hour.strftime('%Y') / hour.strftime('%Y%m%d') / (hour.strftime('%H') + '.npy')


def fetch_hour(session, hour, box, retries=4):
    """Return the hourly grid (kg m-2, NaN where no land value). Cached on disk.

    Returns None when the granule is not published yet (HTTP 404); raises on
    other failures so a gap is never silently treated as data.
    """
    path = hourly_path(hour)
    if path.exists():
        return np.load(path)
    import netCDF4
    url, ce = granule_url(hour, box)
    error = None
    for attempt in range(retries):
        try:
            r = session.get(url, params={'dap4.ce': ce}, timeout=120)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            with DECODE_LOCK, netCDF4.Dataset('inmemory.nc', memory=r.content) as f:
                lat = np.asarray(f['lat'][:]); lon = np.asarray(f['lon'][:])
                if abs(lat[0] - cell_lat(box[0])) > 1e-3 or abs(lon[0] - cell_lon(box[2])) > 1e-3:
                    raise ValueError('Returned grid does not match requested NLDAS cells')
                v = f[VARIABLE]
                units = str(getattr(v, 'units', ''))
                if units.replace(' ', '') not in ('kgm-2', 'kg/m2', 'kgm**-2'):
                    raise ValueError('Unexpected units: ' + units)
                a = np.ma.filled(np.ma.masked_invalid(v[0, :, :]).astype('float64'), np.nan)
            a[(a < 0) | (a > 1000)] = np.nan
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix('.tmp.npy'); np.save(tmp, a); tmp.replace(path)
            return a
        except Exception as exc:  # do not echo exception text: may contain signed URLs
            error = type(exc).__name__
    raise RuntimeError('Hourly NLDAS fetch failed for %s (%s)' % (hour.isoformat(), error))


def day_hours(day, start_hour_utc):
    first = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(hours=start_hour_utc)
    return [first + timedelta(hours=k) for k in range(24)]


def load_weights():
    w = json.loads((BASINS / 'weights.json').read_text(encoding='utf-8'))
    return w


def watershed_means(grid, weights):
    """Area-weighted mean storage (kg m-2) per watershed over cells with valid values."""
    j0, _, i0, _ = weights['box']
    out = {}
    for sid, cells in weights['watersheds'].items():
        total = 0.0; wsum = 0.0; possible = 0.0
        for j, i, wt in cells:
            possible += wt
            v = grid[j - j0, i - i0]
            if np.isfinite(v):
                total += wt * v; wsum += wt
        out[sid] = (total / wsum if wsum > 0 and wsum >= 0.5 * possible else float('nan'), wsum / possible if possible else 0.0)
    return out


def daterange(a, b):
    return [a + timedelta(days=k) for k in range((b - a).days + 1)]


def parse_day(s):
    return date.fromisoformat(s)
