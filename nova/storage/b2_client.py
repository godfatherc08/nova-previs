"""
Backlog 2.3: write-through to B2 via ``genblaze-s3``'s ``S3StorageBackend``
(confirmed native per CLAUDE.md — ``S3StorageBackend.for_backblaze()`` /
``.put()`` verified by reading the installed ``genblaze_s3/backend.py``
directly).

Reuses the ``keyID`` / ``applicationKey`` env var names already established
by ``tests/test_b2_connection.py`` and ``scripts/setup_b2_bucket.py``,
rather than introducing a second, differently-named credential pair.

The backend is constructed lazily (only on the first real write) so
importing this module — or running tests that don't touch B2 — never
requires credentials, matching the skip-if-no-creds convention used
elsewhere in this repo.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from genblaze_core.storage.base import ObjectLockConfig
from genblaze_s3 import S3StorageBackend

BUCKET_NAME = "nova-previs"
# The genblaze-s3 default ("us-west-004") only auto-corrects on a redirect;
# some regions (this bucket's included) reject cross-region requests with a
# bare 403 instead, which can't be auto-detected — confirmed by hitting
# that exact 403 against the real bucket, whose actual region (checked via
# b2sdk's account_info.get_s3_api_url()) is us-east-005.
DEFAULT_REGION = "us-east-005"

_backend: S3StorageBackend | None = None
_ssl_patched = False


def _get_backend() -> S3StorageBackend:
    global _backend, _ssl_patched
    if not _ssl_patched:
        # Same Windows/Avast HTTPS-inspection workaround as
        # tests/test_b2_connection.py — applies to any HTTPS client, not
        # just b2sdk, so it belongs here too, once, before the first call.
        import truststore

        truststore.inject_into_ssl()
        _ssl_patched = True
    if _backend is None:
        _backend = S3StorageBackend.for_backblaze(
            bucket=BUCKET_NAME,
            region=os.environ.get("B2_REGION", DEFAULT_REGION),
            key_id=os.environ.get("keyID"),
            app_key=os.environ.get("applicationKey"),
        )
    return _backend


# Matches the GOVERNANCE-mode retention scripts/setup_b2_bucket.py applies
# (backlog 0.9): long enough to cover the full hackathon judging window,
# recoverable by an authorized key if a retention date was set in error.
LOCK_RETENTION_DAYS = 30


def _governance_lock(retention_days: int = LOCK_RETENTION_DAYS) -> ObjectLockConfig:
    return ObjectLockConfig(
        retain_until=datetime.now(timezone.utc) + timedelta(days=retention_days),
        mode="GOVERNANCE",
    )


def put_json(key: str, data: dict, *, object_lock: bool = False) -> str:
    """Write ``data`` as a JSON object to ``key``. Returns the storage key.

    ``object_lock=True`` applies per-object GOVERNANCE retention — used for
    ``locked/manifest.json`` (backlog 4.1/4.2), where immutability is the
    point. Draft-path JSON (scene.json, spec versions) stays unlocked so it
    remains freely editable/deletable.
    """
    backend = _get_backend()
    payload = json.dumps(data, indent=2).encode("utf-8")
    return backend.put(
        key,
        payload,
        content_type="application/json",
        object_lock=_governance_lock() if object_lock else None,
    )


def put_bytes(key: str, data: bytes, *, content_type: str, object_lock: bool = False) -> str:
    """Write raw bytes to ``key`` (frames, clips, audio). Returns the key."""
    backend = _get_backend()
    return backend.put(
        key,
        data,
        content_type=content_type,
        object_lock=_governance_lock() if object_lock else None,
    )


def get_bytes(key: str) -> bytes:
    """Read an object's full bytes from B2."""
    return _get_backend().get(key)


def get_json(key: str) -> dict:
    return json.loads(get_bytes(key).decode("utf-8"))


def exists(key: str) -> bool:
    return _get_backend().exists(key)


def presigned_url(key: str, *, expires_in: int = 3600) -> str:
    """Short-lived credentialed URL — used to hand a private-bucket object
    to an external provider (e.g. the locked frame to Runway/Luma, backlog
    6.1). Never persisted anywhere: manifests record ``durable_url``/keys.
    """
    return _get_backend().presigned_get_url(key, expires_in=expires_in)


def durable_url(key: str) -> str:
    """Credential-free, never-expiring canonical URL for ``key`` (backlog 4.3).

    Built locally (no network round-trip) from the bucket's known region so
    manifests can be assembled offline. NOTE the bucket is ``allPrivate``
    (backlog 0.9's Object Lock setup), so this URL identifies the object
    durably — for manifests and provenance — but fetching it anonymously
     403s. The *user-facing* share link is the app's media proxy
    (``GET /api/media/{key}``, api/routes.py), which streams from B2 server-
    side and therefore works from a fresh browser session with no auth.
    """
    region = os.environ.get("B2_REGION", DEFAULT_REGION)
    return f"https://s3.{region}.backblazeb2.com/{BUCKET_NAME}/{quote(key, safe='/')}"
