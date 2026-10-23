import assert from 'node:assert/strict';
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
console.log('Conversación: continuidad, reinicio, rotación y contrato sin identidad ni permisos verificados.');
