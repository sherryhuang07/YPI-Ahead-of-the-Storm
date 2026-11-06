"""Long Island Sound / Connecticut coastal water temperature from NOAA NDBC.

Standard meteorological files (column WTMP, deg C, UTC) from three NDBC layers:
  1. yearly history     data/historical/stdmet/<id>h<year>.txt.gz
  2. current-year months data/stdmet/<Mon>/<id>.txt   (before they join the yearly files)
  3. last 45 days        data/realtime2/<ID>.txt      (provisional)
Earlier layers win where they overlap (they are NDBC's quality-controlled versions).
Raw files are cached with hashes; daily Connecticut-local means are written to
data/water-temp/daily.csv. A day needs readings in at least 12 different hours;
values outside -3..35 C, and readings more than 5 C from that day's median, are
dropped as faulty. Missing days stay missing.

    fetch_water_temp.py            full history (cached years are reused)
    fetch_water_temp.py --recent   only layers 2-3 (daily update)
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np
import requests
from statewide_common import ROOT, save, log

OUT = ROOT / 'data/water-temp'; RAW = OUT / 'raw'
BASE = 'https://www.ndbc.noaa.gov'
HEADERS = {'User-Agent': 'Connecticut agricultural water forecast research'}
LOCAL = ZoneInfo('America/New_York')
# station key -> (NDBC ids, oldest first, name)
STATIONS = {
    '44039': (['44039'], 'Central Long Island Sound buoy'),
    '44040': (['44040'], 'Western Long Island Sound buoy'),
    '44022': (['44022'], 'Execution Rocks buoy (western Sound)'),
    'ldlc3': (['ldlc3'], 'New London Ledge Light'),
    'brhc3': (['brhc3'], 'Bridgeport, CT (NOAA 8467150)'),
    'nwhc3': (['nwhc3'], 'New Haven, CT (NOAA 8465705)'),
    '8461490': (['nlnc3', 'nlhc3'], 'New London, CT (NOAA 8461490; NDBC id changed 2023)'),
    'kptn6': (['kptn6'], 'Kings Point, NY (western end of the Sound)'),
    'mtkn6': (['mtkn6'], 'Montauk, NY (eastern entrance)'),
}
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def get(url):
    for a in range(4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=120)
            if r.status_code == 404: return None
            r.raise_for_status(); return r.content
        except requests.RequestException:
            if a == 3: raise
            time.sleep(10 * (a + 1))


def cached(name, url, refresh=False):
    path = RAW / name
    if path.exists() and not refresh: return path.read_bytes()
    data = get(url); time.sleep(0.5)
    if data is None: return None
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data); return data


def parse(text):
    """Yield (utc datetime, wtmp C) from an NDBC stdmet text file of any vintage."""
    lines = text.splitlines(); header = None
    for line in lines:
        if line.startswith('#YY') or line.startswith('YY') or line.startswith('YYYY'):
            header = line.lstrip('#').split(); continue
        if line.startswith('#') or not line.strip() or header is None: continue
        v = line.split()
        if len(v) < len(header): continue
        row = dict(zip(header, v))
        try:
            y = int(row.get('YY') or row.get('YYYY')); y = y + 1900 if y < 100 else y
            t = datetime(y, int(row['MM']), int(row['DD']), int(row['hh']), int(row.get('mm', 0)), tzinfo=timezone.utc)
            w = float(row['WTMP'])
        except (KeyError, ValueError):
            continue
        if w >= 99: continue
        yield t, w


def station_readings(key, recent_only):
    ids, _ = STATIONS[key]; now = datetime.now(timezone.utc); layers = []
    for sid in ids:
        if not recent_only:
            for year in range(2004, now.year):
                data = cached('%s/%sh%d.txt.gz' % (sid, sid, year), '%s/data/historical/stdmet/%sh%d.txt.gz' % (BASE, sid, year))
                if data: layers.append(('yearly', gzip.decompress(data).decode('ascii', 'replace')))
        else:
            for p in sorted((RAW / sid).glob('%sh*.txt.gz' % sid)): layers.append(('yearly', gzip.decompress(p.read_bytes()).decode('ascii', 'replace')))
        for m in range(1, now.month + 1):
            data = cached('%s/%d-%02d.txt' % (sid, now.year, m), '%s/data/stdmet/%s/%s.txt' % (BASE, MONTHS[m - 1], sid), refresh=True)
            if data: layers.append(('monthly', data.decode('ascii', 'replace')))
        data = cached('%s/realtime.txt' % sid, '%s/data/realtime2/%s.txt' % (BASE, sid.upper()), refresh=True)
        if data: layers.append(('realtime', data.decode('ascii', 'replace')))
    readings = {}
    for _, text in layers:                  # earlier (quality-controlled) layers win
        for t, w in parse(text): readings.setdefault(t, w)
    return readings


def daily_means(readings):
    by_day = defaultdict(list)
    for t, w in readings.items():
        if -3 <= w <= 35: by_day[t.astimezone(LOCAL).date()].append((t, w))
    out = {}
    for d, v in by_day.items():
        med = np.median([w for _, w in v]); good = [(t, w) for t, w in v if abs(w - med) <= 5]
        hours = {t.astimezone(LOCAL).hour for t, _ in good}
        if len(hours) >= 12: out[str(d)] = (round(float(np.mean([w for _, w in good])), 3), len(hours))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--recent', action='store_true'); a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True); series = {}; info = {}
    for key, (ids, name) in STATIONS.items():
        print('%s (%s)...' % (key, name), flush=True)
        series[key] = daily_means(station_readings(key, a.recent))
        days = sorted(series[key])
        info[key] = dict(name=name, ndbc_ids=ids, days=len(days), first=days[0] if days else None, last=days[-1] if days else None)
        print('  %d daily means, %s to %s' % (len(days), info[key]['first'], info[key]['last']), flush=True)
    path = OUT / 'daily.csv'
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['date', 'station', 'water_temp_c', 'hours_with_readings'])
        for key in STATIONS:
            for d in sorted(series[key]): w.writerow([d, key, series[key][d][0], series[key][d][1]])
    save(OUT / 'manifest.json', dict(created_at=datetime.now(timezone.utc).isoformat(), stations=info, daily_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                     rules='Connecticut local days; >=12 hours with readings; -3..35 C; >5 C from daily median dropped; NDBC yearly > monthly > realtime precedence.',
                                     source='NOAA National Data Buoy Center standard meteorological data (WTMP)'))
    log('Water temperature: daily means assembled for %d stations.' % len(STATIONS))


if __name__ == '__main__':
    main()
