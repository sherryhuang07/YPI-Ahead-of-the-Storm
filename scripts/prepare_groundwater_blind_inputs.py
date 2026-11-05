"""Prepare past-only snapshots for the blind hindcast before fitting forecasts."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from groundwater_hindcast_common import history_before, latest_archive, month_issues, exclusive_json
from statewide_common import ROOT

TRAIN_END = date(2022, 12, 31)
TEST_START = date(2023, 1, 1)


def save_snapshot(path, well, cutoff, values):
    snapshot = {
        'well_id': well['id'],
        'series_id': well['series_id'],
        'latest_allowed_observation_date': str(cutoff),
        'observations': [[str(day), value] for day, value in sorted(values.items())],
    }
    exclusive_json(path, snapshot)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest(), len(values)


def main():
    archive, source = latest_archive()
    from statewide_common import read
    registry = read(ROOT / 'data/prospective/model-v1.json')
    end = date.fromisoformat(source['observation_cutoff'])
    issues = list(month_issues(TEST_START, end))
    created = datetime.now(timezone.utc)
    prep_id = created.strftime('%Y%m%dT%H%M%S%fZ')
    root = ROOT / 'outputs/forecasts/groundwater/blind-hindcast/prepared-inputs' / prep_id
    training_folder = root / 'training'
    test_folder = root / 'test'
    training_folder.mkdir(parents=True, exist_ok=False)
    files = []
    for well in registry['groundwater']:
        values = history_before(archive, well, TRAIN_END)
        path = training_folder / f"{well['id']}.json"
        sha, count = save_snapshot(path, well, TRAIN_END, values)
        files.append({'path': str(path.relative_to(root)), 'sha256': sha, 'well_id': well['id'], 'kind': 'training', 'records': count, 'cutoff': str(TRAIN_END)})

    for issue in issues:
        issue_folder = test_folder / issue.isoformat()
        issue_folder.mkdir(parents=True, exist_ok=False)
        cutoff = issue - timedelta(days=7)
        for well in registry['groundwater']:
            values = history_before(archive, well, cutoff)
            path = issue_folder / f"{well['id']}.json"
            sha, count = save_snapshot(path, well, cutoff, values)
            files.append({'path': str(path.relative_to(root)), 'sha256': sha, 'well_id': well['id'], 'kind': 'test-input', 'issue_date': str(issue), 'records': count, 'cutoff': str(cutoff)})

    manifest = {
        'preparation_id': prep_id,
        'created_at_utc': created.isoformat(),
        'source_archive': str(archive.relative_to(ROOT)),
        'source_manifest_sha256': hashlib.sha256((archive / 'manifest.json').read_bytes()).hexdigest(),
        'source_record_hashes': source['records'],
        'training_period': ['2001-01-01', str(TRAIN_END)],
        'method_selection_period': ['2019-01-01', '2022-12-31'],
        'testing_issue_dates': [str(issue) for issue in issues],
        'target_period_rule': 'Each simulated monthly issue targets issue date +1 through +14.',
        'availability_lag_days': 7,
        'files': files,
        'leakage_guard': 'Each snapshot contains only observations dated on or before its stated cutoff. The preparation step filters by observation date before reading any value; target-date values are omitted.',
    }
    exclusive_json(root / 'manifest.json', manifest)
    print(json.dumps({
        'preparation_id': prep_id,
        'snapshot_files': len(files),
        'test_issue_dates': len(issues),
        'test_input_files': sum(x['kind'] == 'test-input' for x in files),
        'training_files': sum(x['kind'] == 'training' for x in files),
        'manifest': str((root / 'manifest.json').relative_to(ROOT)),
    }, indent=2), flush=True)


if __name__ == '__main__':
    main()
