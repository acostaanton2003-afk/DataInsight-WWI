import { describe,it,expect,vi } from 'vitest';
import { apiBase,fetchApi,parseKpis,parseMonths,parseProducts,parseCustomers } from '../lib/api';
import {kpis,months,products,customers} from './fixtures';
describe('contrato y transporte',()=>{
  it('acepta los cuatro contratos reales con valores ficticios',()=>{
    expect(parseKpis(kpis)).toEqual(kpis);expect(parseMonths(months)).toEqual(months);
    expect(parseProducts(products)).toEqual(products);expect(parseCustomers(customers)).toEqual(customers);
  });
  it.each([null,{}, {...kpis,impuestos:3}, {...kpis,cantidad_clientes:-1}])('rechaza KPI inválido',value=>expect(()=>parseKpis(value)).toThrow());
  it.each([13,0])('rechaza mes fuera de rango %s',mes=>expect(()=>parseMonths([{...months[0],mes}])).toThrow());
  it('permite miembros desconocidos y listas vacías',()=>{
    expect(parseMonths([{...months[0],anio:null,mes:null}])[0].anio).toBeNull();
    expect(parseProducts([{...products[0],producto_key:0,stock_item_id:null}])[0].stock_item_id).toBeNull();
    expect(parseCustomers([])).toEqual([]);
  });
  it.each(['ftp://localhost','http://user:secret@localhost','http://localhost/?secret=1'])('rechaza URL insegura',value=>expect(()=>apiBase(value)).toThrow());
  it('elimina barra final',()=>expect(apiBase('http://127.0.0.1:8000/')).toBe('http://127.0.0.1:8000'));
  it('consulta con señal y sin credenciales',async()=>{
    const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(kpis)));vi.stubGlobal('fetch',fetch);
    const signal=new AbortController().signal;
    await expect(fetchApi('/kpis',parseKpis,signal)).resolves.toEqual(kpis);
    expect(fetch.mock.calls[0][0]).toContain('/api/v1/kpis');
    expect(fetch.mock.calls[0][1]).toMatchObject({credentials:'omit',signal});
  });
  it('no muestra detalles de errores del servidor',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('sensitive-detail',{status:503})));
    await expect(fetchApi('/kpis',parseKpis,new AbortController().signal)).rejects.toThrow('No se pudo consultar la API.');
  });
  it('rechaza JSON malformado',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('invalid json')));
    await expect(fetchApi('/kpis',parseKpis,new AbortController().signal)).rejects.toThrow();
  });
});

it.each(['postgresql://fixture:fixture@db.invalid/database','https://fixture:fixture@api.invalid',
  'http://external-api.invalid'])('rechaza configuración que filtraría credenciales o Bearer: %s',value=>{
  expect(()=>apiBase(value)).toThrow();
});
