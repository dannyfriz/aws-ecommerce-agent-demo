"""Crea identidades de práctica fuera del state y pedidos con propietarios reales."""
import argparse
from datetime import datetime, timezone
from getpass import getpass
import json
from pathlib import Path
import re
import secrets
import string
import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parent.parent


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--foundation', default=str(ROOT/'.build/outputs/foundation.json'))
    parser.add_argument('--data', default=str(ROOT/'.build/outputs/data.json'))
    parser.add_argument('--reset-orders', action='store_true', help='Reinicia exclusivamente los dos pedidos ficticios conocidos.')
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
            password = read_password(username)
            temporary = 'Aa1!' + ''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24))
            cognito.admin_create_user(UserPoolId=pool, Username=username, TemporaryPassword=temporary, MessageAction='SUPPRESS')
            cognito.admin_set_user_password(UserPoolId=pool, Username=username, Password=password, Permanent=True)
            del password, temporary
            user = cognito.admin_get_user(UserPoolId=pool, Username=username)
        if user['UserStatus'] == 'FORCE_CHANGE_PASSWORD':
            password = read_password(username)
            cognito.admin_set_user_password(UserPoolId=pool, Username=username, Password=password, Permanent=True)
            del password
        groups = cognito.admin_list_groups_for_user(UserPoolId=pool, Username=username)['Groups']
        if any(group['GroupName'] != role for group in groups):
            raise SystemExit(f'{username} tiene un grupo inesperado. Revisa su acceso antes de continuar.')
        cognito.admin_add_user_to_group(UserPoolId=pool, Username=username, GroupName=role)
        users[username] = next(attribute['Value'] for attribute in user['UserAttributes'] if attribute['Name']=='sub')
    for order_id, username, product, amount in [('P-104','camila','Audífonos inalámbricos',39990),
                                               ('P-205','diego','Mouse inalámbrico',24990)]:
        item = {'order_id':order_id,'owner_sub':users[username],'customer_name':username.capitalize(),'product':product,'amount':amount,
                'currency':'CLP','status':'entregado','return_status':'NONE','version':1,'approved_from_version':-1}
        if args.reset_orders:
            previous = table.get_item(Key={'order_id':order_id},ConsistentRead=True).get('Item')
            if previous:
                if previous['owner_sub'] != users[username]:
                    raise SystemExit('El pedido existente tiene otro propietario. No se reemplazó.')
                item['version'] = int(previous['version']) + 1
                table.put_item(Item=item,ConditionExpression='owner_sub = :owner AND #v = :version',
                               ExpressionAttributeNames={'#v':'version'},ExpressionAttributeValues={':owner':users[username],':version':previous['version']})
                continue
        try:
            table.put_item(Item=item,ConditionExpression='attribute_not_exists(order_id)')
        except ClientError as exc:
            if exc.response['Error']['Code'] != 'ConditionalCheckFailedException':
                raise
            previous = table.get_item(Key={'order_id':order_id},ConsistentRead=True).get('Item')
            if not previous or previous['owner_sub'] != users[username]:
                raise SystemExit('El pedido existente no pertenece al usuario de práctica esperado.')
            if previous.get('customer_name') != item['customer_name']:
                # Actualizar solo el nombre; la versión protege confirmaciones abiertas y escrituras concurrentes.
                table.update_item(Key={'order_id':order_id},
                    UpdateExpression='SET customer_name = :name, #v = :next',
                    ConditionExpression='owner_sub = :owner AND #v = :version',
                    ExpressionAttributeNames={'#v':'version'},
                    ExpressionAttributeValues={':name':item['customer_name'], ':owner':users[username],
                                               ':version':previous['version'], ':next':int(previous['version'])+1})
    destination = ROOT/'.build/demo-users.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps({'created_at':datetime.now(timezone.utc).isoformat(),'users':users},indent=2),encoding='utf-8')
    print('Usuarios camila, diego y sofia preparados. Pedidos ficticios vinculados a sus identidades.')
    print('Las contraseñas no se guardaron. El archivo .build/demo-users.json no se versiona.')


if __name__ == '__main__':
    main()
