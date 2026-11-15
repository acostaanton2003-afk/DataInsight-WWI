export interface Kpis {
  ventas_sin_impuestos: string; impuestos: string; total_facturado: string;
  cantidad_facturas: number; cantidad_pedidos: number; cantidad_clientes: number;
}
export interface Month { anio: number | null; mes: number | null; importe: string; cantidad_facturas: number }
export interface Product { producto_key: number; stock_item_id: number | null; stock_item_name: string; ventas_sin_impuestos: string }
export interface Customer { cliente_key: number; customer_id: number | null; customer_name: string; ventas_sin_impuestos: string }
export type Parser<T> = (value: unknown) => T;
const invalid = () => { throw new Error('Respuesta de la API no válida.'); };
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
  return value as Record<string, unknown>;
}
const count = (value: unknown): number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : invalid();
const id = (value: unknown): number | null => value === null ? null : count(value);
const text = (value: unknown): string => typeof value === 'string' ? value : invalid();
const amount = (value: unknown): string => typeof value === 'string' && /^-?\d+\.\d{2}$/.test(value) ? value : invalid();
function list<T>(value: unknown, parse: Parser<T>): T[] { return Array.isArray(value) ? value.map(parse) : invalid(); }
export const parseKpis: Parser<Kpis> = value => {
  const row = object(value);
  return { ventas_sin_impuestos: amount(row.ventas_sin_impuestos), impuestos: amount(row.impuestos),
    total_facturado: amount(row.total_facturado), cantidad_facturas: count(row.cantidad_facturas),
    cantidad_pedidos: count(row.cantidad_pedidos), cantidad_clientes: count(row.cantidad_clientes) };
};
export const parseMonths: Parser<Month[]> = value => list(value, item => {
  const row = object(item); const anio = id(row.anio); const mes = id(row.mes);
  if ((mes !== null && (mes < 1 || mes > 12)) || (anio !== null && (anio < 1 || anio > 9999))) return invalid();
  return {anio, mes, importe: amount(row.importe), cantidad_facturas: count(row.cantidad_facturas)};
});
export const parseProducts: Parser<Product[]> = value => list(value, item => {
  const row = object(item); return {producto_key: count(row.producto_key), stock_item_id: id(row.stock_item_id),
    stock_item_name: text(row.stock_item_name), ventas_sin_impuestos: amount(row.ventas_sin_impuestos)};
});
export const parseCustomers: Parser<Customer[]> = value => list(value, item => {
  const row = object(item); return {cliente_key: count(row.cliente_key), customer_id: id(row.customer_id),
    customer_name: text(row.customer_name), ventas_sin_impuestos: amount(row.ventas_sin_impuestos)};
});
export function apiBase(value: string) {
  const url = new URL(value);
  if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
    throw new Error('Configura VITE_API_BASE_URL con una URL HTTP(S) sin credenciales.');
  return url.href.replace(/\/$/,'');
}
export async function fetchApi<T>(path: string, parse: Parser<T>, signal: AbortSignal): Promise<T> {
  const base = apiBase(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000');
  const response = await fetch(`${base}/api/v1${path}`, {signal, credentials:'omit', headers:{Accept:'application/json'}});
  if (!response.ok) throw new Error('No se pudo consultar la API.');
  return parse(await response.json());
}
