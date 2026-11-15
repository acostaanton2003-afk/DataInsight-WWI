import {it,expect,vi} from 'vitest';
import {render,screen,fireEvent,waitFor,act} from '@testing-library/react';
import type {Session,SupabaseClient} from '@supabase/supabase-js';
import {AuthGate} from '../components/AuthGate';
import {Dashboard} from '../App';
import {ApiError,requestJson,UNAUTHORIZED_EVENT,FORBIDDEN_EVENT} from '../lib/http';
import {parseIdentity,type Identity,type Role} from '../lib/identity';
import {getAccessToken,publicAuthConfig} from '../lib/supabase';
import {kpis,months,products,customers,predictions} from './fixtures';

const USER='11111111-1111-4111-8111-111111111111';
const PERMISSIONS={
  VIEWER:['profile:read','general:read'],
  ANALYST:['profile:read','general:read','customers:read','predictions:read','assistant:use'],
  ADMIN:['profile:read','general:read','customers:read','predictions:read','assistant:use','roles:manage'],
};
function identity(role:Role='ADMIN'):Identity{return {user_id:USER,role,permissions:PERMISSIONS[role] as Identity['permissions']};}
function session(token='synthetic-test-token',expires=Math.floor(Date.now()/1000)+3600):Session {
  return {access_token:token,refresh_token:'synthetic-refresh',expires_at:expires,user:{id:USER}} as Session;
}
function fakeClient(initial:Session|null=null){
  let listener:((event:string,next:Session|null)=>void)|undefined;
  const unsubscribe=vi.fn();
  const emit=(next:Session|null)=>listener?.(next?'TOKEN_REFRESHED':'SIGNED_OUT',next);
  const auth={
    getSession:vi.fn().mockResolvedValue({data:{session:initial},error:null}),
    onAuthStateChange:vi.fn(callback=>{listener=callback;return {data:{subscription:{unsubscribe}}};}),
    signInWithPassword:vi.fn().mockImplementation(async()=>{emit(session());return {data:{session:session()},error:null};}),
    signOut:vi.fn().mockImplementation(async()=>{emit(null);return {error:null};}),
  };
  return {client:{auth} as unknown as SupabaseClient,auth,emit,unsubscribe};
}
function mockFetch(role:Role='ADMIN'){
  const values:Record<string,unknown>={'/auth/me':identity(role),'/kpis':kpis,'/ventas/por-mes':months,
    '/productos/top?limit=10':products,'/clientes/top?limit=10':customers,'/predicciones/ventas':predictions};
  const fetch=vi.fn(async(url:string)=>new Response(JSON.stringify(values[url.split('/api/v1')[1]])));
  vi.stubGlobal('fetch',fetch);return fetch;
}
function gated(client:SupabaseClient|null){return render(<AuthGate client={client}>{(_identity,signOut)=><><p>Contenido protegido</p><button onClick={()=>void signOut()}>Cerrar sesión</button></>}</AuthGate>);}
function submitLogin(){
  fireEvent.change(screen.getByLabelText('Correo electrónico'),{target:{value:'fixture@example.invalid'}});
  fireEvent.change(screen.getByLabelText('Contraseña'),{target:{value:'synthetic-test-password'}});
  fireEvent.click(screen.getByRole('button',{name:'Entrar'}));
}
vi.mock('../components/Chart',()=>({Chart:()=> <div role="img"/>}));

