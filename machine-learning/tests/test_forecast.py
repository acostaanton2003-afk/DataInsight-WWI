"""Solo datos sintéticos; sin .env ni consultas reales."""
import copy
import json
import math
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch,MagicMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import pandas as pd
from wwi_forecast.data import ForecastError,validate_series,select_complete,input_hash,read_months
from wwi_forecast.modeling import FEATURES,feature_row,supervised,fit_model,predict_saved
from wwi_forecast.evaluation import metrics,evaluate,calibration,quantile90
from wwi_forecast.artifacts import ARTIFACTS,experiment,publish,load_model,local_path


def synthetic(n=41):
    rows=[]
    for i,period in enumerate(pd.period_range('2013-01',periods=n,freq='M')):
        rows.append(dict(anio=period.year,mes=period.month,
            importe=f'{100000+i*1000+(i%12)*200:.2f}',cantidad_facturas=10,
            primera_fecha=period.start_time.date(),ultima_fecha=period.end_time.date(),dias_con_ventas=20))
    return rows


class SeriesTests(unittest.TestCase):
    def test_valid_exact_decimal(self):
        frame=validate_series(synthetic())
        self.assertEqual(len(frame),41);self.assertIsInstance(frame.importe.iloc[0],Decimal)
        self.assertEqual(str(frame.index[-1]),'2016-05')

    def test_missing_wrong_count(self):
        with self.assertRaises(ForecastError):validate_series(synthetic()[:-1])

    def test_duplicate_gap_and_order(self):
        for mutate in ('duplicate','gap','order'):
            rows=synthetic()
            if mutate=='duplicate':rows[2]=rows[1]
            elif mutate=='gap':rows.pop(2)
            else:rows[2],rows[3]=rows[3],rows[2]
            with self.subTest(mutate=mutate),self.assertRaises(ForecastError):validate_series(rows,len(rows))

    def test_invalid_amounts(self):
        for value in [None,12.5,'NaN','Infinity','12.1','1e6']:
            rows=synthetic();rows[0]['importe']=value
            with self.subTest(value=value),self.assertRaises(ForecastError):validate_series(rows)

    def test_invalid_dates(self):
        for change in [dict(anio=None),dict(mes=13),dict(primera_fecha=date(2014,1,1)),dict(dias_con_ventas=32)]:
            rows=synthetic();rows[0].update(change)
            with self.subTest(change=change),self.assertRaises(ForecastError):validate_series(rows)

    def test_last_month_excluded_without_confirmation(self):
        rows=synthetic();rows[-1]['ultima_fecha']=date(2016,5,15)
        frame=validate_series(rows);usable,metadata=select_complete(frame)
        self.assertEqual(len(usable),40);self.assertEqual(metadata['excluded_months'],['2016-05'])
        self.assertFalse(metadata['final_has_invoice_on_calendar_end'])
        with self.assertRaises(ForecastError):select_complete(frame,'2016-05','Cierre declarado sin evidencia de final de mes')

    def test_explicit_closure_and_bad_confirmation(self):
        frame=validate_series(synthetic())
        usable,metadata=select_complete(frame,'2016-05','Cierre sintético declarado')
        self.assertEqual(len(usable),41);self.assertTrue(metadata['final_has_invoice_on_calendar_end'])
        for cutoff,note in [('2016-05',''),('2016-13','nota'),('2016-06','nota')]:
            with self.assertRaises(ForecastError):select_complete(frame,cutoff,note)

    def test_input_fingerprint(self):
        frame=validate_series(synthetic());changed=frame.copy();changed.iloc[0,changed.columns.get_loc('importe')]=Decimal('1.00')
        self.assertEqual(input_hash(frame),input_hash(frame.copy()))
        self.assertNotEqual(input_hash(frame),input_hash(changed))

    def test_read_errors_are_sanitized(self):
        from backend.app.database import DatabaseReadError
        with patch('backend.app.database.read_connection',side_effect=DatabaseReadError('secret')):
            with self.assertRaises(ForecastError) as context:read_months(settings=object())
        self.assertNotIn('secret',str(context.exception))


