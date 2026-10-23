"""Construye un ZIP Lambda reproducible con dependencias verificadas por hash."""
from pathlib import Path
import subprocess
import sys
import uuid
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent


def main():
    build = ROOT / '.build'
    stage = build / ('lambda-' + uuid.uuid4().hex)
    stage.mkdir(parents=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--require-hashes',
                    '--only-binary=:all:', '--platform', 'manylinux2014_aarch64',
                    '--python-version', '3.14', '--implementation', 'cp', '--abi', 'cp314',
                    '--no-compile', '--target', str(stage), '-r', str(ROOT/'requirements.lock')], check=True)
    sources = {}
    for folder in [stage, ROOT/'src']:
        for file in folder.rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc' and file.name != 'README.md':
                if folder == ROOT/'src' and file.suffix != '.py':
                    continue
                sources[file.relative_to(folder).as_posix()] = file
    with ZipFile(build/'backend.zip', 'w', ZIP_DEFLATED) as archive:
        for name, file in sorted(sources.items()):
            entry = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, file.read_bytes())
    with ZipFile(build/'backend.zip') as archive:
        assert archive.testzip() is None
        assert 'ecommerce_agent/handler.py' in archive.namelist()
        assert 'ecommerce_agent/gateway_handler.py' in archive.namelist()
    print('Paquete Lambda listo: .build/backend.zip')


if __name__ == '__main__':
    main()
