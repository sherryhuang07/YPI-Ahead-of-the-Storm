"""Daily report: today's forecasts, how yesterday's measurements scored, and what each learning
version learned. Written at the end of every daily run (night and morning parts), so the
morning report is the complete one for the day.

Outputs (one per Connecticut day, rewritten by each run that day):
  outputs/daily-reports/YYYY-MM-DD.md     plain-English report
  outputs/daily-reports/YYYY-MM-DD.json   the same content as data (the app's report page reads it)
  outputs/daily-reports/latest.json       pointer to the newest report
"Newly scored" means comparisons scored since the last report written on an earlier day (or in the
last 24 hours for the first report). Learning changes compare the weights each learning version used
for today's forecast with those it used for the previous day's forecast.
"""
import glob
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import numpy as np
from statewide_common import ROOT, read, save, log
import prospective_daily as p

OUT = ROOT / 'outputs/daily-reports'
LEVELS = ['LOW', 'MODERATE', 'HIGH', 'VERY HIGH', 'EXTREME']

# name, ledger folder, variable, unit label, display multiplier (applied to errors)
LEDGERS = [
    ('Rain, NOAA forecast (shown in app)', 'noaa-rain-prospective', 'precipitation', 'in', 1 / 25.4),
    ('Rain, history average (old baseline)', 'prospective', 'precipitation', 'in', 1 / 25.4),
    ('Streams v2, with NOAA rain', 'streamflow-v2-prospective', 'streamflow', 'cfs', 1),
    ('Streams v1', 'prospective', 'streamflow', 'cfs', 1),
    ('Neighboring-state streams v2, with NOAA rain', 'regional-streamflow-v2-prospective', 'streamflow', 'cfs', 1),
    ('Neighboring-state streams v1', 'regional-prospective', 'streamflow', 'cfs', 1),
    ('Wells v2, with NOAA rain', 'groundwater-v2-prospective', 'groundwater', 'ft', 1),
    ('Wells v1', 'prospective', 'groundwater', 'ft', 1),
    ('Soil moisture', 'root-zone-prospective', 'root-zone', '% water', 100),
    ('Fire danger', 'fire-danger-prospective', 'fire-danger', 'classes', 1),
    ('Coastal water temperature', 'water-temp-prospective', 'water-temp', '°F', 1.8),
    ('Drought v1', 'drought-prospective', 'drought', 'index pts', 1),
    ('Drought v2 (satellite plant stress)', 'drought-v2-prospective', 'drought', 'index pts', 1),
]


def ro(path):
    return sqlite3.connect('file:%s?mode=ro' % path.as_posix(), uri=True) if path.exists() else None


def today_issue(folder, kind, day):
    files = sorted(glob.glob(str(ROOT / 'outputs' / folder / 'issued' / day / (kind + '-*.json'))))
    for f in reversed(files):
        r = read(f)
        if r.get('forecasts'): return r
    return None


def fmt(v, d=2):
    return '–' if v is None or (isinstance(v, float) and not np.isfinite(v)) else ('%.' + str(d) + 'f') % v


# ---------------------------------------------------------------- sections
def run_status(day):
    rows = []
    for part in ('night', 'morning'):
        s = ROOT / ('outputs/daily-run-summary-%s.json' % part)
        if not s.exists(): continue
        r = json.loads(s.read_text(encoding='utf-8-sig'))
        when = datetime.fromisoformat(r['completed_at'].replace('Z', '+00:00')).astimezone(p.LOCAL)
        if str(when.date()) != day: rows.append([part, 'not run yet today', '', '']); continue
        bad = [j['job'] for j in r['jobs'] if j['exit_code'] != 0]
        rows.append([part, when.strftime('%I:%M %p').lstrip('0'), '%d of %d' % (len(r['jobs']) - len(bad), len(r['jobs'])), '; '.join(bad) or 'none'])
    return dict(title='Daily runs', table=dict(head=['Part', 'Finished', 'Steps ok', 'Failed'], rows=rows),
                notes=['Scheduled at 12:05 AM (night) and 6:30 AM (morning); a sleeping laptop runs them when it next wakes.'])


