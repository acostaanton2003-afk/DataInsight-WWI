"""Pruebas offline: no requieren daemon ni modelo real."""
import json
from unittest.mock import MagicMock,patch
import pytest
from backend.app.assistant import classify
from backend.app.assistant_models import ProviderPlan
from backend.app.assistant_provider import OllamaProvider,ProviderError
from backend.app.config import AssistantSettings,load_settings
from backend.app.routers.assistant import get_assistant_provider
from backend.tests.test_assistant import assistant_repo

PLAN=dict(fact_ids=['f1'],interpretation='ranking',limitation='alcance_limitado')

def mocked_provider(content,**envelope_values):
    provider=OllamaProvider(AssistantSettings(provider='ollama',model='qwen3:1.7b'))
    opener=MagicMock()
    envelope={'message':{'content':content,'thinking':'private-reasoning-never-publish'},'done':True,**envelope_values}
    opener.open.return_value.__enter__.return_value.read.return_value=json.dumps(envelope).encode()
    return provider,opener

@pytest.mark.parametrize('question,topic',[
    ('¿Cómo marcha el negocio?','kpis'),('Dame las cifras generales','kpis'),('Nuestra facturación total','kpis'),
    ('¿Cómo cambiaron las ventas?','mensual'),('Muéstrame las ventas mes a mes','mensual'),('¿Cuál fue el mes con mayor venta?','mensual'),
    ('¿Cómo se comportaron las ventas?','mensual'),('Artículos con más ventas','productos'),('¿Qué se vende más?','productos'),
    ('Compradores principales','clientes'),('¿Quiénes nos compran más?','clientes'),('¿Qué cuentas comerciales lideran?','clientes'),
    ('¿Cuáles son las previsiones de ventas?','pronosticos'),('Estimaciones de ventas mensuales','pronosticos'),('¿Qué se espera vender?','pronosticos'),
])
def test_spanish_variants(question,topic):assert classify(question)==topic

@pytest.mark.parametrize('content',[json.dumps(PLAN),'<think>private internal text</think>\n'+json.dumps(PLAN),'```json\n'+json.dumps(PLAN)+'\n```'])
def test_qwen_final_only_and_request_parameters(content):
    provider,opener=mocked_provider(content)
    with patch('backend.app.assistant_provider.build_opener',return_value=opener):
        plan=provider.generate({'facts':[{'id':'f1'}]})
    assert plan.model_dump()==PLAN
    assert 'private' not in plan.model_dump_json()
    request=json.loads(opener.open.call_args.args[0].data)
    assert request['think'] is False and request['stream'] is False
    assert request['model']=='qwen3:1.7b'
    assert request['options']['num_ctx']==2048 and request['options']['num_predict']==256
    assert request['options']['num_thread']==2

@pytest.mark.parametrize('content',['<think>private without close','<think>private</think>',json.dumps({**PLAN,'reasoning':'private'}),'<think>x</think><think>y</think>'+json.dumps(PLAN),'x'*4097])
def test_incomplete_or_extra_reasoning_never_becomes_answer(content):
    provider,opener=mocked_provider(content)
    with patch('backend.app.assistant_provider.build_opener',return_value=opener),pytest.raises(ProviderError):
        provider.generate({'facts':[{'id':'f1'}]})

@pytest.mark.parametrize('extra',[{'done':False},{'done_reason':'length'}])
def test_partial_model_response_rejected(extra):
    provider,opener=mocked_provider(json.dumps(PLAN),**extra)
    with patch('backend.app.assistant_provider.build_opener',return_value=opener),pytest.raises(ProviderError):provider.generate({'facts':[]})

def test_qwen_defaults_for_enabled_provider_and_local_remains_default():
    enabled=load_settings(None,environ={'ASSISTANT_PROVIDER':'ollama'})
    assert enabled.assistant.model=='qwen3:1.7b' and enabled.assistant.timeout==30
    assert load_settings(None,environ={}).assistant.provider=='local'
    assert AssistantSettings(provider='ollama',model='qwen3:1.7b',timeout=60).timeout==60
    with pytest.raises(ValueError):AssistantSettings(provider='ollama',model='qwen3:1.7b',timeout=61)

def test_endpoint_identifies_model_and_hides_thinking(client,assistant_repo):
    class FakeQwen:
        model_name='qwen3:1.7b'
        def generate(self,context):return ProviderPlan(fact_ids=[r['id'] for r in context['facts']],interpretation=context['interpretation'],limitation='alcance_limitado')
    client.app.dependency_overrides[get_assistant_provider]=lambda:FakeQwen()
    data=client.post('/api/v1/asistente/consultar',json={'pregunta':'Artículos con más ventas'}).json()
    assert data['modo']=='llm_local_restringido' and data['proveedor']=='ollama' and data['modelo']=='qwen3:1.7b'
    class Broken(FakeQwen):
        def generate(self,context):raise ProviderError('private reasoning and internal path')
    client.app.dependency_overrides[get_assistant_provider]=lambda:Broken()
    response=client.post('/api/v1/asistente/consultar',json={'pregunta':'Artículos con más ventas'})
    assert response.json()['proveedor']=='local' and response.json()['modelo'] is None
    assert 'private' not in response.text
