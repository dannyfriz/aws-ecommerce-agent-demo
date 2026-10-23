const actions = {
  'chat:clarify':'El asistente necesita una aclaración',
  'policy:read':'Consulta de políticas de la demo',
  'preferences:write':'Preferencia de respuesta guardada',
  'pending:read':'Consulta de solicitudes pendientes',
  reset_order:'Reinicio del pedido para la actividad',
  read_order:'Consulta de pedido', request_return:'Solicitud de devolución',
  approve_refund:'Aprobación de reembolso', chat:'Consulta al asistente',
  'audit:read':'Consulta de auditoría'
};
const reasons = {
  REFUND_WINDOW_EXPIRED:'No aplica reembolso en este laboratorio: la compra supera los 90 días permitidos desde la fecha registrada. El pedido no se modificó. Es una regla de la demo.',
  PURCHASE_DATE_UNAVAILABLE:'No se puede comprobar el plazo de reembolso porque falta una fecha de compra válida. El servidor bloqueó la operación y el pedido no se modificó. Debe revisarse el dato registrado.',
  GUARDRAIL_BLOCKED:'El filtro de contenido bloqueó la consulta. Reformúlala sin contraseñas, datos sensibles ni instrucciones para evadir controles. No se ejecutaron acciones sobre pedidos.',
  PREFERENCE_UPDATED:'Se guardó el nivel de detalle elegido. Tus permisos no cambiaron.',
  POLICY_INFORMATION_ONLY:'Se consultaron las políticas ficticias de la demo. Esta información no autoriza ni modifica pedidos.',
  MISSING_ORDER:'Falta el número del pedido. Puedes responderlo en el siguiente mensaje.',
  AMBIGUOUS_ORDER:'Hay más de un pedido mencionado. Indica con cuál quieres continuar.',
  UNKNOWN_INTENT:'Aclara si quieres consultar un pedido o solicitar una devolución.',
  PENDING_SUPERVISOR_REQUIRED:'La bandeja de solicitudes pendientes está disponible solo para supervisión. Puedes consultar el estado de tus propios pedidos.',
  CHAT_APPROVAL_REQUIRES_REVIEW:'Tu perfil de cliente no permite aprobar reembolsos. Escribir «soy gerente» no cambia la identidad de tu sesión. La aprobación requiere revisión de supervisión; el pedido no se modificó.',
  RESET_SUPERVISOR_REQUIRED:'Solo el perfil de supervisión puede reiniciar la actividad de un pedido.',
  LAB_RESET:'El pedido volvió a estar sin devolución. Se conservó el historial y aumentó su versión.',
  ALREADY_RESET:'El pedido ya estaba sin devolución. No se aplicó otro cambio.',
  AUTHORIZED:'El servidor verificó los permisos para esta operación.',
  ALREADY_REQUESTED:'La devolución ya estaba registrada. El reintento no creó otra solicitud.',
  ALREADY_APPROVED:'El reembolso ya estaba aprobado. El reintento no repitió la aprobación.',
  RESOURCE_NOT_AUTHORIZED:'Esta cuenta no puede acceder al pedido indicado. Revisa su identificador y usa un pedido autorizado.',
  OWNER_REQUIRED:'Solo la persona propietaria del pedido puede solicitar su devolución.',
  HUMAN_SUPERVISOR_REQUIRED:'La aprobación requiere una persona con perfil de supervisión.',
  SUPERVISOR_REQUIRED:'Solo el perfil de supervisión puede consultar la auditoría.',
  MODEL_TOOL_NOT_ALLOWED:'El asistente no puede aprobar reembolsos ni ejecutar acciones fuera de las herramientas permitidas.',
  TOOL_NOT_ALLOWED:'La acción solicitada no está habilitada.',
  ROLE_NOT_ALLOWED:'El perfil de esta sesión no está habilitado para la actividad.',
  INVALID_CONFIRMATION:'Falta confirmar el pedido y la versión revisada antes de continuar.',
  STALE_OR_INVALID_STATE:'El pedido cambió o no tiene una devolución pendiente. Consulta su estado antes de continuar.',
  CONCURRENT_CHANGE:'Otra operación modificó el pedido. Actualízalo y revisa su estado.',
  MODEL_INVALID_RESPONSE:'El asistente no logró identificar una operación válida. No se ejecutó ninguna herramienta. Escribe, por ejemplo: «Consulta el pedido P-104», usando un pedido de tu cuenta.'
};

