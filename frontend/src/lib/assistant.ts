import {object,text} from './api';
import {requestJson} from './http';
export interface AssistantAnswer {
  soportada:boolean;tema:string;modo:'reglas'|'llm_local_restringido';proveedor:'local'|'ollama';modelo:string|null;
  respuesta:{hechos:string[];interpretacion:string;limitaciones:string[]};
  fuentes:{nombre:string;ruta:string}[];periodo:{inicio:string;fin:string}|null;advertencias:string[];
}
const routes=['/api/v1/kpis','/api/v1/ventas/por-mes','/api/v1/productos/top','/api/v1/clientes/top','/api/v1/predicciones/ventas'];
const invalid=():never=>{throw new Error('Respuesta del asistente inválida.');};
const bounded=(value:unknown)=>{const result=text(value);return result.length<=1000?result:invalid();};
const strings=(value:unknown,max:number)=>Array.isArray(value)&&value.length<=max?value.map(bounded):invalid();
export function parseAssistant(value:unknown):AssistantAnswer {
  const row=object(value),answer=object(row.respuesta);
  if(typeof row.soportada!=='boolean'||!['reglas','llm_local_restringido'].includes(text(row.modo))||!['kpis','mensual','productos','clientes','pronosticos','no_soportada'].includes(text(row.tema)))return invalid();
  if(!['local','ollama'].includes(text(row.proveedor)) || (row.modo==='reglas')!==(row.proveedor==='local') || (row.modelo!==null && (typeof row.modelo!=='string'||row.modelo.length>80)) || (row.proveedor==='local'&&row.modelo!==null))return invalid();
  if(!Array.isArray(row.fuentes)||row.fuentes.length>5)return invalid();
  let period=null;
  if(row.periodo!==null){const p=object(row.periodo);const inicio=text(p.inicio),fin=text(p.fin);
    if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(inicio)||!/^\d{4}-(0[1-9]|1[0-2])$/.test(fin)||inicio>fin)return invalid();
    period={inicio,fin};}
  return {soportada:row.soportada,tema:text(row.tema),modo:row.modo as AssistantAnswer['modo'],proveedor:row.proveedor as AssistantAnswer['proveedor'],modelo:row.modelo as string|null,
    respuesta:{hechos:strings(answer.hechos,8),interpretacion:bounded(answer.interpretacion),limitaciones:strings(answer.limitaciones,6)},
    fuentes:row.fuentes.map(value=>{const source=object(value);const route=text(source.ruta);if(!routes.includes(route))return invalid();return {nombre:bounded(source.nombre),ruta:route};}),
    periodo:period,advertencias:strings(row.advertencias,8)};
}
export async function consultAssistant(question:string,signal:AbortSignal) {
  return parseAssistant(await requestJson('/api/v1/asistente/consultar', signal, {pregunta:question}));
}
