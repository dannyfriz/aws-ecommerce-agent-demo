"""Consulta costos diarios del laboratorio por centro de costo, sin atribuirle toda la cuenta."""
import argparse
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
import json
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', default='default')
    parser.add_argument('--cost-center', default='ecommerce-agent-demo')
    parser.add_argument('--start')
    parser.add_argument('--end')
    args = parser.parse_args()
    end = date.fromisoformat(args.end) if args.end else datetime.now(timezone.utc).date()
    start = date.fromisoformat(args.start) if args.start else end - timedelta(days=7)
    if start >= end:
        raise SystemExit('La fecha inicial debe ser anterior a la final; la final es exclusiva y los días son UTC.')
    values = json.loads((ROOT/'.build/outputs/bootstrap.json').read_text(encoding='utf-8-sig'))
    account = values['state_kms_key_arn']['value'].split(':')[4]
    client = boto3.Session(profile_name=args.profile, region_name='us-east-1').client('ce')
    period = {'Start': start.isoformat(), 'End': end.isoformat()}
    available = client.get_tags(TimePeriod=period, TagKey='CostCenter', SearchString=args.cost_center)
    if args.cost_center not in available.get('Tags', []):
        raise SystemExit('CostCenter todavía no está disponible en facturación para ese período. Actívalo en la cuenta administradora y espera la actualización; esto no significa costo cero.')
    query = {'TimePeriod': period, 'Granularity': 'DAILY', 'Metrics': ['UnblendedCost'],
             'Filter': {'And': [{'Tags': {'Key': 'CostCenter', 'Values': [args.cost_center]}},
                               {'Dimensions': {'Key': 'LINKED_ACCOUNT', 'Values': [account]}}]},
             'GroupBy': [{'Type': 'DIMENSION', 'Key': 'SERVICE'}]}
    rows = {}
    while True:
        response = client.get_cost_and_usage(**query)
        for day in response['ResultsByTime']:
            row = rows.setdefault(day['TimePeriod']['Start'], {'date_utc':day['TimePeriod']['Start'], 'estimated':False,'services':[]})
            row['estimated'] = row['estimated'] or day.get('Estimated', False)
            for group in day.get('Groups', []):
                metric = group['Metrics']['UnblendedCost']
                row['services'].append({'service':group['Keys'][0],'amount':metric['Amount'],'unit':metric['Unit']})
        if not response.get('NextPageToken'):
            break
        query['NextPageToken'] = response['NextPageToken']
    if not any(row['services'] for row in rows.values()):
        raise SystemExit('No hay cargos atribuibles disponibles para ese filtro y período; no se interpreta como costo total cero.')
    for row in rows.values():
        total = sum((Decimal(item['amount']) for item in row['services']), Decimal(0))
        row['total'] = str(total)
        print(f"{row['date_utc']}: {total:.6f} USD" + (' (estimado por AWS)' if row['estimated'] else ''))
        for item in row['services']:
            print(f"  {item['service']}: {Decimal(item['amount']):.6f} {item['unit']}")
    destination = ROOT/'.build/costs'
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'daily-costs.json').write_text(json.dumps({'account':account,'cost_center':args.cost_center,'period':period,'metric':'UnblendedCost','days':list(rows.values())}, indent=2),encoding='utf-8')
    print('Reporte guardado en .build/costs/daily-costs.json. Excluye cargos compartidos o sin tags; no es una medición en tiempo real.')


if __name__ == '__main__':
    try:
        main()
    except ClientError as error:
        raise SystemExit(f"No se pudo consultar facturación: {error.response['Error']['Code']}. Revisa permisos y activación de CostCenter en la cuenta administradora.") from None