export function errorExplanation(error,role) {
  if(role==='supervisor'){
    const messages={
      CHAT_APPROVAL_REQUIRES_REVIEW:'Puedes aprobar solicitudes pendientes como supervisión, pero debes revisar y confirmar desde «Revisar reembolso». El chat no realiza esa aprobación; el pedido no se modificó.',
      OWNER_REQUIRED:'La devolución debe solicitarla el cliente propietario. Como supervisión puedes consultar su pedido y revisar la solicitud cuando esté enviada.',
      MODEL_TOOL_NOT_ALLOWED:'El chat de supervisión consulta pedidos de clientes. Para aprobar o reiniciar, usa los botones del pedido con confirmación explícita.',
      MODEL_INVALID_RESPONSE:'No se ejecutó ninguna herramienta. Indica el número del pedido del cliente para consultarlo. La aprobación y el reinicio se realizan desde sus botones, fuera del chat.',
      RESOURCE_NOT_AUTHORIZED:'No puedes acceder al pedido indicado. Revisa su número o la vigencia de tu sesión de supervisión.'
    };
    if(messages[error.reason] || messages[error.code])return messages[error.reason] || messages[error.code];
  }
  return reasons[error.reason] || reasons[error.code] || error.message;
}

export function chatErrorReply(error,role) {
  if(error.reason==='REFUND_WINDOW_EXPIRED' || error.code==='REFUND_WINDOW_EXPIRED')return reasons.REFUND_WINDOW_EXPIRED+(role==='supervisor'?' El perfil de supervisión también debe respetar este plazo.':' Puedes consultar el pedido, pero no enviar una devolución fuera de plazo.');
  if(error.reason==='PURCHASE_DATE_UNAVAILABLE' || error.code==='PURCHASE_DATE_UNAVAILABLE')return reasons.PURCHASE_DATE_UNAVAILABLE;
  if(role==='supervisor'){
    const replies={
      CHAT_APPROVAL_REQUIRES_REVIEW:'Tienes perfil de supervisión, pero la aprobación no se realiza por chat. Consulta el pedido del cliente y, si hay una solicitud pendiente, usa «Revisar reembolso» para revisar y confirmar tu decisión. No modifiqué el pedido.',
      OWNER_REQUIRED:'Como supervisión no puedes iniciar una devolución por el cliente. El propietario debe enviarla desde su cuenta. Puedo consultar el pedido y mostrarte si ya tiene una solicitud para revisar.',
      MODEL_TOOL_NOT_ALLOWED:'Tu perfil permite revisar solicitudes de clientes, pero no aprobarlas desde el chat. Consulta el pedido y usa «Revisar reembolso» si hay una solicitud pendiente. Para repetir la actividad usa «Reiniciar pedido (demo)».',
      HUMAN_SUPERVISOR_REQUIRED:'Aunque tu perfil sea de supervisión, la aprobación requiere una revisión y confirmación explícita en «Revisar reembolso»; no se realiza por chat.',
      TOOL_NOT_ALLOWED:'Esa acción no está disponible en el chat de supervisión. Puedo consultar pedidos y solicitudes de clientes. La aprobación y el reinicio tienen botones separados.',
      MODEL_INVALID_RESPONSE:'No pude identificar una consulta válida y no se ejecutó ninguna herramienta. Como supervisión, indica el número del pedido del cliente para revisar su estado. La devolución la solicita el propietario; tú puedes revisar reembolsos pendientes o reiniciar la actividad desde los botones del pedido.',
      RESOURCE_NOT_AUTHORIZED:'No puedo acceder al pedido indicado con tu sesión de supervisión. Revisa el número y vuelve a ingresar si tu sesión venció.'
    };
    if(replies[error.reason] || replies[error.code])return replies[error.reason] || replies[error.code];
    if(error.code==='ACCESS_DENIED' || error.code==='HTTP_403')return 'El servidor rechazó esta operación para tu sesión de supervisión. Revisa el pedido y la acción. Puedo consultar pedidos de clientes; las aprobaciones y reinicios requieren sus controles de confirmación.';
  }
  const replies = {
    CHAT_APPROVAL_REQUIRES_REVIEW:'No puedo aprobar el reembolso: tu sesión tiene perfil de cliente. Escribir «soy gerente» no cambia tus permisos. Si ya enviaste la solicitud, un supervisor debe revisarla desde su cuenta; puedo ayudarte a consultar su estado. No modifiqué el pedido.',
    RESOURCE_NOT_AUTHORIZED:'No puedo consultar ni modificar ese pedido desde tu cuenta. Revisa el número y usa un pedido asociado a tu usuario.',
    OWNER_REQUIRED:'Solo puedes solicitar la devolución de un pedido de tu propia cuenta. Consulta uno de tus pedidos para continuar.',
    HUMAN_SUPERVISOR_REQUIRED:'Tu perfil de cliente no puede aprobar reembolsos. Puedes enviar la solicitud de devolución de tu pedido; un supervisor revisará y confirmará la decisión desde su cuenta.',
    MODEL_TOOL_NOT_ALLOWED:'No puedo ejecutar esa acción. Como cliente puedes consultar tus pedidos y solicitar devoluciones. La aprobación requiere revisión humana por un supervisor desde su cuenta.',
    TOOL_NOT_ALLOWED:'Esa acción no está disponible en el asistente. Puedes pedirme consultar un pedido o solicitar su devolución.',
    RESET_SUPERVISOR_REQUIRED:'No puedo reiniciar pedidos desde el chat. El perfil de supervisión puede hacerlo con «Reiniciar pedido (demo)».',
    SUPERVISOR_REQUIRED:'La auditoría solo está disponible para supervisión mediante «Actualizar auditoría». Puedo ayudarte con las consultas permitidas para tu cuenta.',
    ROLE_NOT_ALLOWED:'Tu sesión no tiene un perfil habilitado para esta actividad. Ingresa con una cuenta de cliente o supervisión.',
    MODEL_INVALID_RESPONSE:'No pude convertir tu mensaje en una acción válida y no se ejecutó ninguna herramienta. Como cliente puedes consultar tus pedidos y solicitar devoluciones. Indica el número de un pedido asociado a tu cuenta. Si ya enviaste una solicitud, puedo consultar su estado; la aprobación y el reinicio requieren la cuenta de supervisión.'
  };
  if (replies[error.reason] || replies[error.code]) return replies[error.reason] || replies[error.code];
  if (error.code === 'ACCESS_DENIED' || error.code === 'HTTP_403') {
    return 'El servidor no permitió esta operación con tu sesión actual. Revisa la cuenta y los permisos de tu perfil. Puedo ayudarte a consultar pedidos y solicitar devoluciones autorizadas.';
  }
  return `No pude completar la solicitud. ${errorExplanation(error) || 'Consulta el estado de la API y vuelve a intentar.'}`;
}

