"""Contratos acotados: hechos del servidor, nunca prosa libre de un proveedor."""
import unicodedata
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator
from backend.app.predictions import Month

Topic=Literal['kpis','mensual','productos','clientes','pronosticos','no_soportada']
Interpretation=Literal['resumen','comparacion','ranking','experimental']

class Question(BaseModel):
    model_config=ConfigDict(extra='forbid')
    pregunta: Annotated[str,Field(min_length=5,max_length=500)]

    @field_validator('pregunta')
    @classmethod
    def plain_question(cls,value):
        value=value.strip()
        if len(value)<5 or any(unicodedata.category(c).startswith('C') for c in value):
            raise ValueError('Pregunta vacía o con caracteres de control.')
        return value

class Source(BaseModel):
    nombre: str
    ruta: Literal['/api/v1/kpis','/api/v1/ventas/por-mes','/api/v1/productos/top','/api/v1/clientes/top','/api/v1/predicciones/ventas']

class Period(BaseModel):
    inicio: Month
    fin: Month

class AnswerText(BaseModel):
    hechos: Annotated[list[str],Field(max_length=8)]
    interpretacion: Annotated[str,Field(max_length=700)]
    limitaciones: Annotated[list[str],Field(max_length=6)]

class AssistantResponse(BaseModel):
    soportada: bool
    tema: Topic
    modo: Literal['reglas','llm_local_restringido']
    proveedor: Literal['local','ollama']='local'
    modelo: Annotated[str|None,Field(max_length=80)]=None
    respuesta: AnswerText
    fuentes: list[Source]
    periodo: Period | None
    advertencias: list[str]

class ProviderPlan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    fact_ids: Annotated[list[Annotated[str,Field(pattern=r'^f[1-8]$')]],Field(min_length=1,max_length=8)]
    interpretation: Interpretation
    limitation: Literal['alcance_limitado']
