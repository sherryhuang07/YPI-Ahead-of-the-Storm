"""Compare ratings rebuilt from airport weather with DEEP's published ratings.

Every archived DEEP rating (Internet Archive snapshots and daily captures) is matched with
the rebuilt statewide indexes for the same date, under each open choice: timber or grass
spread index; class from the higher of the two indexes or one alone; median or highest
airport. Reports exact agreement, within-one-class agreement and bias, per rule.
DEEP rates a forecast of 1 PM conditions made in the morning; the rebuild uses observed
1 PM weather, so perfect agreement is not expected.
"""
import csv
import json
from datetime import datetime, timezone
import numpy as np
from statewide_common import ROOT, save, log
from fire_danger_model import rating, LEVELS

FD = ROOT / 'data/fire-danger'


def main():
    deep = json.loads((FD / 'deep-ratings.json').read_text(encoding='utf-8'))['ratings']
    hist = {r['date']: r for r in csv.DictReader((FD / 'history.csv').open(encoding='utf-8'))}
    rules = {}
    for spread in ('timber', 'grass'):
        for agg in ('median', 'max'):
            for rule in ('max', 'spread', 'buildup'):
                rules['%s/%s/%s' % (spread, agg, rule)] = (spread, agg, rule)
    results = {}; matched = []
    for name, (spread, agg, rule) in rules.items():
        pairs = []
        for d, v in sorted(deep.items()):
            h = hist.get(d)
            if not h or h['median_timber'] == '': continue
            if agg == 'median':
                si = float(h['median_' + spread]); bi = float(h['median_bui'])
            else:
                st = [k[:-len('_' + spread)] for k in h if k.endswith('_' + spread) and not k.startswith(('median', 'max'))]
                vals = [(float(h[s + '_' + spread]), float(h[s + '_bui'])) for s in st if h[s + '_' + spread] not in ('', None)]
                si = max(x[0] for x in vals); bi = max(x[1] for x in vals)
            pairs.append((d, v['level_index'], rating(si, bi, rule), si, bi))
        if not pairs: continue
        y = np.array([p[1] for p in pairs]); f = np.array([p[2] for p in pairs])
        results[name] = dict(dates=len(pairs), exact=float(np.mean(y == f)), within_one=float(np.mean(abs(y - f) <= 1)), bias_classes=float(np.mean(f - y)))
        if name == 'timber/median/max': matched = pairs
    best = max(results.items(), key=lambda kv: (kv[1]['exact'], kv[1]['within_one'])) if results else None
    report = dict(created_at=datetime.now(timezone.utc).isoformat(), deep_ratings=len(deep), results=results,
                  best=best[0] if best else None,
                  detail_default_rule=[dict(date=d, deep=LEVELS[a], rebuilt=LEVELS[b], spread_index=round(s, 1), buildup_index=round(bi, 1)) for d, a, b, s, bi in matched],
                  caution='Few DEEP ratings are available; agreement on them is indicative, not a calibration. DEEP publishes mostly in fire seasons and high-danger periods.')
    save(FD / 'validation.json', report)
    log('Fire danger: validated rebuilt ratings against %d DEEP ratings.' % len(deep))
    for k, v in sorted(results.items(), key=lambda kv: -kv[1]['exact']):
        print('%-22s dates %3d  exact %.2f  within one %.2f  bias %+.2f' % (k, v['dates'], v['exact'], v['within_one'], v['bias_classes']))


if __name__ == '__main__':
    main()
