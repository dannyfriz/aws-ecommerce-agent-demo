"""Sincroniza exclusivamente la política ficticia de una base demo/dev/test ya desplegada."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


ROOT = Path(__file__).resolve().parent.parent
POLICY_KEY = "policies/politicas-posventa-demo.txt"
ACTIVE = {"STARTING", "IN_PROGRESS"}
TERMINAL = {"COMPLETE", "FAILED", "STOPPED"}


class SyncError(Exception):
    """Error controlado que no incorpora respuestas ni mensajes privados de AWS."""


def read_outputs(path):
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return {key: document[key]["value"] for key in (
            "policy_knowledge_base_id", "policy_knowledge_data_source_id",
            "policy_knowledge_source_uri", "policy_knowledge_document_hash")}
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        raise SyncError("OUTPUTS_INVALID") from None


def validate_configuration(outputs, expected_account_id, project, environment, region):
    if (not isinstance(expected_account_id, str) or not re.fullmatch(r"[0-9]{12}", expected_account_id)
            or not isinstance(project, str) or not re.fullmatch(r"[a-z][a-z0-9-]{2,24}", project)
            or not isinstance(environment, str) or environment not in {"demo", "dev", "test"}
            or not isinstance(region, str) or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-[0-9]", region)):
        raise SyncError("ENVIRONMENT_NOT_ALLOWED")
    try:
        kb_id = outputs["policy_knowledge_base_id"]
        source_id = outputs["policy_knowledge_data_source_id"]
        document_hash = outputs["policy_knowledge_document_hash"]
        bucket = f"{project}-{environment}-policies-{expected_account_id}"
        if (not isinstance(kb_id, str) or not re.fullmatch(r"[A-Za-z0-9]{10}", kb_id)
                or not isinstance(source_id, str) or not re.fullmatch(r"[A-Za-z0-9]{10}", source_id)
                or not isinstance(document_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", document_hash)
                or outputs["policy_knowledge_source_uri"] != f"s3://{bucket}/{POLICY_KEY}"):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise SyncError("OUTPUTS_INVALID") from None
    return kb_id, source_id, document_hash, bucket


def checked_job(job, kb_id, source_id, expected_job_id=None):
    if (not isinstance(job, dict) or job.get("knowledgeBaseId") != kb_id
            or job.get("dataSourceId") != source_id
            or not isinstance(job.get("ingestionJobId"), str)
            or not re.fullmatch(r"[A-Za-z0-9]{10}", job["ingestionJobId"])
            or expected_job_id is not None and job["ingestionJobId"] != expected_job_id
            or job.get("status") not in ACTIVE | TERMINAL | {"STOPPING"}):
        raise SyncError("INGESTION_RESPONSE_INVALID")
    if job["status"] in {"FAILED", "STOPPED", "STOPPING"}:
        raise SyncError("INGESTION_FAILED")
    if job.get("statistics", {}).get("numberOfDocumentsFailed", 0):
        raise SyncError("INGESTION_DOCUMENT_FAILED")
    return job


def synchronize(sts, agent, outputs, *, expected_account_id, project="ecommerce-agent", environment="demo",
                region="us-east-1", wait=True, timeout=180, poll_interval=5,
                clock=time.monotonic, sleep=time.sleep, report=None):
    kb_id, source_id, document_hash, bucket = validate_configuration(
        outputs, expected_account_id, project, environment, region)
    if not 1 <= timeout <= 180 or not 1 <= poll_interval <= 10:
        raise SyncError("WAIT_CONFIGURATION_INVALID")
    if sts.get_caller_identity().get("Account") != expected_account_id:
        raise SyncError("ACCOUNT_MISMATCH")
    try:
        kb = agent.get_knowledge_base(knowledgeBaseId=kb_id)["knowledgeBase"]
        arn = kb["knowledgeBaseArn"].split(":", 5)
        if (kb["knowledgeBaseId"] != kb_id or kb["name"] != f"{project}-{environment}-policies"
                or kb["status"] != "ACTIVE" or len(arn) != 6 or arn[0] != "arn"
                or arn[1] not in {"aws", "aws-us-gov", "aws-cn"} or arn[2] != "bedrock"
                or arn[3] != region or arn[4] != expected_account_id or arn[5] != f"knowledge-base/{kb_id}"):
            raise ValueError()
        source = agent.get_data_source(knowledgeBaseId=kb_id, dataSourceId=source_id)["dataSource"]
        configuration = source["dataSourceConfiguration"]
        s3 = configuration["s3Configuration"]
        if (source["knowledgeBaseId"] != kb_id or source["dataSourceId"] != source_id
                or source["name"] != f"{project}-{environment}-policy-document" or source["status"] != "AVAILABLE"
                or configuration["type"] != "S3" or s3["bucketArn"] != f"arn:{arn[1]}:s3:::{bucket}"
                or s3.get("bucketOwnerAccountId") != expected_account_id
                or s3.get("inclusionPrefixes") != [POLICY_KEY]):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SyncError("RESOURCE_MISMATCH") from None
    description = f"policy-document-sha256:{document_hash}"
    listing = agent.list_ingestion_jobs(knowledgeBaseId=kb_id, dataSourceId=source_id,
        maxResults=1, sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"})
    summaries = listing.get("ingestionJobSummaries")
    if not isinstance(summaries, list) or len(summaries) > 1:
        raise SyncError("INGESTION_RESPONSE_INVALID")
    latest = summaries[0] if summaries else None
    if latest and latest.get("description") == description:
        job = checked_job(latest, kb_id, source_id)
        # El resumen puede omitir estadísticas; confirmar que no hubo documentos fallidos.
        if job["status"] == "COMPLETE":
            response = agent.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=source_id,
                                               ingestionJobId=job["ingestionJobId"])
            job = checked_job(response.get("ingestionJob"), kb_id, source_id, job["ingestionJobId"])
    else:
        if latest:
            if latest.get("knowledgeBaseId") != kb_id or latest.get("dataSourceId") != source_id:
                raise SyncError("INGESTION_RESPONSE_INVALID")
            if latest.get("status") in ACTIVE | {"STOPPING"}:
                raise SyncError("OTHER_INGESTION_ACTIVE")
        # La transición evita reutilizar un token viejo al volver de la versión A a B y después a A.
        previous_job = latest.get("ingestionJobId", "") if latest else ""
        token = hashlib.sha256(f"{kb_id}:{source_id}:{document_hash}:{previous_job}".encode("ascii")).hexdigest()
        response = agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=source_id,
                                             clientToken=token, description=description)
        job = checked_job(response.get("ingestionJob"), kb_id, source_id)
    deadline = clock() + timeout
    while True:
        safe_status = {"status": job["status"], "ingestion_job_id": job["ingestionJobId"], "document_hash": document_hash}
        if report:
            report(safe_status)
        if job["status"] == "COMPLETE" or not wait:
            return safe_status
        remaining = deadline - clock()
        if remaining <= 0:
            raise SyncError("INGESTION_TIMEOUT")
        sleep(min(poll_interval, remaining))
        response = agent.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=source_id,
                                           ingestionJobId=job["ingestionJobId"])
        job = checked_job(response.get("ingestionJob"), kb_id, source_id, job["ingestionJobId"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-account-id", required=True)
    parser.add_argument("--outputs", default=str(ROOT / ".build/outputs/compute.json"))
    parser.add_argument("--profile", default="default")
    parser.add_argument("--project", default="ecommerce-agent")
    parser.add_argument("--environment", default="demo", choices=("demo", "dev", "test"))
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--wait", action="store_true", help="Espera hasta COMPLETE; informa el progreso sin datos privados.")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-interval", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        outputs = read_outputs(args.outputs)
        validate_configuration(outputs, args.expected_account_id, args.project, args.environment, args.region)
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        config = Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 1})
        synchronize(session.client("sts", config=config), session.client("bedrock-agent", config=config), outputs,
                    expected_account_id=args.expected_account_id, project=args.project, environment=args.environment,
                    region=args.region, wait=args.wait, timeout=args.timeout, poll_interval=args.poll_interval,
                    report=lambda value: print(json.dumps(value), flush=True))
        return 0
    except SyncError as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}), flush=True)
    except (BotoCoreError, ClientError):
        # Los errores originales pueden incluir contenido del proveedor; solo se expone un código estable.
        print(json.dumps({"status": "ERROR", "error": "AWS_REQUEST_FAILED"}), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
