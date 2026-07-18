"""
Backlog 5.1: configure the B2 Event Notification rule that fires on lock.

Creates/updates a rule on nova-previs: ``b2:ObjectCreated:*`` scoped to the
``projects/`` prefix, pointed at Nova's webhook. B2 rules only support a
literal *prefix* filter (no mid-path wildcards), so the exact
``locked/frame.png`` suffix match lives in the handler
(``nova/webhooks/lock_handler.py``) — the rule just narrows delivery to
project object writes.

Requires a deployed webhook URL, so this runs at deploy time, not in CI:

    NOVA_WEBHOOK_URL=https://<app-host>/webhooks/b2/lock \
    B2_WEBHOOK_SIGNING_SECRET=<32-char-secret> \
    python scripts/setup_event_notification.py

The signing secret must match what the app validates with (same env var).
B2 requires the secret to be exactly 32 characters. On rule creation B2
sends a test event to the URL and requires a 2xx — deploy the app first.

Safe to re-run: replaces the previous nova-lock rule wholesale.
"""

import truststore

truststore.inject_into_ssl()

import os
import sys

from b2sdk.v2 import B2Api, InMemoryAccountInfo
from dotenv import load_dotenv

load_dotenv()

BUCKET_NAME = "nova-previs"
RULE_NAME = "nova-lock-trigger"


def main() -> int:
    webhook_url = os.environ.get("NOVA_WEBHOOK_URL")
    signing_secret = os.environ.get("B2_WEBHOOK_SIGNING_SECRET")
    if not webhook_url or not signing_secret:
        print("Set NOVA_WEBHOOK_URL and B2_WEBHOOK_SIGNING_SECRET first.", file=sys.stderr)
        return 1
    if len(signing_secret) != 32:
        print("B2 requires a signing secret of exactly 32 characters.", file=sys.stderr)
        return 1

    info = InMemoryAccountInfo()
    api = B2Api(info)
    api.authorize_account("production", os.environ["keyID"], os.environ["applicationKey"])
    bucket = api.get_bucket_by_name(BUCKET_NAME)

    rule = {
        "name": RULE_NAME,
        "eventTypes": ["b2:ObjectCreated:*"],
        "isEnabled": True,
        # Prefix-only filtering is a B2 platform constraint; the handler
        # does the locked/frame.png suffix match.
        "objectNamePrefix": "projects/",
        "targetConfiguration": {
            "targetType": "webhook",
            "url": webhook_url,
            "hmacSha256SigningSecret": signing_secret,
        },
    }

    existing = [
        r for r in (bucket.get_notification_rules() or []) if r.get("name") != RULE_NAME
    ]
    bucket.set_notification_rules([*existing, rule])
    print(f"rule '{RULE_NAME}' set on {BUCKET_NAME} -> {webhook_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
