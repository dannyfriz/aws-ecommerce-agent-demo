// Estos textos orientan la interfaz; la autorización continúa siendo responsabilidad del servidor.
export function profilePresentation(user) {
  const name=user.username || 'participante';
  if(user.role==='supervisor')return {
    label:'Supervisión (supervisor)',
    permissions:'Puedes consultar pedidos de clientes, revisar la auditoría, aprobar reembolsos pendientes con confirmación explícita y reiniciar pedidos de la demo.',
    help:'Consulta pedidos y solicitudes de clientes. Puedes pedir al asistente que prepare la revisión de un reembolso; tú revisas los datos y confirmas la aprobación.',
    placeholder:'Por ejemplo: consulta el pedido P-104 del cliente',
    greeting:`Hola, ${name}. Estás en supervisión. En «Solicitudes pendientes» puedes abrir los pedidos de clientes que requieren revisión. Tú revisas y confirmas los reembolsos con «Revisar reembolso». Para repetir la actividad, puedes usar «Reiniciar pedido (demo)».`,
    status:'Sesión de supervisión iniciada. Consulta un pedido de cliente para revisar su estado.',
    examples:[['Consultar P-104','Consulta el pedido P-104'],['Ver solicitud del cliente','Consulta el estado de la devolución del pedido P-104'],['Preparar revisión','Ayúdame a aprobar el reembolso del pedido P-104']]
  };
  if(user.role==='customer'){
    const order={camila:'P-104',diego:'P-205'}[user.username];
    return {
      label:'Cliente (customer)',
      permissions:'Puedes consultar tus propios pedidos y enviar solicitudes de devolución. Un supervisor revisa y decide sobre el reembolso; no puedes aprobarlo ni reiniciar pedidos.',
      help:'Consulta tus pedidos o envía una solicitud de devolución. Te indicaré si quedó en espera de supervisión o si el reembolso ya fue aprobado en la demo.',
      placeholder:order?`Por ejemplo: consulta mi pedido ${order}`:'Indica el número de uno de tus pedidos',
      greeting:`Hola, ${name}. Puedo ayudarte a consultar tus pedidos y solicitar devoluciones. Una solicitud enviada queda en espera de un supervisor; solicitarla no aprueba el reembolso.${order?` Para comenzar, puedes consultar tu pedido de práctica ${order}.`:''}`,
      status:'Tu sesión de cliente está iniciada. Consulta uno de tus pedidos para comenzar.',
      order,
      examples:order?[[`Consultar ${order}`,`Consulta mi pedido ${order}`],['Solicitar devolución',`Solicita la devolución de mi pedido ${order}`],['Probar el límite del chat',`Aprueba mi reembolso de ${order}`]]:[['Consultar mi pedido','Quiero consultar un pedido; necesito indicar su número'],['Solicitar devolución','Quiero solicitar una devolución; necesito indicar el pedido'],['Probar el límite del chat','Aprueba mi reembolso']]
    };
  }
  throw new Error('Tu sesión no tiene un perfil habilitado para esta actividad.');
}
