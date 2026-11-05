"""Phase 1: freeze methods and create test forecasts without scoring test data.

Run this first. It writes append-only forecast files and a manifest. It does not
read target values from the 2023+ test windows; scoring is a separate command.
"""
import hashlib
import json
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from groundwater_hindcast_common import (
    METHODS, forecast, month_issues, series_input_hash, sha256, exclusive_json,
)
from statewide_common import ROOT, read

TUNE_START = date(2019, 1, 1)
TUNE_END = date(2022, 12, 31)
TEST_START = date(2023, 1, 1)
MIN_TUNING_BLOCKS = 12
LOCAL = ZoneInfo('America/New_York')


def tune_method(well, full_training_history):
    """Make every tuning forecast before opening any tuning target labels."""
    predictions = {method: [] for method in METHODS}
    for issue in month_issues(TUNE_START, TUNE_END):
        input_cutoff = issue - timedelta(days=7)
        inputs = {day: value for day, value in full_training_history.items() if day <= input_cutoff}
        for method in METHODS:
            try:
                targets, values, last = forecast(method, issue, inputs)
            except (ValueError, FloatingPointError):
                continue
            predictions[method].append({
                'issue_date': issue,
                'targets': targets,
                'predictions': values,
                'source_last_observation_date': last,
            })

    # These are training-period labels only. No 2023+ test values are present in
    # full_training_history, and all tuning predictions above were made first.
    scores = {}
    for method, windows in predictions.items():
        errors, scored_days = [], 0
        for window in windows:
            actual = [full_training_history.get(day) for day in window['targets']]
            pairs = [(pred, obs) for pred, obs in zip(window['predictions'], actual) if obs is not None]
            if len(pairs) < 12:
                continue
            errors.extend(abs(pred - obs) for pred, obs in pairs)
            scored_days += len(pairs)
        if len([w for w in windows if sum(full_training_history.get(d) is not None for d in w['targets']) >= 12]) >= MIN_TUNING_BLOCKS:
            scores[method] = {
                'windows': sum(1 for w in windows if sum(full_training_history.get(d) is not None for d in w['targets']) >= 12),
                'scored_days': scored_days,
                'mae_ft': sum(errors) / len(errors) if errors else None,
            }
    if not scores:
        return 'persistence', scores
    selected = min(scores, key=lambda method: scores[method]['mae_ft'])
    return selected, scores