class ModelingTests(unittest.TestCase):
    def setUp(self):
        self.frame=validate_series(synthetic());self.values=[float(x) for x in self.frame.importe];self.periods=list(self.frame.index)

    def test_features_only_use_previous_values(self):
        X,y=supervised(self.values,self.periods)
        self.assertEqual(tuple(X.columns),FEATURES)
        self.assertEqual(X.iloc[0]['lag_1'],self.values[11]);self.assertEqual(X.iloc[0]['lag_12'],self.values[0])
        self.assertEqual(y[0],self.values[12])
        changed=list(self.values);changed[24:]=[999999.0]*len(changed[24:])
        X2,_=supervised(changed,self.periods)
        pd.testing.assert_frame_equal(X.iloc[:12],X2.iloc[:12])

    def test_scaler_fits_only_training_rows(self):
        model=fit_model('ridge',self.values[:24],self.periods[:24]);X,_=supervised(self.values[:24],self.periods[:24])
        for actual,expected in zip(model.pipeline.steps[0][1].mean_,X.mean(),strict=True):self.assertAlmostEqual(actual,expected)

    def test_recursive_baselines(self):
        model=fit_model('naive',self.values,self.periods)
        self.assertEqual(model.predict(),[self.values[-1]]*3)
        moving=fit_model('moving_average_3',self.values,self.periods).predict()
        self.assertAlmostEqual(moving[1],sum([*self.values[-2:],moving[0]])/3)

    def test_saved_json_predictions_match_fitted(self):
        for name in ('naive','moving_average_3','ridge'):
            with self.subTest(name=name):
                model=fit_model(name,self.values,self.periods)
                restored=predict_saved(json.loads(json.dumps(model.to_dict())))
                for a,b in zip(restored,model.predict(),strict=True):self.assertAlmostEqual(a,b,places=7)

    def test_invalid_model_horizon_history(self):
        with self.assertRaises(ForecastError):feature_row([1],self.periods[0],1)
        with self.assertRaises(ForecastError):fit_model('complex',self.values,self.periods)
        model=fit_model('ridge',self.values,self.periods)
        for horizon in (0,4):
            with self.assertRaises(ForecastError):model.predict(horizon)
        for payload in ({},dict(schema_version=1,name='ridge',history=[math.nan]*20,features=list(FEATURES),start='2013-01')):
            with self.assertRaises(ForecastError):predict_saved(payload)

    def test_metrics_zero_and_known_errors(self):
        self.assertEqual(metrics([0,0],[0,0]),dict(mae=0,rmse=0,smape=0))
        result=metrics([1,3],[2,2]);self.assertEqual(result['mae'],1);self.assertEqual(result['rmse'],1)
        self.assertAlmostEqual(metrics([0],[1])['smape'],200)
        self.assertTrue(math.isfinite(metrics([1e-12],[2e-12])['smape']))
        with self.assertRaises(ForecastError):metrics([],[])
        with self.assertRaises(ForecastError):metrics([1],[math.nan])

    def test_walk_forward_no_future_or_holdout_leak(self):
        with patch('wwi_forecast.evaluation.fit_model',wraps=fit_model) as fitter:
            evaluation=evaluate(self.values,self.periods)
            for call in fitter.call_args_list:self.assertLessEqual(len(call.args[1]),38)
        self.assertEqual(evaluation['design']['selection_origins'],12)
        for row in evaluation['records']:
            self.assertLess(pd.Period(row['origin']),pd.Period(row['month']))
            if row['split']=='selection':self.assertLess(pd.Period(row['month']),self.periods[-3])
        changed=self.values[:-3]+[99999999]*3
        second=evaluate(changed,self.periods)
        self.assertEqual(evaluation['selected_model'],second['selected_model'])
        for name in evaluation['results']:self.assertEqual(evaluation['results'][name]['selection'],second['results'][name]['selection'])
        self.assertEqual(calibration(evaluation),calibration(second))

    def test_small_series_stops(self):
        with self.assertRaises(ForecastError):evaluate(self.values[:29],self.periods[:29])

    def test_quantile(self):
        self.assertEqual(quantile90([10]*12),10)
        with self.assertRaises(ForecastError):quantile90([])


class ArtifactTests(unittest.TestCase):
    def test_reproducibility_forecasts_and_local_publication(self):
        output=experiment(synthetic(),complete_through='2016-05',coverage_note='Cierre sintético')
        summary,model,frame,records=output
        self.assertEqual([row['month'] for row in summary['forecasts']],['2016-06','2016-07','2016-08'])
        self.assertEqual(summary,experiment(synthetic(),complete_through='2016-05',coverage_note='Cierre sintético')[0])
        for row in summary['forecasts']:
            self.assertLessEqual(Decimal(row['lower']),Decimal(row['forecast']));self.assertGreaterEqual(Decimal(row['upper']),Decimal(row['forecast']))
        ARTIFACTS.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix='ml-test-',dir=ARTIFACTS) as folder:
            first=publish(*output,output_root=folder);second=publish(*output,output_root=folder)
            self.assertNotEqual(first,second)
            self.assertEqual(load_model(first),summary['forecasts'])
            self.assertEqual((first/'resumen.json').read_bytes(),(second/'resumen.json').read_bytes())
            self.assertEqual(len(list(first.iterdir())),5)

    def test_no_outputs_outside_ignored_artifacts(self):
        with self.assertRaises(ForecastError):local_path(Path(__file__).resolve().parents[2]/'published')
        with self.assertRaises(ForecastError):load_model(ARTIFACTS/'nonexistent-ml-run')


if __name__=='__main__':unittest.main()
