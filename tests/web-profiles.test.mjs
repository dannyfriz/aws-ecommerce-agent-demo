import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {profilePresentation,orderPurchasePresentation} from '../web/profiles.js';
import {chatErrorReply,errorExplanation,decisionEvidence} from '../web/evidence.js';

for(const [username,order] of [['camila','P-104'],['diego','P-205']]){
  const view=profilePresentation({username,role:'customer'});
  assert.equal(view.order,order);
  assert.ok(view.greeting.includes(username));
  assert.ok(view.examples.every(([,message])=>message.includes(order)));
  assert.ok(view.placeholder.includes(order));
  const denied=chatErrorReply({reason:'MODEL_TOOL_NOT_ALLOWED'},'customer');
  assert.ok(denied.includes('desde su cuenta'));
  assert.ok(!denied.includes('«Revisar reembolso»'));
}
const supervisor=profilePresentation({username:'sofia',role:'supervisor'});
assert.ok(supervisor.greeting.includes('sofia'));
assert.ok(supervisor.help.includes('clientes'));
assert.ok(supervisor.examples.every(([,message])=>!message.includes('mi pedido')));
assert.ok(supervisor.examples[1][1].startsWith('Consulta'));
for(const role of ['customer','supervisor']){
  const reply=chatErrorReply({reason:'CHAT_APPROVAL_REQUIRES_REVIEW'},role);
  assert.ok(!reply.includes('convertir tu mensaje'));
  assert.ok(reply.includes(role==='customer'?'«soy gerente»':'«Revisar reembolso»'));
  assert.ok(reply.includes('No modifiqué el pedido'));
}
assert.ok(chatErrorReply({reason:'OWNER_REQUIRED'},'supervisor').includes('El propietario debe enviarla'));
const unclear=chatErrorReply({code:'MODEL_INVALID_RESPONSE'},'supervisor');
assert.ok(unclear.includes('pedido del cliente'));
assert.ok(!unclear.includes('pedido asociado a tu cuenta'));
assert.ok(errorExplanation({reason:'RESOURCE_NOT_AUTHORIZED'},'supervisor').includes('sesión de supervisión'));
assert.ok(decisionEvidence({decision:'ALLOW',order:{}},'Consulta','supervisor').lines.some(line=>line.includes('pedido del cliente')));
assert.ok(decisionEvidence({decision:'ALLOW',order:{}},'Consulta','customer').lines.some(line=>line.includes('tu pedido')));
assert.ok(!decisionEvidence({decision:'DENY',action:'read_order',executed:false},'Consulta','supervisor').lines.some(line=>line.includes('Se consultó')));
assert.throws(()=>profilePresentation({username:'intruso',role:'administrator'}));
assert.equal(profilePresentation({username:'otro-cliente',role:'customer'}).order,undefined);
const diego=profilePresentation({username:'diego',role:'customer'});
assert.equal(diego.order,'P-205');
assert.ok(diego.expiredReturnExample[0].includes('P-206'));
assert.equal(diego.expiredReturnExample[1],'Solicita la devolución de mi pedido P-206');
assert.ok(diego.greeting.includes('más de 90 días'));
assert.equal(profilePresentation({username:'camila',role:'customer'}).expiredReturnExample,undefined);
assert.equal(supervisor.expiredReturnExample,undefined);
const recent=orderPurchasePresentation({purchased_on:'2026-09-23',purchase_age_days:30,refund_eligible:true});
assert.deepEqual(recent.rows,[['Fecha de compra','23/09/2026'],['Antigüedad de compra','30 días'],['Plazo para reembolso','Dentro del plazo de la demo']]);
assert.ok(recent.notice.includes('no aprueba el reembolso'));
assert.equal(orderPurchasePresentation({purchased_on:'2026-07-25',purchase_age_days:90,refund_eligible:true}).state,'eligible');
const expired=orderPurchasePresentation({purchased_on:'2026-06-25',purchase_age_days:120,refund_eligible:false});
assert.equal(expired.state,'expired');
assert.ok(expired.rows.some(([,value])=>value==='120 días'));
assert.ok(expired.notice.includes('rechazo del servidor'));
assert.ok(!expired.notice.includes('permiso'));
assert.ok(orderPurchasePresentation({purchased_on:'2026-06-25',purchase_age_days:120,refund_eligible:false},'supervisor').notice.includes('supervisión también debe respetar'));
for(const order of [{}, {purchased_on:null,purchase_age_days:null,refund_eligible:false}, {purchased_on:'2026-11-01',purchase_age_days:null,refund_eligible:false}]){
  const unknown=orderPurchasePresentation(order);
  assert.equal(unknown.state,'unavailable');
  assert.ok(unknown.notice.includes('fecha de compra válida'));
}
for(const role of ['customer','supervisor']){
  const unavailable=chatErrorReply({code:'DEPENDENCY_UNAVAILABLE',message:'No se confirmó la operación.'},role);
  assert.ok(unavailable.includes('No se confirmó la operación'));
  assert.ok(!unavailable.includes('permitió'));
}

