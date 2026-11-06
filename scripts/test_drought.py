"""Synthetic checks for the combined drought model; no real data."""
import unittest
import numpy as np
from train_drought import finish, dsci, category, fit_logistic, prob, auc, events
from drought_features import palmer_on, rain_between


class DroughtTests(unittest.TestCase):
    def test_class_is_most_severe_category_covering_half(self):
        self.assertEqual(category(np.array([.9, .6, .4, 0, 0])), 2)       # D1 covers 60% -> D1
        self.assertEqual(category(np.array([.3, 0, 0, 0, 0])), 0)          # D0 under half -> None
        self.assertEqual(dsci(np.array([1, 1, 1, 0, 0])), 300)

    def test_results_stay_ordered_bounded_and_respect_deadband(self):
        cur = np.array([.5, .2, 0, 0, 0])
        y = finish(cur, np.array([.7, .9, .1, -.2, 0]))
        self.assertTrue(np.all(np.diff(y) <= 0) and y.min() >= 0 and y.max() <= 1)
        np.testing.assert_array_equal(finish(cur, np.array([.01, 0, 0, 0, 0]), deadband=5), cur)

    def test_logistic_learns_and_auc_ranks(self):
        rng = np.random.default_rng(3); x = rng.normal(size=(800, 2)); y = (x[:, 0] + rng.normal(scale=.5, size=800) > 1).astype(float)
        m = fit_logistic(x, y, 1.0); p = prob(m, x)
        self.assertGreater(auc(p, y), 0.9); self.assertAlmostEqual(auc(np.array([.1, .9]), np.array([0, 1])), 1.0)

    def test_events_and_palmer_publication_lag(self):
        self.assertEqual(events(dict(cur=np.array([0, 0, 0, 0, 0.]), y=np.array([1, .6, 0, 0, 0.]))), (1.0, 0.0))
        pal = {'2026-08': {'pdsi': -1}, '2026-09': {'pdsi': 1}}
        self.assertEqual(palmer_on(pal, '2026-10-09')['pdsi'], -1)          # September not published until Oct 10
        self.assertEqual(palmer_on(pal, '2026-10-10')['pdsi'], 1)

    def test_rain_window_needs_most_days(self):
        rain = {'2026-01-0%d' % d: 0.1 for d in range(1, 9)}
        self.assertAlmostEqual(rain_between(rain, '2026-01-01', '2026-01-08'), 0.8)
        self.assertIsNone(rain_between({'2026-01-01': 1.0}, '2026-01-01', '2026-01-08'))


if __name__ == '__main__':
    unittest.main()
