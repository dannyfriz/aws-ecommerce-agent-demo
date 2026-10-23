"""Comprueba HTTPS y el rechazo de llamadas anónimas sin pedir credenciales."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outputs',default=str(Path(__file__).resolve().parent.parent/'.build/outputs/compute.json'))
    args=parser.parse_args()
    values={key:value['value'] for key,value in json.loads(Path(args.outputs).read_text(encoding='utf-8-sig')).items()}
    api=values['api_url'].rstrip('/')
    frontend=values['frontend_url'].rstrip('/')
    assert urlparse(api).scheme=='https' and urlparse(frontend).scheme=='https','Solo se admiten destinos HTTPS.'
    with urlopen(frontend+'/',timeout=15) as response:
        assert response.status==200
    try:
        urlopen(Request(api+'/api/me'),timeout=15)
    except HTTPError as exc:
        assert exc.code in {401,403},f'Código inesperado: {exc.code}'
    else:
        raise SystemExit('La API permitió una petición sin token.')
    print('Frontend HTTPS disponible y API anónima bloqueada. Falta ejecutar la demo autenticada.')


if __name__=='__main__':
    main()
