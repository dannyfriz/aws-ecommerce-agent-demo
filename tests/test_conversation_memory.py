"""Memoria de sesión con aislamiento, vigencia y contrato real del SDK sin llamadas remotas."""
from datetime import datetime, timezone
import hashlib
import json
import unittest
from unittest.mock import Mock

import boto3
from botocore.stub import ANY, Stubber

from ecommerce_agent.conversation_memory import (
    AgentCoreConversationMemory, AgentCorePreferenceMemory, ConversationContext,
    LocalConversationMemory, LocalPreferenceMemory, memory_actor_id, validate_session_id,
)
from ecommerce_agent.domain import AppError


SESSION = "e9c98491-2d3b-466b-87b0-37e64d411f68"
OTHER_SESSION = "a5cf82bd-9674-4a96-bcc9-0bf038004fec"
MEMORY_ID = "demo_conversation-abcdefghij"
PREFERENCES_ID = "demo_preferences-abcdefghij"
RECORD_ID = "mem-e9c98491-2d3b-466b-87b0-37e64d411f68"
NOW = 1700000000


def event(actor="camila", session=SESSION, order_id="P-104", pending_action=None, timestamp=NOW, expiry=None):
    """Construye eventos del SDK con contenido mínimo y tiempo controlado."""
    return {
        "memoryId": MEMORY_ID, "actorId": memory_actor_id(actor, "demo"), "sessionId": session,
        "eventId": f"{timestamp}#abcdef", "eventTimestamp": datetime.fromtimestamp(timestamp, timezone.utc),
        "payload": [{"blob": {"schema_version": 1, "order_id": order_id, "pending_action": pending_action,
                              "expires_at": timestamp + 900 if expiry is None else expiry}}],
    }


class LocalConversationMemoryTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.memory = LocalConversationMemory("demo", clock=lambda: self.now)

    def test_context_isolated_by_authenticated_actor_and_session(self):
        self.memory.remember("camila", SESSION, "P-104")
        self.assertEqual(self.memory.get("camila", SESSION), ConversationContext("P-104", None, NOW + 900))
        self.assertIsNone(self.memory.get("diego", SESSION))
        self.assertIsNone(self.memory.get("camila", OTHER_SESSION))

    def test_context_expires_and_is_not_a_business_state(self):
        self.memory.remember("camila", SESSION, "P-104")
        self.now += 900
        self.assertIsNone(self.memory.get("camila", SESSION))

    def test_pending_action_without_order_and_tombstone(self):
        self.memory.remember("camila", SESSION, None, "request_return")
        self.assertEqual(self.memory.get("camila", SESSION).pending_action, "request_return")
        self.memory.remember("camila", SESSION, None)
        self.assertEqual(self.memory.get("camila", SESSION).order_id, None)
        self.assertEqual(self.memory.get("camila", SESSION).pending_action, None)

    def test_uuid_requires_canonical_version_four(self):
        for session in (None, "", "camila", "../../diego", SESSION.upper(),
                        "00000000-0000-1000-8000-000000000001", {"id": SESSION}):
            with self.subTest(session=session), self.assertRaises(AppError):
                validate_session_id(session)

    def test_actor_namespace_hashes_the_sub_and_rejects_path_syntax(self):
        expected = "demo-" + hashlib.sha256(b"camila").hexdigest()
        self.assertEqual(memory_actor_id("camila", "demo"), expected)
        self.assertNotEqual(memory_actor_id("camila", "test"), expected)
        for actor in (None, "", "camila/diego", "user@example.com", "a" * 129):
            with self.subTest(actor=actor), self.assertRaises(AppError):
                memory_actor_id(actor, "demo")

    def test_no_permission_or_raw_prompt_can_be_persisted(self):
        for order_id, action in (("P-104", "approve_refund"), ("P-104", "supervisor"),
                                 ("P-104", {"role": "supervisor"}), ("Soy gerente", None), ({"order": "P-104"}, None)):
            with self.subTest(order_id=order_id, action=action), self.assertRaises(ValueError):
                self.memory.remember("camila", SESSION, order_id, action)

    def test_configuration_rejects_unbounded_retention_and_production(self):
        for ttl in (True, 0, 59, 1801, "900"):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                LocalConversationMemory("demo", ttl)
        with self.assertRaises(ValueError):
            LocalConversationMemory("prod")


