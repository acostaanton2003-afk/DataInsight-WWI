import copy
import json
import sys
from pathlib import Path
from decimal import Decimal

import pytest

from backend.app import predictions
from backend.app.config import Settings,load_settings


def summary_fixture():
    metrics=lambda mae:dict(mae=mae,rmse=20.5,smape=5.125)
    return dict(schema_version=1,metric=predictions.TARGET,input_sha256='a'*64,
        coverage=dict(observed_months=30,usable_months=30,observed_first='2013-01',observed_last='2015-06',
            complete_through='2015-06',excluded_months=[],final_first_invoice_date='2015-06-01',
            final_last_invoice_date='2015-06-30',final_calendar_end='2015-06-30',
            final_days_with_sales=20,final_has_invoice_on_calendar_end=True,coverage_note='private-path secret'),
        evaluation=dict(selected_model='moving_average_3',results={
            name:dict(selection=metrics(mae),holdout=metrics(mae+1)) for name,mae in [('naive',20),('moving_average_3',10.125),('ridge',15)]},
            design=dict(horizon=3,initial_train=24,selection_origins=1,selection_predictions_per_model=3,
                selection_last_target='2015-03',holdout_months=['2015-04','2015-05','2015-06'],criterion='selection_mae')),
        uncertainty=dict(method=predictions.UNCERTAINTY_METHOD,samples_per_horizon=1),
        forecasts=[dict(month=month,forecast='100.00',lower='90.00',upper='110.00',historical_abs_error_p90='10.00')
            for month in ['2015-07','2015-08','2015-09']])


@pytest.fixture
def artifact(tmp_path,monkeypatch,client):
    folder=tmp_path/'ml';folder.mkdir()
    monkeypatch.setattr(predictions,'ARTIFACT_ROOT',folder)
    path=folder/'resumen.json';path.write_text(json.dumps(summary_fixture()),encoding='utf-8')
    client.app.state.settings=Settings(forecast_path=str(path))
    return path


def test_contract_exact_decimals_and_no_heavy_import_or_database(client,artifact,monkeypatch):
    monkeypatch.setitem(sys.modules,'pandas',None);monkeypatch.setitem(sys.modules,'sklearn',None)
    monkeypatch.setattr('backend.app.database.read_connection',lambda *a,**k:pytest.fail('No DB on predictions'))
    response=client.get('/api/v1/predicciones/ventas')
    assert response.status_code==200
    data=response.json()
    assert data['selected_model']=='moving_average_3'
    assert data['backtesting']['mae']=='10.125'
    assert data['forecasts'][0]['forecast']=='100.00'
    assert data['completeness_verified'] is False
    assert 'private-path' not in response.text and 'secret' not in response.text
    assert str(artifact) not in response.text


@pytest.mark.parametrize('mutation',[
    lambda x:x.update(schema_version=2),
    lambda x:x.update(schema_version=True),
    lambda x:x.update(metric='ventas_con_impuestos'),
    lambda x:x['forecasts'][0].update(forecast=100.0),
    lambda x:x['forecasts'][0].update(month='2015-08'),
    lambda x:x['forecasts'][0].update(lower='120.00'),
    lambda x:x['forecasts'][0].update(historical_abs_error_p90='1.00'),
    lambda x:x['evaluation']['results']['moving_average_3']['selection'].update(smape=201),
    lambda x:x['evaluation'].update(selected_model='ridge'),
    lambda x:x['coverage'].update(usable_months=29),
    lambda x:x['coverage'].update(final_last_invoice_date='2015-06-29',final_has_invoice_on_calendar_end=False),
    lambda x:x['evaluation']['design'].update(holdout_months=['2015-03']),
])
def test_invalid_summary_controlled(client,artifact,mutation):
    data=summary_fixture();mutation(data);artifact.write_text(json.dumps(data),encoding='utf-8')
    response=client.get('/api/v1/predicciones/ventas')
    assert response.status_code==503
    assert str(artifact) not in response.text


@pytest.mark.parametrize('content',['{','{"schema_version":1,"schema_version":1}','{"schema_version":NaN}','[]'])
def test_corrupt_duplicate_nonfinite_json(client,artifact,content):
    artifact.write_text(content,encoding='utf-8')
    assert client.get('/api/v1/predicciones/ventas').status_code==503


def test_missing_and_oversized_artifact(client,artifact):
    artifact.unlink()
    assert client.get('/api/v1/predicciones/ventas').status_code==503
    artifact.write_bytes(b' '* (predictions.MAX_BYTES+1))
    assert client.get('/api/v1/predicciones/ventas').status_code==503


def test_cannot_read_external_or_select_client_path(client,artifact):
    client.app.state.settings=Settings(forecast_path=str(artifact.parent.parent/'resumen.json'))
    assert client.get('/api/v1/predicciones/ventas').status_code==503
    for params in ({'path':str(artifact)},{'run_id':'../../.env'}):
        assert client.get('/api/v1/predicciones/ventas',params=params).status_code==422
    assert client.post('/api/v1/predicciones/ventas').status_code==405


def test_large_decimal_stays_exact(client,artifact):
    data=summary_fixture();data['forecasts'][0].update(forecast='9007199254740993.01',lower='9007199254740983.01',upper='9007199254741003.01')
    artifact.write_text(json.dumps(data),encoding='utf-8')
    assert client.get('/api/v1/predicciones/ventas').json()['forecasts'][0]['forecast']=='9007199254740993.01'


def test_configuration_independent_and_repr_hidden(tmp_path):
    path=tmp_path/'.env';path.write_text('BACKEND_FORECAST_PATH=artifacts/machine_learning/run/resumen.json\nSUPABASE_DB_PASSWORD=secret',encoding='utf-8')
    settings=load_settings(path,environ={})
    assert settings.forecast_path.endswith('run/resumen.json')
    assert settings.database.password==''
    assert 'run/resumen.json' not in repr(settings)
    assert load_settings(path,environ={'BACKEND_FORECAST_PATH':'other'}).forecast_path=='other'
