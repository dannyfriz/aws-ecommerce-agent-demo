"""Pruebas sin conexión para contratos AWS y concurrencia."""
from dataclasses import asdict, replace
import unittest
import boto3
from botocore.stub import Stubber, ANY
from ecommerce_agent.adapters import DynamoRepository, BedrockPlanner
from ecommerce_agent.domain import AppError, Order


def client(service):
    return boto3.client(service, region_name="us-east-1", aws_access_key_id="testing",
                        aws_secret_access_key="testing")


class DynamoTests(unittest.TestCase):
    def setUp(self):
        self.client = client("dynamodb")
        self.repo = DynamoRepository(self.client, "orders", "audit")
        self.order = Order("P-104", "camila", "Notebook", 499990)

    def test_get_uses_consistent_read(self):
        with Stubber(self.client) as stub:
            stub.add_response("get_item", {"Item": self.repo.encode(asdict(self.order))},
                              {"TableName": "orders", "Key": {"order_id": {"S": "P-104"}}, "ConsistentRead": True})
            self.assertEqual(self.repo.get("P-104"), self.order)

    def test_audit_queries_latest_decisions_in_descending_order(self):
        events = [{"stream": "DECISIONS", "event_id": "2026-10-17T12:00:02+00:00#b", "created_at": "2026-10-17T12:00:02+00:00"},
                  {"stream": "DECISIONS", "event_id": "2026-10-17T12:00:01+00:00#a", "created_at": "2026-10-17T12:00:01+00:00"}]
        with Stubber(self.client) as stub:
            stub.add_response("query", {"Items": [self.repo.encode(item) for item in events]},
                {"TableName": "audit", "KeyConditionExpression": "#stream = :stream",
                 "ExpressionAttributeNames": {"#stream": "stream"},
                 "ExpressionAttributeValues": {":stream": {"S": "DECISIONS"}},
                 "Limit": 50, "ScanIndexForward": False, "ConsistentRead": True})
            self.assertEqual(self.repo.audit(), events)

    def test_transaction_binds_owner_version_state_and_audit(self):
        def inspect(params, **kwargs):
            transaction = params["TransactItems"]
            self.assertEqual(len(transaction), 2)
            put = transaction[0]["Put"]
            self.assertIn("owner_sub", put["ConditionExpression"])
            self.assertEqual(put["ExpressionAttributeValues"][":owner"], {"S": "camila"})
            self.assertEqual(put["ExpressionAttributeValues"][":v"], {"N": "1"})
            self.assertEqual(transaction[1]["Put"]["TableName"], "audit")
        self.client.meta.events.register("before-parameter-build.dynamodb.TransactWriteItems", inspect)
        with Stubber(self.client) as stub:
            stub.add_response("transact_write_items", {}, {"TransactItems": ANY})
            self.repo.mutate(self.order, replace(self.order, version=2, return_status="REQUESTED"), {"event_id": "event"})

    def test_race_becomes_conflict(self):
        with Stubber(self.client) as stub:
            stub.add_client_error("transact_write_items", "TransactionCanceledException",
                service_error_meta={"CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {"Code": "None"}]},
                modeled_fields={"CancellationReasons": [{"Code": "ConditionalCheckFailed"}, {"Code": "None"}]})
            with self.assertRaises(AppError) as error:
                self.repo.mutate(self.order, replace(self.order, version=2), {"event_id": "event"})
            self.assertEqual(error.exception.status, 409)


class BedrockTests(unittest.TestCase):
    def test_unknown_model_tool_is_proposal_not_authority(self):
        model = client("bedrock-runtime")
        result = {"output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "t1", "name": "approve_refund", "input": {"order_id": "P-104"}}}]}},
            "stopReason": "tool_use", "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            "metrics": {"latencyMs": 1}}
        with Stubber(model) as stub:
            stub.add_response("converse", result)
            self.assertEqual(BedrockPlanner(model, "us.amazon.nova-2-lite-v1:0").plan("aprueba")[0]["action"], "approve_refund")

    def test_model_text_is_never_returned_as_business_data(self):
        model = client("bedrock-runtime")
        result = {"output": {"message": {"role": "assistant", "content": [{"text": "Compra ajena: secreto"}]}},
            "stopReason": "end_turn", "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            "metrics": {"latencyMs": 1}}
        with Stubber(model) as stub:
            stub.add_response("converse", result)
            with self.assertRaises(AppError) as error:
                BedrockPlanner(model, "us.amazon.nova-2-lite-v1:0").plan("hola")
            self.assertNotIn("secreto", error.exception.message)


if __name__ == "__main__":
    unittest.main()
