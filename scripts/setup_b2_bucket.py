"""
Backlog 0.8 / 0.9 / 0.10: provision the nova-previs B2 bucket.

- 0.8: creates the projects/{id}/... key structure from PRD 8.2 via a
  matching set of test uploads.
- 0.9: creates the bucket with Object Lock (file lock) enabled — this can
  ONLY be set at creation, never toggled on later — and applies GOVERNANCE
  retention to the locked/ objects specifically, not bucket-wide, so draft
  versions stay freely deletable.
- 0.10: applies a bucket lifecycle rule scoped to a scratch/ prefix (see
  "Design note" below) so rejected multi-take candidates auto-expire.

Safe to re-run: skips bucket creation if nova-previs already exists, and
re-applies lifecycle rules idempotently either way.

Run:
    python scripts/setup_b2_bucket.py
"""

import truststore

truststore.inject_into_ssl()

import os
import time
from datetime import datetime, timedelta, timezone

from b2sdk.v2 import (
    B2Api,
    FileRetentionSetting,
    InMemoryAccountInfo,
    RetentionMode,
)
from dotenv import load_dotenv

load_dotenv()

BUCKET_NAME = "nova-previs"

# Design note (not in PRD 8.2 as written): PRD 8.2 doesn't define a path for
# multi-take fan-out candidates that don't get promoted to a numbered
# version (PRD 9.5 use case 3 / backlog 8.6). frames/v{n}.png is version
# history the app deliberately keeps for scrub/revert (PRD 8.4) and must
# NOT be swept by a lifecycle rule. Standard B2/S3 lifecycle rules only
# match a literal prefix (no mid-path wildcards), so per-project/per-shot
# paths like projects/*/shots/*/takes/ can't be targeted by one rule
# anyway. Using a single flat scratch/ prefix outside projects/ is the
# only way one lifecycle rule can cover every project/shot's rejected
# takes. scripts writing multi-take candidates should key them as
# scratch/{project_id}/{shot_id}/{take_id}.png.
SCRATCH_LIFECYCLE_RULE = {
    "fileNamePrefix": "scratch/",
    "daysFromUploadingToHiding": 3,
    "daysFromHidingToDeleting": 1,
}

RETENTION_DAYS = 30


def _authorized_api() -> B2Api:
    info = InMemoryAccountInfo()
    api = B2Api(info)
    api.authorize_account("production", os.environ["keyID"], os.environ["applicationKey"])
    return api


def _get_or_create_bucket(api: B2Api):
    try:
        bucket = api.get_bucket_by_name(BUCKET_NAME)
        print(f"bucket '{BUCKET_NAME}' already exists (id={bucket.id_}) — reusing")
    except Exception:
        bucket = api.create_bucket(
            BUCKET_NAME,
            "allPrivate",
            is_file_lock_enabled=True,
            lifecycle_rules=[SCRATCH_LIFECYCLE_RULE],
        )
        print(f"created bucket '{BUCKET_NAME}' (id={bucket.id_}) with Object Lock enabled")
        return bucket

    if not bucket.is_file_lock_enabled:
        raise RuntimeError(
            f"bucket '{BUCKET_NAME}' exists but was NOT created with Object Lock enabled — "
            "B2 cannot toggle this on retroactively. Delete and recreate, or pick a new name."
        )

    bucket.update(lifecycle_rules=[SCRATCH_LIFECYCLE_RULE])
    print(f"re-applied lifecycle rules on existing bucket '{BUCKET_NAME}'")
    return bucket


def _upload_structure(bucket) -> dict:
    """Task 0.8: populate the PRD 8.2 key structure with a test project/shot."""
    retain_until_ms = int((datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)).timestamp() * 1000)
    governance_lock = FileRetentionSetting(RetentionMode.GOVERNANCE, retain_until_ms)

    uploads = [
        ("projects/test-project/scene.json", b'{"scene": "test scene for backlog 0.8"}', "application/json", None),
        ("projects/test-project/shots/test-shot/spec/v1.json", b'{"shot_id": "test-shot", "version": 1}', "application/json", None),
        ("projects/test-project/shots/test-shot/frames/v1.png", b"\x89PNG\r\n\x1a\n" + b"placeholder-frame-v1", "image/png", None),
        ("projects/test-project/shots/test-shot/locked/frame.png", b"\x89PNG\r\n\x1a\n" + b"placeholder-locked-frame", "image/png", governance_lock),
        ("projects/test-project/shots/test-shot/locked/manifest.json", b'{"sha256": "test", "model": "test"}', "application/json", governance_lock),
        ("projects/test-project/shots/test-shot/animatic/clip.mp4", b"placeholder-clip", "video/mp4", None),
        ("projects/test-project/shots/test-shot/animatic/audio.mp3", b"placeholder-audio", "audio/mpeg", None),
        ("projects/test-project/previs/sequence.mp4", b"placeholder-sequence", "video/mp4", None),
        ("projects/test-project/previs/manifest.json", b'{"sha256": "test-full-chain"}', "application/json", None),
        # Task 0.10: a scratch-prefix object to exercise the lifecycle rule.
        ("scratch/test-project/test-shot/test-take.png", b"\x89PNG\r\n\x1a\n" + b"placeholder-rejected-take", "image/png", None),
    ]

    file_versions = {}
    for key, data, content_type, retention in uploads:
        fv = bucket.upload_bytes(data, key, content_type=content_type, file_retention=retention)
        file_versions[key] = fv
        locked_note = " [GOVERNANCE locked]" if retention else ""
        print(f"  uploaded {key}{locked_note}")

    return file_versions


def _verify_object_lock(bucket, file_versions: dict) -> None:
    """Task 0.9: prove the locked object actually can't be deleted before retention expiry."""
    locked_key = "projects/test-project/shots/test-shot/locked/frame.png"
    locked_fv = file_versions[locked_key]

    try:
        bucket.delete_file_version(locked_fv.id_, locked_key)
    except Exception as e:
        print(f"  delete correctly BLOCKED on locked object: {type(e).__name__}: {e}")
    else:
        raise RuntimeError(
            "Object Lock did not block deletion of a GOVERNANCE-retained object — "
            "retention is not actually enforced, investigate before trusting it."
        )

    unlocked_key = "projects/test-project/shots/test-shot/frames/v1.png"
    unlocked_fv = file_versions[unlocked_key]
    bucket.delete_file_version(unlocked_fv.id_, unlocked_key)
    print(f"  delete correctly SUCCEEDED on unlocked object ({unlocked_key}) — confirms lock is selective, not bucket-wide")


def main() -> None:
    api = _authorized_api()
    bucket = _get_or_create_bucket(api)

    print("\nuploading PRD 8.2 key structure + lifecycle test object...")
    file_versions = _upload_structure(bucket)

    print("\nverifying Object Lock enforcement (backlog 0.9)...")
    _verify_object_lock(bucket, file_versions)

    print(f"\nlifecycle rule applied (backlog 0.10): {SCRATCH_LIFECYCLE_RULE}")
    print("B2 sweeps lifecycle rules on its own daily schedule, not instantly —")
    print("actual deletion of scratch/test-project/test-shot/test-take.png can't")
    print("be confirmed synchronously; re-check after a few days if you want to")
    print("verify the sweep itself, not just that the rule is attached.")

    print(f"\ndone. bucket '{BUCKET_NAME}' ready at {time.strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
