import {useEffect, useState, type FormEvent, type ReactNode} from 'react';
import type {Session, SupabaseClient} from '@supabase/supabase-js';
import {getSupabaseClient} from '../lib/supabase';
import {fetchApi} from '../lib/api';
import {parseIdentity, type Identity} from '../lib/identity';
import {ApiError, errorMessage, FORBIDDEN_EVENT, UNAUTHORIZED_EVENT} from '../lib/http';

function LoginForm({client, notice}: {client: SupabaseClient; notice: string}) {
  const [email,setEmail]=useState('');
  const [password,setPassword]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  async function login(event: FormEvent) {
    event.preventDefault();setBusy(true);setError('');
    try {
      const result=await client.auth.signInWithPassword({email:email.trim(),password});
      if (result.error) setError(result.error.status===429 ? 'Demasiados intentos. Espera antes de reintentar.' : 'No se pudo iniciar sesión. Revisa tus datos o contacta al administrador.');
    } catch {setError('No se pudo iniciar sesión. Comprueba la conexión.');}
    finally {setPassword('');setBusy(false);}
  }
  return <section className="auth-card" aria-labelledby="login-title">
    <span className="eyebrow">ACCESO AL ESPACIO DE ANÁLISIS</span><h1 id="login-title">Iniciar sesión<span>.</span></h1>
    <p>Usa la cuenta habilitada por el administrador de DataInsight WWI.</p>
    {notice&&<p role="status">{notice}</p>}
    <form onSubmit={event=>void login(event)}>
      <label htmlFor="login-email">Correo electrónico</label><input id="login-email" type="email" autoComplete="username" value={email} onChange={event=>setEmail(event.target.value)} required maxLength={254} disabled={busy}/>
      <label htmlFor="login-password">Contraseña</label><input id="login-password" type="password" autoComplete="current-password" value={password} onChange={event=>setPassword(event.target.value)} required maxLength={1024} disabled={busy}/>
      {error&&<p className="auth-error" role="alert">{error}</p>}
      <button className="button" disabled={busy} type="submit">{busy?'Iniciando sesión…':'Entrar'}</button>
    </form><small>No se permite registro público desde esta aplicación.</small>
  </section>;
}

