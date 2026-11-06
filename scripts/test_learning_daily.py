"""Synthetic checks for the learning versions; never touches real ledgers."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
import numpy as np
from learning_daily import Weights, train, learned_rows, MODELS


def ledger(rows):
    c = sqlite3.connect(':memory:')
    c.execute('CREATE TABLE scores (forecast_sha TEXT, variable TEXT, location TEXT, day TEXT, lead INTEGER, predicted REAL, observed REAL, '
              'absolute_error REAL, baseline_error REAL, scored_at TEXT)')
    c.executemany('INSERT INTO scores VALUES (?,?,?,?,?,?,?,0,0,"")', rows)
    return c


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(); self.path = Path(self.dir.name) / 'w.npz'
        self.cfg = MODELS['groundwater']

    def tearDown(self): self.dir.cleanup()

    def test_starts_identical_to_original(self):
        w = Weights(self.path)
        rows = learned_rows(dict(forecasts=[dict(id='a', dates=['d'] * 14, prediction=[5.0] * 14)]), w, self.cfg)
        self.assertEqual(rows[0]['prediction'], [5.0] * 14); self.assertEqual(rows[0]['baseline'], [5.0] * 14)

    def test_learns_a_persistent_bias_for_that_location_and_day(self):
        # The original is always 0.4 ft too shallow at well a, forecast day 3.
        c = ledger([('s%d' % k, 'groundwater', 'a', '2026-11-%02d' % (k + 1), 3, 10.0, 10.4, ) for k in range(40)])
        w = Weights(self.path); self.assertEqual(train(w, c, 'groundwater', self.cfg), 40)
        self.assertAlmostEqual(w.apply('a', 3, 10.0, self.cfg['scale']), 10.4, delta=0.05)  # cautious start: ~90%+ after 40 days
        self.assertEqual(w.apply('a', 4, 10.0, self.cfg['scale']), 10.0)   # other forecast days untouched
        self.assertEqual(w.apply('b', 3, 10.0, self.cfg['scale']), 10.0)   # other locations untouched

    def test_each_comparison_is_learned_once_and_state_persists(self):
        c = ledger([('s', 'groundwater', 'a', '2026-11-04', 1, 10.0, 11.0)])
        w = Weights(self.path); train(w, c, 'groundwater', self.cfg); w.save(self.path)
        again = Weights(self.path); self.assertEqual(train(again, c, 'groundwater', self.cfg), 0)
        np.testing.assert_array_equal(again.w, w.w)
        c.execute('INSERT INTO scores VALUES ("t","groundwater","a","2026-11-05",1,10,11,0,0,"")')
        self.assertEqual(train(again, c, 'groundwater', self.cfg), 1)

    def test_other_variables_in_the_same_ledger_are_ignored(self):
        c = ledger([('s', 'streamflow', 'a', '2026-11-04', 1, 10.0, 99.0)])
        w = Weights(self.path); self.assertEqual(train(w, c, 'groundwater', self.cfg), 0)

    def test_bounds_and_log_space(self):
        cfg = MODELS['streamflow']
        c = ledger([('s%d' % k, 'streamflow', 'g', '2026-11-%02d' % (k + 1), 1, 100.0, 50.0) for k in range(60)])
        w = Weights(self.path); train(w, c, 'streamflow', cfg)
        y = learned_rows(dict(forecasts=[dict(id='g', dates=['d'], prediction=[100.0])]), w, cfg)[0]['prediction'][0]
        self.assertTrue(45 < y < 60)   # learned the halving in log space
        rz = MODELS['root-zone']; w2 = Weights(Path(self.dir.name) / 'r.npz')
        train(w2, ledger([('s%d' % k, 'root-zone', 'r', '2026-11-%02d' % (k + 1), 1, .98, 1.0) for k in range(60)]), 'root-zone', rz)
        self.assertLessEqual(learned_rows(dict(forecasts=[dict(id='r', dates=['d'], prediction=[.99])]), w2, rz)[0]['prediction'][0], 1.0)


if __name__ == '__main__':
    unittest.main()
