import {getAccessToken} from './supabase';

export const UNAUTHORIZED_EVENT = 'datainsight:unauthorized';
export const FORBIDDEN_EVENT = 'datainsight:forbidden';
const messages: Record<number,string> = {
  401: 'La sesión no es válida o ha expirado. Inicia sesión de nuevo.',
  403: 'Tu cuenta no tiene permiso para esta función.',
  429: 'Límite de consultas alcanzado. Espera un minuto antes de reintentar.',
  503: 'No se pudo consultar la API. Servicio temporalmente no disponible (503).',
};
export class ApiError extends Error {
  constructor(public readonly status: number) {super(messages[status] || 'No se pudo consultar la API.');}
}
export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : 'No se pudo consultar la API. Comprueba la conexión y reintenta.';
}
export function apiBase(value: string): string {
  const url = new URL(value);
  if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash ||
      (url.protocol === 'http:' && !['localhost','127.0.0.1','[::1]'].includes(url.hostname))) throw new Error('URL de API no válida.');
  return url.toString().replace(/\/$/,'');
}
export async function requestJson(path: string, signal: AbortSignal, body?: unknown): Promise<unknown> {
  if (!path.startsWith('/api/v1/') || path.includes('://')) throw new Error('Ruta de API no válida.');
  const token = await getAccessToken();
  if (signal.aborted) throw new DOMException('Solicitud cancelada.', 'AbortError');
  if (!token) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(401);
  }
  const response = await fetch(`${apiBase(import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000')}${path}`, {
    signal, credentials:'omit', redirect:'error', method: body === undefined ? 'GET' : 'POST',
    headers: {Accept:'application/json', Authorization:`Bearer ${token}`, ...(body === undefined ? {} : {'Content-Type':'application/json'})},
    ...(body === undefined ? {} : {body:JSON.stringify(body)}),
  });
  if (!response.ok) {
    if (response.status === 401 && !signal.aborted && token === await getAccessToken()) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    if (response.status === 403 && path !== '/api/v1/auth/me' && !signal.aborted) window.dispatchEvent(new Event(FORBIDDEN_EVENT));
    throw new ApiError(response.status);
  }
  return response.json();
}
