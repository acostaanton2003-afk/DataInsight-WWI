import {errorMessage} from '../lib/http';
import {useEffect,useId,useRef,useState,type FormEvent} from 'react';
import {consultAssistant,type AssistantAnswer} from '../lib/assistant';

const EXAMPLES=['Dame un resumen de los KPI','¿Cómo evolucionan las ventas por mes?','¿Cuáles son los productos destacados?','¿Cuáles son los clientes destacados?','¿Cuáles son los pronósticos históricos?'];
export function AssistantPanel(){
  const inputId=useId();const [question,setQuestion]=useState('');
  const [failure,setFailure]=useState('');
  const [status,setStatus]=useState<'idle'|'loading'|'error'|'success'>('idle');
  const [answer,setAnswer]=useState<AssistantAnswer|null>(null);
  const controller=useRef<AbortController|null>(null);const lastQuestion=useRef('');
  useEffect(()=>()=>{controller.current?.abort();controller.current=null;},[]);
  async function submit(value=question){
    const normalized=value.trim();if(normalized.length<5||normalized.length>500)return;
    controller.current?.abort();const current=new AbortController();controller.current=current;
    const timeout=window.setTimeout(()=>current.abort(),60000);
    lastQuestion.current=normalized;setStatus('loading');setAnswer(null);
    try {const result=await consultAssistant(normalized,current.signal);
      if(controller.current===current){setAnswer(result);setStatus('success');}
    }catch(error){if(controller.current===current){setStatus('error');setFailure(errorMessage(error));}}
    finally{window.clearTimeout(timeout);}
  }
  function handleSubmit(event:FormEvent){event.preventDefault();void submit();}
  return <section className="panel assistant-panel" id="asistente" aria-labelledby="assistant-title">
    <div className="panel-heading"><div><span className="section-index">05 / ANÁLISIS DE NEGOCIO</span><h2 id="assistant-title">Asistente IA</h2><p>Consulta indicadores y pronósticos históricos verificados</p></div><span className="top-label">CONSULTAS ACOTADAS</span></div>
    <div className="assistant-body"><p className="assistant-intro">Modo predeterminado: <strong>respuestas basadas en reglas, no IA generativa</strong>. Ollama local es opcional; el modo realmente utilizado se indica en cada respuesta.</p>
      <div className="assistant-examples" aria-label="Preguntas de ejemplo">{EXAMPLES.map(example=><button type="button" key={example} disabled={status==='loading'} onClick={()=>setQuestion(example)}>{example}</button>)}</div>
      <form onSubmit={handleSubmit} className="assistant-form"><label htmlFor={inputId}>Pregunta de negocio</label>
        <div className="assistant-input-row"><input id={inputId} type="text" value={question} onChange={e=>setQuestion(e.target.value)} minLength={5} maxLength={500} required autoComplete="off" readOnly={status==='loading'} placeholder="Por ejemplo: ¿cuáles son los productos destacados?" aria-describedby={`${inputId}-help`}/>
          <button className="button" type="submit" disabled={status==='loading'||question.trim().length<5}>{status==='loading'?'Consultando…':'Consultar'}</button></div>
        <small id={`${inputId}-help`}>Un tema por pregunta · {question.length}/500 caracteres. No incluyas datos personales ni secretos.</small>
      </form>
      {status==='idle'&&<p className="assistant-empty">Elige un ejemplo o escribe tu pregunta para comenzar.</p>}
      {status==='loading'&&<div className="assistant-loading" role="status"><span className="loader"/>Consultando indicadores autorizados…</div>}
      {status==='error'&&<div className="assistant-error" role="alert"><strong>No se pudo completar la consulta.</strong><p>{failure}</p><button className="button" onClick={()=>void submit(lastQuestion.current)}>Reintentar consulta</button></div>}
      {status==='success'&&answer&&<article className="assistant-answer" aria-label="Respuesta del asistente" aria-live="polite"><div className="assistant-mode">{answer.modo==='reglas'?'Reglas locales · no es IA generativa':`Ollama local${answer.modelo ? ` · ${answer.modelo}` : ''} · hechos validados`}</div>
        {answer.periodo&&<p className="assistant-period">Período: {answer.periodo.inicio} — {answer.periodo.fin}</p>}
        <h3>{answer.soportada?'Hechos verificables':'Consulta no soportada'}</h3>
        {answer.respuesta.hechos.length>0&&<ul>{answer.respuesta.hechos.map((fact,i)=><li key={i}>{fact}</li>)}</ul>}
        <h3>Interpretación</h3><p>{answer.respuesta.interpretacion}</p>
        <h3>Limitaciones</h3><ul>{answer.respuesta.limitaciones.map((value,i)=><li key={i}>{value}</li>)}</ul>
        {answer.fuentes.length>0&&<><h3>Fuentes consultadas</h3><ul className="assistant-sources">{answer.fuentes.map(source=><li key={source.ruta}>{source.nombre} <code>{source.ruta}</code></li>)}</ul></>}
        <div className="assistant-warnings"><h3>Advertencias</h3><ul>{answer.advertencias.map((warning,i)=><li key={i}>{warning}</li>)}</ul></div>
      </article>}
    </div>
  </section>;
}
