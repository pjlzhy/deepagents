from deepagents_runtime.inputs import (
    InputEnvelope,
    coerce_input_envelope,
    normalize_input_mode,
)


def test_normalize_input_mode_returns_none_for_unknown_values() -> None:
    assert normalize_input_mode("nope") is None
    assert normalize_input_mode(123) is None


def test_coerce_input_envelope_rejects_non_dict_payload() -> None:
    assert coerce_input_envelope("hello") is None


def test_coerce_input_envelope_requires_thread_id_mode_and_text() -> None:
    assert coerce_input_envelope({}) is None
    assert coerce_input_envelope({"thread_id": "t1", "mode": "normal"}) is None
    assert coerce_input_envelope({"thread_id": "t1", "text": "hi"}) is None
    assert coerce_input_envelope({"mode": "normal", "text": "hi"}) is None


def test_coerce_input_envelope_accepts_minimal_payload() -> None:
    envelope = coerce_input_envelope(
        {"thread_id": "t1", "mode": "normal", "text": "hi"}
    )

    assert envelope == InputEnvelope(
        thread_id="t1",
        mode="normal",
        text="hi",
        attachments=(),
    )


def test_coerce_input_envelope_accepts_null_or_empty_attachments() -> None:
    envelope = coerce_input_envelope(
        {"thread_id": "t1", "mode": "command", "text": "/help", "attachments": None}
    )

    assert envelope is not None
    assert envelope.attachments == ()


def test_coerce_input_envelope_rejects_invalid_attachments_shape() -> None:
    assert (
        coerce_input_envelope(
            {"thread_id": "t1", "mode": "normal", "text": "hi", "attachments": 123}
        )
        is None
    )
    assert (
        coerce_input_envelope(
            {"thread_id": "t1", "mode": "normal", "text": "hi", "attachments": ["nope"]}
        )
        is None
    )


def test_coerce_input_envelope_accepts_supported_attachment_kinds() -> None:
    payload: dict[str, object] = {
        "thread_id": "t1",
        "mode": "normal",
        "text": "hi",
        "attachments": [
            {"kind": "file", "path": "/path/example.txt", "inject": True},
            {
                "kind": "image",
                "data_url": "data:image/png;base64,AAAA",
                "name": "x.png",
            },
        ],
    }
    envelope = coerce_input_envelope(payload)

    assert envelope is not None
    assert envelope.attachments[0]["kind"] == "file"
    assert envelope.attachments[1]["kind"] == "image"


def test_coerce_input_envelope_rejects_unknown_attachment_kind() -> None:
    payload: dict[str, object] = {
        "thread_id": "t1",
        "mode": "normal",
        "text": "hi",
        "attachments": [{"kind": "nope", "value": 1}],
    }

    assert coerce_input_envelope(payload) is None


def test_coerce_input_envelope_rejects_invalid_attachment_fields() -> None:
    assert (
        coerce_input_envelope(
            {
                "thread_id": "t1",
                "mode": "normal",
                "text": "hi",
                "attachments": [{"kind": "file", "inject": True}],
            }
        )
        is None
    )
    assert (
        coerce_input_envelope(
            {
                "thread_id": "t1",
                "mode": "normal",
                "text": "hi",
                "attachments": [{"kind": "file", "path": 123}],
            }
        )
        is None
    )
    assert (
        coerce_input_envelope(
            {
                "thread_id": "t1",
                "mode": "normal",
                "text": "hi",
                "attachments": [{"kind": "file", "path": "/x", "inject": "yes"}],
            }
        )
        is None
    )
    assert (
        coerce_input_envelope(
            {
                "thread_id": "t1",
                "mode": "normal",
                "text": "hi",
                "attachments": [{"kind": "image"}],
            }
        )
        is None
    )
    assert (
        coerce_input_envelope(
            {
                "thread_id": "t1",
                "mode": "normal",
                "text": "hi",
                "attachments": [{"kind": "image", "data_url": 123}],
            }
        )
        is None
    )
    assert (
        coerce_input_envelope(
            {
                "thread_id": "t1",
                "mode": "normal",
                "text": "hi",
                "attachments": [
                    {
                        "kind": "image",
                        "data_url": "data:image/png;base64,AAAA",
                        "name": 1,
                    }
                ],
            }
        )
        is None
    )
