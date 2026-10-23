"""Crea identidades de práctica fuera del state y pedidos con propietarios reales."""
import argparse
from datetime import datetime, timedelta, timezone
from getpass import getpass
import json
from pathlib import Path
import re
import secrets
import string
import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent
ORDER_SEEDS = [('P-104', 'camila', 'Audífonos inalámbricos', 39990, 30),
               ('P-205', 'diego', 'Mouse inalámbrico', 24990, 30),
               ('P-206', 'diego', 'Teclado mecánico', 59990, 120)]


def outputs(path):
    return {key: value['value'] for key, value in json.loads(Path(path).read_text(encoding='utf-8-sig')).items()}


def read_password(username):
    while True:
        password = getpass(f'Contraseña nueva para {username} (no se muestra ni guarda): ')
        if (len(password) < 14 or not re.search(r'[a-z]', password) or not re.search(r'[A-Z]', password)
                or not re.search(r'\d', password) or not re.search(r'[^a-zA-Z0-9]', password)):
            print('Usa al menos 14 caracteres con mayúsculas, minúsculas, números y símbolos.')
            continue
        if password == getpass('Repite la contraseña: '):
            return password
        print('Las contraseñas no coinciden.')


def prepare_orders(table, users, *, today=None, reset_orders=False):
    """Carga escenarios ficticios sin rejuvenecer compras ni reiniciar pedidos existentes."""
    today = today or datetime.now(timezone.utc).date()
    counts = {'created': 0, 'backfilled': 0, 'preserved': 0, 'reset': 0}
    for order_id, username, product, amount, age_days in ORDER_SEEDS:
        purchased_on = (today - timedelta(days=age_days)).isoformat()
        item = {'order_id': order_id, 'owner_sub': users[username], 'customer_name': username.capitalize(),
                'product': product, 'amount': amount, 'currency': 'CLP', 'status': 'entregado',
                'return_status': 'NONE', 'version': 1, 'approved_from_version': -1, 'purchased_on': purchased_on}
        previous = table.get_item(Key={'order_id': order_id}, ConsistentRead=True).get('Item')
        if previous is None:
            try:
                table.put_item(Item=item, ConditionExpression='attribute_not_exists(order_id)')
                counts['created'] += 1
                continue
            except ClientError as exc:
                if exc.response['Error']['Code'] != 'ConditionalCheckFailedException':
                    raise
                previous = table.get_item(Key={'order_id': order_id}, ConsistentRead=True).get('Item')
        if not previous or previous.get('owner_sub') != users[username]:
            raise SystemExit('El pedido existente no pertenece al usuario de práctica esperado. No se reemplazó.')
        version = previous['version']
        next_version = int(version) + 1
        condition = 'owner_sub = :owner AND #v = :version'
        values = {':owner': users[username], ':version': version}
        if reset_orders:
            # El reinicio es explícito y conserva la compra original, incluso si ya supera el plazo.
            reset = dict(previous, return_status='NONE', status='entregado', approved_from_version=-1,
                         version=next_version)
            reset.setdefault('purchased_on', purchased_on)
            table.put_item(Item=reset, ConditionExpression=condition,
                           ExpressionAttributeNames={'#v': 'version'}, ExpressionAttributeValues=values)
            counts['reset'] += 1
        elif 'purchased_on' not in previous:
            # La migración cambia únicamente la fecha faltante y la versión para invalidar revisiones antiguas.
            table.update_item(Key={'order_id': order_id},
                UpdateExpression='SET purchased_on = :date, #v = :next',
                ConditionExpression=condition + ' AND attribute_not_exists(purchased_on)',
                ExpressionAttributeNames={'#v': 'version'},
                ExpressionAttributeValues=dict(values, **{':date': purchased_on, ':next': next_version}))
            counts['backfilled'] += 1
        else:
            counts['preserved'] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--foundation', default=str(ROOT/'.build/outputs/foundation.json'))
    parser.add_argument('--data', default=str(ROOT/'.build/outputs/data.json'))
    parser.add_argument('--reset-orders', action='store_true', help='Reinicia explícitamente los tres pedidos ficticios conocidos sin cambiar su fecha de compra.')
    parser.add_argument('--orders-only', action='store_true', help='Prepara pedidos usando identidades existentes; no crea usuarios, cambia contraseñas ni asigna grupos.')
    args = parser.parse_args()
    foundation, data = outputs(args.foundation), outputs(args.data)
    account = data['orders_table_arn'].split(':')[4]
    region = foundation['user_pool_id'].split('_')[0]
    if not any(mark in data['orders_table_name'] for mark in ('-demo-', '-dev-', '-test-')):
        raise SystemExit('La carga de datos solo admite tablas demo/dev/test.')
    session = boto3.Session(profile_name=args.profile, region_name=region)
    if session.client('sts').get_caller_identity()['Account'] != account:
        raise SystemExit('La cuenta del perfil no coincide con los outputs. No se modificaron datos.')
    cognito, table = session.client('cognito-idp'), session.resource('dynamodb').Table(data['orders_table_name'])
    pool = foundation['user_pool_id']
    users = {}
    for username, role in [('camila', 'customer'), ('diego', 'customer'), ('sofia', 'supervisor')]:
        try:
            user = cognito.admin_get_user(UserPoolId=pool, Username=username)
        except cognito.exceptions.UserNotFoundException:
            if args.orders_only:
                raise SystemExit(f'No existe el usuario de práctica {username}. No se crearon identidades.') from None
            password = read_password(username)
            temporary = 'Aa1!' + ''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24))
            cognito.admin_create_user(UserPoolId=pool, Username=username, TemporaryPassword=temporary, MessageAction='SUPPRESS')
            cognito.admin_set_user_password(UserPoolId=pool, Username=username, Password=password, Permanent=True)
            del password, temporary
            user = cognito.admin_get_user(UserPoolId=pool, Username=username)
        if user['UserStatus'] == 'FORCE_CHANGE_PASSWORD':
            if args.orders_only:
                raise SystemExit(f'{username} tiene una contraseña temporal. No se modificó su identidad.')
            password = read_password(username)
            cognito.admin_set_user_password(UserPoolId=pool, Username=username, Password=password, Permanent=True)
            del password
        groups = cognito.admin_list_groups_for_user(UserPoolId=pool, Username=username)['Groups']
        if any(group['GroupName'] != role for group in groups):
            raise SystemExit(f'{username} tiene un grupo inesperado. Revisa su acceso antes de continuar.')
        if args.orders_only:
            if not user.get('Enabled', False) or user['UserStatus'] != 'CONFIRMED' or not any(group['GroupName'] == role for group in groups):
                raise SystemExit(f'{username} no tiene una identidad activa con el perfil esperado. No se modificaron pedidos.')
        else:
            cognito.admin_add_user_to_group(UserPoolId=pool, Username=username, GroupName=role)
        users[username] = next(attribute['Value'] for attribute in user['UserAttributes'] if attribute['Name']=='sub')
    counts = prepare_orders(table, users, reset_orders=args.reset_orders)
    destination = ROOT/'.build/demo-users.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps({'created_at':datetime.now(timezone.utc).isoformat(),'users':users},indent=2),encoding='utf-8')
    print('Usuarios camila, diego y sofia preparados. Pedidos ficticios vinculados a sus identidades.')
    print('Pedidos: ' + ', '.join(f'{key}={value}' for key, value in counts.items()) + '.')
    print('Las contraseñas no se guardaron. El archivo .build/demo-users.json no se versiona.')


if __name__ == '__main__':
    main()
