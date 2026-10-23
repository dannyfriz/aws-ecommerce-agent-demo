import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {createConversation} from '../web/conversation.js';

const ids=['12345678-1234-4123-8123-123456789abc','22345678-1234-4123-8123-123456789abc'];
const conversation=createConversation(()=>ids.shift());
assert.equal(conversation.payload('Consulta P-104').session_id,'12345678-1234-4123-8123-123456789abc');
assert.deepEqual(conversation.payload('Quiero devolverlo'),{message:'Quiero devolverlo',session_id:'12345678-1234-4123-8123-123456789abc'});
conversation.accept({session_id:'../../otra-persona'});
assert.equal(conversation.payload('estado').session_id,'12345678-1234-4123-8123-123456789abc');
conversation.reset();
assert.equal(conversation.payload('estado').session_id,'22345678-1234-4123-8123-123456789abc');
conversation.accept({session_id:'32345678-1234-4123-8123-123456789abc'});
assert.equal(conversation.payload('estado').session_id,'32345678-1234-4123-8123-123456789abc');
assert.deepEqual(Object.keys(conversation.payload('hola')).sort(),['message','session_id']);

// Una falla abandona el contexto anterior y avisa; nunca repite una acción automáticamente.
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
for(const code of ['MEMORY_UNAVAILABLE','ACCESS_DENIED']){
  const ids=['42345678-1234-4123-8123-123456789abc','52345678-1234-4123-8123-123456789abc'];
  const state=createConversation(()=>ids.shift());
  const nodes=new Map();
  const $=id=>{if(!nodes.has(id))nodes.set(id,{value:'Consulta P-104',handlers:{},addEventListener(type,fn){this.handlers[type]=fn;}});return nodes.get(id);};
  const calls=[],messages=[];
  let running;
  const context=vm.createContext({$,conversation:state,currentUser:{role:'customer'},
    addMessage:(speaker,text)=>{messages.push({speaker,text});return {append(){}};},
    status(){},evidence(){},chatErrorReply:error=>error.message,
    perform:(work,onFailure)=>{running=work().catch(onFailure);},
    request:async(path,body)=>{calls.push({path,body});if(calls.length===1)throw Object.assign(new Error('Error controlado'),{code});return {data:{message:'Consulta confirmada',results:[],session_id:body.session_id}};}
  });
  vm.runInContext(source.split('\n').find(line=>line.startsWith("$('chat-form').addEventListener")),context);
  $('chat-form').handlers.submit({preventDefault(){}});
  await running;
  assert.equal(calls.length,1);
  assert.equal(calls[0].body.session_id,'42345678-1234-4123-8123-123456789abc');
  assert.match(messages.at(-1).text,/nueva conversación/);
  assert.match(messages.at(-1).text,/indica nuevamente el número/);
  $('message').value='Consulta P-104';
  $('chat-form').handlers.submit({preventDefault(){}});
  await running;
  assert.equal(calls.length,2);
  assert.equal(calls[1].body.session_id,'52345678-1234-4123-8123-123456789abc');
  assert.equal(calls.filter(call=>call.path!=='/api/chat').length,0);
}
console.log('Conversación: continuidad, reinicio, rotación y contrato sin identidad ni permisos verificados.');