export function decisionEvidence(data, label, role) {
  const action = actions[data.action] || label;
  const title = data.created_at ? `${action} · ${data.order_id || 'sin pedido'} · ${data.created_at}` : action;
  const lines = [];
  if (data.decision === 'CLARIFY') {
    lines.push('Se pidió información adicional. No se consultó ni modificó ningún pedido.');
  } else if (data.decision === 'DENY') {
    lines.push(['REFUND_WINDOW_EXPIRED','PURCHASE_DATE_UNAVAILABLE'].includes(data.reason)
      ?'Operación rechazada: el servidor aplicó una regla de negocio del laboratorio.'
      :'Acceso rechazado: el servidor bloqueó la operación.');
  } else if (data.decision === 'ALLOW') {
    lines.push('Acceso permitido: el servidor autorizó la operación para esta cuenta.');
  }
  if (data.decision !== 'DENY' && (data.action === 'read_order' || (data.order && data.executed === undefined))) {
    lines.push(role==='supervisor'?'Se consultó el pedido del cliente; su estado no fue modificado.':role==='customer'?'Se consultó tu pedido; su estado no fue modificado.':'Se consultó el pedido; su estado no fue modificado.');
  } else if (data.executed === false && data.decision !== 'CLARIFY' && data.action !== 'policy:read') {
    lines.push(data.decision === 'DENY'
      ? 'La acción fue bloqueada antes de ejecutarse.'
      : data.action === 'reset_order'
        ? 'El pedido ya estaba listo para repetir la actividad. No se modificó su estado.'
      : 'No se aplicó un nuevo cambio. La operación ya estaba registrada.');
  } else if (data.executed === true) {
    lines.push(data.action === 'reset_order'
      ? 'El pedido quedó listo para repetir la actividad. Su historial de auditoría se conserva.'
      : data.order?.return_status === 'REQUESTED'
      ? 'Solicitud enviada a revisión. El reembolso sigue pendiente de aprobación humana por supervisión.'
      : data.order?.return_status === 'REFUNDED' || data.action === 'approve_refund'
        ? 'El reembolso fue aprobado en la demo. No se transfieren fondos.'
        : 'La operación autorizada se ejecutó.');
  }
  if (reasons[data.reason]) lines.push(errorExplanation({reason:data.reason},role));
  return {title, lines};
}
