"""Walk-forward a tres pasos; tres meses finales separados de la selección."""
import math
from statistics import fmean

from sklearn.metrics import mean_absolute_error, mean_squared_error

from .data import ForecastError
from .modeling import NAMES,fit_model

HORIZON=3
INITIAL_TRAIN=24


def metrics(actual,predicted):
    if not actual or len(actual)!=len(predicted) or not all(math.isfinite(float(x)) for x in [*actual,*predicted]):
        raise ForecastError('Métricas requieren pares finitos no vacíos.')
    errors=[0.0 if abs(a)+abs(p)==0 else 200*abs(a-p)/(abs(a)+abs(p)) for a,p in zip(actual,predicted,strict=True)]
    return dict(mae=float(mean_absolute_error(actual,predicted)),
                rmse=math.sqrt(float(mean_squared_error(actual,predicted))),smape=fmean(errors))


def evaluate(values,periods):
    n=len(values)
    if n<INITIAL_TRAIN+2*HORIZON or n!=len(periods):
        raise ForecastError('Se requieren al menos 30 meses completos para selección y prueba final.')
    # Todos los objetivos de selección son anteriores al primer mes del holdout.
    origins=list(range(INITIAL_TRAIN,n-2*HORIZON+1))
    results={}; records=[]
    for name in NAMES:
        errors=[]
        for origin in origins:
            fitted=fit_model(name,values[:origin],periods[:origin])
            predictions=fitted.predict(HORIZON)
            for h,prediction in enumerate(predictions,1):
                index=origin+h-1
                errors.append(dict(model=name,origin=str(periods[origin-1]),month=str(periods[index]),
                    horizon=h,actual=values[index],prediction=prediction))
        results[name]=dict(selection=metrics([r['actual'] for r in errors],[r['prediction'] for r in errors]),
            selection_by_horizon={str(h):metrics([r['actual'] for r in errors if r['horizon']==h],
                [r['prediction'] for r in errors if r['horizon']==h]) for h in range(1,HORIZON+1)})
        origin=n-HORIZON
        predictions=fit_model(name,values[:origin],periods[:origin]).predict(HORIZON)
        results[name]['holdout']=metrics(values[origin:],predictions)
        records.extend([{**r,'split':'selection'} for r in errors])
        records.extend(dict(model=name,origin=str(periods[origin-1]),month=str(periods[origin+h-1]),
            horizon=h,actual=values[origin+h-1],prediction=p,split='holdout') for h,p in enumerate(predictions,1))
    # Orden fijo de candidatos para desempates; jamás se selecciona con holdout.
    selected=min(NAMES,key=lambda name:results[name]['selection']['mae'])
    best_base=min(NAMES[:2],key=lambda name:results[name]['selection']['mae'])
    baseline=results[best_base]['selection']['mae'];chosen=results[selected]['selection']['mae']
    improvement=0.0 if baseline==0 else 100*(baseline-chosen)/baseline
    warnings=['Serie corta: resultados experimentales, no aptos para decisiones automáticas.',
              'Ventanas solapadas: errores correlacionados; no equivalen a muestras independientes.',
              'La selección utiliza backtesting: la mejora puede ser optimista y debe confirmarse en datos nuevos.']
    if selected!='ridge' or improvement<10:
        warnings.append('Ningún modelo ofrece mejora convincente frente a la mejor base (umbral descriptivo 10% MAE).')
    if results[selected]['holdout']['mae']>min(results[name]['holdout']['mae'] for name in NAMES[:2]):
        warnings.append('El modelo seleccionado no supera la mejor base en la prueba final; no cambiarlo usando ese resultado.')
    return dict(results=results,selected_model=selected,best_baseline=best_base,
        improvement_vs_best_baseline_pct=improvement,warnings=warnings,
        design=dict(horizon=HORIZON,initial_train=INITIAL_TRAIN,selection_origins=len(origins),
            selection_predictions_per_model=len(origins)*HORIZON,
            selection_last_target=str(periods[n-HORIZON-1]),
            holdout_months=[str(p) for p in periods[n-HORIZON:]],criterion='selection_mae'),
        records=records)


def quantile90(values):
    values=sorted(values)
    if not values or not all(math.isfinite(v) and v>=0 for v in values):
        raise ForecastError('Errores históricos inválidos para incertidumbre.')
    position=(len(values)-1)*0.9;low=math.floor(position);high=math.ceil(position)
    return values[low]+(values[high]-values[low])*(position-low)


def calibration(evaluation):
    selected=evaluation['selected_model']
    return {str(h):quantile90([abs(r['actual']-r['prediction']) for r in evaluation['records']
        if r['model']==selected and r['split']=='selection' and r['horizon']==h]) for h in range(1,HORIZON+1)}
