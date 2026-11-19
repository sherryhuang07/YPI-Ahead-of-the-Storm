"""Turn the nightly NEWA station capture into 5-day weather for each Connecticut planning region.

Input: data/newa/<date>.json, written each night (about 11:30 PM) by the scheduled browser session that
opens https://newa.cornell.edu/ and picks every active Connecticut station (scripts/newa_capture.js,
scripts/newa_stations.json). Each station carries NEWA's measured daily rain for the last 10 days and
its forecast for the next days: high/low, weather word, highest 12-hour chance of rain, and rain amount
with how many hours of the day had an amount.

Output: outputs/newa/latest-regions.json, per planning region (stations placed by the TIGERweb region
boundaries; regions with no active station take the 2 nearest stations) and statewide:
  next 5 days: mean high/low, highest chance of rain, rain amount (mean of stations whose day is complete,
               i.e. at least 20 of 24 hours carry an amount; otherwise no amount for that day)
  measured: rain over the last 3 and 7 days
A capture older than 30 hours is not used (stale), and the drought forecast falls back to NOAA NBM.
"""
import glob
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import numpy as np
from shapely.geometry import shape, Point
from statewide_common import ROOT, read, save, log

D = ROOT / 'data/newa'; OUT = ROOT / 'outputs/newa'
MAX_AGE_HOURS = 30


def latest_capture():
    files = sorted(glob.glob(str(D / '*.json')))
    if not files: return None, None
    cap = read(files[-1]); when = datetime.fromisoformat(cap['saved_at'].replace('Z', '+00:00'))
    return cap, when


def regions():
    g = read(ROOT / 'data/drought/raw/planning-regions.geojson')
    return {'%s|%s' % (f['properties']['GEOID'], f['properties']['NAME']): shape(f['geometry']) for f in g['features']}


def quality(stations):
    """Gut-checks on the measured data. Returns {sid: [problems]} and the stations whose rain/temps to skip."""
    problems = {}; skip_rain, skip_temp = set(), set()
    week = {sid: sum(o[1] for o in v['obs'] if o[1] is not None) for sid, v in stations.items()}
    typical = float(np.median(list(week.values()))) if week else 0.0
    for sid, v in stations.items():
        o = v['obs']
        if sum(1 for x in o if x[2] is not None and x[2] == x[3]) >= 3:
            problems.setdefault(sid, []).append('temperature stuck (high equals low on %d days)' % sum(1 for x in o if x[2] == x[3])); skip_temp.add(sid)
        if week[sid] == 0 and typical >= 0.2:
            problems.setdefault(sid, []).append('rain gauge read 0 in for the week while the typical station caught %.2f in' % typical); skip_rain.add(sid)
    return problems, skip_rain, skip_temp


def build(today=None):
    cap, when = latest_capture()
    now = datetime.now(timezone.utc)
    if cap is None or (now - when).total_seconds() > MAX_AGE_HOURS * 3600:
        res = dict(status='no recent NEWA capture', checked_at=now.isoformat(), capture_saved_at=when.isoformat() if when else None)
        OUT.mkdir(parents=True, exist_ok=True); save(OUT / 'latest-regions.json', res); return res
    meta = {s['sid']: s for s in read(ROOT / 'scripts/newa_stations.json')['stations']}
    stations = {sid: v for sid, v in cap['stations'].items() if sid in meta and v.get('fc')}
    problems, skip_rain, skip_temp = quality(stations)
    regs = regions(); members = {k: [] for k in regs}
    for sid in stations:
        pt = Point(meta[sid]['lon'], meta[sid]['lat'])
        for k, poly in regs.items():
            if poly.contains(pt): members[k].append(sid)
    for k, poly in regs.items():          # regions without an active station: the 2 nearest stations
        if not members[k]:
            c = poly.centroid
            members[k] = sorted(stations, key=lambda s: (meta[s]['lat'] - c.y) ** 2 + (meta[s]['lon'] - c.x) ** 2)[:2]
    members['CT'] = list(stations)
    from zoneinfo import ZoneInfo
    first = str(today or datetime.now(ZoneInfo('America/New_York')).date())
    days = [str(date.fromisoformat(first) + timedelta(days=k)) for k in range(5)]
    out = {}
    for k, sids in members.items():
        rows = []
        for d in days:
            f = [r for s in sids for r in stations[s]['fc'] if r[0] == d]       # [date, high, low, chance, rain or None, weather]
            hi = [r[1] for r in f if r[1] is not None]; lo = [r[2] for r in f if r[2] is not None]
            pops = [r[3] for r in f if r[3] is not None]; rain = [r[4] for r in f if r[4] is not None]
            words = [r[5] for r in f if r[5]]
            rows.append(dict(date=d, stations=len(f), high_f=round(float(np.mean(hi)), 1) if hi else None, low_f=round(float(np.mean(lo)), 1) if lo else None,
                             max_chance_of_rain=max(pops) if pops else None, rain_in=round(float(np.mean(rain)), 3) if rain else None, rain_stations=len(rain),
                             weather=max(set(words), key=words.count) if words else None))
        obs3 = [sum(o[1] for o in stations[s]['obs'][-3:] if o[1] is not None) for s in sids if s not in skip_rain]
        obs7 = [sum(o[1] for o in stations[s]['obs'] if o[1] is not None) for s in sids if s not in skip_rain]
        out[k] = dict(name='Connecticut (statewide)' if k == 'CT' else k.split('|')[1], stations=[meta[s]['name'] for s in sids], next_days=rows,
                      measured_rain_last_3_days_in=round(float(np.mean(obs3)), 2) if obs3 else None,
                      measured_rain_last_7_days_in=round(float(np.mean(obs7)), 2) if obs7 else None)
    res = dict(status='ok', built_at=now.isoformat(), capture_saved_at=when.isoformat(), stations_captured=len(stations), stations_expected=len(meta),
               missing=[meta[s]['name'] for s in meta if s not in stations], data_problems={meta[s]['name']: p for s, p in problems.items()}, regions=out,
               note='NEWA forecasts come from the National Weather Service; rain amounts usually cover about 3 days, then only the chance of rain. '
                    'Stations failing a gut-check are left out of the measured rain (gauge) or temperature (stuck sensor) averages.')
    OUT.mkdir(parents=True, exist_ok=True); save(OUT / 'latest-regions.json', res)
    log('NEWA weather: %d of %d stations captured %s; %d with data problems; regional 5-day weather written.' % (len(stations), len(meta), when.isoformat(), len(problems)))
    return res


if __name__ == '__main__':
    r = build(); print(json.dumps({k: r[k] for k in r if k != 'regions'}, indent=1))
