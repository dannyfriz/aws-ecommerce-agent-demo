import {configuration,completeSignIn,signIn,signOut} from './auth.js';
import {request,checkApiHealth} from './api.js';
import {decisionEvidence,errorExplanation,chatErrorReply} from './evidence.js';
import {createOrderSync} from './order-sync.js';
import {profilePresentation} from './profiles.js';
import {createPendingQueue} from './pending.js';
import {createConversation} from './conversation.js';

const $ = id => document.getElementById(id);
let currentOrder = null;
let approvalOrder = null;
let resetOrder = null;
let currentUser = null;
let busy = false;
let checkingHealth = false;
let pendingNext=null;
let pendingSignature='';
let responseDetail='brief';
const conversation=createConversation();

const refreshPending=createPendingQueue({
  getSession:()=>currentUser,
  isPaused:()=>busy || document.hidden || $('approval-dialog').open || $('reset-dialog').open,
  readPage:after=>request(`/api/refunds/pending${after?`?after=${encodeURIComponent(after)}`:''}`,undefined,{signal:AbortSignal.timeout(8000)}),
  onUpdated:(result,{after,nextAfter})=>{
    pendingNext=nextAfter;
    $('pending-first').hidden=!after;
    $('pending-next').hidden=!nextAfter;
    $('pending-count').textContent=`${result.data.orders.length} en esta página`;
    const signature=JSON.stringify([after,result.data]);
    if(signature!==pendingSignature){
      $('pending-list').replaceChildren();
      if(!result.data.orders.length)$('pending-list').append(element('p',after?'No hay solicitudes vigentes en esta página. Puedes volver al inicio.':'No hay solicitudes pendientes de revisión en esta página.'));
      for(const order of result.data.orders){
        const card=element('article','');card.className='pending-item';
        card.append(element('h3',order.order_id),element('p',`Cliente: ${order.customer_name || 'No registrado'}`),element('p',`${order.product} · ${money(order)}`));
        const button=element('button','Abrir pedido');button.type='button';
        button.addEventListener('click',()=>perform(async()=>{
          const fresh=await request(`/api/orders/${encodeURIComponent(order.order_id)}`);
          $('order-id').value=order.order_id;
          renderOrder(fresh.data.order);
          evidence('Pedido abierto desde solicitudes pendientes',fresh);
          $('order-title').scrollIntoView({block:'start',behavior:'smooth'});
          status(fresh.data.order.return_status==='REQUESTED'?'Solicitud abierta. Usa «Revisar reembolso» para revisar y confirmar tu decisión.':'El pedido ya no tiene una solicitud pendiente. Se mostró su estado actualizado.');
        }));
        card.append(button);$('pending-list').append(card);
      }
      pendingSignature=signature;
    }
    $('pending-status').dataset.state='online';
    $('pending-status').textContent=`Actualizado a las ${new Date().toLocaleTimeString('es-CL')}. Se actualiza cada 15 segundos. Abrir un pedido no aprueba el reembolso.`;
  },
  onFailure:error=>{
    $('pending-status').dataset.state='error';
    $('pending-status').textContent=`No se pudieron actualizar las solicitudes. La lista puede estar desactualizada. ${errorExplanation(error,currentUser?.role) || 'Vuelve a intentar.'}`;
  }
});
$('refresh-pending').addEventListener('click',()=>refreshPending());
$('pending-first').addEventListener('click',()=>refreshPending(null));
$('pending-next').addEventListener('click',()=>{if(pendingNext)refreshPending(pendingNext);});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshPending();});
window.addEventListener('online',()=>refreshPending());
window.addEventListener('focus',()=>refreshPending());
window.setInterval(()=>refreshPending(),15000);

