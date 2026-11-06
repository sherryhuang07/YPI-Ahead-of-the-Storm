"""Verify a USGS EarthExplorer machine-to-machine (M2M) login token, and find VegDRI.

Credentials come only from environment variables set by connect-usgs.ps1. Never log the
username or token. Writes data/drought/access/usgs-login-status.json (no credentials).
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import requests

API = 'https://m2m.cr.usgs.gov/api/api/json/stable/'
ROOT = Path(__file__).resolve().parents[1]


def login():
    r = requests.post(API + 'login-token', json=dict(username=os.environ['USGS_USERNAME'], token=os.environ['USGS_TOKEN']), timeout=60)
    body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
    if r.status_code != 200 or body.get('errorCode'): return None, body.get('errorCode') or 'HTTP %d' % r.status_code
    return body['data'], None


def main():
    if not (os.getenv('USGS_USERNAME') and os.getenv('USGS_TOKEN')):
        print('Please open Connect USGS EarthExplorer.cmd to sign in on this computer.'); return 1
    folder = ROOT / 'data/drought/access'; folder.mkdir(parents=True, exist_ok=True)
    key, error = None, None
    try: key, error = login()
    except Exception as e: error = type(e).__name__
    result = dict(checked_at=datetime.now(timezone.utc).isoformat(), authenticated=bool(key), error_code=error, vegdri_datasets=[])
    if key:
        try:
            r = requests.post(API + 'dataset-search', json=dict(datasetName='vegdri'), headers={'X-Auth-Token': key}, timeout=60).json()
            result['vegdri_datasets'] = [dict(name=d.get('datasetAlias'), title=d.get('collectionName'), start=d.get('temporalCoverage', {}).get('startDate') if isinstance(d.get('temporalCoverage'), dict) else None)
                                         for d in (r.get('data') or [])]
            requests.post(API + 'logout', headers={'X-Auth-Token': key}, timeout=30)
        except Exception as e:
            result['dataset_search_error'] = type(e).__name__
    (folder / 'usgs-login-status.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if key:
        print('USGS sign-in verified. VegDRI datasets visible: %s' % (', '.join(d['name'] or '?' for d in result['vegdri_datasets']) or 'none found yet'))
        return 0
    hint = {'AUTH_UNAUTHROIZED': 'This account does not have M2M access yet: request "Access to EE\'s M2M API" in your USGS profile.',
            'AUTH_UNAUTHORIZED': 'This account does not have M2M access yet: request "Access to EE\'s M2M API" in your USGS profile.',
            'AUTH_INVALID': 'Username or token not accepted. Check the username, and generate a new application token.'}.get(error, '')
    print('USGS sign-in did not succeed (%s). %s' % (error, hint)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
