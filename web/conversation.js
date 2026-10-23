const sessionPattern=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

// El servidor combina este identificador con la identidad validada; no es una credencial.
export function createConversation(newId=()=>crypto.randomUUID()) {
  let sessionId=newId();
  return {
    payload(message){return {message,session_id:sessionId};},
    accept(data){if(typeof data.session_id==='string' && sessionPattern.test(data.session_id))sessionId=data.session_id;},
    reset(){sessionId=newId();}
  };
}
