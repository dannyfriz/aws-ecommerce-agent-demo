"""Reinicio educativo con autorización, concurrencia y auditoría."""
from dataclasses import replace
from datetime import date
import unittest
from unittest.mock import Mock, patch
from ecommerce_agent import handler
from ecommerce_agent.adapters import MemoryRepository, LocalPlanner
from ecommerce_agent.application import Service
from ecommerce_agent.domain import Actor, AppError, Order
from test_application import event


class ResetTests(unittest.TestCase):
    def setUp(self):
        clock = patch("ecommerce_agent.application.utc_today", return_value=date(2026, 10, 23))
        clock.start()
        self.addCleanup(clock.stop)
        self.order = Order('P-104', 'camila', 'Producto', 39990,
                           return_status='REFUNDED', version=3, approved_from_version=2, customer_name='Camila', purchased_on='2026-10-01')
        self.repo = MemoryRepository([self.order])
        self.service = Service(self.repo, LocalPlanner())
        self.supervisor = Actor('sofia', 'supervisor')

    def test_reset_preserves_data_and_history_and_invalidates_old_approval(self):
        self.repo.record({'previous': True})
        result = self.service.reset_order(self.supervisor, 'P-104', 'reset', 3, True)
        self.assertTrue(result['executed'])
        self.assertEqual(self.repo.get('P-104'), replace(self.order, return_status='NONE', version=4, approved_from_version=-1))
        self.assertEqual(self.repo.events[0], {'previous': True})
        self.assertEqual(self.repo.events[-1]['reason'], 'LAB_RESET')
        with self.assertRaises(AppError):
            self.service.execute(self.supervisor, 'approve_refund', 'P-104', 'old', 2, True)
        self.service.execute(Actor('camila', 'customer'), 'request_return', 'P-104', 'new')
        self.assertEqual(self.repo.get('P-104').return_status, 'REQUESTED')

    def test_customer_denied_even_with_confirm(self):
        with self.assertRaises(AppError) as error:
            self.service.reset_order(Actor('camila', 'customer'), 'P-104', 'r', 3, True)
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.repo.get('P-104'), self.order)

    def test_confirmation_version_and_retries(self):
        for version, confirm in [(True, True), (3, False), (None, True), (2, True)]:
            with self.assertRaises(AppError):
                self.service.reset_order(self.supervisor, 'P-104', 'r', version, confirm)
        self.service.reset_order(self.supervisor, 'P-104', 'r', 3, True)
        with self.assertRaises(AppError) as error:
            self.service.reset_order(self.supervisor, 'P-104', 'r', 3, True)
        self.assertEqual(error.exception.status, 409)
        self.assertFalse(self.service.reset_order(self.supervisor, 'P-104', 'r', 4, True)['executed'])

    def test_audit_failure_prevents_reset(self):
        with patch.object(self.repo, 'record', side_effect=RuntimeError('Sin auditoría')):
            with self.assertRaises(RuntimeError):
                self.service.reset_order(self.supervisor, 'P-104', 'r', 3, True)
        self.assertEqual(self.repo.get('P-104'), self.order)

    def test_http_route_and_tools_boundary(self):
        body = {'order_id': 'P-104', 'expected_version': 3, 'confirm': True}
        with patch.object(handler, '_service', self.service):
            self.assertEqual(handler.lambda_handler(event('/api/orders/reset', 'POST', body, 'sofia', 'supervisor'), None)['statusCode'], 200)
            self.assertEqual(handler.lambda_handler(event('/api/tools', 'POST', {**body, 'action': 'reset_order'}, 'sofia', 'supervisor'), None)['statusCode'], 403)
        planner = Mock()
        planner.plan.return_value = [{'action': 'reset_order', 'order_id': 'P-104'}]
        with self.assertRaises(AppError):
            Service(self.repo, planner).chat(self.supervisor, 'Reinicia', 'r')
