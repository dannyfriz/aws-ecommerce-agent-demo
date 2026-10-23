"""Comprueba fechas estables y migraciones del laboratorio sin llamadas a AWS."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date
import importlib.util
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError


SPEC = importlib.util.spec_from_file_location('seed_refund_demo', Path(__file__).resolve().parents[1] / 'scripts/seed_demo.py')
seed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(seed)
TODAY = date(2026, 10, 23)
USERS = {'camila': 'sub-camila', 'diego': 'sub-diego', 'sofia': 'sub-sofia'}


def conditional_failure():
    return ClientError({'Error': {'Code': 'ConditionalCheckFailedException'}}, 'UpdateItem')


def existing_orders(*, dated=True):
    records = {}
    for order_id, username, product, amount, age in seed.ORDER_SEEDS:
        item = {'order_id': order_id, 'owner_sub': USERS[username], 'customer_name': username.capitalize(),
                'product': product, 'amount': amount, 'currency': 'CLP', 'status': 'entregado',
                'return_status': 'REQUESTED', 'version': 24, 'approved_from_version': -1}
        if dated:
            item['purchased_on'] = '2026-06-25' if age == 120 else '2026-09-23'
        records[order_id] = item
    return records


class SeedOrdersTests(unittest.TestCase):
    def table_with(self, records):
        table = Mock()
        table.get_item.side_effect = lambda **kwargs: {'Item': deepcopy(records[kwargs['Key']['order_id']])}
        return table

    def test_new_scenarios_have_recent_and_expired_purchase_dates(self):
        table = Mock()
        table.get_item.return_value = {}
        result = seed.prepare_orders(table, USERS, today=TODAY)
        orders = {call.kwargs['Item']['order_id']: call.kwargs['Item'] for call in table.put_item.call_args_list}
        self.assertEqual(orders['P-104']['purchased_on'], '2026-09-23')
        self.assertEqual(orders['P-205']['purchased_on'], '2026-09-23')
        self.assertEqual(orders['P-206']['purchased_on'], '2026-06-25')
        self.assertEqual(orders['P-206']['owner_sub'], USERS['diego'])
        self.assertEqual(result, {'created': 3, 'backfilled': 0, 'preserved': 0, 'reset': 0})
        for call in table.put_item.call_args_list:
            self.assertEqual(call.kwargs['ConditionExpression'], 'attribute_not_exists(order_id)')
        for call in table.get_item.call_args_list:
            self.assertTrue(call.kwargs['ConsistentRead'])

    def test_existing_purchase_dates_and_refund_states_are_never_reseeded(self):
        records = existing_orders()
        original = deepcopy(records)
        table = self.table_with(records)
        result = seed.prepare_orders(table, USERS, today=date(2027, 5, 1))
        self.assertEqual(result['preserved'], 3)
        self.assertEqual(records, original)
        table.put_item.assert_not_called()
        table.update_item.assert_not_called()

    def test_backfill_changes_only_missing_date_and_invalidates_old_review_version(self):
        records = existing_orders(dated=False)
        table = self.table_with(records)
        result = seed.prepare_orders(table, USERS, today=TODAY)
        self.assertEqual(result['backfilled'], 3)
        table.put_item.assert_not_called()
        for call in table.update_item.call_args_list:
            kwargs = call.kwargs
            self.assertEqual(kwargs['UpdateExpression'], 'SET purchased_on = :date, #v = :next')
            self.assertEqual(kwargs['ConditionExpression'], 'owner_sub = :owner AND #v = :version AND attribute_not_exists(purchased_on)')
            self.assertEqual(kwargs['ExpressionAttributeValues'][':version'], 24)
            self.assertEqual(kwargs['ExpressionAttributeValues'][':next'], 25)
            self.assertNotIn('return_status', kwargs['UpdateExpression'])
            self.assertNotIn('customer_name', kwargs['UpdateExpression'])

    def test_second_seed_does_not_increment_version_or_rejuvenate_orders(self):
        records = existing_orders(dated=False)
        table = self.table_with(records)

        def store_backfill(**kwargs):
            values = kwargs['ExpressionAttributeValues']
            item = records[kwargs['Key']['order_id']]
            item.update(purchased_on=values[':date'], version=values[':next'])

        table.update_item.side_effect = store_backfill
        seed.prepare_orders(table, USERS, today=TODAY)
        after_first = deepcopy(records)
        table.reset_mock()
        self.assertEqual(seed.prepare_orders(table, USERS, today=date(2027, 5, 1))['preserved'], 3)
        self.assertEqual(records, after_first)
        table.update_item.assert_not_called()
        table.put_item.assert_not_called()

    def test_explicit_reset_preserves_original_expired_purchase_and_owner(self):
        records = existing_orders()
        table = self.table_with(records)
        result = seed.prepare_orders(table, USERS, today=date(2027, 5, 1), reset_orders=True)
        self.assertEqual(result['reset'], 3)
        expired = next(call.kwargs for call in table.put_item.call_args_list if call.kwargs['Item']['order_id'] == 'P-206')
        self.assertEqual(expired['Item']['purchased_on'], '2026-06-25')
        self.assertEqual(expired['Item']['owner_sub'], USERS['diego'])
        self.assertEqual(expired['Item']['version'], 25)
        self.assertEqual(expired['Item']['return_status'], 'NONE')
        self.assertEqual(expired['ConditionExpression'], 'owner_sub = :owner AND #v = :version')

    def test_existing_foreign_owner_is_not_replaced_or_backfilled(self):
        records = existing_orders(dated=False)
        records['P-104']['owner_sub'] = 'another-identity'
        table = self.table_with(records)
        with self.assertRaisesRegex(SystemExit, 'no pertenece'):
            seed.prepare_orders(table, USERS, today=TODAY)
        table.put_item.assert_not_called()
        table.update_item.assert_not_called()

    def test_reset_also_refuses_foreign_owner(self):
        records = existing_orders()
        records['P-104']['owner_sub'] = USERS['diego']
        table = self.table_with(records)
        with self.assertRaises(SystemExit):
            seed.prepare_orders(table, USERS, today=TODAY, reset_orders=True)
        table.put_item.assert_not_called()
        table.update_item.assert_not_called()

    def test_concurrent_backfill_conflict_is_not_retried_or_overwritten(self):
        table = self.table_with(existing_orders(dated=False))
        table.update_item.side_effect = conditional_failure()
        with self.assertRaises(ClientError):
            seed.prepare_orders(table, USERS, today=TODAY)
        self.assertEqual(table.update_item.call_count, 1)
        table.put_item.assert_not_called()

    def test_create_collision_checks_owner_after_consistent_read(self):
        table = Mock()
        table.get_item.side_effect = [{}, {'Item': dict(existing_orders()['P-104'], owner_sub=USERS['diego'])}]
        table.put_item.side_effect = conditional_failure()
        with self.assertRaises(SystemExit):
            seed.prepare_orders(table, USERS, today=TODAY)
        self.assertEqual(table.get_item.call_count, 2)
        self.assertEqual(table.put_item.call_count, 1)
        table.update_item.assert_not_called()

    def test_invalid_existing_date_is_preserved_for_server_validation(self):
        records = existing_orders()
        records['P-206']['purchased_on'] = 'fecha-no-valida'
        table = self.table_with(records)
        seed.prepare_orders(table, USERS, today=TODAY)
        table.put_item.assert_not_called()
        table.update_item.assert_not_called()


class SeedExistingUsersTests(unittest.TestCase):
    def setUp(self):
        self.session, self.cognito, self.table = Mock(), Mock(), Mock()
        self.session.client.side_effect = lambda name: self.cognito if name == 'cognito-idp' else self.sts
        self.sts = Mock()
        self.sts.get_caller_identity.return_value = {'Account': '123456789012'}
        self.session.resource.return_value.Table.return_value = self.table
        self.table.get_item.return_value = {}
        self.cognito.admin_get_user.side_effect = lambda **kwargs: {
            'Enabled': True, 'UserStatus': 'CONFIRMED', 'Username': kwargs['Username'],
            'UserAttributes': [{'Name': 'sub', 'Value': USERS[kwargs['Username']]}]}
        self.cognito.admin_list_groups_for_user.side_effect = lambda **kwargs: {
            'Groups': [{'GroupName': 'supervisor' if kwargs['Username'] == 'sofia' else 'customer'}]}
        self.cognito.exceptions.UserNotFoundException = type('UserNotFoundException', (Exception,), {})

    def run_main(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            foundation, data = root / 'foundation.json', root / 'data.json'
            foundation.write_text(json.dumps({'user_pool_id': {'value': 'us-east-1_example'}}))
            data.write_text(json.dumps({'orders_table_arn': {'value': 'arn:aws:dynamodb:us-east-1:123456789012:table/shop-demo-orders'},
                                        'orders_table_name': {'value': 'shop-demo-orders'}}))
            argv = ['seed', '--profile', 'demo', '--orders-only', '--foundation', str(foundation), '--data', str(data)]
            with patch.object(seed, 'ROOT', root), patch.object(seed.boto3, 'Session', return_value=self.session), patch('sys.argv', argv), redirect_stdout(StringIO()):
                seed.main()

    def test_orders_only_never_creates_users_rotates_passwords_or_assigns_roles(self):
        self.run_main()
        self.cognito.admin_create_user.assert_not_called()
        self.cognito.admin_set_user_password.assert_not_called()
        self.cognito.admin_add_user_to_group.assert_not_called()
        self.assertEqual(self.table.put_item.call_count, 3)

    def test_missing_user_aborts_before_order_writes(self):
        self.cognito.admin_get_user.side_effect = self.cognito.exceptions.UserNotFoundException()
        with self.assertRaisesRegex(SystemExit, 'No existe'):
            self.run_main()
        self.cognito.admin_create_user.assert_not_called()
        self.table.put_item.assert_not_called()

    def test_wrong_role_aborts_before_order_writes(self):
        self.cognito.admin_list_groups_for_user.return_value = {'Groups': [{'GroupName': 'supervisor'}]}
        self.cognito.admin_list_groups_for_user.side_effect = None
        with self.assertRaises(SystemExit):
            self.run_main()
        self.cognito.admin_add_user_to_group.assert_not_called()
        self.table.put_item.assert_not_called()

    def test_temporary_password_is_not_rotated_in_orders_only_mode(self):
        self.cognito.admin_get_user.side_effect = None
        self.cognito.admin_get_user.return_value = {'Enabled': True, 'UserStatus': 'FORCE_CHANGE_PASSWORD'}
        with self.assertRaisesRegex(SystemExit, 'temporal'):
            self.run_main()
        self.cognito.admin_set_user_password.assert_not_called()
        self.table.put_item.assert_not_called()


if __name__ == '__main__':
    unittest.main()
