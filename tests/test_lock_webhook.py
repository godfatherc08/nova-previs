"""
Backlog 5.2 acceptance: the webhook validates the B2 event signature before
anything else, answers fast with a 200, triggers the animatic stage in the
background, and stays idempotent under at-least-once delivery (the
idempotency itself lives in advance_locked_shot — covered in
test_advance.py; here we assert the handler's contract: auth, routing,
filtering).
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import nova.webhooks.lock_handler as lock_handler
from nova.api.app import app

_SECRET = "s" * 32


def _sign(body: bytes, secret: str = _SECRET) -> str:
    return "v1=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _event_body(object_name: str, event_type: str = "b2:ObjectCreated:Upload") -> bytes:
    return json.dumps(
        {"events": [{"eventType": event_type, "objectName": object_name}]}
    ).encode()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("B2_WEBHOOK_SIGNING_SECRET", _SECRET)
    monkeypatch.setattr("nova.api.app.init_db", lambda: None)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        lock_handler, "advance_locked_shot", lambda pid, sid: calls.append((pid, sid))
    )
    with TestClient(app) as test_client:
        yield test_client, calls


def test_valid_locked_frame_event_triggers_advance(client):
    test_client, calls = client
    body = _event_body("projects/p1/shots/s3/locked/frame.png")

    res = test_client.post(
        "/webhooks/b2/lock",
        content=body,
        headers={"x-bz-event-notification-signature": _sign(body)},
    )

    assert res.status_code == 200
    assert res.json()["triggered"] == ["p1/s3"]
    # TestClient runs background tasks before returning — the advance call
    # happened, with the ids parsed from the object key.
    assert calls == [("p1", "s3")]


def test_bad_signature_is_rejected_before_any_processing(client):
    test_client, calls = client
    body = _event_body("projects/p1/shots/s3/locked/frame.png")

    res = test_client.post(
        "/webhooks/b2/lock",
        content=body,
        headers={"x-bz-event-notification-signature": _sign(body, "w" * 32)},
    )

    assert res.status_code == 401
    assert calls == []


def test_missing_signature_header_is_rejected(client):
    test_client, calls = client
    res = test_client.post(
        "/webhooks/b2/lock", content=_event_body("projects/p1/shots/s3/locked/frame.png")
    )
    assert res.status_code == 401
    assert calls == []


def test_unconfigured_secret_returns_503_not_open_trigger(client, monkeypatch):
    test_client, calls = client
    monkeypatch.delenv("B2_WEBHOOK_SIGNING_SECRET")
    body = _event_body("projects/p1/shots/s3/locked/frame.png")

    res = test_client.post(
        "/webhooks/b2/lock",
        content=body,
        headers={"x-bz-event-notification-signature": _sign(body)},
    )

    assert res.status_code == 503
    assert calls == []


def test_non_locked_frame_objects_are_ignored(client):
    """The rule is prefix-scoped only (B2 can't filter suffixes), so every
    project object write is delivered — draft frames must not trigger."""
    test_client, calls = client
    body = _event_body("projects/p1/shots/s3/frames/v2.png")

    res = test_client.post(
        "/webhooks/b2/lock",
        content=body,
        headers={"x-bz-event-notification-signature": _sign(body)},
    )

    assert res.status_code == 200
    assert res.json()["triggered"] == []
    assert calls == []


def test_b2_test_event_gets_200_so_rule_creation_succeeds(client):
    test_client, calls = client
    body = json.dumps({"events": [{"eventType": "b2:TestEvent"}]}).encode()

    res = test_client.post(
        "/webhooks/b2/lock",
        content=body,
        headers={"x-bz-event-notification-signature": _sign(body)},
    )

    assert res.status_code == 200
    assert calls == []


def test_bare_hex_signature_without_v1_prefix_is_accepted(client):
    test_client, calls = client
    body = _event_body("projects/p1/shots/s3/locked/frame.png")
    bare = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()

    res = test_client.post(
        "/webhooks/b2/lock",
        content=body,
        headers={"x-bz-event-notification-signature": bare},
    )

    assert res.status_code == 200
    assert calls == [("p1", "s3")]
