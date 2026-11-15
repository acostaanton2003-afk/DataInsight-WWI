from fastapi import APIRouter,Depends,HTTPException,Request,Response
from pydantic import ValidationError
from backend.app.analytics import AnalyticsRepository
from backend.app.assistant import answer,AssistantDataError
from backend.app.assistant_models import Question,AssistantResponse
from backend.app.assistant_provider import provider_for
from backend.app.database import DatabaseReadError
from backend.app.predictions import ArtifactUnavailable

router=APIRouter(prefix='/api/v1/asistente',tags=['asistente'])
def get_assistant_repository(request:Request):return AnalyticsRepository(request.app.state.settings.database)
def get_assistant_provider(request:Request):return provider_for(request.app.state.settings.assistant)

@router.post('/consultar',response_model=AssistantResponse,summary='Consulta de negocio acotada; reglas locales por defecto',responses={503:{'description':'Indicadores o artefacto no disponibles.'}})
def consult(body:Question,request:Request,response:Response,repo=Depends(get_assistant_repository),provider=Depends(get_assistant_provider)):
    response.headers['Cache-Control']='no-store'
    if request.query_params:raise HTTPException(status_code=422,detail='No se admiten parámetros de consulta.')
    try:return answer(body.pregunta,repo,request.app.state.settings.forecast_path,provider)
    except (DatabaseReadError,ArtifactUnavailable,AssistantDataError,ValidationError,ValueError,TypeError):
        raise HTTPException(status_code=503,detail='No se pudieron consultar los indicadores o las predicciones verificadas. Reintenta más tarde.') from None
