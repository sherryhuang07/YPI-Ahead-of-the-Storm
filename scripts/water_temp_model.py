"""Standalone 14-day coastal water temperature model (Long Island Sound / Connecticut coast).

Only NDBC water temperature is used (isolated dataset). For each station and each lead L
(days from the last complete input day to the target):

    target = normal(target day) + w . [departure yesterday, mean departure over the last
             7 days, 7-day change, seasonal terms of the target day]

`normal` is the station's seasonal cycle (annual + semiannual harmonics) fitted on training
years only. Ridge regression per station and lead; chosen over "unchanged since yesterday"
only if it wins on the calibration years. Nominal 90% band from calibration errors.
"""
import numpy as np
from datetime import date

POLICY = dict(version='water-temp-v1', train_end='2018-12-31', calibration=['2019-01-01', '2021-12-31'], test=['2022-01-01', '2025-12-31'],
              leads=list(range(2, 16)), issue_offset_days=1, ridge_penalty=1.0, min_train=300, min_calibration=60,
              note='Issue day = last complete input day + 1; forecast days 1-14 are leads 2-15 from the last input. Chosen before scoring the test years.')


def phase(d):
    return 2 * np.pi * (date.fromisoformat(d).timetuple().tm_yday - 1) / 365.2425


def harmonics(days):
    p = np.array([phase(d) for d in days])
    return np.column_stack([np.ones(len(p)), np.sin(p), np.cos(p), np.sin(2 * p), np.cos(2 * p)])


def fit_normal(days, temps):
    coef, *_ = np.linalg.lstsq(harmonics(days), np.asarray(temps), rcond=None)
    return coef


def normal(coef, days):
    return harmonics(days) @ coef


def features(series, i, normal_vals, day_list):
    """series: temps aligned to consecutive days (NaN gaps); i: index of last input day."""
    if i < 7 or not np.isfinite(series[i]) or not np.isfinite(series[i - 7]): return None
    dep = series[i - 6:i + 1] - normal_vals[i - 6:i + 1]
    if np.isfinite(dep).sum() < 5: return None
    return np.array([series[i] - normal_vals[i], np.nanmean(dep), series[i] - series[i - 7]])


def design(f, target_day):
    p = phase(target_day)
    return np.concatenate([f, [np.sin(p), np.cos(p)]])


def fit(x, y, penalty):
    mean = x.mean(axis=0); scale = x.std(axis=0); scale[scale < 1e-9] = 1
    z = np.column_stack([np.ones(len(x)), (x - mean) / scale]); reg = np.eye(z.shape[1]) * penalty; reg[0, 0] = 0
    return dict(mean=mean.tolist(), scale=scale.tolist(), coef=np.linalg.solve(z.T @ z + reg, z.T @ y).tolist())


def predict(m, x):
    z = np.column_stack([np.ones(len(x)), (x - np.array(m['mean'])) / np.array(m['scale'])])
    return z @ np.array(m['coef'])
