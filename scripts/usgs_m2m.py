"""Minimal USGS EarthExplorer machine-to-machine (M2M) client. Credentials only from the
environment (set by the encrypted-credential launcher); never logged."""
import os
import requests

API = 'https://m2m.cr.usgs.gov/api/api/json/stable/'


class M2M:
    def __init__(self):
        if not (os.getenv('USGS_USERNAME') and os.getenv('USGS_TOKEN')):
            raise RuntimeError('USGS sign-in not provided. Run through the USGS launcher (uses the saved encrypted sign-in).')
        r = requests.post(API + 'login-token', json=dict(username=os.environ['USGS_USERNAME'], token=os.environ['USGS_TOKEN']), timeout=60)
        body = r.json()
        if body.get('errorCode'): raise RuntimeError('USGS sign-in failed: %s' % body['errorCode'])
        self.key = body['data']

    def call(self, endpoint, payload, attempts=4):
        import time
        for a in range(attempts):
            r = requests.post(API + endpoint, json=payload, headers={'X-Auth-Token': self.key}, timeout=300)
            try:
                body = r.json(); break
            except ValueError:
                if a == attempts - 1:
                    import re
                    text = re.sub(r'<[^>]+>', ' ', re.sub(r'(?s)<(script|style|head)\b.*?</\1>', ' ', r.text))
                    raise RuntimeError('%s returned HTTP %d, not JSON: %s' % (endpoint, r.status_code, ' '.join(text.split())[600:1600]))
                time.sleep(15 * (a + 1))
        if body.get('errorCode'): raise RuntimeError('%s failed: %s %s' % (endpoint, body['errorCode'], body.get('errorMessage', '')[:200]))
        return body['data']

    def close(self):
        try: requests.post(API + 'logout', headers={'X-Auth-Token': self.key}, timeout=30)
        except requests.RequestException: pass
