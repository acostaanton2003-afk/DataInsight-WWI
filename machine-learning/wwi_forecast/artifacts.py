"""Artefactos JSON/CSV locales, sin código ejecutable serializado."""
import json
import math
import os
import platform
import uuid
import hashlib
from importlib.metadata import version
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_EVEN
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import sklearn
from threadpoolctl import threadpool_limits

from .data import ForecastError,input_hash,select_complete,validate_series
from .evaluation import evaluate,calibration
from .modeling import fit_model,predict_saved

ROOT=Path(__file__).resolve().parents[2]
ARTIFACTS=ROOT/'artifacts'


def local_path(path):
    resolved=Path(path).resolve()
    if not resolved.is_relative_to(ARTIFACTS.resolve()):
        raise ForecastError('Los modelos/resultados deben permanecer dentro de artifacts/.')
    return resolved


def money(value):
    if not math.isfinite(float(value)):raise ForecastError('Resultado no finito.')
    return str(Decimal(str(value)).quantize(Decimal('0.01'),rounding=ROUND_HALF_EVEN))


def forecasts(payload):
    predictions=predict_saved(payload)
    first=pd.Period(payload['start'],freq='M')+len(payload['history'])
    rows=[]
    for h,prediction in enumerate(predictions,1):
        try:width=payload['uncertainty_abs_p90'][str(h)]
        except (KeyError,TypeError):raise ForecastError('Falta calibración de incertidumbre.') from None
        if type(width) not in (int,float) or not math.isfinite(width) or width<0:
            raise ForecastError('Incertidumbre inválida.')
        rows.append(dict(month=str(first+h-1),forecast=money(prediction),
            lower=money(prediction-width),upper=money(prediction+width),historical_abs_error_p90=money(width)))
    return rows


def experiment(rows,expected_months=41,complete_through=None,coverage_note=''):
    frame=validate_series(rows,expected_months)
    usable,coverage=select_complete(frame,complete_through,coverage_note)
    values=[float(v) for v in usable.importe]
    with threadpool_limits(limits=1):
        evaluation=evaluate(values,list(usable.index))
        model=fit_model(evaluation['selected_model'],values,list(usable.index)).to_dict()
    model['uncertainty_abs_p90']=calibration(evaluation)
    model['input_sha256']=input_hash(frame)
    summary=dict(schema_version=1,source='dwh vía BACKEND_DB_* / wwi_backend_reader / SELECT',
        metric='SUM(ventas_sin_impuestos), is_credit_note=false; moneda no verificada',
        input_sha256=input_hash(frame),coverage=coverage,
        code_sha256=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.glob('*.py')))).hexdigest(),
        environment=dict(python=platform.python_version(),pandas=pd.__version__,scikit_learn=sklearn.__version__,
            numpy=version('numpy'),scipy=version('scipy'),threadpoolctl=version('threadpoolctl')),
        config=dict(ridge_alpha=10.0,ridge_solver='svd',moving_average_window=3,
            features=model['features'],clip_negative_forecasts=False,threads=1),
        evaluation={k:v for k,v in evaluation.items() if k!='records'},
        uncertainty=dict(method='Percentil 90 de error absoluto por horizonte del backtesting de selección',
            samples_per_horizon=evaluation['design']['selection_origins'],
            limitation='Banda descriptiva simétrica; no intervalo de confianza ni garantía de cobertura. No se recorta a cero.'),
        forecasts=forecasts(model))
    return summary,model,frame,evaluation['records']


def publish(summary,model,frame,records,output_root=None):
    base=local_path(output_root or ARTIFACTS/'machine_learning')
    base.mkdir(parents=True,exist_ok=True)
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]
    destination=base/run_id
    with TemporaryDirectory(prefix='.tmp-',dir=base) as temporary:
        staging=Path(temporary)
        for filename,value in [('resumen.json',summary),('modelo.json',model)]:
            (staging/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        frame.to_csv(staging/'serie_observada.csv',index=False,encoding='utf-8-sig')
        pd.DataFrame(records).to_csv(staging/'backtesting.csv',index=False,encoding='utf-8-sig')
        pd.DataFrame(summary['forecasts']).to_csv(staging/'pronosticos.csv',index=False,encoding='utf-8-sig')
        os.rename(staging,destination)  # Destino único, misma unidad; no sobrescribe.
    return destination


def load_model(run_dir):
    path=local_path(Path(run_dir)/'modelo.json')
    try:payload=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):raise ForecastError('No se pudo leer el modelo JSON local.') from None
    return forecasts(payload)
