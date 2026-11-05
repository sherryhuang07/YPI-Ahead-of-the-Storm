"""Build and evaluate a research challenger using full-period well histories.

This creates a separate, timestamped archive. It never edits model-v1 or its
sealed prospective forecasts. The retrospective test uses archived USGS values
as currently returned, so it is not a replacement for prospective scoring.
"""
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import numpy as np

from forecast_methods import predict
from statewide_common import ROOT, read, save

KIND = 'groundwater'
METHODS = ('persistence', 'damped_trend', 'autoregression', 'seasonal_median')
TUNE_START = date(2019, 1, 1)
TEST_START = date(2023, 1, 1)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_latest_archive():
    folders = [p for p in (ROOT / 'data/groundwater-history').iterdir() if (p / 'manifest.json').exists()]
    if not folders:
        raise FileNotFoundError('No complete USGS groundwater history archive with a manifest was found.')
    folder = max(folders, key=lambda p: p.name)
    manifest = read(folder / 'manifest.json')
    for source in manifest['records']:
        path = folder / source['path']
        if digest(path) != source['sha256']:
            raise ValueError('Groundwater history hash mismatch: ' + str(path))
    return folder, manifest


def observations(folder, well):
    raw = read(folder / f"{well['id']}.json")
    result, excluded = {}, {'qualified': 0, 'wrong_unit': 0, 'invalid_value': 0}
    for feature in raw['features']:
        p = feature['properties']
        if p.get('time_series_id') != well['series_id'] or p.get('parameter_code') != '72019' or p.get('statistic_id') != '00003':
            raise ValueError('Unexpected series metadata in the archived groundwater history.')
        if p.get('qualifier'):
            excluded['qualified'] += 1
            continue
        if p.get('unit_of_measure') != 'ft':
            excluded['wrong_unit'] += 1
            continue
        try:
            value = float(p['value'])
        except (TypeError, ValueError):
            excluded['invalid_value'] += 1
            continue
        if not math.isfinite(value):
            excluded['invalid_value'] += 1
            continue
        day = date.fromisoformat(p['time'][:10])
        if day in result and result[day]['value'] != value:
            raise ValueError(f"Conflicting daily values for {well['id']} on {day}")
        result[day] = {'value': value, 'approval_status': p.get('approval_status')}
    return result, excluded


def seasonal_value(target, history, cutoff, years=5, half_window=14):
    """Median same-season depth from up to five prior years, never future dates."""
    reference = date(2000, target.month, target.day).timetuple().tm_yday
    values, used_years = [], set()
    for day, item in history.items():
        if day >= cutoff or day.year < cutoff.year - years:
            continue
        seasonal_day = date(2000, day.month, day.day).timetuple().tm_yday
        distance = abs(reference - seasonal_day)
        distance = min(distance, 366 - distance)
        if distance <= half_window:
            values.append(item['value'])
            used_years.add(day.year)
    if len(values) < 20 or len(used_years) < 3:
        raise ValueError('Not enough same-season history from at least three earlier years')
    return float(median(values))


def candidate_forecast(method, issue, target_dates, history):
    available = {d: v for d, v in history.items() if d < issue}
    if not available:
        raise ValueError('No pre-issue observations')
    last = max(available)
    if (issue - last).days > 7:
        raise ValueError('Latest clean observation is more than seven days before issue')
    if method == 'seasonal_median':
        return [seasonal_value(day, history, issue) for day in target_dates], last
    start = last - timedelta(days=89)
    q = np.array([available.get(start + timedelta(days=i), {}).get('value', np.nan) for i in range(90)])
    lead = (target_dates[0] - last).days
    if lead < 1:
        raise ValueError('Target period does not start after the latest observation')
    horizon = lead + len(target_dates) - 1
    if method == 'persistence':
        if not np.isfinite(q[-1]):
            raise ValueError('Latest daily observation unavailable')
        pred = np.repeat(q[-1], horizon)
    else:
        pred = predict(q, method, KIND, horizon=horizon)
    return np.asarray(pred[lead - 1:lead - 1 + len(target_dates)], dtype=float).tolist(), last


def first_of_months(start, end):
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        current = date(year, month, 1)
        if current >= start and current <= end:
            yield current
        month += 1
        if month == 13:
            year, month = year + 1, 1


def score_block(method, issue, history):
    target_dates = [issue + timedelta(days=i) for i in range(1, 15)]
    actual = [history[d]['value'] for d in target_dates if d in history]
    if len(actual) < 12:
        return None
    try:
        forecast, last = candidate_forecast(method, issue, target_dates, history)
    except (ValueError, FloatingPointError, np.linalg.LinAlgError):
        return None
    pairs = [(forecast[i], history[d]['value'], d) for i, d in enumerate(target_dates) if d in history]
    if len(pairs) < 12:
        return None
    return {
        'issue_date': str(issue),
        'first_target_date': str(target_dates[0]),
        'last_target_date': str(target_dates[-1]),
        'source_last_day': str(last),
        'usable_days': len(pairs),
        'mae_ft': float(np.mean([abs(pred - observed) for pred, observed, _ in pairs])),
        'absolute_errors': [abs(pred - observed) for pred, observed, _ in pairs],
    }


