"""Sincroniza la oratoria de nivel 200 con el guion y las notas de la PPT final."""
import argparse
from html import escape
import json
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent
NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
PRESENTATION = ROOT / 'docs/presentaciones/Danny_Friz_SCD_2026_arquitectura_IA.pptx'
SOURCE = ROOT / 'docs/presentaciones/oratoria-nivel-200.json'


def clock(seconds):
    return f'{seconds // 60:02}:{seconds % 60:02}'


def load_plan(source):
    document = json.loads(source.read_text(encoding='utf-8'))
    plan = document['slides']
    if [item['slide'] for item in plan] != list(range(1, 31)):
        raise ValueError('Se necesitan las treinta diapositivas ordenadas, sin omisiones.')
    if document.get('main_slide_count', 22) != 22 or document.get('demo_pause_count', 3) != 3:
        raise ValueError('Se requieren veintidós diapositivas principales y tres pausas de demo.')
    if document['duration_seconds'] != 2100 or document.get('qa_seconds', 600) != 600:
        raise ValueError('El bloque contempla treinta y cinco minutos de charla y diez de preguntas.')
    if [item.get('section') for item in plan] != ['main'] * 22 + ['appendix'] * 8:
        raise ValueError('Las veintidós diapositivas principales deben preceder a los ocho anexos.')
    if any(type(item['seconds']) is not int or item['seconds'] < 0 for item in plan):
        raise ValueError('Cada duración debe ser un número entero de segundos, sin valores negativos.')
    if any(item['seconds'] == 0 for item in plan[:22]) or any(item['seconds'] != 0 for item in plan[22:]):
        raise ValueError('Solo las diapositivas principales tienen tiempo; los anexos deben indicar cero.')
    if sum(item['seconds'] for item in plan[:22]) != document['duration_seconds']:
        raise ValueError('Los tiempos del recorrido principal no coinciden con la duración declarada.')
    if [item['slide'] for item in plan if item.get('demo')] != [8, 10, 12]:
        raise ValueError('Las tres pausas de demo deben estar en las diapositivas principales 8, 10 y 12.')
    elapsed = 0
    for item in plan:
        if not item['speech'].strip() or not item['transition'].strip() or not item['definitions']:
            raise ValueError(f"Falta oratoria, transición o conceptos en la diapositiva {item['slide']}.")
        item.update(start=clock(elapsed), end=clock(elapsed + item['seconds']))
        elapsed += item['seconds']
    return document, plan


def notes_text(item):
    """Deja en PowerPoint únicamente el discurso listo para decir en voz alta."""
    return item['speech'].strip()


def replace_notes_body(content, text):
    xml = content.decode('utf-8')
    shapes = list(re.finditer(r'<p:sp(?:\s[^>]*)?>.*?</p:sp>', xml, re.S))
    bodies = [match for match in shapes if re.search(r'<p:ph\b[^>]*\btype="body"', match.group())]
    if len(bodies) != 1:
        raise ValueError('No se identificó un único cuadro de notas del expositor.')
    match = bodies[0]
    paragraphs = ''.join('<a:p><a:r><a:rPr lang="es-CL"/><a:t xml:space="preserve">' +
                         escape(line, quote=False) + '</a:t></a:r><a:endParaRPr lang="es-CL"/></a:p>'
                         for line in text.split('\n'))
    body = '<p:txBody><a:bodyPr/><a:lstStyle/>' + paragraphs + '</p:txBody>'
    updated, count = re.subn(r'<p:txBody>.*?</p:txBody>', lambda _: body, match.group(), flags=re.S)
    if count != 1:
        raise ValueError('No se pudo actualizar únicamente el texto de las notas.')
    result = xml[:match.start()] + updated + xml[match.end():]
    ET.fromstring(result)
    return result.encode('utf-8')


