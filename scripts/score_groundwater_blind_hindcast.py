"""Phase 2: score only after blind historical forecasts have been sealed."""
import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

from groundwater_hindcast_common import latest_archive, sha256, exclusive_json
from statewide_common import ROOT, read


def clean_targets(folder, well, target_days):
    path = folder / f"{well['well_id']}.json"
    raw = read(path)
    wanted = set(target_days)
    result = {}
    for feature in raw['features']:
        p = feature['properties']
        day_text = p.get('time', '')[:10]
        if day_text not in wanted:
            continue
        if (p.get('monitoring_location_id') != well['well_id']
                or p.get('time_series_id') != well['series_id']
                or p.get('parameter_code') != '72019'
                or p.get('statistic_id') != '00003'
                or p.get('unit_of_measure') != 'ft'
                or p.get('qualifier')):
            continue
        try:
            value = float(p['value'])
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            result[day_text] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_id', help='Run folder ID printed by create_groundwater_blind_hindcast.py')
    args = parser.parse_args()
    run_folder = ROOT / 'outputs/forecasts/groundwater/blind-hindcast' / args.run_id
    run_path = run_folder / 'run.json'
    run = read(run_path)
    if run['run_id'] != args.run_id or run['phase'] != 'forecast creation only; testing outcomes not loaded':
        raise ValueError('The run manifest does not identify a complete blind forecast phase.')

    # Verify every prediction file and its target dates before opening any target values.
    verified = []
    for item in run['issued_forecasts']:
        path = ROOT / item['path']
        if sha256(path) != item['sha256']:
            raise ValueError('Sealed test forecast hash mismatch: ' + str(path))
        issue = date.fromisoformat(item['issue_date'])
        record = read(path)
        if record.get('test_targets_loaded') is not False:
            raise ValueError('Forecast record does not prove that test outcomes were withheld.')
        for well in record['forecasts']:
            dates = [date.fromisoformat(d) for d in well['dates']]
            if len(dates) != 14 or dates != [issue + timedelta(days=i) for i in range(1, 15)]:
                raise ValueError('Forecast target dates do not match the sealed issue window.')
            if date.fromisoformat(well['input_cutoff_date']) != issue - timedelta(days=7):
                raise ValueError('Forecast input cutoff did not use the seven-day embargo.')
            if date.fromisoformat(well['source_last_observation_date']) > issue - timedelta(days=7):
                raise ValueError('Forecast used an observation after its allowed input cutoff.')
        verified.append((item, record))

    # Verify the input-only snapshots too. They contain no target-date values.
    prepared = ROOT / run['prepared_inputs']
    prepared_manifest_path = prepared / 'manifest.json'
    if sha256(prepared_manifest_path) != run['prepared_inputs_manifest_sha256']:
        raise ValueError('Prepared input manifest changed after forecasts were created.')
    for item in run['prepared_input_file_hashes']:
        path = prepared / item['path']
        if sha256(path) != item['sha256']:
            raise ValueError('Prepared pre-issue input snapshot changed: ' + str(path))

    # Only now, after all test forecasts are sealed and verified, load target labels.
    archive = ROOT / run['source_archive']
    if sha256(archive / 'manifest.json') != run['source_manifest_sha256']:
        raise ValueError('The input archive manifest changed after forecast creation.')
    archive, manifest = latest_archive()
    if str(archive.relative_to(ROOT)) != run['source_archive']:
        raise ValueError('The archive used to score is not the archive used to issue forecasts.')
    registry = read(ROOT / 'data/prospective/model-v1.json')
    well_meta = {w['id']: {'well_id': w['id'], 'series_id': w['series_id'], 'name': w['name']} for w in registry['groundwater']}
    all_scores, windows = [], []
    by_well = defaultdict(list)
    by_lead = defaultdict(list)
    for item, record in verified:
        issue = date.fromisoformat(item['issue_date'])
        for row in record['forecasts']:
            meta = well_meta[row['well_id']]
            targets = row['dates']
            actuals = clean_targets(archive, meta, targets)
            paired = []
            for lead, (day, prediction, baseline) in enumerate(zip(targets, row['prediction_ft_below_land'], row['persistence_baseline_ft']), 1):
                if day not in actuals:
                    continue
                error = abs(float(prediction) - actuals[day])
                baseline_error = abs(float(baseline) - actuals[day])
                paired.append((lead, day, error, baseline_error, prediction, actuals[day]))
            score = {
                'well_id': row['well_id'],
                'name': row['name'],
                'issue_date': str(issue),
                'target_start': targets[0],
                'target_end': targets[-1],
                'method': row['method'],
                'scored_days': len(paired),
                'forecast_mae_ft': sum(x[2] for x in paired) / len(paired) if paired else None,
                'persistence_mae_ft': sum(x[3] for x in paired) / len(paired) if paired else None,
                'status': 'scored' if len(paired) >= 12 else 'incomplete; fewer than 12 clean target days',
            }
            windows.append(score)
            if len(paired) >= 12:
                by_well[row['well_id']].append(score)
                for lead, day, error, baseline_error, prediction, actual in paired:
                    by_lead[lead].append((error, baseline_error))
                    all_scores.append((row['well_id'], day, error, baseline_error))

    well_results = []
    for well_id, entries in sorted(by_well.items()):
        well_results.append({
            'well_id': well_id,
            'name': entries[0]['name'],
            'scored_windows': len(entries),
            'scored_days': sum(x['scored_days'] for x in entries),
            'forecast_mean_window_mae_ft': sum(x['forecast_mae_ft'] for x in entries) / len(entries),
            'persistence_mean_window_mae_ft': sum(x['persistence_mae_ft'] for x in entries) / len(entries),
        })
    scored_wells = [x for x in well_results if x['scored_windows']]
    leads = [{
        'forecast_day': lead,
        'comparisons': len(values),
        'forecast_mae_ft': sum(v[0] for v in values) / len(values) if values else None,
        'persistence_mae_ft': sum(v[1] for v in values) / len(values) if values else None,
    } for lead, values in sorted(by_lead.items())]
    valid_windows = [x for x in windows if x['status'] == 'scored']
    result = {
        'run_id': args.run_id,
        'scored_at_utc': datetime.now(timezone.utc).isoformat(),
        'model_version': 'blind-hindcast-v1',
        'forecast_run_sha256': sha256(run_path),
        'scoring_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source_archive': run['source_archive'],
        'test_issue_period': run['testing_issue_period'],
        'training_period_for_method_selection': run['training_period'],
        'availability_lag_days': run['availability_lag_days'],
        'issued_windows': len(verified),
        'well_windows_issued': len(windows),
        'well_windows_scored': len(valid_windows),
        'well_windows_incomplete': len(windows) - len(valid_windows),
        'scored_well_days': len(all_scores),
        'mean_station_forecast_mae_ft': sum(x['forecast_mean_window_mae_ft'] for x in scored_wells) / len(scored_wells) if scored_wells else None,
        'mean_station_persistence_mae_ft': sum(x['persistence_mean_window_mae_ft'] for x in scored_wells) / len(scored_wells) if scored_wells else None,
        'wells_beating_persistence': sum(x['forecast_mean_window_mae_ft'] < x['persistence_mean_window_mae_ft'] for x in scored_wells),
        'wells_with_scores': len(scored_wells),
        'by_forecast_day': leads,
        'by_well': well_results,
        'windows': windows,
        'interpretation': 'A time-ordered hindcast: methods were chosen using only 2019–2022 training windows; each 2023+ forecast was sealed using only observations through issue date minus seven days; target values were loaded only by this separate scoring step. Historical USGS values may have been revised and their original publication times are unavailable, so this is not a true archived-vintage replay or live prospective verification. Overlapping wells share weather, and monthly outcomes are temporally related. No prediction interval is calibrated.',
    }
    output = run_folder / 'scorecard.json'
    exclusive_json(output, result)
    print(json.dumps({
        'scorecard': str(output.relative_to(ROOT)),
        'issued_windows': result['issued_windows'],
        'well_windows_scored': result['well_windows_scored'],
        'well_windows_incomplete': result['well_windows_incomplete'],
        'scored_well_days': result['scored_well_days'],
        'mean_station_forecast_mae_ft': result['mean_station_forecast_mae_ft'],
        'mean_station_persistence_mae_ft': result['mean_station_persistence_mae_ft'],
        'wells_beating_persistence': f"{result['wells_beating_persistence']}/{result['wells_with_scores']}",
        'by_well': [{k: x[k] for k in ('well_id','name','scored_windows','scored_days','forecast_mean_window_mae_ft','persistence_mean_window_mae_ft')} for x in well_results],
    }, indent=2), flush=True)


if __name__ == '__main__':
    main()