it('no monta datos ni envía solicitudes antes del login',async()=>{
  const fake=fakeClient();const fetch=mockFetch();gated(fake.client);
  await screen.findByRole('heading',{name:'Iniciar sesión.'});
  expect(screen.queryByText('Contenido protegido')).toBeNull();expect(fetch).not.toHaveBeenCalled();
});
it('login correcto usa SDK y valida el rol con FastAPI',async()=>{
  const fake=fakeClient();const fetch=mockFetch();gated(fake.client);
  await screen.findByLabelText('Correo electrónico');submitLogin();await screen.findByText('Contenido protegido');
  expect(fake.auth.signInWithPassword).toHaveBeenCalledWith({email:'fixture@example.invalid',password:'synthetic-test-password'});
  expect(fetch).toHaveBeenCalledTimes(1);expect(fetch.mock.calls[0][0]).toContain('/auth/me');
});
it('login incorrecto es genérico y borra contraseña',async()=>{
  const fake=fakeClient();fake.auth.signInWithPassword.mockResolvedValue({error:{status:400,message:'secret-detail'}});
  const fetch=mockFetch();gated(fake.client);await screen.findByLabelText('Correo electrónico');submitLogin();
  await screen.findByRole('alert');expect(screen.queryByText('secret-detail')).toBeNull();
  expect((screen.getByLabelText('Contraseña') as HTMLInputElement).value).toBe('');expect(fetch).not.toHaveBeenCalled();
});
it('restaura sesión y se desuscribe al desmontar',async()=>{
  const fake=fakeClient(session());mockFetch();const view=gated(fake.client);
  await screen.findByText('Contenido protegido');view.unmount();expect(fake.unsubscribe).toHaveBeenCalled();
});
it('sesión expirada no muestra datos',async()=>{
  const fake=fakeClient(session('expired',1));const fetch=mockFetch();gated(fake.client);
  await screen.findByLabelText('Correo electrónico');expect(fetch).not.toHaveBeenCalled();
  expect(screen.queryByText('Contenido protegido')).toBeNull();
});
it('renovación de token vuelve a obtener identidad antes de mostrar contenido',async()=>{
  const fake=fakeClient(session());const fetch=mockFetch();gated(fake.client);await screen.findByText('Contenido protegido');
  vi.mocked(getAccessToken).mockResolvedValue('synthetic-renewed');
  fireEvent(window,new Event('noop'));fake.emit(session('synthetic-renewed'));
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));await screen.findByText('Contenido protegido');
});
it('logout elimina contenido y evita recuperación de respuestas pendientes',async()=>{
  const fake=fakeClient(session());mockFetch();gated(fake.client);await screen.findByText('Contenido protegido');
  fireEvent.click(screen.getByRole('button',{name:'Cerrar sesión'}));await screen.findByLabelText('Correo electrónico');
  expect(fake.auth.signOut).toHaveBeenCalledWith({scope:'local'});expect(screen.queryByText('Contenido protegido')).toBeNull();
});
it('error de logout oculta datos y permite reintentar',async()=>{
  const fake=fakeClient(session());mockFetch();gated(fake.client);await screen.findByText('Contenido protegido');
  fake.auth.signOut.mockResolvedValueOnce({error:{message:'private error'}});
  fireEvent.click(screen.getByRole('button',{name:'Cerrar sesión'}));await screen.findByText('Cierre de sesión pendiente');
  expect(screen.queryByText('Contenido protegido')).toBeNull();expect(screen.queryByText('private error')).toBeNull();
  fireEvent.click(screen.getByText('Reintentar cierre'));await screen.findByLabelText('Correo electrónico');
});
it.each([403,503,429])('error de perfil %s bloquea contenido sin revelar respuesta',async status=>{
  const fake=fakeClient(session());vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('private',{status})));gated(fake.client);
  await screen.findByRole('alert');expect(screen.queryByText('Contenido protegido')).toBeNull();expect(screen.queryByText('private')).toBeNull();
});
it('401 del backend retira sesión y contenido',async()=>{
  const fake=fakeClient(session());mockFetch();gated(fake.client);await screen.findByText('Contenido protegido');
  window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));await screen.findByLabelText('Correo electrónico');
  expect(screen.queryByText('Contenido protegido')).toBeNull();
});
it('403 oculta datos y revalida solo por reintento manual, sin bucles',async()=>{
  const fake=fakeClient(session());const fetch=mockFetch();gated(fake.client);await screen.findByText('Contenido protegido');
  act(()=>window.dispatchEvent(new Event(FORBIDDEN_EVENT)));await screen.findByRole('alert');
  expect(fetch).toHaveBeenCalledTimes(1);expect(screen.queryByText('Contenido protegido')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Reintentar'}));
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));await screen.findByText('Contenido protegido');
});
it.each(['VIEWER','ANALYST','ADMIN'] as Role[])('dashboard %s solo consulta recursos permitidos',async role=>{
  const fetch=mockFetch(role);render(<Dashboard identity={identity(role)} onSignOut={async()=>{}}/>);
  await screen.findByText('33,00');
  const restricted=role==='VIEWER';expect(fetch).toHaveBeenCalledTimes(restricted?3:5);
  expect(screen.queryByRole('link',{name:'Clientes'})===null).toBe(restricted);
  expect(screen.queryByRole('heading',{name:'Asistente IA'})===null).toBe(restricted);
  if(restricted){expect(screen.queryByText('Cliente ficticio')).toBeNull();expect(screen.queryByText('Predicciones')).toBeNull();}
});
it('falta de clave pública bloquea aplicación sin datos falsos',()=>{
  const fetch=mockFetch();gated(null);expect(screen.getByText('Configuración pendiente')).toBeTruthy();expect(fetch).not.toHaveBeenCalled();
});
it('Bearer no se envía a una URL de cliente ni se hace fetch anónimo',async()=>{
  const fetch=mockFetch();
  await expect(requestJson('https://attacker.invalid',new AbortController().signal)).rejects.toThrow();
  vi.mocked(getAccessToken).mockResolvedValue(null);
  await expect(requestJson('/api/v1/kpis',new AbortController().signal)).rejects.toMatchObject({status:401});
  expect(fetch).not.toHaveBeenCalled();
});
it.each([401,403,429,503])('HTTP %s usa un error tipado sin cuerpo sensible',async status=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('secret-body',{status})));
  await expect(requestJson('/api/v1/auth/me',new AbortController().signal)).rejects.toBeInstanceOf(ApiError);
});
it('GET y POST incluyen token y evitan cookies y redirecciones',async()=>{
  const fetch=vi.fn().mockResolvedValue(new Response('{}'));vi.stubGlobal('fetch',fetch);
  await requestJson('/api/v1/kpis',new AbortController().signal);
  expect(fetch.mock.calls[0][1]).toMatchObject({credentials:'omit',redirect:'error',headers:{Authorization:'Bearer synthetic-test-token'}});
});
it('no acepta claves secretas ni URLs no oficiales',()=>{
  expect(()=>publicAuthConfig('https://abcdefghijklmnopqrst.supabase.co','sb_publishable_fixture')).not.toThrow();
  expect(()=>publicAuthConfig('https://abcdefghijklmnopqrst.supabase.co','sb_secret_fixture')).toThrow();
  expect(()=>publicAuthConfig('https://attacker.invalid','sb_publishable_fixture')).toThrow();
});
it('rechaza identidad con rol o permisos desconocidos',()=>{
  expect(()=>parseIdentity({...identity(),role:'ROOT'})).toThrow();
  expect(()=>parseIdentity({...identity(),permissions:['execute:sql']})).toThrow();
});