def forecasts(day):
    rows = []; notes = []
    # rain (NOAA, what the app shows)
    try:
        l = read(ROOT / 'outputs/forecasts/precipitation/noaa-live/latest.json'); r = read(ROOT / l['path'])
        tot = np.array([[v or 0 for v in f['daily_precipitation_mm'][:7]] for f in r['forecasts']]).sum(1)
        yale = next(f for f in r['forecasts'] if f['id'] == 'yale-farm-new-haven')
        days = r['forecast_dates']; daily = np.array([[v or 0 for v in f['daily_precipitation_mm']] for f in r['forecasts']]).mean(0)
        wet = [days[i] for i in range(10) if daily[i] >= 2.54]
        rows.append(['Rain (NOAA)', 'Next 7 days: %.2f in statewide average (%.2f–%.2f across farms); Yale Farm %.2f in. Wetter days (0.1 in+): %s.' % (
            tot.mean() / 25.4, tot.min() / 25.4, tot.max() / 25.4, sum(v or 0 for v in yale['daily_precipitation_mm'][:7]) / 25.4,
            ', '.join(datetime.fromisoformat(d).strftime('%a %b %d') for d in wet) or 'none in the next 10 days')])
    except Exception as e: rows.append(['Rain (NOAA)', 'not available (%s)' % type(e).__name__])
    # streams and wells: the version the app shows
    for label, kinds in (('Streams', [('streamflow-v2-prospective', 'v2 with rain'), ('prospective', 'v1')]),
                         ('Neighboring-state streams', [('regional-streamflow-v2-prospective', 'v2 with rain'), ('regional-prospective', 'v1')]),
                         ('Wells', [('groundwater-v2-prospective', 'v2 with rain'), ('prospective', 'v1')])):
        kind = 'groundwater' if label == 'Wells' else 'streamflow'
        r = None
        for folder, tag in kinds:
            r = today_issue(folder, kind, day)
            if r: break
        if not r: rows.append([label, 'not issued yet today']); continue
        if kind == 'streamflow':
            ch = [(f['prediction'][6] / max(f['baseline'][0], 0.01), f['name']) for f in r['forecasts']]
            up = sum(c >= 1.25 for c, _ in ch); down = sum(c <= 0.8 for c, _ in ch); top = max(ch)
            rows.append([label, '%s, %d gauges: by day 7, %d expected to rise 25%%+ and %d to fall 20%%+; biggest rise %s (×%.1f).' % (
                tag, len(ch), up, down, top[1].title(), top[0])])
        else:
            ch = [f['prediction'][13] - f['baseline'][0] for f in r['forecasts']]
            rows.append([label, '%s, %d wells: in 14 days %d rising (water closer to the surface) and %d falling; average change %+.2f ft of depth.' % (
                tag, len(ch), sum(c < -0.05 for c in ch), sum(c > 0.05 for c in ch), float(np.mean(ch)))])
    r = today_issue('root-zone-prospective', 'root-zone', day)
    if r:
        a = np.mean([f['baseline'][0] for f in r['forecasts']]) * 100; b = np.mean([f['prediction'][13] for f in r['forecasts']]) * 100
        rows.append(['Soil moisture', '%d watersheds: %.1f%% water now (NASA data to %s), %.1f%% expected in 14 days.' % (len(r['forecasts']), a, r['forecasts'][0]['source_last_day'], b)])
    r = today_issue('fire-danger-prospective', 'fire-danger', day)
    if r:
        f = r['forecasts'][0]
        rows.append(['Fire danger', 'Next 7 days: ' + ', '.join('%s %s' % (datetime.fromisoformat(d).strftime('%a'), lv) for d, lv in zip(f['dates'][:7], f['levels'][:7])) + '.'])
    r = today_issue('water-temp-prospective', 'water-temp', day)
    if r:
        a = np.mean([f['baseline'][0] for f in r['forecasts']]) * 1.8 + 32; b = np.mean([f['prediction'][13] for f in r['forecasts']]) * 1.8 + 32
        rows.append(['Coastal water', '%d stations: %.1f °F now, %.1f °F expected in 14 days.' % (len(r['forecasts']), a, b)])
    for folder, label in (('drought-v2-prospective', 'Drought (v2, shown in app)'), ('drought-prospective', 'Drought (v1)')):
        r = today_issue(folder, 'drought', day)
        if r:
            ct = next((f for f in r['forecasts'] if f['id'] == 'CT'), None)
            hi = max(r['forecasts'], key=lambda f: f['chance_worse'][1])
            if ct: rows.append([label, 'Connecticut now %s (map of %s); maps of %s: %s, chance worse %d%% / %d%%. Highest chance worse by %s: %s %d%%.' % (
                ct['current_class'], ct['current_map'], ' and '.join(ct['dates']), ' / '.join(ct['dominant_class']), round(100 * ct['chance_worse'][0]), round(100 * ct['chance_worse'][1]),
                ct['dates'][1], hi['id'].split('|')[-1], round(100 * hi['chance_worse'][1]))])
    return dict(title="Today's forecasts", table=dict(head=['Model', 'Forecast'], rows=rows), notes=notes)


