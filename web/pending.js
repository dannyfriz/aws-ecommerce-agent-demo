// La bandeja es solo para supervisión; cada apertura vuelve a consultar el pedido autorizado.
export function createPendingQueue({getSession,isPaused,readPage,onUpdated,onFailure}) {
  let loading=false;
  let cursor=null;
  return async function refreshPending(after=cursor) {
    const session=getSession();
    if(loading || session?.role!=='supervisor' || isPaused())return;
    loading=true;
    const active=()=>getSession()===session && !isPaused();
    try {
      const result=await readPage(after);
      if(!active())return;
      const data=result?.data;
      if(!Array.isArray(data?.orders) || data.orders.length>25 ||
         data.orders.some(order=>order.return_status!=='REQUESTED') ||
         (data.next_after!==null && (typeof data.next_after!=='string' || !/^[A-Za-z0-9_-]{1,64}$/.test(data.next_after)))) {
        throw new Error('La respuesta de solicitudes pendientes no es válida.');
      }
      cursor=after;
      onUpdated(result,{after,nextAfter:data.next_after});
    } catch(error) {
      if(active())onFailure(error);
    } finally {loading=false;}
  };
}
