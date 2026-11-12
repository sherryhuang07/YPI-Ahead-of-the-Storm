"""Synthetic checks for the rain-aware v2 stream and well models; no real data."""
import unittest
import numpy as np
from site_rain import window_sum, normal_by_month
from rain_models_daily import ahead
import train_streamflow_rain as sf
import train_groundwater_rain as gw
from datetime import date


class RainModelTests(unittest.TestCase):
    def test_window_sum_never_treats_missing_as_zero(self):
        r = np.array([1.0, 2.0, np.nan, 4.0])
        self.assertEqual(window_sum(r, 1, 2), 3.0)
        self.assertTrue(np.isnan(window_sum(r, 3, 2)))
        self.assertTrue(np.isnan(window_sum(r, 0, 2)))          # window starts before the record

    def test_rain_ahead_stops_at_noaa_reach(self):
        r = np.ones(60); i = 10
        f14 = sf.rain_features(r, i, 14); f10 = sf.rain_features(r, i, 10)
        self.assertEqual(f14[4:], f10[4:])                       # rain after day 10 is not an input
        self.assertAlmostEqual(f10[4], np.log1p(10.0)); self.assertAlmostEqual(f10[5], np.log1p(3.0))
        self.assertEqual(gw.rain_features(r, i, 15)[3:], gw.rain_features(r, i, 10)[3:])

    def test_live_uses_typical_inputs_when_forecast_rain_is_missing(self):
        r = np.ones(30); src = ['station'] * 20 + ['NOAA NBM'] * 5 + ['normal'] * 5
        vals, note = ahead(r, src, 19, 5, np.array([9.0, 9.0]), 10)
        self.assertAlmostEqual(vals[0], np.log1p(5.0)); self.assertIn('NOAA NBM', note)
        vals, note = ahead(r, src, 19, 8, np.array([9.0, 9.0]), 10)     # window reaches a 'normal' day
        self.assertEqual(list(vals), [9.0, 9.0]); self.assertIn('typical', note)

    def test_saved_noaa_forecasts_newest_wins_and_never_from_today(self):
        import json, tempfile, site_rain
        from pathlib import Path
        old = site_rain.D
        with tempfile.TemporaryDirectory() as t:
            site_rain.D = Path(t); a = Path(t) / 'nbm-archive' / 'x'; a.mkdir(parents=True)
            (a / '2026-11-09.json').write_text(json.dumps({'g': {'2026-11-10': 5.0, '2026-11-11': 1.0}}))
            (a / '2026-11-10.json').write_text(json.dumps({'g': {'2026-11-11': 2.0}}))
            (a / '2026-11-12.json').write_text(json.dumps({'g': {'2026-11-11': 9.0}}))   # today's own file: ignored
            got = site_rain.saved_nbm('x', date(2026, 11, 12))
            site_rain.D = old
        self.assertEqual(got['g'], {'2026-11-10': 5.0, '2026-11-11': 2.0})

    def test_monthly_normal(self):
        start = date(2000, 1, 1); s = np.array([1.0 if (start.toordinal() + i) % 2 else 3.0 for i in range(800)])
        n = normal_by_month(s, start)
        self.assertAlmostEqual(n[1], 2.0, delta=0.1)


if __name__ == '__main__':
    unittest.main()
