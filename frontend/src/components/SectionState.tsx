export function SectionState({kind, retry, message}: {kind:'loading'|'error'|'empty'; retry?:()=>void;message?:string}) {
  return <div className={`section-state ${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
    {kind === 'loading' ? <><span className="loader"/>Consultando datos…</> : kind === 'error' ? <>
      <span className="state-symbol">!</span><strong>No pudimos cargar esta sección</strong>
      <p>{message||'Comprueba que FastAPI esté disponible e inténtalo de nuevo.'}</p>
      <button className="button subtle" onClick={retry}>Reintentar</button>
    </> : <><span className="state-symbol">—</span><strong>No hay datos disponibles</strong><p>Esta consulta no devolvió registros.</p></>}
  </div>;
}
