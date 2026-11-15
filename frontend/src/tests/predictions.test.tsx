import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent,within} from '@testing-library/react';
import {parsePredictions,compatibleHistory} from '../lib/predictions';
import {predictionOption} from '../components/predictionChart';
import {PredictionsPanel} from '../components/PredictionsPanel';
import {formatMetric} from '../lib/format';
import {predictions,months} from './fixtures';
vi.mock('../components/Chart',()=>({Chart:({label}:{label:string})=><div role="img" aria-label={label}/> }));
const prediction=()=>({state:{status:'success' as const,data:parsePredictions(predictions),updated:new Date()},reload:vi.fn()});
const history=()=>({state:{status:'success' as const,data:months,updated:new Date()},reload:vi.fn()});
it('contrato y métricas se conservan como cadenas decimales',()=>{
  expect(parsePredictions(predictions).backtesting.mae).toBe('10.125');
  expect(formatMetric('10.125')).toBe('10,12');expect(formatMetric('10.135')).toBe('10,14');
  expect(formatMetric('9007199254740993.125')).toBe('9.007.199.254.740.993,12');
});
it('rechaza unidad, horizonte, moneda, bandas y montos incompatibles',()=>{
  const mutations=[(v:any)=>v.metric='total_facturado',(v:any)=>v.currency='USD',(v:any)=>v.completeness_verified=true,
    (v:any)=>v.forecasts[0].month='2015-06',(v:any)=>v.forecasts[0].forecast=100,(v:any)=>v.forecasts[0].lower='200.00'];
  for(const mutate of mutations){const data=structuredClone(predictions);mutate(data);expect(()=>parsePredictions(data)).toThrow();}
});
it('no une históricos desordenados, desconocidos o distintos de la cobertura',()=>{
  const p=parsePredictions(predictions);
  expect(compatibleHistory(months,p)).toHaveLength(30);
  expect(()=>compatibleHistory(months.slice(1),p)).toThrow();
  expect(()=>compatibleHistory([...months].reverse(),p)).toThrow();
  expect(()=>compatibleHistory([{...months[0],anio:null},...months.slice(1)],p)).toThrow();
});
it('separa series reales, estimadas y bandas, conserva tooltip exacto',()=>{
  const p=parsePredictions(predictions);const option=predictionOption(months,p) as any;
  expect(option.series).toHaveLength(4);
  expect(option.series[2].data.slice(-3)).toEqual([null,null,null]);
  expect(option.series[3].lineStyle.type).toBe('dashed');
  expect(option.series[3].data.slice(-3)).toEqual([100,100,100]);
  expect(option.tooltip.formatter([{dataIndex:30}])).toContain('Estimado: 100,00');
  expect(option.tooltip.formatter([{dataIndex:29}])).toContain('Real: 30,00');
});
it('muestra métricas del artefacto y avisos sin afirmar cierre auditado',()=>{
  render(<PredictionsPanel prediction={prediction()} history={history()}/>);
  expect(screen.getByText('Promedio móvil de 3 meses')).toBeTruthy();
  expect(screen.getByText('10,12')).toBeTruthy();expect(screen.getByText('20,50')).toBeTruthy();
  expect(screen.getByText(/Pronóstico histórico experimental; no representa/)).toBeTruthy();
  expect(screen.getByText(/Cobertura de junio de 2015 no certificada/)).toBeTruthy();
  expect(screen.getByRole('img')).toBeTruthy();
});
it('error de artefacto no fabrica datos y permite reintentar',()=>{
  const reload=vi.fn();render(<PredictionsPanel prediction={{state:{status:'error'},reload}} history={history()}/>);
  expect(screen.getByRole('alert').textContent).toContain('Predicciones no disponibles');
  expect(screen.queryByRole('img')).toBeNull();fireEvent.click(screen.getByText('Reintentar predicciones'));expect(reload).toHaveBeenCalledOnce();
});
it('incompatibilidad bloquea el gráfico y reintenta ambas consultas',()=>{
  const p=prediction(),h=history();h.state.data=months.slice(1);
  render(<PredictionsPanel prediction={p} history={h}/>);
  expect(screen.getByRole('alert').textContent).toContain('Las series no son compatibles');
  expect(screen.queryByRole('img')).toBeNull();fireEvent.click(screen.getByText('Reintentar predicciones'));
  expect(p.reload).toHaveBeenCalledOnce();expect(h.reload).toHaveBeenCalledOnce();
});
it('carga y ausencia de histórico son explícitas',()=>{
  const {unmount}=render(<PredictionsPanel prediction={{state:{status:'loading'},reload:vi.fn()}} history={history()}/>);
  expect(screen.getByRole('status').textContent).toContain('Consultando datos');unmount();
  const h=history();h.state.data=[];render(<PredictionsPanel prediction={prediction()} history={h}/>);
  expect(screen.getByText('No hay datos disponibles')).toBeTruthy();
});

it('tabla accesible conserva cuatro columnas e importes completos dentro de una región enfocables',()=>{
  const p=prediction();p.state.data.forecasts[0]={...p.state.data.forecasts[0],
    forecast:'9007199254740993.01',lower:'9007199254740983.01',upper:'9007199254741003.01'};
  render(<PredictionsPanel prediction={p} history={history()}/>);
  const region=screen.getByRole('region',{name:'Tabla de pronósticos desplazable'});
  expect(region.tabIndex).toBe(0);region.focus();expect(document.activeElement).toBe(region);
  expect(within(region).getAllByRole('columnheader').map(cell=>cell.textContent)).toEqual(['Mes estimado','Pronóstico','Inferior','Superior']);
  expect(within(region).getByText('9.007.199.254.740.993,01')).toBeTruthy();
  expect(within(region).getByText('9.007.199.254.740.983,01')).toBeTruthy();
  expect(within(region).getByText('9.007.199.254.741.003,01')).toBeTruthy();
  const hint=document.getElementById(region.getAttribute('aria-describedby')!);
  expect(hint?.textContent).toContain('Desplaza horizontalmente');
});