export function AuthGate({children,client=getSupabaseClient()}: {
  children:(identity:Identity,signOut:()=>Promise<void>)=>ReactNode; client?:SupabaseClient|null;
}) {
  const [session,setSession]=useState<Session|null|undefined>(undefined);
  const [profile,setProfile]=useState<{token:string;identity:Identity}|null>(null);
  const [failure,setFailure]=useState('');
  const [notice,setNotice]=useState('');
  const [retry,setRetry]=useState(0);
  const [signingOut,setSigningOut]=useState(false);
  const [logoutError,setLogoutError]=useState('');

  useEffect(()=>{
    if(!client)return;
    let active=true;let revision=0;let timer:number|undefined;
    async function recover(expected:number) {
      try {
        const {data,error}=await client!.auth.getSession();
        if(active&&expected===revision){
          setSession(error?null:data.session);
          if(error)setNotice('No se pudo recuperar la sesión. Inicia sesión de nuevo.');
        }
      } catch {
        if(active&&expected===revision){setSession(null);setNotice('No se pudo recuperar la sesión.');}
      }
    }
    // Events can come from another tab. Read THIS client's storage, not their payload.
    // Defer SDK calls until after the synchronous auth callback releases its lock.
    const {data:{subscription}}=client.auth.onAuthStateChange(()=>{
      const expected=++revision;window.clearTimeout(timer);
      timer=window.setTimeout(()=>void recover(expected),0);
    });
    void recover(++revision);
    return ()=>{active=false;window.clearTimeout(timer);subscription.unsubscribe();};
  },[client]);

  useEffect(()=>{
    if(!client)return;
    const unauthorized=()=>{
      setSession(null);setProfile(null);setNotice('La sesión no es válida o ha expirado. Inicia sesión de nuevo.');
      void client.auth.signOut({scope:'local'}).then(({error})=>{
        if(error)setNotice('No se pudo revocar la sesión. Cierra esta pestaña antes de abandonar el equipo.');
      }).catch(()=>setNotice('No se pudo revocar la sesión. Cierra esta pestaña.'));
    };
    const forbidden=()=>{setProfile(null);setFailure('El servidor rechazó el acceso. Revalida tus permisos con Reintentar o cierra sesión.');};
    window.addEventListener(UNAUTHORIZED_EVENT,unauthorized);window.addEventListener(FORBIDDEN_EVENT,forbidden);
    return ()=>{window.removeEventListener(UNAUTHORIZED_EVENT,unauthorized);window.removeEventListener(FORBIDDEN_EVENT,forbidden);};
  },[client]);

  useEffect(()=>{
    if(!session)return;
    if(!session.expires_at||session.expires_at*1000<=Date.now()){setSession(null);setNotice('La sesión ha expirado. Inicia sesión de nuevo.');return;}
    const controller=new AbortController();let active=true;
    setProfile(null);setFailure('');
    const timeout=window.setTimeout(()=>controller.abort(),25000);
    fetchApi('/auth/me',parseIdentity,controller.signal).then(identity=>{
      if(identity.user_id!==session.user.id)throw new Error('Identidad no válida.');
      if(active)setProfile({token:session.access_token,identity});
    }).catch(error=>{
      if(active){if(error instanceof ApiError&&error.status===401)setSession(null);else setFailure(errorMessage(error));}
    }).finally(()=>window.clearTimeout(timeout));
    return ()=>{active=false;controller.abort();window.clearTimeout(timeout);};
  },[session?.access_token,retry]);

  useEffect(()=>{
    if(!session||!client)return;
    let active=true;
    const remaining=(session.expires_at||0)*1000-Date.now();
    const timer=window.setTimeout(()=>{
      setProfile(null);
      void client.auth.getSession().then(({data,error})=>{
        if(!active)return;
        const next=data.session;
        if(error||!next||!next.expires_at||next.expires_at*1000<=Date.now()){
          setSession(null);setNotice('La sesión ha expirado. Inicia sesión de nuevo.');
        }else setSession(next);
      }).catch(()=>{if(active){setSession(null);setNotice('La sesión ha expirado.');}});
    },Math.min(Math.max(remaining,0),2147483647));
    return ()=>{active=false;window.clearTimeout(timer);};
  },[session,client]);

  async function signOut() {
    if(!client)return;
    setSigningOut(true);setProfile(null);setLogoutError('');
    try {
      const {error}=await client.auth.signOut({scope:'local'});
      if(error)throw new Error();
      setSession(null);setNotice('Sesión cerrada.');
    } catch {setLogoutError('No se pudo cerrar la sesión. Reintenta o cierra esta pestaña antes de abandonar el equipo.');}
    finally {setSigningOut(false);}
  }

  if(client&&session&&session.expires_at&&session.expires_at*1000>Date.now()&&profile?.token===session.access_token&&!signingOut&&!logoutError&&!failure){
    return <>{children(profile.identity,signOut)}</>;
  }
  return <main className="auth-shell"><div className="auth-brand">DataInsight <strong>WWI</strong></div>
    {!client?<section className="auth-card"><h1>Configuración pendiente</h1><p role="alert">Configura VITE_SUPABASE_URL y VITE_SUPABASE_PUBLISHABLE_KEY en frontend/.env.local.</p></section>:
      logoutError?<section className="auth-card"><h1>Cierre de sesión pendiente</h1><p role="alert">{logoutError}</p><button className="button" onClick={()=>void signOut()}>Reintentar cierre</button></section>:
      session===undefined||signingOut?<section className="auth-card" role="status">{signingOut?'Cerrando sesión…':'Recuperando sesión…'}</section>:
      !session?<LoginForm client={client} notice={notice}/>:
      failure?<section className="auth-card"><h1>Acceso no disponible</h1><p role="alert">{failure}</p><button className="button" onClick={()=>setRetry(value=>value+1)}>Reintentar</button><button className="button subtle" onClick={()=>void signOut()}>Cerrar sesión</button></section>:
      <section className="auth-card" role="status">Verificando permisos…</section>}
  </main>;
}