function orderSynchronized() {
  $('order-sync').dataset.state='online';
  $('order-sync').textContent=`Pedido sincronizado a las ${new Date().toLocaleTimeString('es-CL')}. Se actualiza cada 15 segundos mientras esta pestaña esté visible.`;
}
const refreshOrder=createOrderSync({
  getOrder:()=>currentOrder,
  getSession:()=>currentUser,
  isPaused:()=>busy || document.hidden || $('approval-dialog').open || $('reset-dialog').open,
  readOrder:id=>request(`/api/orders/${encodeURIComponent(id)}`,undefined,{signal:AbortSignal.timeout(8000)}),
  onUpdated:(result,changed)=>{
    if(changed){
      renderOrder(result.data.order);
      evidence('Pedido actualizado desde el servidor',result);
      status(`${currentUser.role==='supervisor'?'El pedido del cliente':'Tu pedido'} ${currentOrder.order_id} cambió en otra sesión. Se actualizó su estado y versión.`);
    }
    orderSynchronized();
  },
  onFailure:error=>{
    $('order-sync').dataset.state='error';
    $('order-sync').textContent=`No se pudo sincronizar el pedido. El estado mostrado puede estar desactualizado. ${errorExplanation(error,currentUser?.role) || 'Vuelve a consultar el pedido.'}`;
  }
});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshOrder();});
window.addEventListener('online',refreshOrder);
window.addEventListener('focus',refreshOrder);
window.setInterval(refreshOrder,15000);

async function refreshApiStatus() {
  if (checkingHealth || document.hidden) return;
  checkingHealth = true;
  const indicator = $('api-status');
  indicator.dataset.state = 'checking';
  indicator.textContent = 'API · Comprobando…';
  try {
    await checkApiHealth();
    indicator.dataset.state = 'online';
    indicator.textContent = 'API · Disponible';
  } catch {
    indicator.dataset.state = 'offline';
    indicator.textContent = navigator.onLine ? 'API · Sin respuesta' : 'API · Sin conexión';
  } finally { checkingHealth = false; }
}

$('refresh-api').addEventListener('click',refreshApiStatus);
document.addEventListener('visibilitychange',()=>{ if (!document.hidden) refreshApiStatus(); });
window.addEventListener('online',refreshApiStatus);
window.setInterval(refreshApiStatus,60000);
refreshApiStatus();

function status(message) { $('status').textContent = message; $('status').dataset.state = 'info'; }
function element(tag,text) { const node=document.createElement(tag); node.textContent=String(text ?? ''); return node; }
function money(order) { return new Intl.NumberFormat('es-CL',{style:'currency',currency:order.currency || 'CLP',maximumFractionDigits:0}).format(order.amount); }
function addMessage(who,message) { const row=element('div',''); row.className='message'; row.append(element('strong',who),document.createTextNode(String(message))); $('conversation').append(row); row.scrollIntoView({block:'nearest'}); return row; }
function evidence(label,result) {
  const data=result.data || {};
  const description=decisionEvidence(data,label,currentUser?.role);
  const row=element('li',description.title);
  for (const line of description.lines) row.append(element('small',line));
  const details=element('details','');
  details.append(element('summary','Detalles técnicos para la actividad'));
  details.append(element('small',`Identificador de solicitud: ${result.request_id || 'no disponible'}`));
  for (const [name,value] of [['Decisión',data.decision],['Motivo',data.reason],['Código',result.code]]) {
    if(value)details.append(element('small',`${name}: ${value}`));
  }
  row.append(details);
  $('evidence').prepend(row);
}
function failure(error) { const message=errorExplanation(error,currentUser?.role); status(message); $('status').dataset.state = 'error'; evidence(message,{request_id:error.requestId,code:error.code,data:{reason:error.reason}}); }
function renderOrder(order,{synchronized=true}={}) {
  currentOrder=order;
  $('order').replaceChildren();
  const list=element('dl','');
  const labels={NONE:'Sin devolución',REQUESTED:'Solicitud enviada · En espera de supervisión',REFUNDED:'Reembolso aprobado'};
  for(const [label,value] of [['Pedido',order.order_id],['Cliente',order.customer_name || 'No registrado'],['Producto',order.product],['Monto',money(order)],['Estado',order.status],['Devolución',labels[order.return_status] || order.return_status],['Versión',order.version]]) list.append(element('dt',label),element('dd',value));
  $('order').append(list);
  $('return').disabled=busy || currentUser?.role!=='customer' || order.return_status!=='NONE';
  $('approve').disabled=busy || currentUser?.role!=='supervisor' || order.return_status!=='REQUESTED';
  $('reset-order').disabled=busy || currentUser?.role!=='supervisor' || order.return_status==='NONE';
  if(synchronized)orderSynchronized();
}
async function perform(task,onFailure) {
  if (busy) return;
  busy=true;
  const buttons=[...document.querySelectorAll('#workspace button,#workspace select')];
  const previous=buttons.map(button=>button.disabled);
  buttons.forEach(button=>{button.disabled=true;});
  try { await task(); } catch(error) { if(onFailure)onFailure(error); failure(error); }
  finally { busy=false; buttons.forEach((button,index)=>{button.disabled=previous[index];}); if(currentOrder) renderOrder(currentOrder,{synchronized:false}); refreshPending(); }
}

