"""Instala el binario oficial de Trivy fijado en el manifiesto y verifica su SHA256."""
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import tarfile
from urllib.request import Request, urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent.parent


def main():
    pin = json.loads((ROOT / 'toolchain.versions.json').read_text(encoding='utf-8'))['trivy']
    version = pin['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('La versión debe ser estable y explícita')
    if platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise ValueError('El instalador admite únicamente Windows/Linux x64')
    windows = platform.system() == 'Windows'
    if not windows and platform.system() != 'Linux':
        raise ValueError('Sistema operativo no soportado por este instalador')
    asset = f'trivy_{version}_' + ('windows-64bit.zip' if windows else 'Linux-64bit.tar.gz')
    expected = pin['windows_sha256' if windows else 'linux_sha256']
    request = Request(f'https://github.com/aquasecurity/trivy/releases/download/v{version}/{asset}',
                      headers={'User-Agent': 'tienda-clara-security'})
    with urlopen(request, timeout=90) as response:
        data = response.read(256 * 1024 * 1024 + 1)
    if len(data) > 256 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError('El archivo descargado no coincide con el SHA256 fijado')
    name = 'trivy.exe' if windows else 'trivy'
    if windows:
        with ZipFile(io.BytesIO(data)) as archive:
            binary = archive.read(name)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            member = archive.getmember(name)
            if not member.isfile():
                raise ValueError('El binario no es un archivo regular')
            binary = archive.extractfile(member).read()
    destination = ROOT / '.build/tools/trivy' / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(binary)
    destination.chmod(0o755)
    print(f'Trivy {version}: descarga oficial y SHA256 verificados. {destination}')


if __name__ == '__main__':
    main()
