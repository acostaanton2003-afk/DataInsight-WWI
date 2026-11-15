"""Pocos parámetros fijos. Cada origen se entrena únicamente con su pasado."""
import math
from dataclasses import dataclass
from statistics import fmean

import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .data import ForecastError

NAMES=('naive','moving_average_3','ridge')
FEATURES=('trend','month_sin','month_cos','lag_1','lag_2','lag_3','lag_12','mean_previous_3')
LAG=12


def feature_row(history,period,position):
    if len(history)<LAG:raise ForecastError('Faltan rezagos históricos.')
    angle=2*math.pi*period.month/12
    return [float(position),math.sin(angle),math.cos(angle),history[-1],history[-2],history[-3],history[-12],fmean(history[-3:])]


def supervised(values,periods):
    if len(values)!=len(periods) or len(values)<=LAG:
        raise ForecastError('Historia insuficiente o fechas desalineadas.')
    X=[feature_row(values[:i],periods[i],i) for i in range(LAG,len(values))]
    return pd.DataFrame(X,columns=FEATURES),list(values[LAG:])


@dataclass
class FittedModel:
    name: str
    history: list[float]
    start: str
    pipeline: object=None

    def predict(self,horizon=3):
        if type(horizon) is not int or not 1<=horizon<=3:
            raise ForecastError('Horizonte experimental permitido: 1 a 3 meses.')
        history=list(self.history); result=[]
        for _ in range(horizon):
            period=pd.Period(self.start,freq='M')+len(history)
            if self.name=='naive':value=history[-1]
            elif self.name=='moving_average_3':value=fmean(history[-3:])
            elif self.name=='ridge':
                X=pd.DataFrame([feature_row(history,period,len(history))],columns=FEATURES)
                value=float(self.pipeline.predict(X)[0])
            else:raise ForecastError('Modelo desconocido.')
            if not math.isfinite(value):raise ForecastError('Predicción no finita.')
            result.append(value);history.append(value)
        return result

    def to_dict(self):
        payload=dict(schema_version=1,name=self.name,history=self.history,start=self.start,features=list(FEATURES))
        if self.name=='ridge':
            scaler,regressor=self.pipeline.steps[0][1],self.pipeline.steps[1][1]
            payload['ridge']=dict(mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),
                coefficients=regressor.coef_.tolist(),intercept=float(regressor.intercept_),alpha=10.0)
        return payload


def fit_model(name,values,periods):
    if name not in NAMES or len(values)<LAG+1 or len(values)!=len(periods):
        raise ForecastError('Modelo o historia de entrenamiento inválidos.')
    if not all(math.isfinite(float(x)) for x in values):raise ForecastError('Importes no finitos.')
    pipeline=None
    if name=='ridge':
        X,y=supervised(values,periods)
        pipeline=make_pipeline(StandardScaler(),Ridge(alpha=10.0,solver='svd'))
        pipeline.fit(X,y)
    return FittedModel(name,list(values),str(periods[0]),pipeline)


def predict_saved(payload,horizon=3):
    # Modelo JSON, nunca se carga pickle/joblib ni código serializado.
    try:
        if payload['schema_version']!=1 or payload['name'] not in NAMES or payload['features']!=list(FEATURES):raise ValueError
        history=payload['history']
        if not isinstance(history,list) or len(history)<LAG+1 or len(history)>10000:raise ValueError
        if not all(type(v) in (int,float) and math.isfinite(v) for v in history):raise ValueError
        start=pd.Period(payload['start'],freq='M')
        if type(horizon) is not int or not 1<=horizon<=3:raise ValueError
        ridge=payload.get('ridge')
        if payload['name']=='ridge':
            for key in ('mean','scale','coefficients'):
                if len(ridge[key])!=len(FEATURES) or not all(math.isfinite(v) for v in ridge[key]):raise ValueError
            if not all(v>0 for v in ridge['scale']) or not math.isfinite(ridge['intercept']):raise ValueError
        history=list(history); predictions=[]
        for _ in range(horizon):
            if payload['name']=='naive':value=history[-1]
            elif payload['name']=='moving_average_3':value=fmean(history[-3:])
            else:
                row=feature_row(history,start+len(history),len(history))
                value=ridge['intercept']+sum((v-m)/s*c for v,m,s,c in zip(row,ridge['mean'],ridge['scale'],ridge['coefficients'],strict=True))
            if not math.isfinite(value):raise ValueError
            predictions.append(float(value));history.append(float(value))
        return predictions
    except (KeyError,TypeError,ValueError,OverflowError):
        raise ForecastError('Modelo JSON inválido o incompatible.') from None