def update_presentation(source, output, plan):
    if output.resolve() == source.resolve():
        raise ValueError('Genera una copia nueva para revisar antes de reemplazar la PPT final.')
    output.parent.mkdir(parents=True, exist_ok=True)
    changes = {}
    with ZipFile(source) as archive:
        slides = ET.fromstring(archive.read('ppt/presentation.xml')).find('p:sldIdLst', NS)
        relations = {entry.get('Id'): entry.get('Target') for entry in
                     ET.fromstring(archive.read('ppt/_rels/presentation.xml.rels'))}
        if len(slides) != len(plan):
            raise ValueError('La cantidad de diapositivas no coincide con la oratoria.')
        for item, entry in zip(plan, slides):
            slide_path = posixpath.normpath('ppt/' + relations[entry.get('{' + NS['r'] + '}id')])
            rel_path = posixpath.dirname(slide_path) + '/_rels/' + posixpath.basename(slide_path) + '.rels'
            note_target = next(rel.get('Target') for rel in ET.fromstring(archive.read(rel_path))
                               if rel.get('Type', '').endswith('/notesSlide'))
            note_path = posixpath.normpath(posixpath.dirname(slide_path) + '/' + note_target)
            changes[note_path] = replace_notes_body(archive.read(note_path), notes_text(item))
        with ZipFile(output, 'w') as destination:
            for entry in archive.infolist():
                destination.writestr(entry, changes.get(entry.filename, archive.read(entry)))
    with ZipFile(source) as before, ZipFile(output) as after:
        if after.testzip() is not None or before.namelist() != after.namelist():
            raise ValueError('La estructura del paquete PPTX no se conservó.')
        for name in before.namelist():
            if name not in changes and before.read(name) != after.read(name):
                raise ValueError(f'Se modificó una parte ajena a las notas: {name}')
    return len(changes)


