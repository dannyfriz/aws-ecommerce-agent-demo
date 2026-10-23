import assert from 'node:assert/strict';
import {createOrderSync} from '../web/order-sync.js';

let current={order_id:'P-104',version:3,return_status:'REFUNDED'};
let session={sub:'sofia'};
let paused=false;
let calls=0;
let updates=0;
let errors=0;
let resolveRequest;
const sync=createOrderSync({
  getOrder:()=>current,getSession:()=>session,isPaused:()=>paused,
  readOrder:()=>{calls++;return new Promise(resolve=>{resolveRequest=resolve;});},
  onUpdated:result=>{updates++;current=result.data.order;},onFailure:()=>{errors++;}
});
const respond=(version,order_id='P-104')=>resolveRequest({data:{order:{order_id,version,return_status:'NONE'}}});

// Un reinicio de otra sesión reemplaza el estado aprobado por la nueva versión.
let pending=sync();
await sync();
assert.equal(calls,1);
respond(4);
await pending;
assert.equal(current.return_status,'NONE');
assert.equal(current.version,4);

// Una consulta lenta no pisa una actualización más reciente de la misma pantalla.
pending=sync();
current={...current,version:6,return_status:'REQUESTED'};
respond(5);
await pending;
assert.equal(current.version,6);
assert.equal(current.return_status,'REQUESTED');

// Las respuestas de otro pedido o sesión no se aplican a la selección actual.
pending=sync();
current={order_id:'P-205',version:1};
respond(7);
await pending;
assert.equal(current.order_id,'P-205');
pending=sync();
session={sub:'otra-sesion'};
respond(8,'P-205');
await pending;
assert.equal(updates,1);

// La confirmación humana mantiene su versión; no se refresca detrás del diálogo.
paused=true;
const before=calls;
await sync();
assert.equal(calls,before);
paused=false;
pending=sync();
paused=true;
respond(9,'P-205');
await pending;
assert.equal(updates,1);
paused=false;
pending=sync();
respond(10,'P-INESPERADO');
await pending;
assert.equal(errors,1);

let failure;
const failed=createOrderSync({getOrder:()=>current,getSession:()=>session,isPaused:()=>false,
  readOrder:async()=>{throw new Error('Sin conexión');},onUpdated:()=>assert.fail(),onFailure:error=>{failure=error;}});
await failed();
assert.equal(failure.message,'Sin conexión');
assert.equal(current.order_id,'P-205');
console.log('Sincronización: reinicio entre sesiones, concurrencia, selección, confirmación y errores aprobados.');
