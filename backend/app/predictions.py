"""Lectura acotada de resumen ML: stdlib + Pydantic; sin modelos ni red."""
import calendar
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated,Literal

from pydantic import BaseModel,ConfigDict,Field,PlainSerializer,ValidationError,field_validator,model_validator

from backend.app.config import ROOT

ARTIFACT_ROOT=ROOT/'artifacts'/'machine_learning'
MAX_BYTES=256*1024
ModelName=Literal['naive','moving_average_3','ridge']
Month=Annotated[str,Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')]
Amount=Annotated[str,Field(pattern=r'^-?\d+\.\d{2}$',max_length=64)]
Metric=Annotated[Decimal,Field(ge=0,allow_inf_nan=False,max_digits=64,decimal_places=32),PlainSerializer(lambda v:format(v,'f'),return_type=str,when_used='json')]
TARGET='SUM(ventas_sin_impuestos), is_credit_note=false; moneda no verificada'
UNCERTAINTY_METHOD='Percentil 90 de error absoluto por horizonte del backtesting de selección'


def ordinal(month):
    year,number=map(int,month.split('-'))
    if not 1<=year<=9999:raise ValueError('Año inválido')
    return year*12+number-1


def month_at(index):
    year,month=divmod(index,12)
    return f'{year:04d}-{month+1:02d}'


class Metrics(BaseModel):
    mae: Metric
    rmse: Metric
    smape: Annotated[Metric,Field(le=200)]


class Forecast(BaseModel):
    month: Month
    forecast: Amount
    lower: Amount
    upper: Amount
    historical_abs_error_p90: Amount

    @model_validator(mode='after')
    def bounds(self):
        if not Decimal(self.lower)<=Decimal(self.forecast)<=Decimal(self.upper) or Decimal(self.historical_abs_error_p90)<0:
            raise ValueError('Bandas inválidas')
        # Límites publicados se redondean por separado: permitir hasta 0.02.
        width=Decimal(self.historical_abs_error_p90)
        if abs(Decimal(self.forecast)-Decimal(self.lower)-width)>Decimal('0.02') or abs(Decimal(self.upper)-Decimal(self.forecast)-width)>Decimal('0.02'):
            raise ValueError('Bandas incompatibles con el error histórico')
        return self


class Coverage(BaseModel):
    observed_months: Annotated[int,Field(strict=True,ge=30,le=600)]
    usable_months: Annotated[int,Field(strict=True,ge=30,le=600)]
    observed_first: Month
    observed_last: Month
    complete_through: Month
    excluded_months: list[Month]
    final_first_invoice_date: date
    final_last_invoice_date: date
    final_days_with_sales: Annotated[int,Field(strict=True,ge=1,le=31)]
    final_calendar_end: date
    final_has_invoice_on_calendar_end: bool = Field(strict=True)

    @model_validator(mode='after')
    def consistency(self):
        first,last,cutoff=map(ordinal,(self.observed_first,self.observed_last,self.complete_through))
        if last-first+1!=self.observed_months or cutoff-first+1!=self.usable_months or not first<=cutoff<=last:
            raise ValueError('Cobertura inconsistente')
        if self.excluded_months!=[month_at(i) for i in range(cutoff+1,last+1)]:raise ValueError('Exclusiones inconsistentes')
        year,month=map(int,self.observed_last.split('-'))
        end=date(year,month,calendar.monthrange(year,month)[1])
        if self.final_calendar_end!=end or not date(year,month,1)<=self.final_first_invoice_date<=self.final_last_invoice_date<=end:
            raise ValueError('Fechas de cobertura inconsistentes')
        if self.final_has_invoice_on_calendar_end!=(self.final_last_invoice_date==end):raise ValueError('Marca de cierre inconsistente')
        if self.final_days_with_sales>(self.final_last_invoice_date-self.final_first_invoice_date).days+1:raise ValueError('Días inválidos')
        if cutoff==last and not self.final_has_invoice_on_calendar_end:raise ValueError('Cierre posiblemente parcial')
        return self


class Candidate(BaseModel):
    selection: Metrics
    holdout: Metrics


class Design(BaseModel):
    horizon: Literal[3]
    initial_train: Annotated[int,Field(strict=True,ge=24)]
    selection_origins: Annotated[int,Field(strict=True,ge=1)]
    selection_predictions_per_model: Annotated[int,Field(strict=True,ge=3)]
    selection_last_target: Month
    holdout_months: list[Month]
    criterion: Literal['selection_mae']


class Evaluation(BaseModel):
    selected_model: ModelName
    results: dict[ModelName,Candidate]
    design: Design


class Uncertainty(BaseModel):
    method: Literal[UNCERTAINTY_METHOD]
    samples_per_horizon: Annotated[int,Field(strict=True,ge=1)]


class SourceSummary(BaseModel):
    # Se ignoran metadatos privados, no se reenvían al cliente.
    model_config=ConfigDict(extra='ignore')
    schema_version: Literal[1]
    metric: Literal[TARGET]
    input_sha256: Annotated[str,Field(pattern=r'^[a-f0-9]{64}$')]
    coverage: Coverage
    evaluation: Evaluation
    uncertainty: Uncertainty
    forecasts: Annotated[list[Forecast],Field(min_length=3,max_length=3)]

    @field_validator('schema_version',mode='before')
    @classmethod
    def exact_version(cls,value):
        if type(value) is not int:raise ValueError('Versión inválida')
        return value

    @model_validator(mode='after')
    def consistency(self):
        evaluation=self.evaluation;design=evaluation.design
        names=('naive','moving_average_3','ridge')
        if set(evaluation.results)!=set(names):raise ValueError('Faltan candidatos')
        if evaluation.selected_model!=min(names,key=lambda n:evaluation.results[n].selection.mae):raise ValueError('Ganador inconsistente')
        cutoff=ordinal(self.coverage.complete_through)
        if [p.month for p in self.forecasts]!=[month_at(cutoff+h) for h in (1,2,3)]:raise ValueError('Horizonte inválido')
        if design.holdout_months!=[month_at(i) for i in range(cutoff-2,cutoff+1)] or design.selection_last_target!=month_at(cutoff-3):
            raise ValueError('Prueba final inconsistente')
        if design.selection_origins!=self.coverage.usable_months-6-design.initial_train+1 or design.selection_predictions_per_model!=design.selection_origins*3 or self.uncertainty.samples_per_horizon!=design.selection_origins:
            raise ValueError('Diseño inconsistente')
        return self


class PredictionsResponse(BaseModel):
    selected_model: ModelName
    metric: Literal['ventas_sin_impuestos']='ventas_sin_impuestos'
    currency: None=None
    backtesting: Metrics
    holdout: Metrics
    coverage: Coverage
    design: Design
    uncertainty: Uncertainty
    forecasts: list[Forecast]
    input_sha256: str
    completeness_verified: Literal[False]=False
    coverage_warning: str='Cobertura declarada, no auditada: facturación hasta fin de mes no certifica que todas las ventas estén incluidas.'


class ArtifactUnavailable(Exception):
    pass


def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Clave JSON duplicada')
        result[key]=value
    return result


def read_predictions(configured_path):
    try:
        path=Path(configured_path)
        if not path.is_absolute():path=ROOT/path
        path=path.resolve()
        if not path.is_relative_to(ARTIFACT_ROOT.resolve()) or path.name!='resumen.json':raise ValueError('Ruta inválida')
        with path.open('rb') as source:content=source.read(MAX_BYTES+1)
        if len(content)>MAX_BYTES:raise ValueError('Artefacto excesivo')
        def invalid_constant(value):raise ValueError('Constante no finita')
        payload=json.loads(content,parse_float=Decimal,parse_constant=invalid_constant,object_pairs_hook=no_duplicates)
        summary=SourceSummary.model_validate(payload)
        selected=summary.evaluation.results[summary.evaluation.selected_model]
        return PredictionsResponse(selected_model=summary.evaluation.selected_model,
            backtesting=selected.selection,holdout=selected.holdout,coverage=summary.coverage,
            design=summary.evaluation.design,uncertainty=summary.uncertainty,forecasts=summary.forecasts,input_sha256=summary.input_sha256)
    except (OSError,ValueError,TypeError,ValidationError,RecursionError):
        raise ArtifactUnavailable('Predicciones no disponibles: falta un artefacto válido. Revise la configuración local.') from None
