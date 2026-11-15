export function publicAuthConfig(url: string, key: string) {
  if (!/^https:\/\/[a-z0-9]{20}\.supabase\.co\/?$/.test(url) || !/^sb_publishable_[A-Za-z0-9_-]+$/.test(key)) {
    throw new Error('Configura VITE_SUPABASE_URL y VITE_SUPABASE_PUBLISHABLE_KEY con valores públicos del proyecto.');
  }
  return {url: url.replace(/\/$/, ''), key};
}
