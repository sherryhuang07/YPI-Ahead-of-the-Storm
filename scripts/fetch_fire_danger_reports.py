"""Archive Connecticut DEEP's daily Forest Fire Danger rating (the model's target).

    fetch_fire_danger_reports.py            today's report (run daily)
    fetch_fire_danger_reports.py --wayback  past snapshots from the Internet Archive

DEEP publishes only the current statewide rating (LOW, MODERATE, HIGH, VERY HIGH,
EXTREME) for 1:00 PM, usually before 8:00 AM, during fire seasons and other high-danger
periods. Raw pages are kept with SHA-256 hashes; parsed ratings go to
data/fire-danger/deep-ratings.json. The first capture of a date is kept; a later
different rating for the same date is recorded as a revision, never overwritten.
"""
import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
import requests
from statewide_common import ROOT, save, log

REPORT = 'https://www.depdata.ct.gov/forestry/forestfire/firerpt.cshtml'
OUT = ROOT / 'data/fire-danger'
HEADERS = {'User-Agent': 'Connecticut agricultural water forecast research'}
LEVELS = ['LOW', 'MODERATE', 'HIGH', 'VERY HIGH', 'EXTREME']
PATTERN = re.compile(r'Fire\s+Danger\s+Level\s+for\s+(?:\w+,\s+)?(\w+\s+\d{1,2},\s+\d{4})\s+is\s+(VERY\s+HIGH|LOW|MODERATE|HIGH|EXTREME)', re.I)


def text_of(html):
    t = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', html, flags=re.S | re.I)
    t = re.sub(r'<[^>]+>', ' ', t).replace('&nbsp;', ' ')
    return re.sub(r'\s+', ' ', t)


def parse(html):
    t = text_of(html); m = PATTERN.search(t)
    if not m: return None
    day = datetime.strptime(re.sub(r'\s+', ' ', m.group(1)), '%B %d, %Y').date().isoformat()
    level = re.sub(r'\s+', ' ', m.group(2)).upper()
    note = t[m.end():m.end() + 160].split('Forest Fire Weather Information')[0].strip()
    return dict(date=day, level=level, level_index=LEVELS.index(level), note=note or None)


def load():
    path = OUT / 'deep-ratings.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(ratings={}, revisions=[], unparsed=[])


def record(db, parsed, source, raw_path, captured):
    entry = dict(parsed, source=source, raw=str(raw_path.relative_to(ROOT)), sha256=hashlib.sha256(raw_path.read_bytes()).hexdigest(), captured_at=captured)
    old = db['ratings'].get(parsed['date'])
    if old is None: db['ratings'][parsed['date']] = entry; return 'new'
    if old['level'] != parsed['level']: db['revisions'].append(entry); return 'revision'
    return 'same'


def today():
    r = requests.get(REPORT, headers=HEADERS, timeout=60); r.raise_for_status()
    now = datetime.now(timezone.utc); folder = OUT / 'deep-reports' / now.strftime('%Y'); folder.mkdir(parents=True, exist_ok=True)
    raw = folder / (now.strftime('%Y%m%dT%H%M%SZ') + '.html')
    with raw.open('xb') as f: f.write(r.content)
    db = load(); parsed = parse(r.text)
    if parsed is None:
        db['unparsed'].append(dict(raw=str(raw.relative_to(ROOT)), captured_at=now.isoformat())); save(OUT / 'deep-ratings.json', db)
        raise SystemExit('DEEP report did not contain a recognizable rating; raw page kept for review.')
    status = record(db, parsed, 'DEEP daily report', raw, now.isoformat()); save(OUT / 'deep-ratings.json', db)
    log('Fire danger: DEEP rating for %s is %s (%s).' % (parsed['date'], parsed['level'], status))
    print(json.dumps(dict(parsed, status=status)))


def wayback():
    cdx = requests.get('https://web.archive.org/cdx/search/cdx', headers=HEADERS, timeout=120, params=dict(
        url='depdata.ct.gov/forestry/forestfire/firerpt.cshtml', output='json', fl='timestamp,digest', filter='statuscode:200', collapse='digest')).json()[1:]
    folder = OUT / 'wayback'; folder.mkdir(parents=True, exist_ok=True); db = load(); counts = {}
    for stamp, digest in cdx:
        raw = folder / (stamp + '.html')
        if not raw.exists():
            # The Internet Archive refuses rapid requests; go slowly and back off, skipping a
            # snapshot (to retry on a later run) rather than stopping.
            r = None
            for attempt in range(5):
                try:
                    r = requests.get('https://web.archive.org/web/%sid_/https://www.depdata.ct.gov/forestry/forestfire/firerpt.cshtml' % stamp, headers=HEADERS, timeout=90)
                    r.raise_for_status(); break
                except requests.RequestException:
                    r = None; time.sleep(30 * (attempt + 1))
            if r is None:
                counts['failed_download'] = counts.get('failed_download', 0) + 1; continue
            with raw.open('xb') as f: f.write(r.content)
            time.sleep(6)
        parsed = parse(raw.read_text(encoding='utf-8', errors='replace'))
        if parsed is None:
            db['unparsed'].append(dict(raw=str(raw.relative_to(ROOT)), wayback=stamp)); counts['unparsed'] = counts.get('unparsed', 0) + 1; continue
        # A snapshot can be taken days after the page was last updated; keep the snapshot time.
        parsed['wayback_timestamp'] = stamp
        s = record(db, parsed, 'Internet Archive snapshot', raw, datetime.strptime(stamp, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).isoformat())
        counts[s] = counts.get(s, 0) + 1
    save(OUT / 'deep-ratings.json', db)
    print(json.dumps(dict(snapshots=len(cdx), **counts, ratings=len(db['ratings']))))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--wayback', action='store_true')
    wayback() if ap.parse_args().wayback else today()
