import {it,expect,vi} from 'vitest';
import {render,screen,waitFor,fireEvent} from '@testing-library/react';
import App from '../App';
import {kpis,months,products,customers,predictions} from './fixtures';
vi.mock('../components/Chart',()=>({Chart:({label}:{label:string})=><div role="img" aria-label={label}/> }));
function mockFetch(overrides:Record<string,unknown>={}) {
  const values:Record<string,unknown>={'/kpis':kpis,'/ventas/por-mes':months,'/productos/top?limit=10':products,'/clientes/top?limit=10':customers,'/predicciones/ventas':predictions,...overrides};
  const fetch=vi.fn(async(url:string)=>{
    const value=values[url.split('/api/v1')[1]];
    return value instanceof Error ? new Response('secret-from-server',{status:503}) : new Response(JSON.stringify(value));
  });
  vi.stubGlobal('fetch',fetch);return {fetch,values};
}
it('carga las cinco rutas y presenta seis indicadores, gráficos y tablas exactas',async()=>{
  const {fetch}=mockFetch();render(<App/>);
  await screen.findByText('33,00');
  expect(screen.getByText('Base de las ventas facturadas')).toBeTruthy();
  expect(screen.getAllByRole('img')).toHaveLength(4);
  expect(screen.getByText('Producto ficticio')).toBeTruthy();
  expect(screen.getByText('Cliente ficticio')).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(5);
  expect(screen.getByText(/moneda no está verificada/)).toBeTruthy();
});
it('muestra carga sin fabricar cifras',()=>{
  vi.stubGlobal('fetch',vi.fn(()=>new Promise(()=>{})));render(<App/>);
  expect(screen.getAllByText('Consultando datos…')).toHaveLength(5);
  expect(screen.queryByText('33,00')).toBeNull();
});
it('mantiene secciones independientes, oculta detalles y reintenta solo el fallo',async()=>{
  const {fetch,values}=mockFetch({'/kpis':new Error('private')});render(<App/>);
  await screen.findByRole('alert');
  expect(screen.getByText('Producto ficticio')).toBeTruthy();
  expect(screen.queryByText('secret-from-server')).toBeNull();
  values['/kpis']=kpis;fireEvent.click(screen.getByRole('button',{name:'Reintentar'}));
  await screen.findByText('33,00');expect(fetch).toHaveBeenCalledTimes(6);
});
it('muestra vacíos explícitos y conserva el cero de KPI',async()=>{
  mockFetch({'/ventas/por-mes':[],'/productos/top?limit=10':[],'/clientes/top?limit=10':[], '/kpis':{...kpis,ventas_sin_impuestos:'0.00'}});
  render(<App/>);await screen.findByText('0,00');
  expect(screen.getAllByText('No hay datos disponibles')).toHaveLength(4);
});
it('permite actualizar las cinco consultas',async()=>{
  const {fetch}=mockFetch();render(<App/>);await screen.findByText('33,00');
  await waitFor(()=>expect((screen.getByRole('button',{name:'Actualizar datos'}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Actualizar datos'}));
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(10));
});
it('aborta solicitudes al desmontar',()=>{
  const fetch=vi.fn((_url:string,_init?:RequestInit)=>new Promise(()=>{}));vi.stubGlobal('fetch',fetch);
  const {unmount}=render(<App/>);const signal=fetch.mock.calls[0][1]!.signal as AbortSignal;
  unmount();expect(signal.aborted).toBe(true);
});
