"""Archive full-period USGS daily groundwater series used by the forecast.

Creates a new timestamped folder on every run. Raw API features and their
metadata are retained so this archive cannot overwrite the existing snapshot
or any sealed forecast inputs.
"""
import argparse
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from statewide_common import ROOT, read, request_json, save

API = 'https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items'
LOCAL = ZoneInfo('America/New_York')


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fetch_series(well, start, end):
    params = {
        'f': 'json',
        'limit': 10000,
        'time_series_id': well['series_id'],
        'parameter_code': '72019',
        'statistic_id': '00003',
        'datetime': f'{start}/{end}',
    }
    first_url = API
    features, pages, visited = [], [], set()
    while first_url:
        response = request_json(first_url, params, timeout=120)
        params = None
        if 'features' not in response:
            raise ValueError(f"USGS did not return features for {well['id']}")
        features.extend(response['features'])
        pages.append(first_url)
        visited.add(first_url)
        first_url = next((link['href'] for link in response.get('links', []) if link.get('rel') == 'next'), None)
        if first_url in visited:
            raise ValueError(f"USGS pagination loop for {well['id']}")
        if first_url:
            time.sleep(0.2)
    ids = [feature['id'] for feature in features]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate USGS observation IDs for {well['id']}")
    for feature in features:
        p = feature['properties']
        if p.get('time_series_id') != well['series_id']:
            raise ValueError(f"Unexpected time series in response for {well['id']}")
        if p.get('monitoring_location_id') != well['id']:
            raise ValueError(f"Unexpected monitoring location in response for {well['id']}")
        if p.get('parameter_code') != '72019' or p.get('statistic_id') != '00003':
            raise ValueError(f"Unexpected groundwater parameter/statistic for {well['id']}")
        if p.get('time', '')[:10] > end:
            raise ValueError(f"USGS returned an observation after the declared cutoff for {well['id']}")
    return features, pages


def summarize(well, features):
    days, approvals, qualified = set(), {}, 0
    for feature in features:
        p = feature['properties']
        day = p['time'][:10]
        days.add(day)
        status = p.get('approval_status') or 'Not stated'
        approvals[status] = approvals.get(status, 0) + 1
        if p.get('qualifier'):
            qualified += 1
    ordered = sorted(days)
    gaps = [(datetime.fromisoformat(b) - datetime.fromisoformat(a)).days - 1 for a, b in zip(ordered, ordered[1:])]
    return {
        'well_id': well['id'],
        'name': well['name'],
        'series_id': well['series_id'],
        'raw_record_count': len(features),
        'distinct_observation_days': len(ordered),
        'first_observation_day': ordered[0] if ordered else None,
        'last_observation_day': ordered[-1] if ordered else None,
        'approval_status_counts': approvals,
        'qualified_record_count': qualified,
        'largest_gap_days_between_observations': max(gaps) if gaps else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default='1900-01-01', help='Earliest requested date (default: 1900-01-01)')
    parser.add_argument('--end', help='Last included CT-local observation date; defaults to yesterday')
    args = parser.parse_args()

    datetime.fromisoformat(args.start)
    end = args.end or (datetime.now(timezone.utc).astimezone(LOCAL).date() - timedelta(days=1)).isoformat()
    if datetime.fromisoformat(end).date() >= datetime.now(timezone.utc).astimezone(LOCAL).date():
        raise ValueError('The end date must be a completed Connecticut-local day')

    registry = read(ROOT / 'data/prospective/model-v1.json')
    wells = registry['groundwater']
    captured = datetime.now(timezone.utc)
    folder = ROOT / 'data/groundwater-history' / captured.strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True, exist_ok=False)
    summaries, sources = [], []
    for well in wells:
        features, pages = fetch_series(well, args.start, end)
        if not features:
            raise ValueError(f"No daily groundwater history returned for {well['id']}")
        path = folder / f"{well['id']}.json"
        save(path, {
            'type': 'FeatureCollection',
            'features': features,
            'source_pages': pages,
            'request': {
                'time_series_id': well['series_id'],
                'monitoring_location_id': well['id'],
                'parameter_code': '72019',
                'statistic_id': '00003',
                'start': args.start,
                'end': end,
            },
            'captured_at': datetime.now(timezone.utc).isoformat(),
        })
        summaries.append(summarize(well, features))
        sources.append({
            'well_id': well['id'],
            'path': path.name,
            'sha256': sha256(path),
            'pages': len(pages),
            'bytes': path.stat().st_size,
        })
        print(f"{well['id']}: {len(features):,} raw records; {summaries[-1]['first_observation_day']} to {summaries[-1]['last_observation_day']}", flush=True)

    manifest = {
        'source': 'USGS Water Data OGC API daily collection',
        'api': API,
        'captured_at': captured.isoformat(),
        'observation_cutoff': end,
        'requested_start': args.start,
        'parameter': {'code': '72019', 'meaning': 'Depth to water below land surface'},
        'statistic': {'code': '00003', 'meaning': 'Daily mean'},
        'time_series_count': len(wells),
        'records': sources,
        'wells': summaries,
        'notes': [
            'Raw records are archived without filtering approval status or qualifiers.',
            'A daily mean series may contain gaps, provisional values, or revisions; inspect these before fitting a model.',
            'The existing 90-day snapshot and all sealed forecast inputs are unchanged.',
        ],
    }
    save(folder / 'manifest.json', manifest)
    print(json.dumps({'archive': str(folder.relative_to(ROOT)), 'wells': summaries}, indent=2), flush=True)


if __name__ == '__main__':
    main()