it('ignora respuestas de perfil tardías tras cerrar sesión',async()=>{
  const fake=fakeClient(session());let resolve!: (response:Response)=>void;
  const fetch=vi.fn(()=>new Promise<Response>(done=>{resolve=done;}));vi.stubGlobal('fetch',fetch);
  gated(fake.client);await waitFor(()=>expect(fetch).toHaveBeenCalled());
  act(()=>fake.emit(null));await screen.findByLabelText('Correo electrónico');
  await act(async()=>{resolve(new Response(JSON.stringify(identity())));});
  expect(screen.queryByText('Contenido protegido')).toBeNull();
});
it('un 401 tardío de otro token no cierra una sesión renovada',async()=>{
  const listener=vi.fn();window.addEventListener(UNAUTHORIZED_EVENT,listener);
  vi.mocked(getAccessToken).mockResolvedValueOnce('synthetic-old').mockResolvedValueOnce('synthetic-new');
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('',{status:401})));
  await expect(requestJson('/api/v1/kpis',new AbortController().signal)).rejects.toMatchObject({status:401});
  expect(listener).not.toHaveBeenCalled();window.removeEventListener(UNAUTHORIZED_EVENT,listener);
});
it('el rol efectivo del backend gobierna la UI aunque metadata anuncie ADMIN',async()=>{
  const next=session();next.user.app_metadata={role:'ADMIN'};
  const fake=fakeClient(next);const fetch=mockFetch('VIEWER');
  render(<AuthGate client={fake.client}>{(effective,signOut)=><Dashboard identity={effective} onSignOut={signOut}/>}</AuthGate>);
  await screen.findByText('33,00');expect(fetch).toHaveBeenCalledTimes(4);
  expect(screen.queryByText('Cliente ficticio')).toBeNull();expect(screen.queryByRole('heading',{name:'Asistente IA'})).toBeNull();
});
it('envía el Bearer también en POST del asistente',async()=>{
  const fetch=vi.fn().mockResolvedValue(new Response('{}'));vi.stubGlobal('fetch',fetch);
  await requestJson('/api/v1/asistente/consultar',new AbortController().signal,{pregunta:'KPI sintético'});
  expect(fetch.mock.calls[0][1]).toMatchObject({method:'POST',headers:{Authorization:'Bearer synthetic-test-token','Content-Type':'application/json'},body:JSON.stringify({pregunta:'KPI sintético'})});
});
it('un perfil de otro usuario no monta contenido',async()=>{
  const fake=fakeClient(session());vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({...identity(),user_id:'22222222-2222-4222-8222-222222222222'}))));
  gated(fake.client);await screen.findByRole('alert');expect(screen.queryByText('Contenido protegido')).toBeNull();
});
