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
    if sum(item['seconds'] for item in plan) != document['duration_seconds']:
        raise ValueError('Los tiempos no coinciden con la duración declarada.')
    if document['duration_seconds'] != 2100 or sum(bool(item.get('demo')) for item in plan) != 8:
        raise ValueError('La charla debe conservar treinta y cinco minutos y ocho pausas de demo.')
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
    lines = [
        '# Guion de la demo en vivo: 35 minutos', '',
        'Oratoria explícita para estudiantes de nivel 200, sincronizada con las 30 diapositivas de [la presentación](presentaciones/Danny_Friz_SCD_2026_arquitectura_IA.pptx). Explica qué es cada concepto, su función en esta demo y un ejemplo. El avance es manual; los tiempos incluyen explicación, participación y uso de la web.', '',
        '## Cómo usar la oratoria', '',
        'Leer o adaptar **Oratoria para decir**. Las definiciones de los conceptos nuevos ya están dentro de ese discurso. **Conceptos de apoyo** y **Apoyo técnico** son referencias para preguntas, no un bloque adicional que se deba leer completo. Las indicaciones de demo describen qué hacer en la web y qué resultado comprobar.', '',
        'Se da más tiempo a la arquitectura y a los controles de ejecución, conservando treinta y cinco minutos y ocho pausas para la demo. Los tiempos son una pauta de ensayo: contemplar pausas para señalar el diagrama y observar la web.', '',
        'Las notas de PowerPoint contienen únicamente la oratoria, en un tono natural para decirla en voz alta. Los tiempos, las instrucciones de demo, las transiciones sugeridas y las referencias quedan en este guion. La [fuente de la oratoria](presentaciones/oratoria-nivel-200.json) mantiene ambos archivos sincronizados mediante `scripts/sync_presentation_notes.py`.', '',
        '## Preparación antes de proyectar', '',
        '- Usar perfiles independientes del navegador, o una ventana normal y otra incógnita. Dos ventanas incógnitas del mismo navegador comparten sesión.',
        '- Verificar usuario y perfil al cambiar de ventana. El enlace no selecciona una cuenta automáticamente.',
        '- El access token, la credencial digital de acceso, dura quince minutos y la página no lo renueva. Ingresar como Camila cerca del primer bloque, como Sofía cerca del suyo y renovar Camila antes de la prueba final. No proyectar contraseñas.',
        '- Preparar P-104 desde Sofía con «Reiniciar pedido (demo)» si corresponde. Revisar, confirmar y comprobar «Sin devolución». La versión aumenta. No reiniciar entre solicitud y aprobación.',
        '- Ensayar P-205 con Diego antes de la charla. En la prueba de Camila, no mostrar datos obtenidos con la otra cuenta.',
        '- Dejar listas la web y la PPT, ocultar notificaciones y mantener cerrado el identificador de identidad de Cognito.',
        '- El indicador de API consulta solamente /api/health. Ensayar también login, chat, consulta y devolución; el indicador verde no comprueba esas dependencias.',
        '- El respaldo disponible es la PPT con diagramas y resultados esperados. No se incluyen capturas ni grabación de la ejecución. No desplegar Terraform durante la charla.', '',
        '## Mapa de tiempos', '',
        '| Tiempo | Diapositiva | Tema | Cambio de ventana |', '|---|---|---|---|',
    ]
    for item in plan:
        surface = 'Web: ' + item['demo']['profile'] if item.get('demo') else 'PPT'
        lines.append(f"| {item['start']}–{item['end']} | {item['slide']} | {item['title']} | {surface} |")
    lines += ['', '## Recorrido de los servicios de IA', '',
              '| Componente | Qué es y para qué se usa aquí |', '|---|---|',
              '| Bedrock y Converse | Bedrock permite invocar el modelo; Converse es la API. El modelo propone consultar un pedido o solicitar una devolución. |',
              '| Herramienta | Función programada con datos de entrada definidos: read_order consulta y request_return solicita una devolución. |',
              '| Lambda backend | Código del servidor que coordina la petición y comprueba la propuesta. |',
              '| AgentCore Gateway | Punto de acceso a las funciones; reconoce a la aplicación que llama y dirige la solicitud. |',
              '| AgentCore Policy | Aplica reglas de acceso al rol de esa aplicación y a las dos funciones disponibles. |',
              '| Lambda de herramientas | Implementa las funciones y verifica contexto, persona, propietario y reglas antes de operar. |', '',
              'La aprobación de reembolsos se confirma por una ruta separada. La ayuda explícita a Sofía y los botones usan código directo del servidor. La respuesta final se construye con resultados comprobados, sin una segunda llamada al modelo.', '',
              '## Oratoria por diapositiva', '']
    for item in plan:
        lines += [f"### {item['slide']}. {item['title']} ({item['start']}–{item['end']})", '',
                  '**Oratoria para decir:**', '', item['speech'], '']
        if demo := item.get('demo'):
            lines += [f"**Pausa en la web. Sesión: {demo['profile']}.**", '', demo['action'], '']
            if demo.get('message'):
                lines += ['Mensaje para copiar:', '', '> ' + demo['message'], '']
            lines += ['**Resultado esperado:** ' + demo['expected'], '',
                      '**Regreso a la PPT:** ' + demo['return'], '', '**Si falla:** ' + demo['backup'], '']
        lines += ['**Transición:** ' + item['transition'], '', '**Conceptos de apoyo:**', '']
        lines += [f"- **{entry['term']}:** {entry['explanation']}" for entry in item['definitions']]
        lines += ['']
        if item.get('technical'):
            lines += ['**Apoyo técnico (consulta opcional):** ' + item['technical'], '']
        if item.get('sources'):
            lines += ['**Fuentes:** ' + '; '.join(item['sources']), '']
    lines += ['## Recuperación durante la demo', '',
              '- Sesión vencida o 401: ingresar nuevamente y comprobar el perfil; no presentarlo como rechazo de negocio.',
              '- Bandeja vacía: esperar su actualización o consultar P-104 directamente desde Sofía. Se refresca cada quince segundos y una solicitud nueva puede tardar en aparecer.',
              '- Conflicto al aprobar: consultar otra vez, revisar estado y versión. No repetir confirmaciones sin revisar.',
              '- Fallo de Bedrock o Gateway: mostrar el error y explicar dónde se interrumpió el recorrido. Un botón directo permite demostrar la API, pero no prueba el recorrido de IA.',
              '- Pedido ya solicitado o aprobado: describir el estado real. No afirmar que repetir una acción produjo un nuevo cambio.',
              '- Fallo prolongado de internet: continuar con los diagramas y presentar los resultados como esperados, sin atribuirles una ejecución en vivo.', '',
              '## Si hay retraso', '',
              'Conservar consulta propia, devolución pendiente, rechazo de aprobación como cliente y confirmación humana con Sofía. Resumir los ejemplos IAM de las diapositivas 22–24. Conservar la consulta ajena de la 28 y el cierre. No acelerar las definiciones nuevas ni confundir el rol de cada servicio.', '',
              'Fuentes del proyecto: [arquitectura](arquitectura.md), [API](api.md), [casos de uso](../src/ecommerce_agent/application.py), [identidad](../infra/foundation/identity.tf) y [autenticación web](../web/auth.js).', '']
    return '\n'.join(lines)


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
    print(f'Oratoria sincronizada: {updated} notas, treinta diapositivas, ocho demos y treinta y cinco minutos.')
    print('El contenido visual de todas las diapositivas se conservó byte por byte.')


if __name__ == '__main__':
    main()
