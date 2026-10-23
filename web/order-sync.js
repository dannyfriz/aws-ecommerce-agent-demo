// Sincronizar solo la selección y sesión vigentes; nunca reemplazar una versión más nueva.
export function createOrderSync({getOrder,getSession,isPaused,readOrder,onUpdated,onFailure}) {
  let pending=false;
  return async function refreshOrder() {
    const selected=getOrder();
    const session=getSession();
    if(pending || !selected || !session || isPaused())return;
    const isCurrent=()=>getSession()===session && getOrder()?.order_id===selected.order_id && !isPaused();
    pending=true;
    try {
      const result=await readOrder(selected.order_id);
      if(!isCurrent())return;
      const order=result?.data?.order;
      if(order?.order_id!==selected.order_id || !Number.isInteger(order.version) || order.version<1) {
        throw new Error('El servidor devolvió un pedido inesperado.');
      }
      if(order.version<getOrder().version)return;
      onUpdated(result,order.version>getOrder().version);
    } catch(error) {
      if(isCurrent())onFailure(error);
    } finally { pending=false; }
  };
}