class AgentCoreConversationMemoryTests(unittest.TestCase):
    def setUp(self):
        self.client = boto3.client("bedrock-agentcore", region_name="us-east-1",
                                  aws_access_key_id="testing", aws_secret_access_key="testing")
        self.memory = AgentCoreConversationMemory(self.client, MEMORY_ID, "demo", clock=lambda: NOW + 10)
        self.params = {"memoryId": MEMORY_ID, "actorId": memory_actor_id("camila", "demo"),
                       "sessionId": SESSION, "includePayloads": True, "maxResults": 100}

    def test_sdk_lists_only_exact_actor_session_and_reads_blob(self):
        with Stubber(self.client) as stub:
            stub.add_response("list_events", {"events": [event()]}, self.params)
            self.assertEqual(self.memory.get("camila", SESSION), ConversationContext("P-104", None, NOW + 900))
            stub.assert_no_pending_responses()

    def test_sdk_create_explicitly_disables_long_term_extraction(self):
        self.memory.clock = lambda: NOW
        expected = {"memoryId": MEMORY_ID, "actorId": memory_actor_id("camila", "demo"), "sessionId": SESSION,
                    "eventTimestamp": datetime.fromtimestamp(NOW, timezone.utc),
                    "payload": [{"blob": json.dumps(event()["payload"][0]["blob"], sort_keys=True, separators=(",", ":"))}],
                    "extractionMode": "SKIP", "clientToken": ANY}
        with Stubber(self.client) as stub:
            stub.add_response("create_event", {"event": event()}, expected)
            self.memory.remember("camila", SESSION, "P-104")
            stub.assert_no_pending_responses()

    def test_sdk_empty_session_is_not_an_error(self):
        with Stubber(self.client) as stub:
            stub.add_response("list_events", {"events": []}, self.params)
            self.assertIsNone(self.memory.get("camila", SESSION))

    def test_create_accepts_metadata_acknowledgement_without_payload_echo(self):
        client = Mock()
        acknowledged = event()
        acknowledged.pop("payload")
        acknowledged["branch"] = {"name": "main"}
        client.create_event.return_value = {"event": acknowledged}
        memory = AgentCoreConversationMemory(client, MEMORY_ID, "demo", clock=lambda: NOW)
        memory.remember("camila", SESSION, "P-104")
        sent = client.create_event.call_args.kwargs
        self.assertEqual(json.loads(sent["payload"][0]["blob"]), event()["payload"][0]["blob"])
        self.assertEqual(sent["extractionMode"], "SKIP")
        client.list_events.assert_not_called()
        client.list_events.return_value = {"events": [{**event(), "payload": sent["payload"]}]}
        self.assertEqual(memory.get("camila", SESSION), ConversationContext("P-104", None, NOW + 900))
        self.assertTrue(client.list_events.call_args.kwargs["includePayloads"])

    def test_metadata_acknowledgement_rejects_wrong_identity_or_malformed_header(self):
        fields = (("actorId", memory_actor_id("diego", "demo")), ("sessionId", OTHER_SESSION),
                  ("memoryId", "other_memory-abcdefghij"), ("eventId", "invalid"),
                  ("eventTimestamp", datetime.fromtimestamp(NOW)), ("eventTimestamp", "2026-10-23"),
                  ("eventTimestamp", datetime.fromtimestamp(NOW + 60, timezone.utc)))
        for field, value in fields:
            acknowledged = event()
            acknowledged.pop("payload")
            acknowledged[field] = value
            client = Mock()
            client.create_event.return_value = {"event": acknowledged}
            memory = AgentCoreConversationMemory(client, MEMORY_ID, "demo", clock=lambda: NOW)
            with self.subTest(field=field, value=value), self.assertRaises(AppError) as error:
                memory.remember("camila", SESSION, "P-104")
            self.assertEqual(error.exception.code, "MEMORY_UNAVAILABLE")
            client.list_events.assert_not_called()

    def test_list_events_still_requires_payload_even_with_valid_metadata(self):
        acknowledged = event()
        acknowledged.pop("payload")
        client = Mock()
        client.list_events.return_value = {"events": [acknowledged]}
        memory = AgentCoreConversationMemory(client, MEMORY_ID, "demo", clock=lambda: NOW)
        with self.assertRaises(AppError) as error:
            memory.get("camila", SESSION)
        self.assertEqual(error.exception.code, "MEMORY_UNAVAILABLE")
        self.assertTrue(client.list_events.call_args.kwargs["includePayloads"])

    def test_create_rejects_present_but_missing_or_malformed_payload_content(self):
        for payload in (None, [], [{"blob": {"order_id": "P-104"}}], event(order_id="P-205")["payload"]):
            client = Mock()
            client.create_event.return_value = {"event": {**event(), "payload": payload}}
            memory = AgentCoreConversationMemory(client, MEMORY_ID, "demo", clock=lambda: NOW)
            with self.subTest(payload=payload), self.assertRaises(AppError):
                memory.remember("camila", SESSION, "P-104")

    def test_selects_latest_across_pages_without_assuming_service_sort_order(self):
        with Stubber(self.client) as stub:
            stub.add_response("list_events", {"events": [event(timestamp=NOW - 50)], "nextToken": "page2"}, self.params)
            stub.add_response("list_events", {"events": [event(order_id="P-205", timestamp=NOW)]},
                              {**self.params, "nextToken": "page2"})
            self.assertEqual(self.memory.get("camila", SESSION).order_id, "P-205")

    def test_expired_latest_or_empty_tombstone_never_resurrects_older_order(self):
        for newest in (event(order_id=None, timestamp=NOW + 1),
                       event(order_id=None, timestamp=NOW, expiry=NOW + 5)):
            with self.subTest(newest=newest), Stubber(self.client) as stub:
                stub.add_response("list_events", {"events": [event(timestamp=NOW - 1), newest]}, self.params)
                result = self.memory.get("camila", SESSION)
                self.assertTrue(result is None or result.order_id is None)

    def test_expired_legacy_map_is_not_parsed_or_reused(self):
        expired = event(timestamp=NOW - 890)
        expired["payload"] = [{"blob": "{schema_version=1, pending_action=request_return, order_id=P-104}"}]
        with Stubber(self.client) as stub:
            stub.add_response("list_events", {"events": [expired]}, self.params)
            self.assertIsNone(self.memory.get("camila", SESSION))

    def test_expired_invalid_history_does_not_block_fresh_valid_context(self):
        expired = event(timestamp=NOW - 1000)
        expired["payload"] = [{"blob": "{schema_version=1, order_id=P-104}"}]
        fresh = event(order_id="P-205", timestamp=NOW)
        for records in ([expired, fresh], [fresh, expired]):
            with self.subTest(records=records), Stubber(self.client) as stub:
                stub.add_response("list_events", {"events": records}, self.params)
                self.assertEqual(self.memory.get("camila", SESSION), ConversationContext("P-205", None, NOW + 900))

    def test_newest_expired_marker_never_resurrects_an_older_order(self):
        older = event(timestamp=NOW - 1000, expiry=NOW + 500)
        latest = event(timestamp=NOW - 900)
        latest["payload"] = [{"blob": "{schema_version=1, order_id=null}"}]
        with Stubber(self.client) as stub:
            stub.add_response("list_events", {"events": [latest], "nextToken": "older"}, self.params)
            stub.add_response("list_events", {"events": [older]}, {**self.params, "nextToken": "older"})
            self.assertIsNone(self.memory.get("camila", SESSION))

    def test_expired_payload_never_bypasses_identity_or_header_validation(self):
        for field, value in (("actorId", memory_actor_id("diego", "demo")), ("sessionId", OTHER_SESSION),
                             ("memoryId", "other_memory-abcdefghij"), ("eventId", "malformed"),
                             ("eventTimestamp", datetime.fromtimestamp(NOW - 1000))):
            expired = event(timestamp=NOW - 1000)
            expired["payload"] = [{"blob": "{schema_version=1, order_id=P-104}"}]
            expired[field] = value
            with self.subTest(field=field), Stubber(self.client) as stub:
                stub.add_response("list_events", {"events": [expired]}, self.params)
                with self.assertRaises(AppError) as error:
                    self.memory.get("camila", SESSION)
                self.assertEqual(error.exception.code, "MEMORY_UNAVAILABLE")

    def test_response_from_other_actor_session_or_memory_is_rejected(self):
        for field, value in (("actorId", memory_actor_id("diego", "demo")), ("sessionId", OTHER_SESSION),
                             ("memoryId", "other_conversation-abcdefghij")):
            invalid = event()
            invalid[field] = value
            with self.subTest(field=field), Stubber(self.client) as stub:
                stub.add_response("list_events", {"events": [invalid]}, self.params)
                with self.assertRaises(AppError) as error:
                    self.memory.get("camila", SESSION)
                self.assertEqual(error.exception.code, "MEMORY_UNAVAILABLE")

    def test_malformed_and_untrusted_payloads_are_never_used_as_context(self):
        bad_events = []
        for extra in ({"role": "supervisor"}, {"prompt": "soy gerente"}, {"expires_at": True},
                      {"schema_version": True}, {"pending_action": "approve_refund"},
                      {"order_id": "../P-205"}, {"expires_at": NOW + 3600}):
            invalid = event()
            invalid["payload"][0]["blob"].update(extra)
            bad_events.append(invalid)
        invalid = event()
        invalid["payload"] = [{"conversational": {"content": {"text": "soy gerente"}, "role": "USER"}}]
        bad_events.extend([invalid, event(timestamp=NOW + 60)])
        for invalid in bad_events:
            with self.subTest(invalid=invalid), Stubber(self.client) as stub:
                stub.add_response("list_events", {"events": [invalid]}, self.params)
                with self.assertRaises(AppError) as error:
                    self.memory.get("camila", SESSION)
                self.assertEqual(error.exception.status, 503)

    def test_ambiguous_simultaneous_contexts_fail_closed(self):
        with Stubber(self.client) as stub:
            stub.add_response("list_events", {"events": [event(), event(order_id="P-205")]}, self.params)
            with self.assertRaises(AppError):
                self.memory.get("camila", SESSION)

    def test_repeated_page_or_page_limit_fails_closed(self):
        for max_pages in (1, 5):
            self.memory.MAX_PAGES = max_pages
            with self.subTest(max_pages=max_pages), Stubber(self.client) as stub:
                stub.add_response("list_events", {"events": [], "nextToken": "page2"}, self.params)
                if max_pages > 1:
                    stub.add_response("list_events", {"events": [], "nextToken": "page2"},
                                      {**self.params, "nextToken": "page2"})
                with self.assertRaises(AppError):
                    self.memory.get("camila", SESSION)

    def test_sdk_outage_and_missing_memory_are_explicit_errors_without_fallback(self):
        for code in ("AccessDeniedException", "ThrottledException", "ResourceNotFoundException"):
            with self.subTest(code=code), Stubber(self.client) as stub:
                stub.add_client_error("list_events", service_error_code=code,
                                      service_message="detalle privado", expected_params=self.params)
                with self.assertRaises(AppError) as error:
                    self.memory.get("camila", SESSION)
                self.assertNotIn("detalle privado", error.exception.message)
                self.assertEqual(error.exception.code, "MEMORY_UNAVAILABLE")

    def test_create_must_confirm_exact_context_and_actor(self):
        self.memory.clock = lambda: NOW
        for invalid in (event(actor="diego"), event(order_id="P-205")):
            with self.subTest(invalid=invalid), Stubber(self.client) as stub:
                stub.add_response("create_event", {"event": invalid},
                    {"memoryId": MEMORY_ID, "actorId": memory_actor_id("camila", "demo"), "sessionId": SESSION,
                     "eventTimestamp": ANY,
                     "payload": [{"blob": json.dumps(event()["payload"][0]["blob"], sort_keys=True, separators=(",", ":"))}],
                     "extractionMode": "SKIP", "clientToken": ANY})
                with self.assertRaises(AppError):
                    self.memory.remember("camila", SESSION, "P-104")

    def test_invalid_session_or_context_rejected_before_aws_call(self):
        client = Mock()
        memory = AgentCoreConversationMemory(client, MEMORY_ID, "demo")
        with self.assertRaises(AppError):
            memory.get("camila", "../diego")
        with self.assertRaises(ValueError):
            memory.remember("camila", SESSION, "P-104", "approve_refund")
        client.list_events.assert_not_called()
        client.create_event.assert_not_called()

    def test_json_string_round_trip_preserves_context_and_sdk_contract(self):
        serialized_event = event(pending_action="request_return")
        serialized_event["payload"] = [{"blob": json.dumps(serialized_event["payload"][0]["blob"], sort_keys=True, separators=(",", ":"))}]
        self.memory.clock = lambda: NOW
        expected = {"memoryId": MEMORY_ID, "actorId": memory_actor_id("camila", "demo"), "sessionId": SESSION,
                    "eventTimestamp": datetime.fromtimestamp(NOW, timezone.utc), "payload": serialized_event["payload"],
                    "extractionMode": "SKIP", "clientToken": ANY}
        with Stubber(self.client) as stub:
            stub.add_response("create_event", {"event": serialized_event}, expected)
            self.memory.remember("camila", SESSION, "P-104", "request_return")
            stub.add_response("list_events", {"events": [serialized_event]}, self.params)
            self.assertEqual(self.memory.get("camila", SESSION), ConversationContext("P-104", "request_return", NOW + 900))

    def test_non_json_map_text_and_oversized_or_injected_json_are_rejected(self):
        for content in ("{schema_version=1, pending_action=request_return, expires_at=1700000900, order_id=null}",
                        " " * 513, "null", "[]", "1", '{"schema_version":1,"role":"supervisor"}'):
            invalid = event()
            invalid["payload"] = [{"blob": content}]
            with self.subTest(content=content), Stubber(self.client) as stub:
                stub.add_response("list_events", {"events": [invalid]}, self.params)
                with self.assertRaises(AppError) as error:
                    self.memory.get("camila", SESSION)
                self.assertEqual(error.exception.code, "MEMORY_UNAVAILABLE")


