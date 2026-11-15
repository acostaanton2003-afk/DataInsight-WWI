import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {AssistantPanel} from '../components/AssistantPanel';
import {parseAssistant} from '../lib/assistant';
const fixture={soportada:true,tema:'kpis',modo:'reglas',proveedor:'local',modelo:null,respuesta:{hechos:['Ventas sintéticas: 60.00.'],interpretacion:'Resumen descriptivo.',limitaciones:['No establece causalidad.']},fuentes:[{nombre:'KPI',ruta:'/api/v1/kpis'}],periodo:{inicio:'2015-01',fin:'2015-03'},advertencias:['Moneda no verificada.','Mayo de 2016 no certificado.','Pronósticos históricos experimentales.','Bandas sin garantía de cobertura.']};
function submit(){fireEvent.change(screen.getByLabelText('Pregunta de negocio'),{target:{value:'Resumen de ventas'}});fireEvent.click(screen.getByRole('button',{name:'Consultar'}));}
it('solo consulta al enviar y etiqueta claramente el modo local',async()=>{
  const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture)));vi.stubGlobal('fetch',fetch);
  render(<AssistantPanel/>);expect(fetch).not.toHaveBeenCalled();submit();
  await screen.findByText('Ventas sintéticas: 60.00.');
  expect(screen.getByText('Reglas locales · no es IA generativa')).toBeTruthy();
  expect(screen.getByText('Fuentes consultadas')).toBeTruthy();expect(screen.getByText('Moneda no verificada.')).toBeTruthy();
  expect(fetch.mock.calls[0][1]).toMatchObject({method:'POST',credentials:'omit'});
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({pregunta:'Resumen de ventas'});
});
it('ejemplos editables, límites y carga',()=>{
  vi.stubGlobal('fetch',vi.fn(()=>new Promise(()=>{})));render(<AssistantPanel/>);
  fireEvent.click(screen.getByText('¿Cuáles son los productos destacados?'));
  const input=screen.getByLabelText('Pregunta de negocio') as HTMLInputElement;
  expect(input.value).toContain('productos');expect(input.maxLength).toBe(500);
  fireEvent.click(screen.getByRole('button',{name:'Consultar'}));expect(screen.getByRole('status').textContent).toContain('Consultando');
});
it('errores no muestran secretos ni datos ficticios y permiten reintentar',async()=>{
  const fetch=vi.fn().mockResolvedValueOnce(new Response('secret-error',{status:503})).mockResolvedValueOnce(new Response(JSON.stringify(fixture)));
  vi.stubGlobal('fetch',fetch);render(<AssistantPanel/>);submit();await screen.findByRole('alert');
  expect(screen.queryByText('secret-error')).toBeNull();expect(screen.queryByText('Ventas sintéticas: 60.00.')).toBeNull();
  fireEvent.click(screen.getByText('Reintentar consulta'));await screen.findByText('Ventas sintéticas: 60.00.');expect(fetch).toHaveBeenCalledTimes(2);
});
it('consulta no soportada y salida LLM como texto sin HTML ejecutable',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({...fixture,soportada:false,tema:'no_soportada',modo:'llm_local_restringido',proveedor:'ollama',modelo:'qwen3:1.7b',respuesta:{...fixture.respuesta,hechos:['<script>alert(1)</script>']}}))));
  const {container}=render(<AssistantPanel/>);submit();await screen.findByText('Consulta no soportada');
  expect(screen.getByText('Ollama local · qwen3:1.7b · hechos validados')).toBeTruthy();expect(container.querySelector('script')).toBeNull();
});
it('rechaza estructura, modos y fuentes arbitrarias',()=>{
  expect(()=>parseAssistant({...fixture,modo:'generative-free'})).toThrow();
  expect(()=>parseAssistant({...fixture,fuentes:[{nombre:'externa',ruta:'https://example.invalid'}]})).toThrow();
  expect(()=>parseAssistant({...fixture,respuesta:{hechos:'SQL'}})).toThrow();
});
it('aborta la consulta al desmontar',async()=>{
  const fetch=vi.fn((_url:string,_options:RequestInit)=>new Promise(()=>{}));vi.stubGlobal('fetch',fetch);
  const {unmount}=render(<AssistantPanel/>);submit();await waitFor(()=>expect(fetch).toHaveBeenCalled());const signal=fetch.mock.calls[0][1].signal as AbortSignal;
  unmount();expect(signal.aborted).toBe(true);
});

it('fallback de Ollama muestra modo local y conserva advertencia sin razonamiento',async()=>{
  const answer={...fixture,advertencias:[...fixture.advertencias,'Ollama no está disponible; se usa el modo local.']};
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify(answer))));
  render(<AssistantPanel/>);submit();await screen.findByText('Reglas locales · no es IA generativa');
  expect(screen.getByText('Ollama no está disponible; se usa el modo local.')).toBeTruthy();
  expect(screen.queryByText(/Ollama local · qwen/)).toBeNull();
});
it('no acepta etiqueta de proveedor contradictoria',()=>{
  expect(()=>parseAssistant({...fixture,proveedor:'ollama'})).toThrow();
  expect(()=>parseAssistant({...fixture,modelo:'qwen3:1.7b'})).toThrow();
});