$('login').addEventListener('click',()=>signIn().catch(failure));
$('clear-evidence').addEventListener('click',()=>{
  if(busy)return;
  $('evidence').replaceChildren();
  status('Evidencias visibles reiniciadas. Puedes comenzar otra ronda; los pedidos y la auditoría del servidor se conservaron.');
});
$('logout').addEventListener('click',()=>{ $('workspace').hidden=true; currentUser=null; currentOrder=null; conversation.reset(); $('conversation').replaceChildren(); $('evidence').replaceChildren(); try {signOut();} catch(error){failure(error);} });
$('new-conversation').addEventListener('click',()=>{
  if(busy)return;
  conversation.reset(); $('conversation').replaceChildren();
  addMessage('Asistente',profilePresentation(currentUser).greeting);
  status('Comenzaste otra conversación. Indica el pedido nuevamente; los pedidos y la auditoría se conservaron.');
});
$('response-detail').addEventListener('change',()=>perform(async()=>{
  const result=await request('/api/preferences',{preferred_detail:$('response-detail').value});
  responseDetail=result.data.preferred_detail; $('response-detail').value=responseDetail;
  status('Preferencia guardada para tus próximas sesiones.');
},()=>{$('response-detail').value=responseDetail;}));
$('policy-example').addEventListener('click',()=>{$('message').value='¿Quién puede solicitar una devolución y quién aprueba el reembolso?';$('message').focus();});
document.querySelectorAll('[data-message]').forEach(button=>button.addEventListener('click',()=>{$('message').value=button.dataset.message; $('message').focus();}));
$('chat-form').addEventListener('submit',event=>{event.preventDefault(); const message=$('message').value.trim(); if(!message)return; perform(async()=>{addMessage('Tú',message); $('message').value=''; const result=await request('/api/chat',conversation.payload(message)); conversation.accept(result.data); const reply=addMessage('Asistente',result.data.message); for(const source of result.data.sources || [])reply.append(element('small',`Fuente: ${source.title}`)); if(currentUser?.role==='supervisor' && result.data.review_order_id){const id=result.data.review_order_id; const button=element('button','Revisar reembolso'); button.type='button'; button.addEventListener('click',()=>perform(()=>reviewRefund(id))); reply.append(button);} for(const item of result.data.results || []){ if(item.order){renderOrder(item.order);orderSynchronized();} evidence('Resultado de la herramienta',{request_id:result.request_id,data:item}); } if(!result.data.results?.length)evidence('Respuesta del asistente',result); status(result.data.clarification?'El asistente necesita una aclaración; responde en el chat.':result.data.memory_warning?'Respuesta confirmada; el contexto no se guardó.':'Solicitud procesada. Revisa la evidencia.');},error=>{conversation.reset(); addMessage('Asistente',chatErrorReply(error,currentUser?.role)+' Inicié una nueva conversación. Para continuar, indica nuevamente el número del pedido.');});});
$('order-form').addEventListener('submit',event=>{event.preventDefault(); perform(async()=>{const id=$('order-id').value.trim(); const result=await request(`/api/orders/${encodeURIComponent(id)}`); renderOrder(result.data.order); orderSynchronized(); evidence('Consulta de pedido',result); status('Pedido consultado.');});});
$('return').addEventListener('click',()=>perform(async()=>{if(!currentOrder)return; const result=await request('/api/tools',{action:'request_return',order_id:currentOrder.order_id}); renderOrder(result.data.order); evidence('Solicitud de devolución',result); status(result.data.order.return_status==='REFUNDED'?'El reembolso ya estaba aprobado en la demo. No se realizó otro cambio.':result.data.executed?'Solicitud enviada a revisión. Está en espera de un supervisor para evaluar el reembolso.':'La solicitud ya estaba enviada y sigue en espera de supervisión. No se duplicó.');}));
async function reviewRefund(orderId){
  if(currentUser?.role!=='supervisor')return;
  const result=await request(`/api/orders/${encodeURIComponent(orderId)}`);
  renderOrder(result.data.order);
  if(currentOrder.return_status!=='REQUESTED')throw new Error('El pedido no tiene una devolución pendiente.');
  approvalOrder=Object.freeze({...currentOrder});
  const list=$('approval-details'); list.replaceChildren();
  for(const [label,value]of [['Pedido',approvalOrder.order_id],['Cliente',approvalOrder.customer_name || 'Sin nombre registrado'],['Producto',approvalOrder.product],['Monto',money(approvalOrder)],['Versión revisada',approvalOrder.version]])list.append(element('dt',label),element('dd',value));
  $('approval-dialog').showModal();
}
$('approve').addEventListener('click',()=>perform(async()=>{if(currentOrder)await reviewRefund(currentOrder.order_id);}));
$('approval-dialog').addEventListener('close',()=>{approvalOrder=null;});
$('reset-order').addEventListener('click',()=>perform(async()=>{
  if(!currentOrder || currentUser?.role!=='supervisor')return;
  const result=await request(`/api/orders/${encodeURIComponent(currentOrder.order_id)}`);
  renderOrder(result.data.order);
  resetOrder=Object.freeze({...currentOrder});
  $('reset-description').textContent=`Vas a reiniciar el pedido ${resetOrder.order_id}, versión ${resetOrder.version}.`;
  $('reset-dialog').showModal();
}));
$('reset-dialog').addEventListener('close',()=>{resetOrder=null;});
$('confirm-reset').addEventListener('click',()=>perform(async()=>{
  if(!resetOrder || currentUser?.role!=='supervisor')return;
  const snapshot=resetOrder;
  $('reset-dialog').close();
  const result=await request('/api/orders/reset',{order_id:snapshot.order_id,expected_version:snapshot.version,confirm:true});
  renderOrder(result.data.order);
  evidence('Pedido reiniciado para la actividad',result);
  status('Pedido reiniciado. Su propietario puede volver a solicitar la devolución; el historial se conservó.');
}));
$('confirm-approval').addEventListener('click',()=>perform(async()=>{
  if(!approvalOrder || currentUser?.role!=='supervisor')return;
  const snapshot=approvalOrder;
  $('approval-dialog').close();
  const result=await request('/api/refunds/approve',{order_id:snapshot.order_id,expected_version:snapshot.version,confirm:true});
  renderOrder(result.data.order); evidence('Aprobación humana de reembolso',result); status('Reembolso autorizado en la demo. No se transfieren fondos.');
}));
$('audit').addEventListener('click',()=>perform(async()=>{
  const result=await request('/api/audit');
  for(const event of result.data.events || [])evidence(`${event.created_at} · ${event.order_id || 'sin pedido'}`,{request_id:event.request_id,data:event});
  status('Auditoría actualizada.');
}));

