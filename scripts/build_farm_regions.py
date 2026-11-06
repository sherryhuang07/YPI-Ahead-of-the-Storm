"""Assign every mapped farm candidate (and the Yale Farm pilot) to its Connecticut planning region.

Boundaries: U.S. Census TIGERweb county-equivalents for Connecticut (the 9 planning regions,
GEOID 09110-09190, the same codes the U.S. Drought Monitor uses). Each farm is placed by its
boundary's representative point. Output: data/drought/farm-regions.json (farm id -> region).
"""
import hashlib
import json
from datetime import datetime, timezone
import requests
from shapely.geometry import shape, Point
from shapely.strtree import STRtree
from statewide_common import ROOT, read, save, log

URL = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query'


def main():
    r = requests.get(URL, params=dict(where="STATE='09'", outFields='GEOID,NAME', returnGeometry='true', outSR=4326, f='geojson'),
                     headers={'User-Agent': 'Connecticut agricultural water forecast research'}, timeout=180)
    r.raise_for_status(); regions = r.json()
    raw = ROOT / 'data/drought/raw/planning-regions.geojson'; raw.parent.mkdir(parents=True, exist_ok=True); raw.write_bytes(r.content)
    polys = [shape(f['geometry']) for f in regions['features']]
    ids = ['%s|%s' % (f['properties']['GEOID'], f['properties']['NAME']) for f in regions['features']]
    tree = STRtree(polys); out = {}; unplaced = []
    farms = read(ROOT / 'data/statewide/field-candidates.geojson')['features']
    points = [((f['properties'].get('candidate_id') or f['properties'].get('id')), shape(f['geometry']).representative_point()) for f in farms]
    points.append(('yale-farm-new-haven', Point(-72.93, 41.31)))
    for fid, pt in points:
        hit = [i for i in tree.query(pt) if polys[i].contains(pt)]
        if not hit:                                   # shoreline/border points: nearest region
            hit = [min(range(len(polys)), key=lambda i: polys[i].distance(pt))]; unplaced.append(fid)
        out[fid] = ids[hit[0]]
    from collections import Counter
    counts = Counter(out.values())
    save(ROOT / 'data/drought/farm-regions.json', dict(created_at=datetime.now(timezone.utc).isoformat(), source='U.S. Census TIGERweb State_County layer 1 (Connecticut planning regions)',
                                                      boundaries_sha256=hashlib.sha256(r.content).hexdigest(), farms=out, by_region=counts,
                                                      placed_by_nearest_region=len(unplaced)))
    log('Drought model: %d farms assigned to planning regions (%d by nearest region).' % (len(out), len(unplaced)))
    print(json.dumps(dict(counts), indent=1), 'nearest:', len(unplaced), 'Yale ->', out['yale-farm-new-haven'])


if __name__ == '__main__':
    main()
