"""Bandeja paginada: identidad, consistencia, límites y privacidad."""
from dataclasses import asdict
import unittest
from unittest.mock import patch
from botocore.stub import Stubber
from ecommerce_agent.adapters import MemoryRepository, DynamoRepository
from ecommerce_agent.application import Service
from ecommerce_agent.domain import Actor, AppError, Order
from ecommerce_agent import handler
from test_application import event
from test_aws_adapters import client


class PendingTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository([Order(f'P-{number:03}', 'camila', 'Producto', 1000,
                                     return_status='REQUESTED', customer_name='Camila') for number in range(27)]
                                    + [Order('P-DONE', 'diego', 'Otro', 2000, return_status='REFUNDED')])
        self.service = Service(self.repo, None)
        self.supervisor = Actor('sofia', 'supervisor')

    def test_only_supervisor_can_list_before_repository_access(self):
        with patch.object(self.repo, 'pending') as pending:
            for role in ('customer', 'administrator'):
                with self.assertRaises(AppError) as error:
                    self.service.pending(Actor('camila', role), 'r')
                self.assertEqual(error.exception.status, 403)
            pending.assert_not_called()

    def test_pages_only_pending_and_hide_owner(self):
        first = self.service.pending(self.supervisor, 'r')
        self.assertEqual(len(first['orders']), 25)
        self.assertEqual(first['next_after'], 'P-024')
        second = self.service.pending(self.supervisor, 'r', first['next_after'])
        self.assertEqual([order['order_id'] for order in second['orders']], ['P-025', 'P-026'])
        self.assertIsNone(second['next_after'])
        self.assertTrue(all('owner_sub' not in order and order['return_status'] == 'REQUESTED' for order in first['orders']))
        self.assertEqual(self.repo.events[-1]['action'], 'pending:read')

    def test_invalid_cursor_and_audit_failure_are_not_empty_success(self):
        with self.assertRaises(AppError) as error:
            self.service.pending(self.supervisor, 'r', '../otro')
        self.assertEqual(error.exception.status, 400)
        with patch.object(self.repo, 'record', side_effect=RuntimeError('Auditoría no disponible')):
            with self.assertRaises(RuntimeError):
                self.service.pending(self.supervisor, 'r')

    def test_http_requires_supervisor(self):
        with patch.object(handler, '_service', self.service):
            self.assertEqual(handler.lambda_handler(event('/api/refunds/pending'), None)['statusCode'], 403)
            self.assertEqual(handler.lambda_handler(event('/api/refunds/pending', sub='sofia', groups='supervisor'), None)['statusCode'], 200)


class PendingDynamoTests(unittest.TestCase):
    def setUp(self):
        self.client = client('dynamodb')
        self.repo = DynamoRepository(self.client, 'orders', 'audit')
        self.params = {'TableName':'orders', 'IndexName':'return_status-order_id',
                       'KeyConditionExpression':'#state = :pending', 'ExpressionAttributeNames':{'#state':'return_status'},
                       'ExpressionAttributeValues':{':pending':{'S':'REQUESTED'}}, 'Limit':25, 'ScanIndexForward':True}
        self.key = {'order_id':{'S':'P-104'}, 'return_status':{'S':'REQUESTED'}}

    def test_index_pagination_and_consistent_recheck_remove_stale_requests(self):
        pending = Order('P-205', 'diego', 'Producto', 1000, return_status='REQUESTED', customer_name='Diego')
        done = Order('P-104', 'camila', 'Producto', 1000, return_status='REFUNDED')
        with Stubber(self.client) as stub:
            stub.add_response('query', {'Items':[self.key, {'order_id':{'S':'P-205'}, 'return_status':{'S':'REQUESTED'}}],
                              'LastEvaluatedKey':{'order_id':{'S':'P-205'}, 'return_status':{'S':'REQUESTED'}}},
                              {**self.params, 'ExclusiveStartKey':{'order_id':{'S':'P-000'}, 'return_status':{'S':'REQUESTED'}}})
            stub.add_response('batch_get_item', {'Responses':{'orders':[self.repo.encode(asdict(done)), self.repo.encode(asdict(pending))]}},
                              {'RequestItems':{'orders':{'Keys':[{'order_id':{'S':'P-104'}}, {'order_id':{'S':'P-205'}}], 'ConsistentRead':True}}})
            orders, cursor = self.repo.pending(after='P-000')
            self.assertEqual(orders, [pending])
            self.assertEqual(cursor, 'P-205')

    def test_empty_index_page_keeps_cursor_without_batch_call(self):
        with Stubber(self.client) as stub:
            stub.add_response('query', {'Items':[], 'LastEvaluatedKey':self.key}, self.params)
            self.assertEqual(self.repo.pending(), ([], 'P-104'))

    def test_unprocessed_keys_fail_instead_of_hiding_requests(self):
        keys = {'orders':{'Keys':[{'order_id':{'S':'P-104'}}], 'ConsistentRead':True}}
        with Stubber(self.client) as stub:
            stub.add_response('query', {'Items':[self.key]}, self.params)
            stub.add_response('batch_get_item', {'UnprocessedKeys':keys}, {'RequestItems':keys})
            with self.assertRaises(AppError) as error:
                self.repo.pending()
            self.assertEqual(error.exception.status, 503)
