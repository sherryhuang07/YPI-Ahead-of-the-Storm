"""Daily 1 PM fire-weather inputs for Connecticut airports, from public NOAA records.

For each station and Connecticut day: the observation nearest 1:00 PM local time
(temperature, dew point, wind), precipitation in the 24 hours ending at that
observation (sum of hourly ASOS amounts; incomplete hours -> missing, never zero),
and NOAA GHCN-Daily snow depth. Hourly data: Iowa Environmental Mesonet ASOS
archive (NOAA METAR reports). Snow depth: NOAA NCEI daily summaries.

    fetch_fire_weather.py --start 1997-01-01 --end 2026-11-05
Output: data/fire-danger/weather/<station>.csv plus a hash manifest.
"""
import argparse
import csv
import hashlib
import io
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import requests
from statewide_common import ROOT, save, log

OUT = ROOT / 'data/fire-danger/weather'
HEADERS = {'User-Agent': 'Connecticut agricultural water forecast research'}
LOCAL = ZoneInfo('America/New_York')
# ASOS id -> (GHCN-Daily id, name)
STATIONS = {'BDL': ('USW00014740', 'Hartford Bradley'), 'BDR': ('USW00094702', 'Bridgeport Sikorsky'),
            'HVN': ('USW00014758', 'New Haven Tweed'), 'DXR': ('USW00054734', 'Danbury'),
            'IJD': ('USW00054767', 'Willimantic Windham')}


def get(url, params, attempts=5):
    for a in range(attempts):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=300); r.raise_for_status(); return r
        except requests.RequestException:
            if a == attempts - 1: raise
            time.sleep(10 * (a + 1))


def hourly(station, start, end):
    rows = []
    for year in range(start.year, end.year + 1):
        a = max(start, date(year, 1, 1)); b = min(end, date(year, 12, 31)) + timedelta(days=1)
        r = get('https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py', dict(
            station=station, data=['tmpf', 'dwpf', 'sknt', 'p01i'], year1=a.year, month1=a.month, day1=a.day,
            year2=b.year, month2=b.month, day2=b.day, tz='Etc/UTC', format='onlycomma', missing='M', trace='0.0001', report_type=3))
        rows.extend(csv.DictReader(io.StringIO(r.text)))
        time.sleep(1)
    return rows


def snow(ghcn, start, end):
    r = get('https://www.ncei.noaa.gov/access/services/data/v1', dict(dataset='daily-summaries', stations=ghcn, dataTypes='SNWD,PRCP',
            startDate=str(start), endDate=str(end), format='json', units='standard'))
    return {x['DATE']: x for x in r.json()}


def num(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def build(station, start, end):
    obs = []
    for r in hourly(station, start - timedelta(days=1), end):
        t = datetime.strptime(r['valid'], '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
        obs.append((t, num(r['tmpf']), num(r['dwpf']), num(r['sknt']), num(r['p01i'])))
    obs.sort(key=lambda o: o[0])
    # Routine hourly reports (minute 45-59) carry the hourly precipitation; index them by hour ending.
    rain_by_hour = {}
    for t, _, _, _, p in obs:
        if 45 <= t.minute <= 59 and p is not None:
            rain_by_hour[(t + timedelta(minutes=60 - t.minute)).replace(second=0)] = p
    by_day = defaultdict(list)
    for o in obs: by_day[o[0].astimezone(LOCAL).date()].append(o)
    daily = snow(STATIONS[station][0], start, end); out = []
    d = start
    while d <= end:
        target = datetime.combine(d, datetime.min.time(), LOCAL).replace(hour=13)
        cands = [o for o in by_day.get(d, []) if o[1] is not None and o[2] is not None and o[3] is not None]
        near = min(cands, key=lambda o: abs((o[0] - target).total_seconds()), default=None)
        if near and abs((near[0] - target).total_seconds()) > 75 * 60: near = None
        rain = None
        if near:
            end_hour = near[0].replace(minute=0, second=0) + timedelta(hours=1 if near[0].minute >= 45 else 0)
            hours = [end_hour - timedelta(hours=k) for k in range(24)]
            if all(h in rain_by_hour for h in hours): rain = round(sum(rain_by_hour[h] for h in hours), 4)
        g = daily.get(str(d), {})
        out.append(dict(date=str(d), station=station, obs_time_local=near[0].astimezone(LOCAL).strftime('%H:%M') if near else '',
                        temp_f=near[1] if near else '', dewpoint_f=near[2] if near else '', wind_knots=near[3] if near else '',
                        precip_24h_in=rain if rain is not None else '', snow_depth_in=num(g.get('SNWD')) if g.get('SNWD') not in (None, '') else '',
                        ghcn_precip_in=num(g.get('PRCP')) if g.get('PRCP') not in (None, '') else ''))
        d += timedelta(days=1)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--start', default='1997-01-01'); ap.add_argument('--end', default=str(datetime.now(LOCAL).date() - timedelta(days=1)))
    ap.add_argument('--stations', nargs='+', default=list(STATIONS))
    ap.add_argument('--merge-days', type=int, help='Daily update: refresh only the last N days and merge them into the saved history.')
    a = ap.parse_args(); start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    if a.merge_days: start = end - timedelta(days=a.merge_days - 1)
    OUT.mkdir(parents=True, exist_ok=True)
    old_manifest = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8')) if (OUT / 'manifest.json').exists() else {}
    manifest = dict(old_manifest.get('stations', {})) if a.merge_days else {}
    for s in a.stations:
        print('Downloading %s (%s)...' % (s, STATIONS[s][1]), flush=True)
        rows = build(s, start, end); path = OUT / (s + '.csv')
        if a.merge_days and path.exists():
            # Recent days are re-read because late reports and snow depth fill in; older days are kept as saved.
            kept = [r for r in csv.DictReader(path.open(encoding='utf-8')) if r['date'] < str(start)]
            rows = kept + rows
        with path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
        complete = sum(1 for r in rows if r['temp_f'] != '' and r['precip_24h_in'] != '')
        manifest[s] = dict(name=STATIONS[s][1], ghcn=STATIONS[s][0], days=len(rows), complete_days=complete, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        print('  %d days, %d with complete 1 PM weather and 24-hour rain' % (len(rows), complete), flush=True)
    first = old_manifest.get('start', a.start) if a.merge_days else a.start
    save(OUT / 'manifest.json', dict(created_at=datetime.now(timezone.utc).isoformat(), start=first, end=a.end, stations=manifest,
                                     sources=['Iowa Environmental Mesonet ASOS archive (NOAA METAR), routine hourly reports', 'NOAA NCEI GHCN-Daily snow depth']))
    log('Fire danger: downloaded 1 PM weather history %s to %s for %s.' % (a.start, a.end, ', '.join(a.stations)))


if __name__ == '__main__':
    main()