def scored(since):
    rows = []
    for name, folder, kind, unit, mult in LEDGERS:
        c = ro(ROOT / 'data' / folder / 'ledger.sqlite')
        if c is None: rows.append([name, '0', '–', '–', '–', 'no ledger yet']); continue
        q = c.execute('SELECT lead, absolute_error, baseline_error, day FROM scores WHERE variable=? AND scored_at>?', (kind, since)).fetchall()
        if not q: rows.append([name, '0', '–', '–', '–', 'waiting for measurements']); continue
        e = np.array([x[1] for x in q]); b = np.array([x[2] for x in q]); d1 = [x for x in q if x[0] == 1]
        days = sorted({x[3] for x in q})
        rows.append([name, '{:,}'.format(len(q)), '%s vs %s' % (fmt(e.mean() * mult), fmt(b.mean() * mult)),
                     '%s vs %s' % (fmt(np.mean([x[1] for x in d1]) * mult), fmt(np.mean([x[2] for x in d1]) * mult)) if d1 else '–',
                     '%d%%' % round(100 * np.mean(e < b)), '%s; target days %s' % (unit, days[0] if len(days) == 1 else days[0] + ' to ' + days[-1])])
    return dict(title='Newly measured: how earlier forecasts did', table=dict(head=['Model', 'New checks', 'Average miss (all days ahead) vs no change', 'Next-day miss vs no change', 'Closer than no change', 'Units, days covered'], rows=rows),
                notes=['"No change" assumes the last reading stays the same (for rain: the last 14 days\' average). Lower misses are better.',
                       'Checks count each location, day and forecast separately; nearby places share weather, so they are not independent.'])


