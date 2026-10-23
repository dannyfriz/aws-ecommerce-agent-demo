"""Detecta artefactos sensibles evidentes y valida los scripts antes de publicar."""
from pathlib import Path
import ast
import re

ROOT=Path(__file__).resolve().parent.parent
EXCLUDED={'.git','.build','.terraform','.venv','__pycache__','node_modules'}
PATTERNS=[re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
          re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]


def main():
    failures=[]
    for file in ROOT.rglob('*'):
        if not file.is_file() or any(part in EXCLUDED for part in file.relative_to(ROOT).parts):
            continue
        if (file.name=='config.js' or file.name=='.env' or file.name.startswith('.env.')
                or '.tfstate' in file.name or file.suffix in {'.tfvars','.tfplan','.pem','.key','.p12'}):
            failures.append(f'Archivo privado fuera de .build: {file.relative_to(ROOT)}')
            continue
        if file.suffix in {'.py','.md','.tf','.json','.js','.mjs','.yml','.yaml','.ps1','.toml','.lock','.example'}:
            content=file.read_text(encoding='utf-8-sig')
            if any(pattern.search(content) for pattern in PATTERNS):
                failures.append(f'Posible credencial: {file.relative_to(ROOT)}')
            if file.suffix=='.py':
                ast.parse(content,filename=str(file))
    if failures:
        raise SystemExit('\n'.join(failures))
    print('Comprobación de artefactos privados y sintaxis Python aprobada. No reemplaza una revisión del historial.')


if __name__=='__main__':
    main()
