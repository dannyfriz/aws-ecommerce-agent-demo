"""Analiza fuentes y dependencias con Trivy; bloquea HIGH/CRITICAL sin ocultar el resto."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def findings(report):
    for result in report.get('Results', []):
        for kind in ('Vulnerabilities', 'Misconfigurations', 'Secrets'):
            for entry in result.get(kind, []):
                if kind == 'Misconfigurations' and entry.get('Status') != 'FAIL':
                    continue
                yield {'type': kind, 'target': result['Target'], 'severity': entry.get('Severity', 'UNKNOWN'),
                       'id': entry.get('VulnerabilityID', entry.get('ID', entry.get('RuleID', ''))),
                       'title': entry.get('Title', ''), 'package': entry.get('PkgName', ''),
                       'installed': entry.get('InstalledVersion', ''), 'fixed': entry.get('FixedVersion', '')}


def validate_dependency_report(report, expected=None):
    targets = [result for result in report.get('Results', []) if result.get('Type') == 'pip']
    if not targets:
        raise ValueError('Trivy no detectó requirements.txt: el análisis de dependencias está incompleto')
    inventory = {}
    for result in targets:
        for package in result.get('Packages', []):
            name = re.sub(r'[-_.]+', '-', package['Name'].lower())
            inventory.setdefault(name, set()).add(package['Version'])
    for name, version in (expected or {}).items():
        normalized = re.sub(r'[-_.]+', '-', name.lower())
        if inventory.get(normalized) != {version}:
            raise ValueError(f'El inventario de dependencias no confirmó el pin: {name}=={version}')
    return len(inventory)


def build_summary(records, reports, trivy_version, checked_at=None):
    """Conservar todos los hallazgos y bloquear HIGH/CRITICAL, tengan corrección o no."""
    blocked = [record for record in records if record['severity'] in {'HIGH', 'CRITICAL'}]
    return {'checked_at': checked_at or datetime.now(timezone.utc).isoformat(), 'trivy_version': trivy_version,
            'passed': not blocked, 'blocking_severities': ['HIGH', 'CRITICAL'],
            'counts': dict(Counter(record['severity'] for record in records)), 'blocking_count': len(blocked),
            'findings': records, 'reports': reports}


def render_markdown(summary):
    """Publicar únicamente campos de evidencia, nunca coincidencias de secretos."""
    def cell(value):
        return html.escape(str(value)).replace('|', '&#124;').replace('\r', ' ').replace('\n', ' ')

    lines = ['## Análisis de seguridad', '',
             f"Trivy {cell(summary['trivy_version'])} · {cell(summary['checked_at'])}", '',
             f"Paquetes verificados: {summary.get('reports', {}).get('dependencies', {}).get('packages', '—')}. "
             f"Vulnerabilidades conocidas: {sum(f['type'] == 'Vulnerabilities' for f in summary['findings'])}. "
             f"Secretos detectados: {sum(f['type'] == 'Secrets' for f in summary['findings'])}.", '',
             ('**Gate aprobado.**' if summary['passed'] else '**Gate bloqueado.**') +
             f" {summary['blocking_count']} hallazgos HIGH/CRITICAL; se incluyen vulnerabilidades sin corrección publicada.", '',
             '| Severidad | Cantidad |', '|---|---:|']
    for severity in ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'):
        lines.append(f"| {severity} | {summary['counts'].get(severity, 0)} |")
    lines.extend(['', '| Severidad | Tipo | ID | Archivo | Paquete | Versión | Corrección |',
                  '|---|---|---|---|---|---|---|'])
    for finding in summary['findings']:
        values = (finding['severity'], finding['type'], finding['id'], finding['target'],
                  finding['package'], finding['installed'],
                  (finding['fixed'] or 'No publicada') if finding['type'] == 'Vulnerabilities' else 'Revisar configuración')
        lines.append('| ' + ' | '.join(cell(value) for value in values) + ' |')
    if not summary['findings']:
        lines.append('| — | Sin hallazgos | — | — | — | — | — |')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trivy-path', type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'toolchain.versions.json').read_text(encoding='utf-8'))
    binary = args.trivy_path or ROOT / '.build/tools/trivy' / ('trivy.exe' if os.name == 'nt' else 'trivy')
    version = subprocess.run([str(binary), '--version'], check=True, capture_output=True, text=True).stdout
    if not re.search(r'^Version: ' + re.escape(manifest['trivy']['version']) + r'\s*$', version, re.M):
        raise ValueError('El binario Trivy no coincide con la versión estable fijada')
    output = ROOT / '.build/security'
    inputs = output / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    # Trivy reconoce requirements.txt; conservar los locks propios y sus hashes sin renombrarlos.
    dependencies = '\n'.join((ROOT / file).read_text(encoding='utf-8')
                             for file in ('requirements.lock', 'build-requirements.lock'))
    (inputs / 'requirements.txt').write_text(dependencies + f"\npip=={manifest['pypi']['pip']}\n", encoding='utf-8')
    common = [str(binary), 'fs', '--config', str(ROOT / 'trivy.yaml'), '--exit-code', '0', '--list-all-pkgs',
              '--cache-dir', str(ROOT / '.build/trivy-cache'), '--format', 'json', '--quiet']
    records, reports = [], {}
    for name, target in (('source', ROOT), ('dependencies', inputs)):
        report_file = output / f'{name}.json'
        command = [*common, '--output', str(report_file)]
        if name == 'dependencies':
            # El target de dependencias vive en .build: anular exclusiones solo para este directorio acotado.
            command += ['--skip-dirs', '', '--scanners', 'vuln']
        subprocess.run([*command, str(target)], check=True, cwd=ROOT)
        report = json.loads(report_file.read_text(encoding='utf-8'))
        reports[name] = {'targets': len(report.get('Results', [])), 'metadata': report.get('Metadata', {})}
        records.extend(findings(report))
    dependency_targets = json.loads((output / 'dependencies.json').read_text(encoding='utf-8')).get('Results', [])
    reports['dependencies']['packages'] = validate_dependency_report({'Results': dependency_targets}, manifest['pypi'])
    summary = build_summary(records, reports, manifest['trivy']['version'])
    database = ROOT / '.build/trivy-cache/db/metadata.json'
    if database.is_file():
        summary['database'] = json.loads(database.read_text(encoding='utf-8'))
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    markdown = render_markdown(summary)
    (output / 'summary.md').write_text(markdown, encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as target:
            target.write(markdown + '\n')
    print(f"Trivy {summary['trivy_version']}: {len(records)} hallazgos; {summary['blocking_count']} HIGH/CRITICAL. Reportes: .build/security/")
    for record in records:
        print(f"{record['severity']} {record['id']} {record['target']} {record['package']} {record['title']}")
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
