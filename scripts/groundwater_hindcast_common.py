"""Helpers for the two-step, no-lookahead groundwater hindcast."""
import hashlib
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median

import numpy as np

from forecast_methods import predict
from statewide_common import ROOT, read

METHODS = ('persistence', 'damped_trend', 'autoregression', 'seasonal_median')
API = 'USGS Water Data daily means, parameter 72019, feet below land surface'
AVAILABILITY_LAG_DAYS = 7


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exclusive_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def latest_archive():
    folders = [p for p in (ROOT / 'data/groundwater-history').iterdir() if (p / 'manifest.json').exists()]
    if not folders:
        raise FileNotFoundError('No complete USGS groundwater history archive is available.')
    folder = max(folders, key=lambda p: p.name)
    manifest = read(folder / 'manifest.json')
    for item in manifest['records']:
        path = folder / item['path']
        if sha256(path) != item['sha256']:
            raise ValueError('USGS history hash mismatch: ' + str(path))
    return folder, manifest


def history_before(folder, well, cutoff):
    """Read eligible values only after date filtering; never parse target values."""
    end = cutoff.isoformat()
    raw = read(folder / f"{well['id']}.json")
    values = {}
    for feature in raw['features']:
        p = feature['properties']
        observation_day = p.get('time', '')[:10]
        if observation_day > end:
            continue
        if (p.get('monitoring_location_id') != well['id']
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
            day = date.fromisoformat(observation_day)
            if day in values and values[day] != value:
                raise ValueError(f"Conflicting readings for {well['id']} on {day}")
            values[day] = value
    return values


def seasonal_median(target, history, cutoff, years=5, half_window=14):
    reference = date(2000, target.month, target.day).timetuple().tm_yday
    values, observed_years = [], set()
    for day, value in history.items():
        if day >= cutoff or day.year < cutoff.year - years:
            continue
        seasonal_day = date(2000, day.month, day.day).timetuple().tm_yday
        distance = abs(reference - seasonal_day)
        distance = min(distance, 366 - distance)
        if distance <= half_window:
            values.append(value)
            observed_years.add(day.year)
    if len(values) < 20 or len(observed_years) < 3:
        raise ValueError('Insufficient same-season readings from three prior years')
    return float(median(values))


def forecast(method, issue, inputs):
    """Forecast issue+1 through issue+14 using only a pre-issued input mapping."""
    if not inputs:
        raise ValueError('No eligible pre-issue daily readings')
    last = max(inputs)
    if (issue - last).days > AVAILABILITY_LAG_DAYS:
        raise ValueError('Most recent eligible reading is older than the seven-day input limit')
    targets = [issue + timedelta(days=i) for i in range(1, 15)]
    if method == 'seasonal_median':
        values = [seasonal_median(day, inputs, issue) for day in targets]
    else:
        start = last - timedelta(days=89)
        q = np.array([inputs.get(start + timedelta(days=i), np.nan) for i in range(90)])
        lead = (targets[0] - last).days
        horizon = lead + len(targets) - 1
        if method == 'persistence':
            if not np.isfinite(q[-1]):
                raise ValueError('Latest eligible daily reading is missing')
            prediction = np.repeat(q[-1], horizon)
        else:
            prediction = predict(q, method, 'groundwater', horizon=horizon)
        values = np.asarray(prediction[lead - 1:lead - 1 + len(targets)], dtype=float).tolist()
    if len(values) != 14 or not np.isfinite(values).all():
        raise ValueError('Forecast did not produce 14 finite daily estimates')
    return targets, values, last


def month_issues(start, latest_target):
    year, month = start.year, start.month
    while True:
        issue = date(year, month, 1)
        if issue + timedelta(days=14) > latest_target:
            return
        yield issue
        month += 1
        if month == 13:
            year, month = year + 1, 1


def series_input_hash(values):
    payload = [[str(day), values[day]] for day in sorted(values)]
    return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()
