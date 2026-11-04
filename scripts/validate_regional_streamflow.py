from collections import defaultdict
from shapely.geometry import shape,Point
from shapely.ops import unary_union
from statewide_common import ROOT,read,save
def main():
    d=ROOT/'outputs/regional-streamflow';gauges=read(d/'relevant-gauges.json');bodies=read(d/'water-feature-context.json');net=read(ROOT/'data/regional-streamflow/regional-network.json')
    ids={g['gauge_id'] for g in gauges};assert len(ids)==len(gauges)
    ct_ids={g['gauge_id'] for g in read(ROOT/'outputs/streamflow/gauges.json')};assert not ids&ct_ids
    mask=unary_union([shape(f['geometry']) for f in read(ROOT/'data/statewide/connecticut-mask.geojson')['features']])
    assert all(not mask.covers(Point(g['coordinates'])) for g in gauges)
    assert all(g['hr_reach_id'] in net['reaches'] for g in gauges)
    for b in bodies:
        assert len({g['gauge_id'] for g in b['outside_gauges']})==len(b['outside_gauges'])
        assert all(g['gauge_id'] in ids for g in b['outside_gauges'])
    assert all(p['ftype']!=566 and p['wbarea_permanent_identifier'] not in net['marine_waterbody_ids'] for p in net['reaches'].values())
    # A known upstream Farmington station must be linked through directed edges, not name alone.
    farm=next(b for b in bodies if b['kind']=='named_waterway' and b['name']=='Farmington River')
    link=next(g for g in farm['outside_gauges'] if g['gauge_id']=='USGS-01185500')
    assert 'upstream of Connecticut water feature' in link['relationships']
    ct=next(b for b in bodies if b['kind']=='named_waterway' and b['name']=='Connecticut River')
    assert any(g['state']=='Vermont' for g in ct['outside_gauges']) and any(g['state']=='New Hampshire' for g in ct['outside_gauges'])
    save(d/'validation.json',dict(gauges=len(gauges),water_features=len(bodies),duplicate_ct_gauges=0,marine_paths_excluded=True,known_farmington_upstream_link=True,upper_connecticut_states_present=True))
    print('PASS: distinct outside-CT gauges, valid reach references, deduplicated body links, marine exclusion and known upstream connections.')
if __name__=='__main__':main()