def learning(since, day):
    import learning_daily as L
    rows = []; notes = []
    for name, cfg in L.MODELS.items():
        wpath = ROOT / 'data/learning' / name / 'weights.npz'
        if not wpath.exists(): continue
        # The weights each sealed learning forecast used are recorded in its sources.
        used = []
        c0 = ro(ROOT / 'data/learning' / name / 'ledger.sqlite')
        if c0 is not None:
            for iday, path in c0.execute('SELECT substr(issue_day,1,10), path FROM forecasts ORDER BY issued_at'):
                w = next((x['path'] for x in read(ROOT / path)['sources'] if x['path'].endswith('weights.npz')), None)
                if w: used.append((iday, ROOT / w))
        cur = [w for d_, w in used if d_ == day]; prev = [w for d_, w in used if d_ < day]
        now = np.load(cur[-1] if cur else wpath); before = np.load(prev[-1]) if prev else None
        s = cfg['scale']; nn = now['n']; trained = nn > 0
        unit = '% flow' if cfg['transform'] == 'log1p' else {'precipitation': 'mm', 'groundwater': 'ft', 'root-zone': 'm³/m³', 'fire-danger': 'classes', 'water-temp': '°C', 'drought': 'index pts'}.get(cfg['kind'], '')
        def nudge(z):
            v = s * z['w'][..., 0][z['n'] > 0]
            return v * 100 if cfg['transform'] == 'log1p' else v       # log-flow nudge ~ percent
        v = nudge(now)
        lessons_new = int(nn.sum() - (before['n'].sum() if before is not None and before['w'].shape == now['w'].shape else 0))
        # A new learning policy registered since yesterday's forecast means the weights were relearned from scratch.
        new_policy = [f for f in glob.glob(str(ROOT / 'data/learning' / name / 'model-v*.json'))
                      if Path(f).name != 'model-v1.json' and prev and read(f)['created_at'] > datetime.strptime(Path(prev[-1]).parent.name[:15], '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc).isoformat()]
        after_issue = bool(new_policy) and cur and read(new_policy[0])['created_at'] > datetime.strptime(Path(cur[-1]).parent.name[:15], '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc).isoformat()
        if after_issue:                                  # relearned after today's forecast: report the weights tomorrow will use
            now = np.load(wpath); nn = now['n']; trained = nn > 0; v = nudge(now)
        relearned = before is not None and (bool(new_policy) or before['w'].shape != now['w'].shape or before['n'].sum() > nn.sum())
        if relearned: lessons_new = int(nn.sum())
        change = ('relearned under %s%s' % (read(new_policy[0])['version'], ' after today\'s forecast; applies from tomorrow' if after_issue else '')) if new_policy else '–'
        if before is not None and not relearned and trained.any():
            ids_b = {k: i for i, k in enumerate(before['ids'])}; d = []
            for i, k in enumerate(now['ids']):
                j = ids_b.get(k)
                if j is not None: d.append(s * (now['w'][i, :, 0] - before['w'][j, :, 0]))
            d = np.abs(np.concatenate(d)) * (100 if cfg['transform'] == 'log1p' else 1) if d else np.array([0.0])
            change = 'median %s, largest %s' % (fmt(float(np.median(d[d > 0])) if (d > 0).any() else 0.0, 3), fmt(float(d.max()), 3))
        c = ro(ROOT / 'data/learning' / name / 'ledger.sqlite')
        comp = '–'
        if c is not None:
            q = c.execute('SELECT absolute_error, baseline_error FROM scores WHERE scored_at>?', (since,)).fetchall()
            if q:
                e = np.mean([x[0] for x in q]); b = np.mean([x[1] for x in q])
                cu = {'precipitation': 'mm', 'groundwater': 'ft', 'streamflow': 'cfs', 'root-zone': 'm³/m³', 'fire-danger': 'classes', 'water-temp': '°C', 'drought': 'index pts'}[cfg['kind']]
                comp = '%s vs %s %s, %d checks (%s)' % (fmt(e, 3), fmt(b, 3), cu, len(q), 'better' if e < b - 1e-9 else 'worse' if e > b + 1e-9 else 'same')
        rows.append([name, '{:,}'.format(lessons_new) + (' (relearned)' if relearned else ''), '{:,}'.format(int(nn.sum())),
                     ('%s median, %s mean, %s largest' % (fmt(float(np.median(v)), 3), fmt(float(np.mean(v)), 3), fmt(float(np.max(np.abs(v))), 3))) if trained.any() else 'no lessons yet',
                     change, unit, comp])
    return dict(title='Learning versions: what changed since yesterday', table=dict(head=['Learning version', 'New lessons', 'Total lessons', 'Correction now (nudge)', 'Change since yesterday', 'Nudge units', 'Newly scored: learning vs original (average miss)'], rows=rows),
                notes=['A lesson is one scored comparison of the original forecast with what was measured. The nudge is the typical amount the learning version now adds to (or, if negative, subtracts from) the original; for streams it is a percentage of flow.',
                       'Learning forecasts are compared with the frozen originals on exactly the same cases. Early on they are usually identical, because corrections only affect forecasts made after the lessons.'])


def to_markdown(rep):
    out = ['# Daily forecast report: %s' % datetime.fromisoformat(rep['date']).strftime('%A, %B %d, %Y'), '', '_Generated %s (Connecticut time)._' % rep['generated_local'], '']
    for s in rep['sections']:
        out += ['## ' + s['title'], '']
        t = s['table']
        out += ['| ' + ' | '.join(t['head']) + ' |', '|' + '---|' * len(t['head'])]
        out += ['| ' + ' | '.join(str(x).replace('|', '/') for x in r) + ' |' for r in t['rows']]
        out += [''] + ['_' + n + '_' for n in s.get('notes', [])] + ['']
    return '\n'.join(out)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc); day = str(now.astimezone(p.LOCAL).date())
    state_path = OUT / 'state.json'; state = read(state_path) if state_path.exists() else {}
    earlier = [v for k, v in state.items() if k < day]
    since = max(earlier) if earlier else (now - timedelta(hours=24)).isoformat()
    rep = dict(date=day, generated_at=now.isoformat(), generated_local=now.astimezone(p.LOCAL).strftime('%B %d, %Y %I:%M %p'), scored_since=since,
               sections=[run_status(day), forecasts(day), scored(since), learning(since, day)])
    save(OUT / (day + '.json'), rep); (OUT / (day + '.md')).write_text(to_markdown(rep), encoding='utf-8')
    save(OUT / 'latest.json', dict(date=day, json='outputs/daily-reports/%s.json' % day, markdown='outputs/daily-reports/%s.md' % day, generated_at=rep['generated_at']))
    state[day] = rep['generated_at']; save(state_path, state)
    log('Daily report written: outputs/daily-reports/%s.md' % day)
    print('outputs/daily-reports/%s.md' % day)


if __name__ == '__main__':
    main()
