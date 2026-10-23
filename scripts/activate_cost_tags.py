"""Activa únicamente los tags de asignación de costos del proyecto en Billing."""
import argparse
import boto3
from botocore.exceptions import ClientError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name='us-east-1')
    account = session.client('sts').get_caller_identity()['Account']
    organization = session.client('organizations').describe_organization()['Organization']
    if account != organization['MasterAccountId']:
        raise SystemExit('Este paso requiere el perfil de la cuenta administradora de facturación, no el perfil de la demo.')
    client = session.client('ce')
    keys = ['CostCenter','Project','Environment']
    result = client.list_cost_allocation_tags(Type='UserDefined',TagKeys=keys)
    tags = {item['TagKey']:item['Status'] for item in result.get('CostAllocationTags',[])}
    updates = [{'TagKey':key,'Status':'Active'} for key in keys if key in tags and tags[key] != 'Active']
    if updates:
        response = client.update_cost_allocation_tags_status(CostAllocationTagsStatus=updates)
        if response.get('Errors'):
            raise SystemExit('AWS no pudo activar todos los tags solicitados. Revisa Billing antes de generar el reporte.')
    for key in keys:
        print(f'{key}: ' + ('activo o activación solicitada' if key in tags else 'todavía no visible; espera la actualización de Billing y reintenta'))


if __name__ == '__main__':
    try:
        main()
    except ClientError as error:
        raise SystemExit(f"No se pudo activar la asignación de costos: {error.response['Error']['Code']}.") from None
