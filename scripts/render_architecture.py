"""Genera diagramas SVG del proyecto con los íconos oficiales guardados en docs/assets."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / 'docs/assets'
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)


def node(parent, tag, **attrs):
    return ET.SubElement(parent, f'{{{NS}}}{tag}', {key.replace('_', '-'): str(value) for key, value in attrs.items()})


class Diagram:
    def __init__(self, height, title, subtitle):
        self.root = ET.Element(f'{{{NS}}}svg', {'viewBox': f'0 0 2080 {height}', 'width': '2080', 'height': str(height), 'role': 'img'})
        node(self.root, 'title').text = title
        node(self.root, 'desc').text = subtitle
        defs = node(self.root, 'defs')
        for color, key in [('#386a98', 'flow'), ('#ab4a87', 'control')]:
            marker = node(defs, 'marker', id=key, viewBox='0 0 10 10', refX=9, refY=5, markerWidth=8, markerHeight=8, orient='auto-start-reverse')
            node(marker, 'path', d='M 0 0 L 10 5 L 0 10 z', fill=color)
        node(self.root, 'rect', width=2080, height=height, fill='#f7f9fc')
        self.text(40, 57, title, 36, '#172b46', '700')
        self.text(40, 96, subtitle, 23)
        self.groups = node(self.root, 'g')
        self.edges = node(self.root, 'g')
        self.cards = node(self.root, 'g')
        self.count = 0

    def text(self, x, y, value, size=21, color='#45566e', weight='400', parent=None):
        item = node(parent if parent is not None else self.root, 'text', x=x, y=y, fill=color, font_size=size,
                    font_family='Segoe UI, Arial, sans-serif', font_weight=weight)
        item.text = value

    def group(self, x, y, w, h, label, fill='#ffffff', stroke='#b8c8dd'):
        node(self.groups, 'rect', x=x, y=y, width=w, height=h, rx=16, fill=fill, stroke=stroke, stroke_width=2)
        self.text(x+20, y+34, label, 22, '#53677e', '600', self.groups)

    def card(self, x, y, title, lines, icon=None, width=280, height=170):
        node(self.cards, 'rect', x=x, y=y, width=width, height=height, rx=12, fill='#ffffff', stroke='#c5d1df', stroke_width=2)
        title_x = x+20
        if icon:
            self.count += 1
            source = ET.parse(ASSETS / 'aws-icons' / f'{icon}.svg').getroot()
            image = node(self.cards, 'svg', x=x+18, y=y+18, width=58, height=58, viewBox=source.get('viewBox', '0 0 80 80'))
            for child in source:
                copy = deepcopy(child)
                for element in copy.iter():
                    for key, value in list(element.attrib.items()):
                        if key == 'id':
                            element.set(key, f'i{self.count}-{value}')
                        elif 'url(#' in value:
                            element.set(key, value.replace('url(#', f'url(#i{self.count}-'))
                image.append(copy)
            title_x = x+90
        self.text(title_x, y+42, title, 24 if width > 300 else 20 if width < 280 else 22, '#172b46', '700', self.cards)
        for index, line in enumerate(lines):
            self.text(x+20, y+99+index*27, line, 21 if width > 300 else 18, parent=self.cards)

    def edge(self, points, label='', lx=0, ly=0, control=False):
        color = '#ab4a87' if control else '#386a98'
        attrs = {'d': 'M '+' L '.join(f'{x} {y}' for x, y in points), 'fill': 'none', 'stroke': color,
                 'stroke_width': 3, 'marker_end': f'url(#{"control" if control else "flow"})'}
        if control:
            attrs['stroke_dasharray'] = '8 6'
        node(self.edges, 'path', **attrs)
        if label:
            self.text(lx, ly, label, 20, color, '600', self.edges)

    def save(self, name):
        ET.indent(self.root)
        ET.ElementTree(self.root).write(ASSETS/name, encoding='utf-8', xml_declaration=True)


def runtime():
    d = Diagram(1440, 'Tienda Clara · Arquitectura de la aplicación',
                'Identidad de la persona → autorización del servidor → herramientas acotadas → evidencia verificable')
    d.group(365, 135, 1680, 1210, 'Cuenta AWS de laboratorio · servicios regionales en us-east-1; CloudFront y WAF de alcance global')
    d.group(1495, 620, 390, 685, 'Datos · cifrado CMK + PITR', '#f0f5fc')
    d.card(40, 240, 'Amazon Route 53', ['Zona DNS compartida', 'demo / api-dev / auth', 'Administración externa'], 'Amazon-Route-53', width=260)
    d.card(40, 690, 'Persona / SPA', ['Cliente o supervisión', 'Tokens solo en memoria', 'Sin credenciales AWS'], width=260)
    d.card(400, 240, 'CloudFront', ['demo.example.com', 'HTTPS, CSP y OAC', 'Distribución web'], 'Amazon-CloudFront')
    d.card(780, 240, 'Amazon S3', ['SPA + config pública', 'Bucket privado', 'Acceso solo por OAC'], 'Amazon-Simple-Storage-Service')
    d.card(1160, 240, 'Amazon Cognito', ['auth.example.com', 'Code + PKCE S256', 'Grupos cliente / supervisor'], 'Amazon-Cognito')
    d.card(1540, 240, 'AWS ACM', ['Certificado wildcard', '*.example.com', 'TLS: demo, api-dev y auth'], 'AWS-Certificate-Manager')
    d.card(400, 460, 'AWS WAF', ['Reglas administradas', 'Límite de solicitudes por IP'], 'AWS-WAF', height=140)
    d.card(400, 690, 'API Gateway', ['api-dev.example.com', 'HTTP API · JWT + scope', '/api/health público mínimo'], 'Amazon-API-Gateway')
    d.card(780, 690, 'Lambda backend', ['Identidad, rol y propietario', 'Orquestación + API directa', 'Aprobación y reinicio humanos'], 'AWS-Lambda')
    d.card(1160, 690, 'Amazon Bedrock', ['Converse · Nova 2 Lite', 'Application inference profile', 'Propone; no autoriza'], 'Amazon-Bedrock')
    d.card(1540, 690, 'DynamoDB', ['Tabla de pedidos', 'Cliente, estado y versión', 'Lectura consistente'], 'Amazon-DynamoDB')
    d.card(400, 1070, 'AWS KMS · HMAC', ['Contexto firmado de 30 s', 'Identidad + acción + pedido', 'Clave separada de cifrado'], 'AWS-Key-Management-Service')
    d.card(780, 1070, 'AgentCore', ['Gateway MCP · AWS_IAM', 'Policy Cedar · ENFORCE', 'read_order / request_return'], 'Amazon-Bedrock-AgentCore')
    d.card(1160, 1070, 'Lambda tools', ['Verifica MAC y vencimiento', 'Revalida rol y propietario', 'Reglas + idempotencia'], 'AWS-Lambda')
    d.card(1540, 1070, 'DynamoDB', ['Tabla de auditoría · TTL', 'ALLOW / DENY + motivo', 'request_id para correlación'], 'Amazon-DynamoDB')
    d.edge([(300,325),(400,325)], 'DNS', 325,310, True)
    d.edge([(40,730),(20,730),(20,180),(1300,180),(1300,240)], '1 · Ingreso OAuth + PKCE / recuperación de contraseña', 450,215)
    d.edge([(300,730),(335,730),(335,370),(400,370)], 'HTTPS web', 190,510)
    d.edge([(680,325),(780,325)], 'OAC', 704,310)
    d.edge([(540,460),(540,410)], control=True)
    d.edge([(1540,325),(1440,325)], 'TLS', 1460,310, True)
    d.edge([(1160,350),(1110,350),(1110,630),(540,630),(540,690)], 'Issuer + claves públicas del JWT', 720,615, True)
    d.edge([(300,775),(400,775)], '2 · JWT', 310,758)
    d.edge([(680,775),(780,775)], 'Claims', 694,758)
    d.edge([(1060,775),(1160,775)], '3 · Plan', 1074,758)
    d.edge([(920,860),(920,1070)], '4 · MCP / SigV4 + contexto firmado', 940,1045)
    d.edge([(780,820),(740,820),(740,1155),(680,1155)], 'GenerateMac', 585,1020, True)
    d.edge([(1060,1155),(1160,1155)], '5 · Invoke', 1065,1138)
    d.edge([(1300,1240),(1300,1300),(540,1300),(540,1240)], 'VerifyMac · no se confía en la identidad del prompt', 680,1280, True)
    d.edge([(1060,830),(1090,830),(1090,935),(1495,935)], 'API directa: lectura / transacción', 1130,920)
    d.edge([(1440,1155),(1495,1155)], 'Datos', 1442,1138)
    d.text(1530, 965, 'Mutación atómica:', 22, '#172b46', '600')
    d.text(1530, 997, 'pedido + evento de auditoría', 21)
    d.text(1530, 1027, 'Condiciones de versión y estado', 21)
    d.text(40, 1385, 'Flecha azul: solicitud o acceso a datos. Línea discontinua: configuración o control de seguridad.', 22)
    d.text(40, 1420, 'Supervisión: aprobar reembolso y reiniciar demo → API → backend. Estas acciones nunca pasan por el modelo ni Gateway.', 22, '#172b46', '600')
    d.save('arquitectura-aplicacion.svg')


def operations():
    d = Diagram(1040, 'Tienda Clara · Controles transversales y despliegue',
                'Servicios de apoyo, separación de identidades, atribución de costos e infraestructura como código')
    d.group(25, 130, 2030, 345, 'Controles aplicados a los componentes de la aplicación')
    items = [
        (50, 'AWS IAM', ['Roles separados: backend, tools', 'y Gateway; mínimo privilegio', 'Workload distinto de persona'], 'AWS-Identity-and-Access-Management', 'Lambdas + Gateway'),
        (560, 'AWS KMS', ['CMK: S3, tablas, logs y AgentCore', 'HMAC y state: claves separadas', 'Cifrado ≠ autorización del pedido'], 'AWS-Key-Management-Service', 'Datos + logs + servicios'),
        (1070, 'CloudWatch', ['Logs: API + backend + tools', 'Cifrados; retención de 7 días', 'Métricas WAF; sin prompts/tokens'], 'Amazon-CloudWatch', 'API + Lambdas + WAF'),
        (1580, 'Cost Explorer', ['CostCenter=ecommerce-agent-demo', 'Incluye perfil Bedrock etiquetado', 'Activación requerida en payer'], 'AWS-Cost-Explorer', 'Recursos etiquetables + Bedrock')]
    for x, title, lines, icon, source in items:
        d.text(x+15, 214, source, 21, '#386a98', '600')
        d.card(x, 265, title, lines, icon, width=450, height=185)
        d.edge([(x+225,225),(x+225,265)])
    d.group(25, 515, 2030, 400, 'Terraform · dependencias de despliegue y lectura de salidas por terraform_remote_state')
    d.card(50, 635, 'Bootstrap / S3 state', ['Backend remoto versionado + CMK', 'States separados por capa/ambiente', 'Bootstrap conserva state local'], 'Amazon-Simple-Storage-Service', width=450, height=200)
    d.card(560, 635, 'Foundation', ['Cognito, CMK, S3 web, WAF', 'CloudFront y dominio de login', 'Certificado existente referenciado'], 'Amazon-Cognito', width=450, height=200)
    d.card(1070, 635, 'Data', ['Pedidos + auditoría DynamoDB', 'PITR, cifrado y TTL de auditoría', 'Consume foundation'], 'Amazon-DynamoDB', width=450, height=200)
    d.card(1580, 635, 'Compute', ['API, Lambdas, IAM y AgentCore', 'Perfil Bedrock + archivos SPA', 'Consume foundation y data'], 'AWS-Lambda', width=450, height=200)
    d.edge([(500,735),(560,735)], control=True)
    d.edge([(1010,735),(1070,735)])
    d.edge([(1520,735),(1580,735)])
    d.edge([(785,635),(785,590),(1805,590),(1805,635)], 'Foundation → compute', 1165,575)
    d.text(65, 884, 'El bucket de bootstrap almacena los tres states remotos; no forma parte del recorrido de solicitudes de la aplicación.', 22)
    d.text(40, 965, 'DNS y certificado wildcard existentes son compartidos y se administran fuera de estas capas. Route 53 está en otra cuenta.', 23)
    d.text(40, 1003, 'No se despliegan VPC, NAT, ECS, RDS, AgentCore Runtime ni Bedrock Agents Classic. La orquestación reside en Lambda.', 23)
    d.save('arquitectura-operacion.svg')


if __name__ == '__main__':
    runtime()
    operations()
    print('Diagramas SVG generados en docs/assets/.')
