import { useMemo, useState } from 'react';
import { parseKpis, parseMonths, parseProducts, parseCustomers, type Month } from './lib/api';
import { useResource } from './lib/useResource';
import { parsePredictions } from './lib/predictions';
import { PredictionsPanel } from './components/PredictionsPanel';
import { formatAmount, formatCount, monthLabel } from './lib/format';
import { Icon } from './components/Icon';
import { Chart } from './components/Chart';
import { monthlyOption, rankingOption, type RankRow } from './components/charts';
import { ResourceView } from './components/ResourceView';

function MonthlyChart({rows}:{rows:Month[]}) {
  const option=useMemo(()=>monthlyOption(rows),[rows]);
  return <><Chart option={option} label="Ventas sin impuestos por mes"/>
    <details className="data-details"><summary>Ver los {rows.length} meses en tabla</summary>
      <div className="table-scroll"><table><caption className="sr-only">Ventas mensuales exactas</caption>
        <thead><tr><th>Mes</th><th>Ventas sin impuestos</th><th>Facturas</th></tr></thead>
        <tbody>{rows.map((row,i)=><tr key={`${row.anio}-${row.mes}-${i}`}><td>{monthLabel(row.anio,row.mes)}</td><td>{formatAmount(row.importe)}</td><td>{formatCount(row.cantidad_facturas)}</td></tr>)}</tbody>
      </table></div></details></>;
}
function Ranking({rows,color,label}:{rows:RankRow[];color:string;label:string}) {
  const option=useMemo(()=>rankingOption(rows,color),[rows,color]);
  return <><Chart option={option} label={label} className="rank-chart"/>
    <details className="data-details"><summary>Ver nombres e importes completos</summary>
      <div className="table-scroll"><table><caption className="sr-only">{label}: datos exactos</caption>
        <thead><tr><th>Nombre / ID</th><th>Ventas sin impuestos</th></tr></thead>
        <tbody>{rows.map(row=><tr key={row.key}><td>{row.name}<small>ID {row.id ?? 'desconocido'}</small></td><td>{formatAmount(row.amount)}</td></tr>)}</tbody>
      </table></div></details></>;
}
function KpiCard({title,value,icon,note,featured=false}:{title:string;value:string;icon:string;note:string;featured?:boolean}) {
  return <article className={`kpi-card ${featured?'featured':''}`}><div className="kpi-top"><span>{title}</span><span className="kpi-icon"><Icon name={icon}/></span></div>
    <strong className="kpi-value">{value}</strong><p>{note}</p></article>;
}
export default function App() {
  const [refresh,setRefresh]=useState(0);
  const kpis=useResource('/kpis',parseKpis,refresh);
  const months=useResource('/ventas/por-mes',parseMonths,refresh);
  const products=useResource('/productos/top?limit=10',parseProducts,refresh);
  const customers=useResource('/clientes/top?limit=10',parseCustomers,refresh);
  const predictions=useResource('/predicciones/ventas',parsePredictions,refresh);
  const states=[kpis.state,months.state,products.state,customers.state,predictions.state];
  const loading=states.some(state=>state.status==='loading');
  const errors=states.some(state=>state.status==='error');
  const updated=states.flatMap(state=>state.status==='success'?[state.updated.getTime()]:[]);
  const known=months.state.status==='success'?months.state.data.filter(row=>row.anio!==null&&row.mes!==null):[];
  const period=known.length?`${monthLabel(known[0].anio,known[0].mes)} — ${monthLabel(known[known.length-1].anio,known[known.length-1].mes)}`:'Histórico disponible';
  return <div className="app-shell">
    <a className="skip-link" href="#contenido">Ir al contenido</a>
    <aside className="sidebar"><a className="brand" href="#resumen" aria-label="DataInsight WWI, inicio"><span className="brand-mark"><Icon name="grid" size={24}/></span><span>DataInsight<small>WIDE WORLD IMPORTERS</small></span></a>
      <div className="workspace-label">ESPACIO DE ANÁLISIS</div>
      <nav aria-label="Navegación principal"><a className="nav-current" href="#resumen"><Icon name="grid"/>Resumen de ventas</a><a href="#ventas"><Icon name="trend"/>Evolución mensual</a><a href="#productos"><Icon name="box"/>Productos</a><a href="#clientes"><Icon name="people"/>Clientes</a><a href="#predicciones"><Icon name="trend"/>Predicciones</a></nav>
      <div className="sidebar-note"><div className="note-symbol"><Icon name="trend"/></div><strong>Una visión más clara.</strong><p>Explora las ventas, los productos y quienes impulsan el negocio.</p><span>DATAINSIGHT / WWI</span></div>
      <div className="sidebar-footer"><span className="sidebar-dot"/>Análisis histórico de ventas</div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb">Workspace <span>/</span> <strong>Ventas</strong></div><span className="project-badge">WWI <span>·</span> Business Intelligence</span></header>
      <main id="contenido"><section className="page-heading" id="resumen"><div><div className="eyebrow">PANORAMA COMERCIAL</div><h1>Resumen de ventas<span>.</span></h1><p>Los números que cuentan la historia de tu negocio.</p></div><button className="button refresh-button" disabled={loading} onClick={()=>setRefresh(value=>value+1)}><Icon name="refresh"/>{loading?'Actualizando…':'Actualizar datos'}</button></section>
        <div className="context-row"><span className="period"><Icon name="calendar" size={16}/>{period}</span><div className={`data-status ${errors?'warning':''}`} role="status"><span className={`status-dot ${loading?'pulsing':''}`}/>{loading?'Consultando datos':errors?'Actualización parcial':'Datos consultados'}{!loading&&updated.length>0&&<span className="update-time">· {new Intl.DateTimeFormat('es-ES',{hour:'2-digit',minute:'2-digit'}).format(new Date(Math.max(...updated)))}</span>}</div></div>
        <section aria-label="Indicadores de ventas" className="kpis-section"><ResourceView state={kpis.state} retry={kpis.reload}>{data=><div className="kpi-grid">
          <KpiCard title="Ventas sin impuestos" value={formatAmount(data.ventas_sin_impuestos)} icon="trend" note="Base de las ventas facturadas"/>
          <KpiCard title="Impuestos" value={formatAmount(data.impuestos)} icon="document" note="Impuestos sobre las ventas"/>
          <KpiCard title="Total facturado" value={formatAmount(data.total_facturado)} icon="arrow" note="Importe facturado con impuestos" featured/>
          <KpiCard title="Facturas" value={formatCount(data.cantidad_facturas)} icon="document" note="Facturas distintas con líneas de venta"/>
          <KpiCard title="Pedidos" value={formatCount(data.cantidad_pedidos)} icon="box" note="Todos los pedidos registrados"/>
          <KpiCard title="Clientes" value={formatCount(data.cantidad_clientes)} icon="people" note="Clientes registrados en el maestro"/>
        </div>}</ResourceView></section>
        <section className="panel monthly-panel" id="ventas" aria-labelledby="monthly-title"><div className="panel-heading"><div><span className="section-index">01 / VENTAS</span><h2 id="monthly-title">Evolución mensual</h2><p>Ventas sin impuestos por fecha de factura</p></div><span className="legend"><i/>Ventas sin impuestos</span></div>
          <ResourceView state={months.state} retry={months.reload} isEmpty={rows=>rows.length===0}>{rows=><MonthlyChart rows={rows}/>}</ResourceView>
        </section>
        <div className="rank-grid"><section className="panel" id="productos" aria-labelledby="products-title"><div className="panel-heading"><div><span className="section-index">02 / PRODUCTOS</span><h2 id="products-title">Los productos que más venden</h2><p>Top 10 por ventas sin impuestos</p></div><span className="top-label">TOP 10</span></div>
          <ResourceView state={products.state} retry={products.reload} isEmpty={rows=>rows.length===0}>{rows=><Ranking label="Top 10 productos por ventas sin impuestos" color="#168a80" rows={rows.map(row=>({key:row.producto_key,id:row.stock_item_id,name:row.stock_item_name,amount:row.ventas_sin_impuestos}))}/>}</ResourceView>
        </section><section className="panel" id="clientes" aria-labelledby="customers-title"><div className="panel-heading"><div><span className="section-index">03 / CLIENTES</span><h2 id="customers-title">Clientes que impulsan las ventas</h2><p>Top 10 por ventas sin impuestos</p></div><span className="top-label">TOP 10</span></div>
          <ResourceView state={customers.state} retry={customers.reload} isEmpty={rows=>rows.length===0}>{rows=><Ranking label="Top 10 clientes por ventas sin impuestos" color="#6684a3" rows={rows.map(row=>({key:row.cliente_key,id:row.customer_id,name:row.customer_name,amount:row.ventas_sin_impuestos}))}/>}</ResourceView>
        </section></div>
        <PredictionsPanel prediction={predictions} history={months}/>
        <footer className="main-footer"><p><strong>Sobre estos indicadores</strong> Ventas y facturas excluyen notas de crédito. Clientes corresponde al maestro, sin el miembro desconocido. Importes sin símbolo: la moneda no está verificada.</p><span>DataInsight WWI <b>·</b> WideWorldImporters</span></footer>
      </main>
    </div>
  </div>;
}
