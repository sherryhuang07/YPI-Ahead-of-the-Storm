"""Checks for the 1964 NFDRS translation and DEEP's class table (synthetic inputs only)."""
import unittest
from datetime import date
from fire_danger_model import danger, rating, wet_bulb_f, herb_stage, A, B, C, LEVELS


class DangerTests(unittest.TestCase):
    def test_fine_fuel_moisture_is_continuous_at_regime_breaks(self):
        import math
        for k, c in enumerate(C):
            left = B[k] * math.exp(A[k] * c); right = B[k + 1] * math.exp(A[k + 1] * c)
            self.assertLess(abs(left - right) / left, 0.02, 'break %.1f F' % c)

    def test_snow_zeroes_spread_and_rain_still_reduces_buildup(self):
        r = danger(40, 35, True, 0.6, 10, 60, 1)
        self.assertEqual((r['grass'], r['timber'], r['fload']), (0.0, 0.0, 0.0))
        self.assertLess(r['bui'], 60)
        self.assertEqual(danger(40, 35, True, 0.05, 10, 60, 1)['bui'], 60)   # 0.1 inch threshold

    def test_rain_resets_buildup_and_drying_adds(self):
        wet = danger(60, 58, False, 2.0, 5, 80, 1); dry = danger(80, 55, False, 0.0, 5, 80, 1)
        self.assertLess(wet['bui'], 30); self.assertGreater(dry['bui'], 80)
        self.assertGreaterEqual(dry['df'], 1)

    def test_dry_windy_spring_day_is_extreme_and_humid_calm_day_low(self):
        d = danger(85, 55, False, 0.0, 22, 40, 1)
        self.assertGreaterEqual(d['timber'], 40); self.assertEqual(LEVELS[rating(d['timber'], d['bui'])], 'EXTREME')
        h = danger(55, 54, False, 0.0, 3, 5, 3)
        self.assertEqual(LEVELS[rating(h['timber'], h['bui'])], 'LOW')

    def test_green_vegetation_lowers_spread(self):
        cured = danger(75, 58, False, 0, 10, 30, 1)['timber']; green = danger(75, 58, False, 0, 10, 30, 3)['timber']
        self.assertGreater(cured, green)

    def test_deep_class_table_boundaries(self):
        self.assertEqual([LEVELS[rating(s, 0, 'spread')] for s in (10, 11, 15, 16, 29, 30, 39, 40)],
                         ['LOW', 'MODERATE', 'MODERATE', 'HIGH', 'HIGH', 'VERY HIGH', 'VERY HIGH', 'EXTREME'])
        self.assertEqual([LEVELS[rating(0, b, 'buildup')] for b in (22, 23, 44, 45, 59, 60, 74, 75)],
                         ['LOW', 'MODERATE', 'MODERATE', 'HIGH', 'HIGH', 'VERY HIGH', 'VERY HIGH', 'EXTREME'])

    def test_wet_bulb_and_herb_calendar(self):
        self.assertAlmostEqual(wet_bulb_f(70, 70), 70, delta=1.0)
        self.assertTrue(50 < wet_bulb_f(70, 40) < 58)
        self.assertEqual([herb_stage(date(2025, m, 15)) for m in (3, 5, 7, 10, 12)], [1, 2, 3, 2, 1])


if __name__ == '__main__':
    unittest.main()
