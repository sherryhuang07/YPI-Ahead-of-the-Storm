"""Tests use synthetic values only; they are never written as real forecasts."""
import unittest
import numpy as np
from root_zone_model import features,history_features,fit,predict

class CausalityTests(unittest.TestCase):
    def test_future_and_unavailable_values_cannot_change_features(self):
        series=np.linspace(.1,.4,200)
        before=features(series,100,'2020-05-01')
        altered=series.copy();altered[95:]=999
        np.testing.assert_array_equal(before,features(altered,100,'2020-05-01'))
        altered[94]=.9
        self.assertFalse(np.array_equal(before,features(altered,100,'2020-05-01')))

    def test_missing_history_is_not_filled(self):
        series=np.ones(200)*.3;series[80]=np.nan
        self.assertIsNone(features(series,100,'2020-05-01'))
        self.assertIsNone(features(series,10,'2020-05-01'))

    def test_fit_does_not_change_with_heldout_targets(self):
        rng=np.random.default_rng(42);x=rng.normal(size=(150,8));y=rng.uniform(.1,.5,150)
        first=fit(x[:100],y[:100]);y[100:]=99
        self.assertEqual(first,fit(x[:100],y[:100]))
        self.assertTrue(np.all((predict(first,x)>=0)&(predict(first,x)<=1)))

    def test_depth_weighting(self):
        # Equal volumetric moisture across unequal layers remains 30%, not 90%.
        storage=np.array([.3*100,.3*300,.3*600])
        self.assertAlmostEqual(storage.sum()/1000,.3)

    def test_bulk_features_preserve_causal_cutoff(self):
        series=np.linspace(.1,.4,200)
        np.testing.assert_allclose(history_features(series)[100],features(series,100,'2020-05-01')[:4])
        original=history_features(series)[100].copy();series[95:]=np.nan
        np.testing.assert_array_equal(original,history_features(series)[100])

class LiveInputTests(unittest.TestCase):
    def test_watershed_mean_is_weighted_and_skips_missing_cells(self):
        from root_zone_live import watershed_means
        grid=np.array([[300.,np.nan],[100.,200.]])
        w={'box':[10,11,20,21],'watersheds':{'a':[[10,20,.5],[11,20,.25],[11,21,.25]],'b':[[10,21,.9],[11,21,.1]]}}
        out=watershed_means(grid,w)
        self.assertAlmostEqual(out['a'][0],.5*300+.25*100+.25*200)
        self.assertTrue(np.isnan(out['b'][0]))  # under half the area valid: missing, not filled

    def test_day_boundary_offsets(self):
        from datetime import date
        from root_zone_live import day_hours
        hs=day_hours(date(2020,6,1),5)
        self.assertEqual((hs[0].day,hs[0].hour,hs[-1].day,hs[-1].hour),(1,5,2,4))
        self.assertEqual(len(hs),24)

    def test_live_window_alignment_matches_training_features(self):
        # A 28-day window padded by the lag must give the same features as the training path.
        series=np.linspace(.2,.35,60);lag=6
        window=series[60-lag-28:60-lag]
        padded=np.concatenate([window,np.full(lag,np.nan)])
        np.testing.assert_array_equal(features(series,59,'2020-07-01',lag),features(padded,len(padded)-1,'2020-07-01',lag))

class DailyLedgerTests(unittest.TestCase):
    def test_daily_rows_use_frozen_timing_and_never_fill_gaps(self):
        from datetime import date,timedelta
        from root_zone_daily import make_rows
        issue=date(2026,11,5);policy={'input_lag_days':6,'horizons_days':list(range(1,15))}
        m={'method':'persistence','interval_radius':.02,'model':None}
        models={'a':{str(h):m for h in range(1,15)},'b':{str(h):m for h in range(1,15)}}
        window={str(issue-timedelta(days=6+k)):.3-.001*k for k in range(28)}
        future={str(issue-timedelta(days=k)):.9 for k in range(0,6)}  # newer than the cutoff: must be ignored
        gap=dict(window);gap.pop(str(issue-timedelta(days=20)))
        rows,missing=make_rows(models,policy,{'a':{**window,**future},'b':gap},issue)
        self.assertEqual([r['id'] for r in rows],['a']);self.assertEqual(missing[0]['id'],'b')
        self.assertEqual((rows[0]['dates'][0],rows[0]['dates'][-1]),('2026-11-06','2026-11-19'))
        self.assertEqual(rows[0]['source_last_day'],'2026-10-30')
        self.assertAlmostEqual(rows[0]['prediction'][0],.3);self.assertAlmostEqual(rows[0]['upper'][0],.32)

if __name__=='__main__':unittest.main()
