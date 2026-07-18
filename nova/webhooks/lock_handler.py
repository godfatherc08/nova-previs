"""
Backlog 5.2: the B2 Event Notification webhook — Nova-built glue, not a
Genblaze feature (CLAUDE.md is emphatic; Genblaze neither consumes nor
emits these events).

Contract, per CLAUDE.md's webhook section + B2's Event Notifications docs:

  1. Validate the ``X-Bz-Event-Notification-Signature`` header FIRST —
     HMAC-SHA256 of the raw request body with the rule's signing secret,
     sent as ``v1=<hex>``. Constant-time compare; reject before parsing.
  2. Respond 200 inside B2's 3-second window: the actual animatic work is
     scheduled as a background task, never run inline.
  3. Idempotent under at-least-once delivery: ``advance_locked_shot``
     no-ops unless the shot is currently LOCKED.
  4. Only ``locked/frame.png`` keys trigger anything. The notification rule
     is prefix-scoped (``projects/``) because B2 rules can't wildcard
     mid-path — the exact-suffix match happens here, via
     ``keys.parse_locked_frame_key`` (never a hand-rolled string match).

B2 also sends a test event when a rule is created/edited; it carries no
object to act on and gets an immediate 200 so rule creation succeeds.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from nova.pipeline.advance import advance_locked_shot
from nova.storage.keys import parse_locked_frame_key

logger = logging.getLogger("nova.webhooks")

router = APIRouter(prefix="/webhooks")

_SIGNATURE_HEADER = "x-bz-event-notification-signature"


def _signing_secret() -> str | None:
    return os.environ.get("B2_WEBHOOK_SIGNING_SECRET")


def _signature_valid(body: bytes, header_value: str | None, secret: str) -> bool:
    if not header_value:
        return False
    # Header format "v1=<hex>"; tolerate a bare hex digest too.
    provided = header_value.split("=", 1)[1] if "=" in header_value else header_value
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided.strip(), expected)


@router.post("/b2/lock")
async def handle_lock_event(request: Request, background: BackgroundTasks) -> dict:
    body = await request.body()

    secret = _signing_secret()
    if secret is None:
        # A webhook with no shared secret is an open trigger — refuse to
        # operate rather than silently accept unauthenticated events.
        logger.error("B2_WEBHOOK_SIGNING_SECRET not configured; rejecting event")
        raise HTTPException(status_code=503, detail="webhook signing not configured")
    if not _signature_valid(body, request.headers.get(_SIGNATURE_HEADER), secret):
        raise HTTPException(status_code=401, detail="invalid event signature")

    import json

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="malformed event payload") from exc

    triggered: list[str] = []
    for event in payload.get("events", []):
        event_type = event.get("eventType", "")
        if event_type == "b2:TestEvent":
            continue
        if not event_type.startswith("b2:ObjectCreated"):
            continue
        parsed = parse_locked_frame_key(event.get("objectName", ""))
        if parsed is None:
            continue
        project_id, shot_id = parsed
        # Schedule and return — the 3-second response window is why this is
        # a background task and not an inline call.
        background.add_task(advance_locked_shot, project_id, shot_id)
        triggered.append(f"{project_id}/{shot_id}")

    return {"ok": True, "triggered": triggered}
