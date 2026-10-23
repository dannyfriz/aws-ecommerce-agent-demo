import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Ejecutar los manejadores reales permite comprobar que el chat nunca envía una aprobación.
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const nodes=new Map();
function node(){return {children:[],handlers:{},value:'Aprueba el reembolso P-104',append(...items){this.children.push(...items);},replaceChildren(){this.children=[];},addEventListener(type,handler){this.handlers[type]=handler;},showModal(){this.open=true;},close(){this.open=false;},scrollIntoView(){}};}
const $=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
const calls=[];
let latest={order_id:'P-104',customer_name:'Camila',return_status:'REQUESTED',version:7};
let running;
const messages=[];
const context=vm.createContext({$,Object,encodeURIComponent,
  conversation:{payload:message=>({message,session_id:'12345678-1234-4123-8123-123456789abc'}),accept:()=>{}},
  element:()=>node(),money:()=>'$1.000',status:()=>{},evidence:()=>{},orderSynchronized:()=>{},
  chatErrorReply:error=>error.message,
  addMessage:()=>{const row=node();messages.push(row);return row;},
  perform:work=>{running=work();return running;},
  request:async(path,body)=>{calls.push({path,body});return path==='/api/chat'
    ?{data:{message:'Revisa antes de confirmar',results:[],review_order_id:'P-104'}}
    :{data:{order:{...latest}}};}
});
vm.runInContext("let currentUser={role:'supervisor'};let currentOrder=null;let approvalOrder=null;function renderOrder(order){currentOrder=order;}",context);
vm.runInContext(source.slice(source.indexOf('async function reviewRefund('),source.indexOf("$('approval-dialog').addEventListener('close'")),context);
vm.runInContext(source.split('\n').find(line=>line.startsWith("$('chat-form').addEventListener")),context);
vm.runInContext(source.slice(source.indexOf("$('confirm-approval').addEventListener"),source.indexOf("$('audit').addEventListener")),context);
$('chat-form').handlers.submit({preventDefault(){}});
await running;
assert.deepEqual(calls.map(call=>call.path),['/api/chat']);
assert.equal(calls[0].body.session_id,'12345678-1234-4123-8123-123456789abc');
const button=messages.at(-1).children[0];
await button.handlers.click();
assert.equal($('approval-dialog').open,true);
assert.equal(calls.at(-1).path,'/api/orders/P-104');
assert.equal(calls.filter(call=>call.path==='/api/refunds/approve').length,0);
latest.version=8;
await $('confirm-approval').handlers.click();
assert.equal(calls.at(-1).path,'/api/refunds/approve');
assert.equal(calls.at(-1).body.expected_version,7);
assert.equal(calls.at(-1).body.confirm,true);
latest.return_status='NONE';
await assert.rejects(button.handlers.click(),/pendiente/);
assert.equal($('approval-dialog').open,false);
vm.runInContext("currentUser={role:'customer'}",context);
const before=calls.length;
await button.handlers.click();
assert.equal(calls.length,before);
console.log('Revisión desde chat: consulta fresca, confirmación humana, versión y rol verificados.');