// La tarjeta usa los datos del servidor y permite observar el rechazo real, sin aprobar en el navegador.
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const nodes=new Map();
function node(tag,text=''){return {tag,textContent:String(text),children:[],dataset:{},handlers:{},append(...children){this.children.push(...children);},replaceChildren(){this.children=[];},addEventListener(type,fn){this.handlers[type]=fn;},focus(){this.focused=true;}};}
const $=id=>{if(!nodes.has(id))nodes.set(id,node('div'));return nodes.get(id);};
const calls=[];
let running;
const context=vm.createContext({$,orderPurchasePresentation,profilePresentation,
  element:node,money:()=>'$1.000',orderSynchronized(){},evidence(){},status(){},
  perform:work=>{running=work();return running;},
  request:async(path,body)=>{calls.push({path,body});throw Object.assign(new Error('Compra fuera del plazo de la demo'),{code:'REFUND_WINDOW_EXPIRED'});}
});
vm.runInContext("let currentUser={username:'diego',role:'customer'};let currentOrder=null;let busy=false;",context);
vm.runInContext(source.slice(source.indexOf('function renderOrder('),source.indexOf('async function perform(')),context);
vm.runInContext(source.split('\n').find(line=>line.startsWith("$('expired-return-example').addEventListener")),context);
vm.runInContext(source.split('\n').find(line=>line.startsWith("$('return').addEventListener")),context);
vm.runInContext("renderOrder({order_id:'P-206',customer_name:'Diego',return_status:'NONE',version:1,purchased_on:'2026-06-25',purchase_age_days:120,refund_eligible:false})",context);
const rows=$('order').children[0].children.map(child=>child.textContent);
assert.ok(rows.includes('25/06/2026'));
assert.ok(rows.includes('120 días'));
assert.ok(rows.includes('Fuera del plazo de la demo'));
assert.equal($('return').disabled,false);
assert.equal($('approve').disabled,true);
$('expired-return-example').handlers.click();
assert.equal($('message').value,'Solicita la devolución de mi pedido P-206');
assert.equal($('message').focused,true);
assert.equal(calls.length,0);
$('return').handlers.click();
await assert.rejects(running,error=>error.code==='REFUND_WINDOW_EXPIRED');
assert.equal(calls.length,1);
assert.equal(calls[0].path,'/api/tools');
assert.equal(calls[0].body.order_id,'P-206');
assert.deepEqual(Object.keys(calls[0].body).sort(),['action','order_id']);
vm.runInContext("currentUser={username:'sofia',role:'supervisor'};renderOrder(currentOrder)",context);
assert.equal($('return').disabled,true);
console.log('Perfiles: Camila, Diego, supervisión, ejemplos, rechazos y errores coherentes.');
