export function validateSupabaseUrl(url: string): string {
  if (!/^https:\/\/[a-z0-9]{20}\.supabase\.co\/?$/.test(url)) {
    throw new Error('VITE_SUPABASE_URL debe ser una URL pública HTTPS de Supabase, sin credenciales.');
  }
  return url.replace(/\/$/, '');
}
export function publicAuthConfig(url: string, key: string) {
  const publicUrl=validateSupabaseUrl(url);
  if (!/^sb_publishable_[A-Za-z0-9_-]+$/.test(key)) {
    throw new Error('Configura VITE_SUPABASE_PUBLISHABLE_KEY con la clave pública del proyecto.');
  }
  return {url: publicUrl, key};
}