try {
  configuration();
  if(await completeSignIn()){
    const result=await request('/api/me'); currentUser=result.data;
    $('response-detail').parentElement.hidden=!currentUser.capabilities?.preferences;
    $('policy-example').hidden=!currentUser.capabilities?.policy_knowledge;
    $('conversation-help').textContent=currentUser.capabilities?.conversation_memory
      ?'Puedes continuar hablando del último pedido durante 15 minutos. Una nueva conversación vuelve a pedir su número.'
      :'Indica el número del pedido en cada mensaje. Nueva conversación limpia el chat visible.';
    if(currentUser.capabilities?.preferences){
      const preferences=await request('/api/preferences');
      responseDetail=preferences.data.preferred_detail; $('response-detail').value=responseDetail;
    }
    $('identity').textContent=currentUser.username || currentUser.sub;
    $('identity-sub').textContent=currentUser.sub;
    const presentation=profilePresentation(currentUser);
    $('role').textContent=presentation.label;
    $('role-permissions').textContent=presentation.permissions;
    $('chat-help').textContent=presentation.help;
    $('message').placeholder=presentation.placeholder;
    document.querySelectorAll('[data-message]').forEach((button,index)=>{
      button.textContent=presentation.examples[index][0];
      button.dataset.message=presentation.examples[index][1];
    });
    $('order-id').value=presentation.order || (currentUser.role==='supervisor'?'P-104':'');
    addMessage('Asistente',presentation.greeting);
    $('workspace').hidden=false; $('login').hidden=true; $('logout').hidden=false;
    $('approve').hidden=currentUser.role!=='supervisor'; $('audit').hidden=currentUser.role!=='supervisor';
    $('reset-order').hidden=currentUser.role!=='supervisor';
    $('pending-requests').hidden=currentUser.role!=='supervisor';
    refreshPending();
    status(presentation.status);
  }
}catch(error){failure(error);}
