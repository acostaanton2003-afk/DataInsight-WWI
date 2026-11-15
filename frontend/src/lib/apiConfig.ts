export function apiBase(value: string): string {
  const url = new URL(value);
  if (!['http:','https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash ||
      (url.protocol === 'http:' && !['localhost','127.0.0.1','[::1]'].includes(url.hostname))) throw new Error('URL de API no válida.');
  return url.toString().replace(/\/$/,'');
}
