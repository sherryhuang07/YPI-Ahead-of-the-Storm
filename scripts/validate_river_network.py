"""Check completeness and integrity without confusing HR identifiers with V2 COMIDs."""
from statewide_common import ROOT,read,save
from collections import Counter

D=ROOT/'data/hydrography';O=ROOT/'outputs/river-network'
def main():
    checks=[]
    for name in ['hr-flowlines','hr-catchments','hr-waterbodies','hr-gauges','public-dams','3dhp-flowlines','3dhp-waterbodies','3dhp-catchments','3dhp-outlets','3dhp-workunits']:
        path=D/(name+'.geojson')
        if not path.exists():checks.append(dict(dataset=name,status='Missing'));continue
        fs=read(path)['features'];ids=[f.get('id',f['properties'].get('OBJECTID')) for f in fs]
        assert len(ids)==len(set(ids)),name+' duplicated features'
        assert len(fs)==read(path.with_suffix('.source.json'))['count']
        checks.append(dict(dataset=name,status='Checked',features=len(fs)))
    rows=read(O/'farm-drainage-links.json');assert len(rows)==11759
    assert len({r['candidate_id'] for r in rows})==len(rows)
    for r in rows:
        for c in r['catchments']:assert 0<c['fraction']<=1.00001
        for b in r['upstream_of_gauges']:assert 0<b['fraction']<=1.00001
    edges=read(O/'directed-reaches.json');ids={e['nhdplusid'] for e in edges};assert len(edges)==len(ids)
    assert all(d in ids and d!=e['nhdplusid'] for e in edges for d in e['downstream'])
    sums=[sum(c['fraction'] for c in r['catchments']) for r in rows]
    # Overlaps are reported, not silently normalized into a false partition.
    save(O/'validation.json',dict(datasets=checks,farms=len(rows),catchment_overlap_above_1_01=sum(x>1.01 for x in sums),farms_without_catchment=sum(not r['catchments'] for r in rows),graph_edges=sum(len(e['downstream']) for e in edges),note='Geometric and identifier checks do not establish hydraulic accuracy.'))
    print('PASS: unique features, source counts, farm links, overlap fractions and directed edge references.')

if __name__=='__main__':main()
