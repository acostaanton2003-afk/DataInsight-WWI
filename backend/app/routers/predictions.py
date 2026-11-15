from backend.app.permissions import Permission, requires_permission
from fastapi import APIRouter,HTTPException,Request
from backend.app.predictions import ArtifactUnavailable,PredictionsResponse,read_predictions

router=APIRouter(prefix='/api/v1/predicciones',tags=['predicciones'])

@router.get('/ventas',response_model=PredictionsResponse,
    summary='Pronóstico histórico experimental desde un artefacto local validado',
    responses={503:{'description':'Artefacto ausente, inválido o inaccesible.'},422:{'description':'No se admiten parámetros de consulta.'}})
@requires_permission(Permission.PREDICTIONS_READ)
def predictions(request:Request):
    if request.query_params:
        raise HTTPException(status_code=422,detail='Este endpoint no admite parámetros de consulta.')
    try:return read_predictions(request.app.state.settings.forecast_path)
    except ArtifactUnavailable:
        raise HTTPException(status_code=503,detail='Predicciones no disponibles: falta un artefacto válido. Revise la configuración local.') from None