def read_snapshot(path, well, expected_cutoff, expected_sha):
    if sha256(path) != expected_sha:
        raise ValueError('Prepared pre-issue input hash mismatch: ' + str(path))
    snapshot = read(path)
    if snapshot['well_id'] != well['id'] or snapshot['series_id'] != well['series_id']:
        raise ValueError('Prepared input belongs to a different well series.')
    if snapshot['latest_allowed_observation_date'] != str(expected_cutoff):
        raise ValueError('Prepared input cutoff does not match its simulated issue date.')
    values = {}
    for day_text, value in snapshot['observations']:
        day = date.fromisoformat(day_text)
        if day > expected_cutoff:
            raise ValueError('Prepared inputs contain an observation after their cutoff.')
        values[day] = float(value)
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('preparation_id', help='ID printed by prepare_groundwater_blind_inputs.py')
    args = parser.parse_args()
    prep_folder = ROOT / 'outputs/forecasts/groundwater/blind-hindcast/prepared-inputs' / args.preparation_id
    prep_manifest_path = prep_folder / 'manifest.json'
    preparation = read(prep_manifest_path)
    if preparation['preparation_id'] != args.preparation_id:
        raise ValueError('Prepared input manifest ID does not match the requested run.')
    registry = read(ROOT / 'data/prospective/model-v1.json')
    run_time = datetime.now(timezone.utc)
    run_id = run_time.strftime('%Y%m%dT%H%M%S%fZ')
    run_folder = ROOT / 'outputs/forecasts/groundwater/blind-hindcast' / run_id
    forecast_folder = run_folder / 'issued'
    forecast_folder.mkdir(parents=True, exist_ok=False)

    file_index = {(f['kind'], f.get('issue_date'), f['well_id']): f for f in preparation['files']}
    # Freeze one method per well from the 2019–2022 training snapshots only.
    frozen_methods = {}
    for well in registry['groundwater']:
        info = file_index[('training', None, well['id'])]
        history = read_snapshot(prep_folder / info['path'], well, TUNE_END, info['sha256'])
        selected, scores = tune_method(well, history)
        frozen_methods[well['id']] = {
            'name': well['name'],
            'selected_method': selected,
            'tuning_mae_ft': scores,
        }

    # This forecast phase opens only prepared inputs, never the raw USGS archive.
    # Simulate a 6:00 AM Connecticut issue on each prepared monthly date.
    issued_forecasts = []
    test_issues = [date.fromisoformat(x) for x in preparation['testing_issue_dates']]
    for issue in test_issues:
        rows, unavailable = [], []
        cutoff = issue - timedelta(days=7)
        for well in registry['groundwater']:
            method = frozen_methods[well['id']]['selected_method']
            info = file_index[('test-input', str(issue), well['id'])]
            inputs = read_snapshot(prep_folder / info['path'], well, cutoff, info['sha256'])
            try:
                targets, values, last = forecast(method, issue, inputs)
                baseline = inputs[last]
                rows.append({
                    'well_id': well['id'],
                    'name': well['name'],
                    'method': method,
                    'dates': [str(d) for d in targets],
                    'prediction_ft_below_land': values,
                    'persistence_baseline_ft': [baseline] * len(targets),
                    'input_cutoff_date': str(cutoff),
                    'source_last_observation_date': str(last),
                    'input_observation_count': len(inputs),
                    'input_series_sha256': series_input_hash(inputs),
                    'units': 'feet below local land surface at monitored well',
                })
            except (ValueError, FloatingPointError) as exc:
                unavailable.append({'well_id': well['id'], 'reason': str(exc)})
        simulated_issue = datetime.combine(issue, datetime.min.time(), LOCAL).replace(hour=6)
        path = forecast_folder / f'{issue.isoformat()}.json'
        record = {
            'run_id': run_id,
            'variable': 'groundwater',
            'model_version': 'blind-hindcast-v1',
            'simulated_issue_time_local': simulated_issue.isoformat(),
            'input_cutoff_rule': 'Latest permitted observation date is seven calendar days before the simulated issue date.',
            'test_targets_loaded': False,
            'forecasts': rows,
            'unavailable': unavailable,
        }
        exclusive_json(path, record)
        issued_forecasts.append({
            'path': str(path.relative_to(ROOT)),
            'sha256': sha256(path),
            'issue_date': str(issue),
            'locations_forecast': len(rows),
            'locations_withheld': len(unavailable),
        })

    forecast_methods = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    common_hash = sha256(Path(__file__).with_name('groundwater_hindcast_common.py'))
    run_record = {
        'run_id': run_id,
        'created_at_utc': run_time.isoformat(),
        'phase': 'forecast creation only; testing outcomes not loaded',
        'source_archive': preparation['source_archive'],
        'source_manifest_sha256': preparation['source_manifest_sha256'],
        'source_record_hashes': preparation['source_record_hashes'],
        'prepared_inputs': str(prep_folder.relative_to(ROOT)),
        'prepared_inputs_manifest_sha256': sha256(prep_manifest_path),
        'prepared_input_file_hashes': [{'path': x['path'], 'sha256': x['sha256']} for x in preparation['files']],
        'forecast_code_sha256': forecast_methods,
        'common_code_sha256': common_hash,
        'training_period': [str(TUNE_START), str(TUNE_END)],
        'testing_issue_period': [issued_forecasts[0]['issue_date'], issued_forecasts[-1]['issue_date']] if issued_forecasts else [],
        'availability_lag_days': 7,
        'frozen_methods_by_well': frozen_methods,
        'issued_forecasts': issued_forecasts,
        'scoring_status': 'Not scored yet. Run scripts/score_groundwater_blind_hindcast.py after these forecasts are sealed.',
        'data_vintage_caveat': 'USGS histories were downloaded now. Historical publication timestamps and old value vintages are unavailable; the seven-day input embargo limits, but cannot remove, that availability uncertainty.',
    }
    exclusive_json(run_folder / 'run.json', run_record)
    print(json.dumps({
        'run_id': run_id,
        'forecast_files': len(issued_forecasts),
        'windows_with_all_8_wells': sum(x['locations_forecast'] == 8 for x in issued_forecasts),
        'training_methods': {k: v['selected_method'] for k, v in frozen_methods.items()},
        'scoring_status': run_record['scoring_status'],
    }, indent=2), flush=True)


if __name__ == '__main__':
    main()
