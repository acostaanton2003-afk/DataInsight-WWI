"""Contratos HTTP; sin SQL libre ni credenciales en respuestas."""
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, PlainSerializer, WithJsonSchema

from backend.app.analytics import AnalyticsRepository
from backend.app.database import DatabaseReadError

Money = Annotated[
    Decimal,
    PlainSerializer(lambda value: format(value,'.2f'),return_type=str,when_used='json'),
    WithJsonSchema({'type':'string','pattern':r'^-?[0-9]+\.[0-9]{2}$'},mode='serialization'),
]
Limit = Annotated[int,Query(ge=1,le=50,description='Máximo de resultados; orden por ventas sin impuestos.')]
router=APIRouter(prefix='/api/v1',tags=['analítica'],responses={503:{'description':'DWH no disponible; sin detalles sensibles.'}})


class KpisResponse(BaseModel):
    ventas_sin_impuestos: Money
    impuestos: Money
    total_facturado: Money
    cantidad_facturas: int = Field(ge=0)
    cantidad_pedidos: int = Field(ge=0)
    cantidad_clientes: int = Field(ge=0)


class MonthlySalesResponse(BaseModel):
    anio: int | None
    mes: int | None = Field(ge=1,le=12)
    importe: Money
    cantidad_facturas: int = Field(ge=0)


class TopProductResponse(BaseModel):
    producto_key: int
    stock_item_id: int | None
    stock_item_name: str
    ventas_sin_impuestos: Money


class TopCustomerResponse(BaseModel):
    cliente_key: int
    customer_id: int | None
    customer_name: str
    ventas_sin_impuestos: Money


def get_repository(request: Request):
    return AnalyticsRepository(request.app.state.settings.database)


def query_safely(operation,*args):
    try:
        return operation(*args)
    except (DatabaseReadError,ValueError):
        raise HTTPException(status_code=503,detail='No se pudo consultar el Data Warehouse.') from None


@router.get('/kpis',response_model=KpisResponse,summary='Indicadores globales de ventas, pedidos y clientes')
def kpis(repository=Depends(get_repository)):
    return query_safely(repository.kpis)


@router.get('/ventas/por-mes',response_model=list[MonthlySalesResponse],summary='Ventas sin impuestos por mes de factura')
def monthly(repository=Depends(get_repository)):
    return query_safely(repository.monthly)


@router.get('/productos/top',response_model=list[TopProductResponse],summary='Productos por ventas sin impuestos')
def products(limit: Limit=10,repository=Depends(get_repository)):
    return query_safely(repository.products,limit)


@router.get('/clientes/top',response_model=list[TopCustomerResponse],summary='Clientes comerciales por ventas sin impuestos')
def customers(limit: Limit=10,repository=Depends(get_repository)):
    return query_safely(repository.customers,limit)
