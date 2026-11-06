"""Issue a live 1-14 day root-zone forecast from the frozen historical model.

Inputs: data/root-zone/daily-inputs/latest.csv (assemble_root_zone_inputs.py live).
Model: outputs/root-zone/<run>/model.json from train_root_zone.py, hash-checked
against its sealed manifest. Coefficients are never refit here.

Timing matches training exactly: the 28-day input window ends input_lag_days
(6) before the issue date, and horizons count from the issue date. Days newer
than that cutoff are reported for context only and do not enter the model.
"""
import csv
import json
from datetime import date, datetime, timedelta, timezone
import numpy as np
from fetch_root_zone_history import ROOT, digest
from root_zone_model import features, predict

INPUTS = ROOT / 'data/root-zone/daily-inputs'


def main():
    latest = json.loads((ROOT / 'outputs/root-zone/latest.json').read_text(encoding='utf-8'))
    run = ROOT / 'outputs/root-zone' / latest['run']
    sealed = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    for name in ('model.json', 'policy.json'):
        if digest(run / name) != sealed['files'][name]:
            raise ValueError('Trained artifact changed since sealing: ' + name)
    models = json.loads((run / 'model.json').read_text(encoding='utf-8'))
    policy = json.loads((run / 'policy.json').read_text(encoding='utf-8'))
    meta = json.loads((INPUTS / 'latest.json').read_text(encoding='utf-8'))
    issue = date.fromisoformat(meta['issue_date']); lag = policy['input_lag_days']
    cutoff = issue - timedelta(days=lag)
    first = date.fromisoformat(meta['required_window'][0])
    days = [first + timedelta(days=k) for k in range((cutoff - first).days + 1)]
    index = {d.isoformat(): k for k, d in enumerate(days)}
    values = {}; newest = {}
    with (INPUTS / 'latest.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            v = float(r['moisture_m3m3']) if r['moisture_m3m3'] else float('nan')
            series = values.setdefault(r['watershed_id'], np.full(len(days), np.nan))
            if r['date'] in index: series[index[r['date']]] = v
            if np.isfinite(v) and r['date'] > newest.get(r['watershed_id'], ('', None))[0]:
                newest[r['watershed_id']] = (r['date'], v)
    check_path = INPUTS / 'archive-check.json'
    check = json.loads(check_path.read_text(encoding='utf-8')) if check_path.exists() else None
    mismatch = None
    if check:
        best = check['offsets'][str(check['best_day_start_utc_hour'])]
        mismatch = best['by_watershed']
    now = datetime.now(timezone.utc); stamp = now.strftime('%Y%m%dT%H%M%S%fZ')
    out = ROOT / 'outputs/root-zone/live' / stamp; out.mkdir(parents=True, exist_ok=False)
    rows = []; withheld = []
    # features() expects a series where position issue_index-lag is the last input.
    pad = np.full(lag, np.nan)
    for sid, per_h in models.items():
        series = values.get(sid)
        if series is None or not np.all(np.isfinite(series)):
            withheld.append(dict(watershed_id=sid, reason='Incomplete 28-day input window ending %s' % cutoff)); continue
        s = np.concatenate([series, pad]); issue_index = len(s) - 1
        for h in policy['horizons_days']:
            m = per_h.get(str(h))
            if m is None:
                withheld.append(dict(watershed_id=sid, horizon_days=h, reason='No trained model for this horizon')); continue
            target = issue + timedelta(days=h)
            x = features(s, issue_index, target.isoformat(), lag)
            v = float(predict(m['model'], x[None, :])[0]) if m['method'] == 'ridge' else float(x[0])
            r = m['interval_radius']
            rows.append(dict(watershed_id=sid, issue_date=issue.isoformat(), latest_input_date=cutoff.isoformat(),
                             target_date=target.isoformat(), horizon_days=h, prediction=round(v, 5),
                             lower=round(max(0, v - r), 5), upper=round(min(1, v + r), 5), method=m['method'],
                             last_input=round(float(x[0]), 5),
                             newest_published_date=newest.get(sid, (None,))[0],
                             newest_published_value=round(newest[sid][1], 5) if sid in newest else None,
                             input_mismatch_mae_vs_archive=round(mismatch[sid]['mae'], 5) if mismatch and sid in mismatch else None))
    with (out / 'forecast.csv').open('x', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['watershed_id']); w.writeheader(); w.writerows(rows)
    ws = sorted({r['watershed_id'] for r in rows})
    summary = {}
    for h in (1, 7, 14):
        p = [r['prediction'] for r in rows if r['horizon_days'] == h]
        if p: summary[str(h)] = dict(watersheds=len(p), median=float(np.median(p)), minimum=min(p), maximum=max(p))
    record = dict(created_at=now.isoformat(), status='Live research forecast issued from frozen historical model.',
                  issue_date=issue.isoformat(), latest_input_date=cutoff.isoformat(),
                  input_window=[first.isoformat(), cutoff.isoformat()], trained_run=latest['run'],
                  model_sha256=sealed['files']['model.json'], inputs_sha256=digest(INPUTS / 'latest.csv'),
                  input_source=meta['source'], day_definition=meta['day_definition'],
                  alignment_source=meta.get('alignment_source'),
                  archive_check=(dict(best_day_start_utc_hour=check['best_day_start_utc_hour'],
                                      mae=check['offsets'][str(check['best_day_start_utc_hour'])]['mae'],
                                      bias=check['offsets'][str(check['best_day_start_utc_hour'])]['bias'],
                                      period=check['period']) if check else None),
                  watersheds_forecast=len(ws), withheld=withheld, summary_by_horizon=summary,
                  forecast_sha256=digest(out / 'forecast.csv'),
                  limits=['Watershed averages of modeled NLDAS moisture, not farm or sensor readings.',
                          'Historical skill was measured on the USGS archive; live inputs are rebuilt from NLDAS v2.0 with NLDI boundaries, adding input mismatch error (see archive_check).',
                          'Bands are nominal 90% from 2010-2014 calibration errors; they do not include input mismatch.',
                          'No future weather forecast is used; no drought index or irrigation advice is produced.'])
    (out / 'manifest.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    (ROOT / 'outputs/root-zone/live/latest.json').write_text(json.dumps(dict(run=stamp, **record), indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in record.items() if k != 'withheld'}, indent=2))
    print('Withheld: %d entries' % len(withheld))


if __name__ == '__main__':
    main()
