const TRANSACTION_KEY = 'tienda-clara.oauth.pending';
let accessToken = null;

function checkedUrl(value, name) {
  const url = new URL(value);
  const local = ['localhost', '127.0.0.1'].includes(url.hostname);
  if (url.protocol !== 'https:' && !(local && url.protocol === 'http:')) throw new Error(`${name} debe usar HTTPS.`);
  if (url.username || url.password || url.hash || url.search) throw new Error(`${name} contiene componentes no permitidos.`);
  return url;
}

export function configuration() {
  const config = window.APP_CONFIG;
  if (!config?.clientId || !config?.region) throw new Error('Falta publicar la configuración de AWS. Revisa la guía de despliegue.');
  const api = checkedUrl(config.apiBaseUrl, 'La API');
  const domain = checkedUrl(config.cognitoDomain, 'Cognito');
  const redirect = checkedUrl(config.redirectUri, 'La redirección');
  if (redirect.origin !== location.origin || redirect.pathname !== location.pathname) throw new Error('La redirección debe coincidir con esta aplicación.');
  if (domain.pathname !== '/' || api.pathname !== '/') throw new Error('La API y Cognito deben indicar únicamente el origen.');
  return {...config, apiBaseUrl:api.origin, cognitoDomain:domain.origin, redirectUri:redirect.href};
}

function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
}

export async function signIn() {
  const config = configuration();
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(48)));
  const state = base64url(crypto.getRandomValues(new Uint8Array(24)));
  const challenge = base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))));
  sessionStorage.setItem(TRANSACTION_KEY, JSON.stringify({verifier,state,createdAt:Date.now()}));
  const url = new URL('/oauth2/authorize', config.cognitoDomain);
  url.search = new URLSearchParams({response_type:'code',client_id:config.clientId,redirect_uri:config.redirectUri,scope:config.scope,state,code_challenge:challenge,code_challenge_method:'S256'});
  location.assign(url.href);
}

export async function completeSignIn() {
  const config = configuration();
  const params = new URLSearchParams(location.search);
  if (!params.has('code') && !params.has('error')) return false;
  let pending;
  try { pending = JSON.parse(sessionStorage.getItem(TRANSACTION_KEY) || 'null'); } catch { pending = null; }
  sessionStorage.removeItem(TRANSACTION_KEY);
  const age = pending ? Date.now() - pending.createdAt : Infinity;
  const valid = pending && params.get('state') === pending.state && age >= 0 && age <= 600000;
  history.replaceState({}, '', location.pathname);
  if (!valid) throw new Error('La sesión de ingreso venció o no corresponde a esta ventana. Vuelve a ingresar.');
  if (params.has('error')) throw new Error('El ingreso fue cancelado o rechazado por Cognito.');
  const response = await fetch(`${config.cognitoDomain}/oauth2/token`, {method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({grant_type:'authorization_code',client_id:config.clientId,code:params.get('code'),redirect_uri:config.redirectUri,code_verifier:pending.verifier}),credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer'});
  if (!response.ok) throw new Error('No se pudo completar el ingreso. Inicia sesión nuevamente.');
  const tokens = await response.json();
  if (typeof tokens.access_token !== 'string') throw new Error('Cognito no entregó un access token válido.');
  accessToken = tokens.access_token;
  // Los tokens permanecen exclusivamente en memoria y no se escriben en almacenamiento.
  return true;
}

export function token() { return accessToken; }

export function signOut() {
  accessToken = null;
  sessionStorage.removeItem(TRANSACTION_KEY);
  const config = configuration();
  const url = new URL('/logout',config.cognitoDomain);
  url.search = new URLSearchParams({client_id:config.clientId,logout_uri:config.redirectUri});
  location.replace(url.href);
}