def preference_record(actor="camila", detail="detailed", timestamp=NOW, extra=None):
    """Representa un registro de largo plazo sin texto de conversaciones."""
    value = {"schema_version": 1, "preferred_detail": detail, "language": "es",
             "updated_at": timestamp * 1000000, "expires_at": timestamp + 31 * 86400}
    if extra:
        value.update(extra)
    return {"memoryRecordId": RECORD_ID, "content": {"text": json.dumps(value, sort_keys=True, separators=(",", ":"))},
            "memoryStrategyId": "manual", "namespaces": [f"/preferences/{memory_actor_id(actor, 'demo')}/"],
            "createdAt": datetime.fromtimestamp(timestamp, timezone.utc)}


class PreferenceMemoryTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.client = boto3.client("bedrock-agentcore", region_name="us-east-1",
                                  aws_access_key_id="testing", aws_secret_access_key="testing")
        self.memory = AgentCorePreferenceMemory(self.client, PREFERENCES_ID, "demo", clock=lambda: self.now)
        self.namespace = f"/preferences/{memory_actor_id('camila', 'demo')}/"
        self.params = {"memoryId": PREFERENCES_ID, "namespace": self.namespace, "maxResults": 100}
        self.get_params = {"memoryId": PREFERENCES_ID, "memoryRecordId": RECORD_ID, "namespace": self.namespace}

    def test_local_preferences_cross_sessions_but_never_users(self):
        local = LocalPreferenceMemory("demo", clock=lambda: self.now)
        self.assertEqual(local.get_preferences("camila"), {"preferred_detail": "brief", "language": "es"})
        local.save_preferences("camila", "detailed")
        self.assertEqual(local.get_preferences("camila")["preferred_detail"], "detailed")
        self.assertEqual(local.get_preferences("diego")["preferred_detail"], "brief")
        self.now += 31 * 86400
        self.assertEqual(local.get_preferences("camila")["preferred_detail"], "brief")

    def test_list_uses_only_namespace_from_authenticated_sub(self):
        with Stubber(self.client) as stub:
            stub.add_response("list_memory_records", {"memoryRecordSummaries": [preference_record()]}, self.params)
            stub.add_response("get_memory_record", {"memoryRecord": preference_record()}, self.get_params)
            self.assertEqual(self.memory.get_preferences("camila"), {"preferred_detail": "detailed", "language": "es"})

    def test_defaults_only_when_no_record_exists_or_latest_expired(self):
        responses = [[], [preference_record(timestamp=NOW - 31 * 86400)]]
        for records in responses:
            with self.subTest(records=records), Stubber(self.client) as stub:
                stub.add_response("list_memory_records", {"memoryRecordSummaries": records}, self.params)
                if records:
                    stub.add_response("get_memory_record", {"memoryRecord": records[0]}, self.get_params)
                self.assertEqual(self.memory.get_preferences("camila")["preferred_detail"], "brief")

    def test_sdk_create_sets_physical_ttl_and_only_normalized_preferences(self):
        expected_record = {"content": preference_record()["content"], "namespaces": [self.namespace],
                           "timestamp": datetime.fromtimestamp(NOW, timezone.utc), "requestIdentifier": "preferences"}
        with Stubber(self.client) as stub:
            stub.add_response("list_memory_records", {"memoryRecordSummaries": []}, self.params)
            stub.add_response("batch_create_memory_records", {"successfulRecords": [
                {"memoryRecordId": RECORD_ID, "requestIdentifier": "preferences", "status": "SUCCEEDED"}], "failedRecords": []},
                {"memoryId": PREFERENCES_ID, "records": [expected_record], "clientToken": ANY,
                 "recordExpirySpecification": {"recordExpiryDurationDays": 31}})
            stub.add_response("get_memory_record", {"memoryRecord": preference_record()}, self.get_params)
            stub.add_response("list_memory_records", {"memoryRecordSummaries": [preference_record()]}, self.params)
            self.assertEqual(self.memory.save_preferences("camila", "detailed")["preferred_detail"], "detailed")

    def test_sdk_update_replaces_existing_record_with_source_namespace(self):
        expected_record = {"content": preference_record(detail="brief")["content"], "namespaces": [self.namespace],
                           "timestamp": datetime.fromtimestamp(NOW, timezone.utc), "memoryRecordId": RECORD_ID,
                           "sourceNamespaces": [self.namespace]}
        with Stubber(self.client) as stub:
            stub.add_response("list_memory_records", {"memoryRecordSummaries": [preference_record()]}, self.params)
            stub.add_response("get_memory_record", {"memoryRecord": preference_record()}, self.get_params)
            stub.add_response("batch_update_memory_records", {"successfulRecords": [
                {"memoryRecordId": RECORD_ID, "status": "SUCCEEDED"}], "failedRecords": []},
                {"memoryId": PREFERENCES_ID, "records": [expected_record],
                 "recordExpirySpecification": {"recordExpiryDurationDays": 31}})
            stub.add_response("get_memory_record", {"memoryRecord": preference_record(detail="brief")}, self.get_params)
            stub.add_response("list_memory_records", {"memoryRecordSummaries": [preference_record()]}, self.params)
            self.assertEqual(self.memory.save_preferences("camila", "brief")["preferred_detail"], "brief")

    def test_write_waits_for_exact_value_visibility_without_repeating_write(self):
        client = Mock()
        client.list_memory_records.side_effect = [
            {"memoryRecordSummaries": []}, {"memoryRecordSummaries": []},
            {"memoryRecordSummaries": []}, {"memoryRecordSummaries": [preference_record()]},
        ]
        client.batch_create_memory_records.return_value = {"successfulRecords": [
            {"memoryRecordId": RECORD_ID, "requestIdentifier": "preferences", "status": "SUCCEEDED"}], "failedRecords": []}
        client.get_memory_record.return_value = {"memoryRecord": preference_record()}
        waits, elapsed = [], [0.0]
        def sleep(delay):
            waits.append(delay)
            elapsed[0] += delay
        memory = AgentCorePreferenceMemory(client, PREFERENCES_ID, "demo", clock=lambda: NOW,
                                          monotonic=lambda: elapsed[0], sleeper=sleep)
        self.assertEqual(memory.save_preferences("camila", "detailed")["preferred_detail"], "detailed")
        self.assertEqual(len(waits), 2)
        self.assertLessEqual(elapsed[0], memory.CONFIRMATION_TIMEOUT_SECONDS)
        client.batch_create_memory_records.assert_called_once()
        client.batch_update_memory_records.assert_not_called()

    def test_visibility_timeout_explicitly_reports_confirmed_write_pending_read(self):
        client = Mock()
        client.list_memory_records.return_value = {"memoryRecordSummaries": []}
        client.batch_create_memory_records.return_value = {"successfulRecords": [
            {"memoryRecordId": RECORD_ID, "requestIdentifier": "preferences", "status": "SUCCEEDED"}], "failedRecords": []}
        client.get_memory_record.return_value = {"memoryRecord": preference_record()}
        elapsed = [0.0]
        def sleep(delay):
            elapsed[0] += delay
        memory = AgentCorePreferenceMemory(client, PREFERENCES_ID, "demo", clock=lambda: NOW,
                                          monotonic=lambda: elapsed[0], sleeper=sleep)
        with self.assertRaises(AppError) as error:
            memory.save_preferences("camila", "detailed")
        self.assertEqual(error.exception.code, "PREFERENCES_PENDING")
        self.assertIn("fue aceptada", error.exception.message)
        self.assertLessEqual(elapsed[0], memory.CONFIRMATION_TIMEOUT_SECONDS)
        self.assertLessEqual(client.list_memory_records.call_count, 1 + memory.MAX_CONFIRMATION_ATTEMPTS)
        client.batch_create_memory_records.assert_called_once()

    def test_confirmation_does_not_accept_stale_style_or_another_users_record(self):
        for record in (preference_record(detail="brief"), preference_record(actor="diego")):
            client = Mock()
            client.list_memory_records.side_effect = [
                {"memoryRecordSummaries": []}, {"memoryRecordSummaries": [record]},
            ]
            client.batch_create_memory_records.return_value = {"successfulRecords": [
                {"memoryRecordId": RECORD_ID, "requestIdentifier": "preferences", "status": "SUCCEEDED"}], "failedRecords": []}
            client.get_memory_record.return_value = {"memoryRecord": record}
            times = iter([0.0, 3.0])
            memory = AgentCorePreferenceMemory(client, PREFERENCES_ID, "demo", clock=lambda: NOW,
                                              monotonic=lambda: next(times), sleeper=Mock())
            with self.subTest(record=record), self.assertRaises(AppError) as error:
                memory.save_preferences("camila", "detailed")
            self.assertEqual(error.exception.code, "PREFERENCES_PENDING" if record["namespaces"] == [self.namespace] else "PREFERENCES_UNAVAILABLE")
            memory.sleeper.assert_not_called()

    def test_untrusted_cross_user_content_or_authorization_fields_are_rejected(self):
        for record in (preference_record(actor="diego"), preference_record(detail="supervisor"),
                       preference_record(extra={"role": "supervisor"}), preference_record(extra={"language": "en"}),
                       preference_record(extra={"expires_at": NOW + 32 * 86400}),
                       preference_record(extra={"updated_at": True})):
            with self.subTest(record=record), Stubber(self.client) as stub:
                stub.add_response("list_memory_records", {"memoryRecordSummaries": [record]}, self.params)
                if record["namespaces"] == [self.namespace]:
                    stub.add_response("get_memory_record", {"memoryRecord": record}, self.get_params)
                with self.assertRaises(AppError) as error:
                    self.memory.get_preferences("camila")
                self.assertEqual(error.exception.code, "PREFERENCES_UNAVAILABLE")

    def test_current_content_comes_from_get_even_when_list_summary_is_stale(self):
        with Stubber(self.client) as stub:
            stub.add_response("list_memory_records", {"memoryRecordSummaries": [preference_record(detail="detailed")]}, self.params)
            stub.add_response("get_memory_record", {"memoryRecord": preference_record(detail="brief")}, self.get_params)
            self.assertEqual(self.memory.get_preferences("camila"), {"preferred_detail": "brief", "language": "es"})
            stub.assert_no_pending_responses()

    def test_get_response_must_match_discovered_id_and_exact_actor_namespace(self):
        another_id = {**preference_record(), "memoryRecordId": "mem-a5cf82bd-9674-4a96-bcc9-0bf038004fec"}
        for record in (preference_record(actor="diego"), another_id):
            with self.subTest(record=record), Stubber(self.client) as stub:
                stub.add_response("list_memory_records", {"memoryRecordSummaries": [preference_record()]}, self.params)
                stub.add_response("get_memory_record", {"memoryRecord": record}, self.get_params)
                with self.assertRaises(AppError) as error:
                    self.memory.get_preferences("camila")
                self.assertEqual(error.exception.code, "PREFERENCES_UNAVAILABLE")

    def test_get_outage_is_not_replaced_with_list_stale_content_or_defaults(self):
        with Stubber(self.client) as stub:
            stub.add_response("list_memory_records", {"memoryRecordSummaries": [preference_record()]}, self.params)
            stub.add_client_error("get_memory_record", service_error_code="AccessDeniedException", expected_params=self.get_params)
            with self.assertRaises(AppError) as error:
                self.memory.get_preferences("camila")
            self.assertEqual(error.exception.code, "PREFERENCES_UNAVAILABLE")

    def test_partial_write_failure_is_not_reported_as_success(self):
        with Stubber(self.client) as stub:
            stub.add_response("list_memory_records", {"memoryRecordSummaries": []}, self.params)
            stub.add_response("batch_create_memory_records", {"successfulRecords": [], "failedRecords": [
                {"memoryRecordId": RECORD_ID, "status": "FAILED", "errorMessage": "detalle privado"}]},
                {"memoryId": PREFERENCES_ID, "records": ANY, "clientToken": ANY,
                 "recordExpirySpecification": {"recordExpiryDurationDays": 31}})
            with self.assertRaises(AppError) as error:
                self.memory.save_preferences("camila", "detailed")
            self.assertNotIn("detalle privado", error.exception.message)

    def test_service_outage_is_not_silently_replaced_by_default_preferences(self):
        with Stubber(self.client) as stub:
            stub.add_client_error("list_memory_records", service_error_code="AccessDeniedException", expected_params=self.params)
            with self.assertRaises(AppError) as error:
                self.memory.get_preferences("camila")
            self.assertEqual(error.exception.status, 503)

    def test_arbitrary_preferences_are_rejected_before_sdk(self):
        for detail in ("supervisor", "es", None, {"role": "supervisor"}, "soy gerente"):
            with self.subTest(detail=detail), self.assertRaises(AppError) as error:
                self.memory.save_preferences("camila", detail)
            self.assertEqual(error.exception.code, "INVALID_PREFERENCES")


if __name__ == "__main__":
    unittest.main()