def render_guide(document, plan):
    main_slides = [item for item in plan if item['section'] == 'main']
    appendices = [item for item in plan if item['section'] == 'appendix']
    lines = [
        '# Guion de la demo en vivo: 35 minutos', '',
        'Recorrido principal de 22 diapositivas y 35 minutos, con tres pausas de demo. Los ocho anexos están ocultos en la presentación normal y sirven de apoyo para preguntas. El bloque propuesto de 45 minutos reserva los últimos diez minutos para conversar con el público. [Abrir la presentación](presentaciones/Danny_Friz_SCD_2026_arquitectura_IA.pptx).', '',
        'El hilo conductor es «¿Quién le dio permisos a tu IA?»: distinguir la identidad de la persona y la identidad de la aplicación, aplicar mínimo privilegio y credenciales temporales, y comprobar la autorización fuera del modelo. La demo propone contrastar una consulta permitida con operaciones bloqueadas y observar la evidencia. IAM y Amazon Bedrock AgentCore se presentan desde ese propósito; el cierre ofrece criterios para asignar responsables, revisar permisos y retirar accesos.', '',
        '## Cómo usar la oratoria', '',
        'Leer o adaptar **Oratoria para decir**. Las definiciones de los conceptos nuevos ya están dentro de ese discurso. **Conceptos de apoyo** y **Apoyo técnico** son referencias para preguntas, no un bloque adicional que se deba leer completo. Las indicaciones de demo describen qué hacer en la web y qué resultado comprobar.', '',
        'El avance es manual. Los tiempos del mapa corresponden solo a las diapositivas 1–22 e incluyen explicación, participación y uso de la web. Los anexos no agregan tiempo al ensayo principal: abrirlos únicamente si una pregunta requiere ese detalle.', '',
        'Las notas de PowerPoint contienen únicamente la oratoria, en un tono natural para decirla en voz alta. Los tiempos, las instrucciones de demo, las transiciones sugeridas y las referencias quedan en este guion. La [fuente de la oratoria](presentaciones/oratoria-nivel-200.json) mantiene ambos archivos sincronizados mediante `scripts/sync_presentation_notes.py`.', '',
        '## Preparación antes de proyectar', '',
        '- Usar perfiles independientes del navegador, o una ventana normal y otra incógnita. Dos ventanas incógnitas del mismo navegador comparten sesión.',
        '- Preparar la sesión de Camila, con perfil cliente, y una sesión separada de Sofía, con perfil supervisor, para consultar la auditoría. Verificar usuario y perfil cada vez que se cambie de ventana; el enlace no selecciona una cuenta automáticamente.',
        '- El access token, la credencial digital de acceso, dura quince minutos y la página no lo renueva. Ingresar como Camila cerca de la primera demo y renovar la sesión antes de las siguientes pruebas si venció. Preparar o renovar también la sesión de Sofía antes de abrir la auditoría. No proyectar contraseñas ni tokens.',
        '- Comprobar que P-104 corresponde a Camila y P-205 a otro cliente. La consulta de P-104 no cambia el pedido: no hace falta reiniciarlo para este recorrido. Registrar su estado y versión antes de empezar para poder comprobar que los intentos bloqueados no los modificaron.',
        '- Ensayar la consulta ajena desde Camila sin mostrar datos obtenidos con la otra cuenta. El rechazo no debe revelar si el pedido existe ni quién es su propietario.',
        '- Ensayar la petición de aprobación como Camila y el mensaje «soy gerente». Deben conservarse los permisos de la sesión real. La ruta de aprobación se explica en la diapositiva 16; no es una cuarta demo ni una herramienta disponible para el modelo.',
        '- Preparar la vista de evidencia y la auditoría de Sofía. Relacionar la consulta o el rechazo con su identificador de solicitud y verificar qué decisión se registró; no confundir un error técnico con una denegación por permisos.',
        '- Dejar listas la web y la PPT, ocultar notificaciones y mantener cerrado el identificador de identidad de Cognito.',
        '- El indicador de API consulta solamente /api/health. Ensayar también inicio de sesión, consulta por chat, recorrido Bedrock/AgentCore y auditoría: el indicador verde no comprueba la aplicación completa ni sus controles de autorización.',
        '- Mantener listos los diagramas de la PPT como respaldo. Si se usan capturas o grabaciones, identificarlas como un registro previo; no presentarlas como una ejecución en vivo. No desplegar Terraform durante la charla.', '',
        '## Mapa de tiempos del recorrido principal', '',
        '| Tiempo | Diapositiva | Tema | Cambio de ventana |', '|---|---|---|---|',
    ]
    for item in main_slides:
        surface = 'Web: ' + item['demo']['profile'] if item.get('demo') else 'PPT'
        lines.append(f"| {item['start']}–{item['end']} | {item['slide']} | {item['title']} | {surface} |")
    lines += ['', 'Las pausas están en las diapositivas 8, 10 y 12. En cada una se debe comprobar el resultado observado antes de describirlo como una ejecución exitosa o como un rechazo por permisos.', '',
              '## Oratoria del recorrido principal', '']
    lines += render_slide_guidance(main_slides, timed=True)
    lines += ['## Anexos: apoyo para preguntas', '',
              'Las diapositivas 23–30 están ocultas en el avance normal. No forman parte de los 35 minutos; elegir el anexo relacionado con la pregunta y volver al cierre al terminar.', '',
              '| Diapositiva | Tema de apoyo |', '|---|---|']
    lines += [f"| {item['slide']} | {item['title']} |" for item in appendices]
    lines += ['', '### Oratoria de apoyo', '']
    lines += render_slide_guidance(appendices, timed=False)
    lines += ['## Apoyo técnico: responsabilidades en el recorrido', '',
              '| Componente | Qué es y qué controla aquí |', '|---|---|',
              '| Cognito | Autentica a la persona y emite el token de acceso. |',
              '| API Gateway | Recibe las peticiones y valida el token y su alcance en las rutas de negocio. |',
              '| IAM | Define qué recursos y operaciones AWS puede usar la aplicación mediante su rol. No decide por sí solo si un pedido pertenece a Camila. |',
              '| Bedrock y Converse | Bedrock permite invocar el modelo; Converse es la API. El modelo interpreta el mensaje y propone una función; su propuesta no concede permisos. |',
              '| Herramienta | Función programada con datos de entrada definidos: read_order consulta y request_return solicita una devolución. |',
              '| Lambda backend | Coordina la petición y comprueba la propuesta del modelo. Usa la identidad de la sesión validada. |',
              '| AgentCore Gateway y Policy | Gateway ofrece acceso a las funciones y reconoce a la aplicación que llama. Policy aplica reglas al rol de esa aplicación y a las dos funciones disponibles. |',
              '| Lambda de herramientas | Verifica el contexto y comprueba persona, propietario y reglas antes de consultar o cambiar un pedido. |',
              '| Auditoría | Conserva evidencia de las decisiones del servidor para poder revisar el resultado y relacionarlo con una solicitud. |', '',
              'Las credenciales temporales de la aplicación se obtienen mediante su rol de ejecución y son distintas del token de la persona. La aprobación de reembolsos se confirma por una ruta separada, con perfil supervisor y versión del pedido; ningún chat ni herramienta Gateway la ejecuta. La respuesta final se construye con resultados comprobados, sin una segunda llamada al modelo.', '',
              '## Recuperación durante la demo', '',
              '- Sesión vencida o 401: ingresar nuevamente y comprobar el perfil; no presentarlo como rechazo de negocio.',
              '- Auditoría sin la solicitud esperada: comprobar la sesión de Sofía, el identificador de solicitud y la actualización de la vista. No inventar evidencia ni interpretar un mensaje de error como prueba suficiente del control.',
              '- Fallo de Bedrock o Gateway: mostrar el error y explicar dónde se interrumpió el recorrido. Un botón directo permite demostrar la API, pero no prueba el recorrido de IA.',
              '- Pedido con un estado distinto del ensayado: describir el estado real. Para este recorrido basta consultar y contrastar los intentos bloqueados; evitar reinicios o aprobaciones improvisadas.',
              '- Fallo prolongado de internet: continuar con los diagramas y presentar los resultados como esperados, sin atribuirles una ejecución en vivo.', '',
              '## Si hay retraso', '',
              'Conservar la consulta de Camila a P-104, el intento de consultar P-205 y el contraste de sus decisiones. Mantener la distinción entre persona y aplicación, el papel de IAM y AgentCore y la guía final de responsables, revisión y retiro. Acortar la interacción de la diapositiva 12 y las explicaciones de apoyo, sin omitir el rechazo esperado ni afirmar una ejecución no realizada. Los anexos ya están fuera del recorrido principal.', '',
              '## Preguntas: últimos diez minutos', '',
              'Abrir preguntas tras la diapositiva 22. Usar los anexos solo cuando aporten a la pregunta: arquitectura completa, contexto firmado, recursos y tablas, costos, rutas de ejecución, confirmación humana, llamada al modelo o reintentos. Volver siempre a quién se identifica, quién autoriza y qué evidencia queda. Si no hay preguntas, repasar cómo asignar un responsable, revisar un permiso y retirarlo en un primer proyecto con IA.', '',
              'Fuentes del proyecto: [arquitectura](arquitectura.md), [API](api.md), [casos de uso](../src/ecommerce_agent/application.py), [identidad](../infra/foundation/identity.tf) y [autenticación web](../web/auth.js).', '']
    return '\n'.join(lines)


