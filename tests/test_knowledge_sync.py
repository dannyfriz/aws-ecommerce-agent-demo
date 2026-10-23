"""Pruebas de ingesta acotada, cuenta esperada, idempotencia y espera sin llamadas reales."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import boto3
from botocore.exceptions import ClientError
from botocore.stub import ANY, Stubber


SPEC = importlib.util.spec_from_file_location("sync_knowledge", Path(__file__).resolve().parents[1] / "scripts/sync_knowledge.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)
ACCOUNT = "123456789012"
KB = "KBDEMO1234"
SOURCE = "DSDEMO1234"
HASH = "a" * 64


def job(status="COMPLETE", description=None, job_id="JOBDEMO123"):
    return {"knowledgeBaseId": KB, "dataSourceId": SOURCE, "ingestionJobId": job_id, "status": status,
            "description": description or f"policy-document-sha256:{HASH}"}


class SyncKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.sts, self.agent = Mock(), Mock()
        self.outputs = {"policy_knowledge_base_id": KB, "policy_knowledge_data_source_id": SOURCE,
                        "policy_knowledge_source_uri": f"s3://ecommerce-agent-demo-policies-{ACCOUNT}/{sync.POLICY_KEY}",
                        "policy_knowledge_document_hash": HASH}
        self.sts.get_caller_identity.return_value = {"Account": ACCOUNT}
        self.agent.get_knowledge_base.return_value = {"knowledgeBase": {"knowledgeBaseId": KB,
            "knowledgeBaseArn": f"arn:aws:bedrock:us-east-1:{ACCOUNT}:knowledge-base/{KB}",
            "name": "ecommerce-agent-demo-policies", "status": "ACTIVE"}}
        self.agent.get_data_source.return_value = {"dataSource": {"knowledgeBaseId": KB, "dataSourceId": SOURCE,
            "name": "ecommerce-agent-demo-policy-document", "status": "AVAILABLE", "dataSourceConfiguration": {
                "type": "S3", "s3Configuration": {"bucketArn": f"arn:aws:s3:::ecommerce-agent-demo-policies-{ACCOUNT}",
                "bucketOwnerAccountId": ACCOUNT, "inclusionPrefixes": [sync.POLICY_KEY]}}}}
        self.agent.list_ingestion_jobs.return_value = {"ingestionJobSummaries": []}
        self.agent.start_ingestion_job.return_value = {"ingestionJob": job("STARTING")}
        self.agent.get_ingestion_job.return_value = {"ingestionJob": job()}

    def run_sync(self, **kwargs):
        return sync.synchronize(self.sts, self.agent, self.outputs, expected_account_id=ACCOUNT, **kwargs)

    def test_complete_same_hash_is_reused_without_mutation(self):
        self.agent.list_ingestion_jobs.return_value = {"ingestionJobSummaries": [job()]}
        result = self.run_sync()
        self.assertEqual(result, {"status": "COMPLETE", "ingestion_job_id": "JOBDEMO123", "document_hash": HASH})
        self.agent.start_ingestion_job.assert_not_called()
        self.agent.get_ingestion_job.assert_called_once_with(knowledgeBaseId=KB, dataSourceId=SOURCE,
                                                            ingestionJobId="JOBDEMO123")

    def test_initial_ingestion_uses_stable_token_and_exact_resources(self):
        result = self.run_sync(sleep=Mock())
        parameters = self.agent.start_ingestion_job.call_args.kwargs
        self.assertEqual(parameters["knowledgeBaseId"], KB)
        self.assertEqual(parameters["dataSourceId"], SOURCE)
        self.assertRegex(parameters["clientToken"], r"^[a-f0-9]{64}$")
        self.assertEqual(parameters["description"], f"policy-document-sha256:{HASH}")
        self.assertEqual(result["status"], "COMPLETE")
        first_token = parameters["clientToken"]
        self.run_sync(sleep=Mock())
        self.assertEqual(self.agent.start_ingestion_job.call_args.kwargs["clientToken"], first_token)

    def test_running_same_document_is_resumed(self):
        self.agent.list_ingestion_jobs.return_value = {"ingestionJobSummaries": [job("IN_PROGRESS")]}
        self.assertEqual(self.run_sync(sleep=Mock())["status"], "COMPLETE")
        self.agent.start_ingestion_job.assert_not_called()

    def test_account_mismatch_is_checked_before_resource_reads_or_writes(self):
        self.sts.get_caller_identity.return_value = {"Account": "000000000000"}
        with self.assertRaisesRegex(sync.SyncError, "ACCOUNT_MISMATCH"):
            self.run_sync()
        self.agent.get_knowledge_base.assert_not_called()
        self.agent.start_ingestion_job.assert_not_called()

    def test_production_or_manipulated_output_is_rejected_before_aws(self):
        for field, value in (("policy_knowledge_base_id", "invalid"),
                             ("policy_knowledge_source_uri", "s3://prod/policies/politicas-posventa-demo.txt"),
                             ("policy_knowledge_document_hash", "not-a-hash")):
            with self.subTest(field=field):
                previous = self.outputs[field]
                self.outputs[field] = value
                with self.assertRaises(sync.SyncError):
                    self.run_sync()
                self.outputs[field] = previous
        with self.assertRaisesRegex(sync.SyncError, "ENVIRONMENT_NOT_ALLOWED"):
            self.run_sync(environment="prod")
        self.sts.get_caller_identity.assert_not_called()

    def test_kb_name_or_arn_from_another_environment_prevents_ingestion(self):
        original = deepcopy(self.agent.get_knowledge_base.return_value)
        for field, value in (("name", "ecommerce-agent-prod-policies"),
                             ("knowledgeBaseArn", f"arn:aws:bedrock:us-east-1:000000000000:knowledge-base/{KB}"),
                             ("status", "CREATING")):
            with self.subTest(field=field):
                response = deepcopy(original)
                response["knowledgeBase"][field] = value
                self.agent.get_knowledge_base.return_value = response
                with self.assertRaisesRegex(sync.SyncError, "RESOURCE_MISMATCH"):
                    self.run_sync()
        self.agent.start_ingestion_job.assert_not_called()

    def test_source_prefix_cannot_expand_to_private_documents(self):
        source = self.agent.get_data_source.return_value["dataSource"]["dataSourceConfiguration"]["s3Configuration"]
        source["inclusionPrefixes"] = ["policies/", "orders/"]
        with self.assertRaisesRegex(sync.SyncError, "RESOURCE_MISMATCH"):
            self.run_sync()
        self.agent.start_ingestion_job.assert_not_called()

    def test_failure_and_partial_document_failure_are_not_success(self):
        for candidate in (job("FAILED"), {**job(), "statistics": {"numberOfDocumentsFailed": 1}}):
            with self.subTest(status=candidate["status"]):
                self.agent.list_ingestion_jobs.return_value = {"ingestionJobSummaries": [candidate]}
                with self.assertRaises(sync.SyncError):
                    self.run_sync()
        self.agent.start_ingestion_job.assert_not_called()

    def test_timeout_has_bounded_polls_and_does_not_cancel_job(self):
        self.agent.list_ingestion_jobs.return_value = {"ingestionJobSummaries": [job("IN_PROGRESS")]}
        clock, sleep = Mock(side_effect=[0, 0, 180]), Mock()
        self.agent.get_ingestion_job.return_value = {"ingestionJob": job("IN_PROGRESS")}
        with self.assertRaisesRegex(sync.SyncError, "INGESTION_TIMEOUT"):
            self.run_sync(clock=clock, sleep=sleep)
        sleep.assert_called_once_with(5)
        self.agent.stop_ingestion_job.assert_not_called()

    def test_other_active_document_ingestion_is_not_overlapped(self):
        self.agent.list_ingestion_jobs.return_value = {"ingestionJobSummaries": [job("IN_PROGRESS", "otro documento")]}
        with self.assertRaisesRegex(sync.SyncError, "OTHER_INGESTION_ACTIVE"):
            self.run_sync()
        self.agent.start_ingestion_job.assert_not_called()

    def test_rollback_creates_a_new_transition_token(self):
        self.run_sync(wait=False)
        first = self.agent.start_ingestion_job.call_args.kwargs["clientToken"]
        self.agent.list_ingestion_jobs.return_value = {"ingestionJobSummaries": [job(description="policy-document-sha256:" + "b" * 64)]}
        self.run_sync(wait=False)
        self.assertNotEqual(self.agent.start_ingestion_job.call_args.kwargs["clientToken"], first)

    def test_nonwaiting_mode_reports_only_safe_fields(self):
        progress = []
        self.agent.start_ingestion_job.return_value["ingestionJob"]["failureReasons"] = ["datos que no se deben imprimir"]
        result = self.run_sync(wait=False, report=progress.append)
        self.assertEqual(set(result), {"status", "ingestion_job_id", "document_hash"})
        self.assertNotIn("datos que no", json.dumps(progress))

    def test_cli_sanitizes_provider_errors(self):
        error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "secreto-no-imprimir"}}, "GetKnowledgeBase")
        output = StringIO()
        with patch.object(sync, "read_outputs", return_value=self.outputs), patch.object(sync.boto3, "Session", side_effect=error), redirect_stdout(output):
            result = sync.main(["--expected-account-id", ACCOUNT])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue()), {"status": "ERROR", "error": "AWS_REQUEST_FAILED"})
        self.assertNotIn("secreto", output.getvalue())

    def test_outputs_reader_accepts_terraform_shape_and_rejects_other_json(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "compute.json"
            path.write_text(json.dumps({key: {"value": value} for key, value in self.outputs.items()}), encoding="utf-8-sig")
            self.assertEqual(sync.read_outputs(path), self.outputs)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(sync.SyncError, "OUTPUTS_INVALID"):
                sync.read_outputs(path)

    def test_real_sdk_shapes_and_parameters_support_complete_workflow(self):
        common = {"region_name": "us-east-1", "aws_access_key_id": "testing", "aws_secret_access_key": "testing"}
        sts, agent = boto3.client("sts", **common), boto3.client("bedrock-agent", **common)
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        kb = deepcopy(self.agent.get_knowledge_base.return_value["knowledgeBase"])
        kb.update(createdAt=now, updatedAt=now, roleArn=f"arn:aws:iam::{ACCOUNT}:role/ecommerce-agent-demo-policy-knowledge",
                  knowledgeBaseConfiguration={"type": "VECTOR", "vectorKnowledgeBaseConfiguration": {
                      "embeddingModelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"}},
                  storageConfiguration={"type": "S3_VECTORS", "s3VectorsConfiguration": {
                      "indexArn": f"arn:aws:s3vectors:us-east-1:{ACCOUNT}:bucket/ecommerce-agent-demo-vectors/index/policies"}})
        source = deepcopy(self.agent.get_data_source.return_value["dataSource"])
        source.update(createdAt=now, updatedAt=now)
        started, complete = job("STARTING"), job()
        for value in (started, complete):
            value.update(startedAt=now, updatedAt=now)
        with Stubber(sts) as sts_stub, Stubber(agent) as agent_stub:
            sts_stub.add_response("get_caller_identity", {"Account": ACCOUNT, "UserId": "testing", "Arn": f"arn:aws:iam::{ACCOUNT}:root"}, {})
            agent_stub.add_response("get_knowledge_base", {"knowledgeBase": kb}, {"knowledgeBaseId": KB})
            agent_stub.add_response("get_data_source", {"dataSource": source}, {"knowledgeBaseId": KB, "dataSourceId": SOURCE})
            agent_stub.add_response("list_ingestion_jobs", {"ingestionJobSummaries": []}, {"knowledgeBaseId": KB,
                "dataSourceId": SOURCE, "maxResults": 1, "sortBy": {"attribute": "STARTED_AT", "order": "DESCENDING"}})
            agent_stub.add_response("start_ingestion_job", {"ingestionJob": started}, {"knowledgeBaseId": KB,
                "dataSourceId": SOURCE, "clientToken": ANY, "description": f"policy-document-sha256:{HASH}"})
            agent_stub.add_response("get_ingestion_job", {"ingestionJob": complete}, {"knowledgeBaseId": KB,
                "dataSourceId": SOURCE, "ingestionJobId": "JOBDEMO123"})
            result = sync.synchronize(sts, agent, self.outputs, expected_account_id=ACCOUNT, sleep=Mock())
            self.assertEqual(result["status"], "COMPLETE")
            agent_stub.assert_no_pending_responses()


if __name__ == "__main__":
    unittest.main()