def evaluate_well(well, history, end):
    eligible_issue_dates = list(first_of_months(TUNE_START, end - timedelta(days=15)))
    tuning, test = {m: [] for m in METHODS}, {m: [] for m in METHODS}
    for issue in eligible_issue_dates:
        group = tuning if issue < TEST_START else test
        for method in METHODS:
            scored = score_block(method, issue, history)
            if scored is not None:
                group[method].append(scored)
    tune_mae = {m: float(np.mean([b['mae_ft'] for b in blocks])) for m, blocks in tuning.items() if len(blocks) >= 12}
    selected = min(tune_mae, key=tune_mae.get) if tune_mae else 'persistence'
    selected_test = test[selected]
    baseline_test = test['persistence']
    return {
        'well_id': well['id'],
        'name': well['name'],
        'history_start': str(min(history)) if history else None,
        'history_end': str(max(history)) if history else None,
        'clean_daily_count': len(history),
        'tuning_period': [str(TUNE_START), str(TEST_START - timedelta(days=1))],
        'test_period': [str(TEST_START), str(end)],
        'tuning_blocks_by_method': {m: len(v) for m, v in tuning.items()},
        'tuning_mae_ft_by_method': tune_mae,
        'selected_method': selected,
        'test_blocks': len(selected_test),
        'test_days': sum(b['usable_days'] for b in selected_test),
        'test_mae_ft': float(np.mean([b['mae_ft'] for b in selected_test])) if selected_test else None,
        'persistence_test_blocks': len(baseline_test),
        'persistence_test_days': sum(b['usable_days'] for b in baseline_test),
        'persistence_test_mae_ft': float(np.mean([b['mae_ft'] for b in baseline_test])) if baseline_test else None,
        'selected_test_windows': selected_test,
        'persistence_test_windows': baseline_test,
    }


def current_prediction(well, history, issue):
    target_dates = [issue + timedelta(days=i) for i in range(1, 15)]
    # Select from historic tune blocks only; the later held-out test period is never used.
    method = well['selected_method']
    prediction, last = candidate_forecast(method, issue, target_dates, history)
    return {
        'id': well['well_id'],
        'name': well['name'],
        'method': method,
        'source_last_day': str(last),
        'dates': [str(d) for d in target_dates],
        'prediction_ft_below_land': prediction,
        'direction_note': 'Increasing depth means a lower water level; this is a monitored-well estimate, not a farm groundwater measurement.',
    }


def main():
    folder, manifest = load_latest_archive()
    registry = read(ROOT / 'data/prospective/model-v1.json')
    cutoff = date.fromisoformat(manifest['observation_cutoff'])
    issue = datetime.now(timezone.utc)
    issue_day = issue.astimezone(ZoneInfo('America/New_York')).date()
    reports, forecasts, exclusions = [], [], {}
    histories = {}
    for well in registry['groundwater']:
        history, excluded = observations(folder, well)
        histories[well['id']] = history
        exclusions[well['id']] = excluded
        reports.append(evaluate_well(well, history, cutoff))
    for report, well in zip(reports, registry['groundwater']):
        try:
            forecasts.append(current_prediction(report, histories[well['id']], issue_day))
        except (ValueError, FloatingPointError, np.linalg.LinAlgError) as e:
            forecasts.append({'id': well['id'], 'name': well['name'], 'status': 'withheld', 'reason': str(e)})

    completed = [r for r in reports if r['test_mae_ft'] is not None and r['persistence_test_mae_ft'] is not None]
    summary = {
        'created_at': issue.isoformat(),
        'model_version': 'groundwater-history-challenger-v1',
        'status': 'research challenger; not substituted into sealed prospective ledger',
        'history_archive': str(folder.relative_to(ROOT)),
        'history_manifest_sha256': digest(folder / 'manifest.json'),
        'model_code_sha256': digest(Path(__file__)),
        'observation_cutoff': str(cutoff),
        'issue_day_connecticut': str(issue_day),
        'target_dates': [str(issue_day + timedelta(days=i)) for i in range(1, 15)],
        'tuning_period': [str(TUNE_START), str(TEST_START - timedelta(days=1))],
        'test_period': [str(TEST_START), str(cutoff)],
        'input_variable_allowlist': ['groundwater'],
        'selection_method': 'Per well, choose the lowest mean absolute error over monthly two-week tuning windows issued 2019–2022. The selected method is then assessed on non-overlapping monthly windows issued 2023 through the archive cutoff.',
        'test_observation_note': 'Retrospective USGS values are the records returned at archive time and may include later revisions or provisional values. This is not first-captured real-time verification.',
        'methods': list(METHODS),
        'mean_station_test_mae_ft': float(np.mean([r['test_mae_ft'] for r in completed])) if completed else None,
        'mean_station_persistence_mae_ft': float(np.mean([r['persistence_test_mae_ft'] for r in completed])) if completed else None,
        'wells_beating_persistence': sum(r['test_mae_ft'] < r['persistence_test_mae_ft'] for r in completed),
        'wells_with_test_scores': len(completed),
        'intervals': 'No prediction intervals are calibrated.',
        'excluded_observations': exclusions,
        'wells': reports,
        'forecast': forecasts,
    }
    out = ROOT / 'outputs/forecasts/groundwater/history-challenger'
    out.mkdir(parents=True, exist_ok=True)
    stamp = issue.strftime('%Y%m%dT%H%M%S%fZ')
    destination = out / f'{stamp}.json'
    if destination.exists():
        raise FileExistsError(destination)
    save(destination, summary)
    print(json.dumps({
        'report': str(destination.relative_to(ROOT)),
        'archive': str(folder.relative_to(ROOT)),
        'test_period': [str(TEST_START), str(cutoff)],
        'mean_station_mae_ft': summary['mean_station_test_mae_ft'],
        'mean_station_persistence_mae_ft': summary['mean_station_persistence_mae_ft'],
        'wells_beating_persistence': f"{summary['wells_beating_persistence']}/{summary['wells_with_test_scores']}",
        'wells': [{k: r[k] for k in ('well_id','name','selected_method','test_blocks','test_days','test_mae_ft','persistence_test_mae_ft')} for r in reports],
        'forecast': forecasts,
    }, indent=2), flush=True)


if __name__ == '__main__':
    main()
