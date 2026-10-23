import assert from 'node:assert/strict';
import {profilePresentation} from '../web/profiles.js';
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
for(const role of ['customer','supervisor']){
  const unavailable=chatErrorReply({code:'DEPENDENCY_UNAVAILABLE',message:'No se confirmó la operación.'},role);
  assert.ok(unavailable.includes('No se confirmó la operación'));
  assert.ok(!unavailable.includes('permitió'));
}
console.log('Perfiles: Camila, Diego, supervisión, ejemplos, rechazos y errores coherentes.');
