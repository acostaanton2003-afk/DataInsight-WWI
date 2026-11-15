import {publicAuthConfig} from './authConfig';
export {publicAuthConfig} from './authConfig';
import {createClient, type SupabaseClient} from '@supabase/supabase-js';

let client: SupabaseClient | null = null;
export function getSupabaseClient(): SupabaseClient | null {
  if (client) return client;
  try {
    const config = publicAuthConfig(import.meta.env.VITE_SUPABASE_URL || '', import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || '');
    client = createClient(config.url, config.key, {auth: {
      persistSession: true, autoRefreshToken: true, detectSessionInUrl: false,
      storage: window.sessionStorage, storageKey: 'datainsight-wwi-auth',
    }});
    return client;
  } catch {return null;}
}
export async function getAccessToken(): Promise<string | null> {
  const auth = getSupabaseClient();
  if (!auth) return null;
  const {data, error} = await auth.auth.getSession();
  if (error || !data.session || !data.session.expires_at || data.session.expires_at <= Date.now()/1000) return null;
  return data.session.access_token;
}