def render_slide_guidance(slides, timed):
    """Separa el discurso de las instrucciones y referencias del expositor."""
    lines = []
    for item in slides:
        suffix = f" ({item['start']}–{item['end']})" if timed else ' — apoyo'
        heading = '###' if timed else '####'
        lines += [f"{heading} {item['slide']}. {item['title']}{suffix}", '',
                  '**Oratoria para decir:**', '', item['speech'], '']
        if demo := item.get('demo'):
            lines += [f"**Pausa en la web. Sesión: {demo['profile']}.**", '', demo['action'], '']
            if demo.get('message'):
                lines += ['Mensaje para copiar:', '', '> ' + demo['message'], '']
            lines += ['**Resultado esperado, por comprobar en vivo:** ' + demo['expected'], '',
                      '**Regreso a la PPT:** ' + demo['return'], '', '**Si falla:** ' + demo['backup'], '']
        lines += ['**Transición:** ' + item['transition'], '', '**Conceptos de apoyo:**', '']
        lines += [f"- **{entry['term']}:** {entry['explanation']}" for entry in item['definitions']]
        lines += ['']
        if item.get('technical'):
            lines += ['**Apoyo técnico (consulta opcional):** ' + item['technical'], '']
        if item.get('sources'):
            lines += ['**Fuentes:** ' + '; '.join(item['sources']), '']
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--presentation', type=Path, default=PRESENTATION)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--guide', type=Path, default=ROOT / 'docs/demo-35-minutos.md')
    args = parser.parse_args()
    document, plan = load_plan(args.source)
    updated = update_presentation(args.presentation, args.output, plan)
    args.guide.write_text(render_guide(document, plan), encoding='utf-8')
    print(f'Oratoria sincronizada: {updated} notas; 22 diapositivas principales, 8 anexos, 3 demos y 35 minutos, más 10 minutos de preguntas.')
    print('El contenido visual de todas las diapositivas se conservó byte por byte.')


if __name__ == '__main__':
    main()
