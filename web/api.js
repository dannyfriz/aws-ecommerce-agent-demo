import {configuration,token} from './auth.js';

export async function checkApiHealth() {
  const response = await fetch(`${configuration().apiBaseUrl}/api/health`, {
    signal:AbortSignal.timeout(8000),credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer'
  });
  if (!response.ok) throw new Error('API no disponible');
  const result = await response.json();
  if (result.ok !== true || result.data?.status !== 'ok') throw new Error('Respuesta de estado inválida');
}

export async function request(path, body, {signal} = {}) {
  if (!token()) throw new Error('Inicia sesión para continuar.');
  const response = await fetch(`${configuration().apiBaseUrl}${path}`, {method:body === undefined?'GET':'POST',headers:{Authorization:`Bearer ${token()}`,...(body === undefined?{}:{'Content-Type':'application/json'})},...(body === undefined?{}:{body:JSON.stringify(body)}),...(signal?{signal}:{}),credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer'});
  let result;
  try { result = await response.json(); } catch { throw new Error('El servidor devolvió una respuesta inesperada.'); }
  if (!response.ok || !result.ok) {
    const explanations = {
      401:'Tu sesión venció o no es válida. Cierra sesión y vuelve a ingresar.',
      403:'Tu perfil no tiene permiso para esta acción. Revisa la cuenta con la que ingresaste.',
      429:'Hay demasiadas solicitudes en este momento. Espera unos segundos y vuelve a intentar.',
      502:'No pudimos procesar la respuesta del servicio. Vuelve a intentar la consulta.',
      503:'El servicio no está disponible. No se confirmó la operación; consulta el pedido antes de volver a intentar.'
    };
    const error = new Error(result.error?.message || explanations[response.status] || 'No fue posible completar la solicitud. Vuelve a intentar o revisa el estado de la API.');
    error.code = result.error?.code || `HTTP_${response.status}`;
    error.reason = result.error?.reason;
    error.requestId = result.request_id;
    throw error;
  }
  return result;
}
