"""Synthetic checks for the water temperature model; no real data."""
import unittest
from datetime import date, timedelta
import numpy as np
from water_temp_model import fit_normal, normal, features, design, fit, predict
from fetch_water_temp import daily_means, parse


def days(n, start=date(2015, 1, 1)): return [str(start + timedelta(days=k)) for k in range(n)]


class WaterTempTests(unittest.TestCase):
    def test_normal_cycle_recovers_a_seasonal_curve(self):
        d = days(3 * 365); p = np.array([2 * np.pi * (date.fromisoformat(x).timetuple().tm_yday - 1) / 365.2425 for x in d])
        t = 12 - 8 * np.cos(p)
        np.testing.assert_allclose(normal(fit_normal(d, t), d), t, atol=1e-6)

    def test_gaps_withhold_and_future_cannot_change_inputs(self):
        d = days(40); t = np.linspace(10, 14, 40); nv = np.full(40, 12.0)
        f = features(t, 30, nv, d); later = t.copy(); later[31:] = 99
        np.testing.assert_array_equal(f, features(later, 30, nv, d))
        gap = t.copy(); gap[30] = np.nan; self.assertIsNone(features(gap, 30, nv, d))
        thin = t.copy(); thin[25:29] = np.nan; self.assertIsNone(features(thin, 30, nv, d))

    def test_ridge_learns_departure_persistence(self):
        rng = np.random.default_rng(1); x = rng.normal(size=(400, 3)); y = 0.8 * x[:, 0] + rng.normal(scale=0.05, size=400)
        X = np.array([design(r, '2020-06-01') for r in x]); m = fit(X, y, 1.0)
        self.assertLess(np.mean(abs(predict(m, X) - y)), 0.1)

    def test_daily_mean_needs_twelve_hours_and_drops_spikes(self):
        from datetime import datetime, timezone
        base = datetime(2024, 7, 1, 5, tzinfo=timezone.utc)      # 1 AM Connecticut daylight time
        r = {base + timedelta(hours=k): 20.0 for k in range(12)}; r[base + timedelta(hours=12)] = 33.0   # spike > 5 C off median
        m = daily_means(r); self.assertAlmostEqual(m['2024-07-01'][0], 20.0)
        self.assertEqual(daily_means({base + timedelta(hours=k): 20.0 for k in range(11)}), {})

    def test_parse_handles_missing_marker_and_two_digit_years(self):
        text = '#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS  TIDE\n' \
               '2024 07 01 05 00 999 99.0 99.0 99.00 99.00 99.00 999 9999.0 999.0  21.4 999.0 99.0 99.00\n' \
               '2024 07 01 06 00 999 99.0 99.0 99.00 99.00 99.00 999 9999.0 999.0  99.0 999.0 99.0 99.00\n'
        self.assertEqual([w for _, w in parse(text)], [21.4])
        old = 'YY MM DD hh WD   WSPD GST  WVHT  DPD   APD  MWD  BAR    ATMP  WTMP  DEWP  VIS\n99 07 01 05 999 99.0 99.0 99.00 99.00 99.00 999 9999.0 999.0  18.0 999.0 99.0\n'
        self.assertEqual([(t.year, w) for t, w in parse(old)], [(1999, 18.0)])


if __name__ == '__main__':
    unittest.main()
