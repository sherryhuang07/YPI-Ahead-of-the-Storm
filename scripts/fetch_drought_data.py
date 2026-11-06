"""Download drought reference data for Connecticut.

- NOAA NCEI climate-division indexes (monthly, 1895-): Palmer Drought Severity Index (PDSI),
  Palmer Hydrological Drought Index (PHDI), Palmer Z-index and precipitation, for Connecticut's
  three divisions (state code 06: 1 Northwest, 2 Central, 3 Coastal).
  https://www.ncei.noaa.gov/monitoring-content/data/us/climdiv/monthly/current/
- U.S. Drought Monitor (weekly maps valid Tuesday, released Thursday, 2000-): percent of area in
  None, D0..D4, statewide and per Connecticut planning region (the service has recalculated 2000- history on the 9 regions).
  https://usdmdataservices.unl.edu/api/

Raw responses are cached under data/drought/raw with hashes; parsed tables go to data/drought/.
"""
import csv
import hashlib
import json
import re
import time
from datetime import date, datetime, timezone
import requests
from statewide_common import ROOT, save, log

OUT = ROOT / 'data/drought'; RAW = OUT / 'raw'
HEADERS = {'User-Agent': 'Connecticut agricultural water forecast research'}
CLIMDIV = 'https://www.ncei.noaa.gov/monitoring-content/data/us/climdiv/monthly/current/'
ELEMENTS = {'pdsidv': 'pdsi', 'phdidv': 'phdi', 'zndxdv': 'zindex', 'pcpndv': 'precip_in'}
USDM = 'https://usdmdataservices.unl.edu/api/'


def get(url, params=None, json_accept=False):
    for a in range(5):
        try:
            r = requests.get(url, params=params, headers=dict(HEADERS, **({'Accept': 'application/json'} if json_accept else {})), timeout=180)
            r.raise_for_status(); return r
        except requests.RequestException:
            if a == 4: raise
            time.sleep(10 * (a + 1))


def keep(name, content):
    path = RAW / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
    return dict(file=str(path.relative_to(ROOT)), sha256=hashlib.sha256(content).hexdigest())


def palmer():
    listing = get(CLIMDIV).text; sources = {}; rows = {}
    for code, name in ELEMENTS.items():
        files = sorted(set(re.findall(r'(climdiv-%s-v[0-9.]+-\d{8})' % code, listing)))
        if not files: raise RuntimeError('No NCEI file for ' + code)
        f = files[-1]; content = get(CLIMDIV + f).content; sources[name] = dict(keep('climdiv/' + f + '.txt', content), ncei_file=f)
        for line in content.decode('ascii').splitlines():
            if not line.startswith('06'): continue          # Connecticut
            div = int(line[2:4]); year = int(line[6:10]); vals = line[10:].split()
            for m, v in enumerate(vals, 1):
                v = float(v)
                if v in (-99.99, -9.99): continue          # NCEI missing markers
                rows.setdefault((div, '%d-%02d' % (year, m)), {})[name] = v
    path = OUT / 'palmer-divisions.csv'
    with path.open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(['division', 'month'] + list(ELEMENTS.values()))
        for (div, month) in sorted(rows): w.writerow([div, month] + [rows[(div, month)].get(n, '') for n in ELEMENTS.values()])
    last = max(m for _, m in rows)
    return dict(sources=sources, months=len({m for _, m in rows}), last_month=last)


def usdm(recent=False):
    end = date.today()
    state = get(USDM + 'StateStatistics/GetDroughtSeverityStatisticsByAreaPercent',
                dict(aoi='09', startdate='1/1/2000', enddate='%d/%d/%d' % (end.month, end.day, end.year), statisticsType=1), True)
    src = dict(state=keep('usdm/state.json', state.content)); counties = []
    for year in range(end.year if recent else 2000, end.year + 1):
        r = get(USDM + 'CountyStatistics/GetDroughtSeverityStatisticsByAreaPercent',
                dict(aoi='CT', startdate='1/1/%d' % year, enddate='12/31/%d' % year if year < end.year else '%d/%d/%d' % (end.month, end.day, end.year), statisticsType=1), True)
        src['counties_%d' % year] = keep('usdm/counties-%d.json' % year, r.content); counties += r.json(); time.sleep(1)
    def rows(items, unit):
        out = []
        for x in items:
            out.append(dict(map_date=x['mapDate'][:10], unit=unit(x), none=x['none'], d0=x['d0'], d1=x['d1'], d2=x['d2'], d3=x['d3'], d4=x['d4']))
        return out
    table = rows(state.json(), lambda x: 'CT') + rows(counties, lambda x: '%s|%s' % (x['fips'], x['county']))
    path = OUT / 'usdm-weekly.csv'
    if recent and path.exists():
        # Nightly mode: keep saved earlier years, replace the current year with the fresh download.
        kept = [r for r in csv.DictReader(path.open(encoding='utf-8')) if r['unit'] != 'CT' and r['map_date'] < '%d-01-01' % end.year]
        table = kept + table
    # Yearly requests overlap at year boundaries; keep one row per unit and map date.
    table = list({(r['unit'], r['map_date']): r for r in table}.values())
    path = OUT / 'usdm-weekly.csv'
    with path.open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=['map_date', 'unit', 'none', 'd0', 'd1', 'd2', 'd3', 'd4']); w.writeheader()
        w.writerows(sorted(table, key=lambda r: (r['unit'], r['map_date'])))
    units = sorted({r['unit'] for r in table})
    return dict(sources=src, weeks=len({r['map_date'] for r in table if r['unit'] == 'CT'}), last_map=max(r['map_date'] for r in table), units=units,
                note='Columns d0..d4 are cumulative percent of area at or above each category (USDM "statisticsType=1").')


def first_seen():
    """Record when each Drought Monitor map value was first downloaded (used to score forecasts fairly)."""
    path = OUT / 'usdm-first-seen.json'; seen = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    now = datetime.now(timezone.utc).isoformat()
    for r in csv.DictReader((OUT / 'usdm-weekly.csv').open(encoding='utf-8')):
        seen.setdefault(r['unit'] + '|' + r['map_date'], now)
    save(path, seen)


def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('--recent', action='store_true', help='Nightly: only refresh the current year of regional maps.')
    a = ap.parse_args(); OUT.mkdir(parents=True, exist_ok=True)
    info = dict(created_at=datetime.now(timezone.utc).isoformat(), palmer=palmer(), usdm=usdm(a.recent))
    first_seen()
    for name in ('palmer-divisions.csv', 'usdm-weekly.csv'): info[name + '_sha256'] = hashlib.sha256((OUT / name).read_bytes()).hexdigest()
    save(OUT / 'manifest.json', info)
    log('Drought data: Palmer through %s; Drought Monitor through %s (%d units).' % (info['palmer']['last_month'], info['usdm']['last_map'], len(info['usdm']['units'])))
    print(json.dumps(dict(palmer_last=info['palmer']['last_month'], palmer_months=info['palmer']['months'], usdm_last=info['usdm']['last_map'],
                          usdm_weeks=info['usdm']['weeks'], units=info['usdm']['units']), indent=1))


if __name__ == '__main__':
    main()
