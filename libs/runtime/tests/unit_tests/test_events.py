import json
from datetime import UTC, datetime

from deepagents_runtime.events import SCHEMA_VERSION, RuntimeEvent, create_runtime_event


class TestRuntimeEvent:
    def test_to_dict_uses_iso_timestamp(self):
        timestamp = datetime(2026, 3, 9, 8, 0, tzinfo=UTC)
        event = RuntimeEvent(
            type="run.started",
            payload={"agent": "coder"},
            run_id="run_1",
            thread_id="thread_1",
            event_id="evt_1",
            timestamp=timestamp,
        )

        assert event.to_dict() == {
            "schema_version": SCHEMA_VERSION,
            "event_id": "evt_1",
            "run_id": "run_1",
            "thread_id": "thread_1",
            "timestamp": timestamp.isoformat(),
            "type": "run.started",
            "payload": {"agent": "coder"},
        }

    def test_to_json_is_valid_json(self):
        event = RuntimeEvent(type="message.assistant.completed", payload={"text": "hi"})

        payload = json.loads(event.to_json())

        assert payload["type"] == "message.assistant.completed"
        assert payload["payload"] == {"text": "hi"}
        assert payload["schema_version"] == SCHEMA_VERSION


class TestCreateRuntimeEvent:
    def test_defaults_payload_to_empty_dict(self):
        event = create_runtime_event("run.completed")

        assert event.payload == {}
        assert event.type == "run.completed"
        assert event.event_id.startswith("evt_")

    def test_uses_explicit_values(self):
        timestamp = datetime(2026, 3, 9, 9, 30, tzinfo=UTC)

        event = create_runtime_event(
            "tool.started",
            payload={"tool": "execute"},
            run_id="run_2",
            thread_id="thread_2",
            event_id="evt_custom",
            timestamp=timestamp,
        )

        assert event == RuntimeEvent(
            type="tool.started",
            payload={"tool": "execute"},
            run_id="run_2",
            thread_id="thread_2",
            event_id="evt_custom",
            timestamp=timestamp,
        )
