"""
Backlog 0.8 / 0.9 / 0.10 verification: confirm the nova-previs bucket is
provisioned the way scripts/setup_b2_bucket.py sets it up — Object Lock
enabled, key structure present, locked objects actually unretractable,
and the scratch/ lifecycle rule attached.

Run with pytest:
    pytest tests/test_b2_bucket_setup.py -v -s

Requires scripts/setup_b2_bucket.py to have been run at least once against
the target account.
"""

import truststore

truststore.inject_into_ssl()

import os

import pytest
from b2sdk.v2 import B2Api, InMemoryAccountInfo
from dotenv import load_dotenv

load_dotenv()

KEY_ID = os.environ.get("keyID")
APPLICATION_KEY = os.environ.get("applicationKey")
BUCKET_NAME = "nova-previs"

pytestmark = pytest.mark.skipif(
    not (KEY_ID and APPLICATION_KEY),
    reason="keyID/applicationKey not set — expected in CI until B2 secrets are configured (backlog 0.7)",
)


@pytest.fixture(scope="module")
def bucket():
    info = InMemoryAccountInfo()
    api = B2Api(info)
    api.authorize_account("production", KEY_ID, APPLICATION_KEY)
    return api.get_bucket_by_name(BUCKET_NAME)


def test_bucket_has_object_lock_enabled(bucket):
    """0.9: Object Lock must be on — B2 can't add this after the fact."""
    assert bucket.is_file_lock_enabled


def test_bucket_has_scratch_lifecycle_rule(bucket):
    """0.10: rejected/intermediate artifacts under scratch/ must auto-expire."""
    rules = bucket.lifecycle_rules
    scratch_rules = [r for r in rules if r.get("fileNamePrefix") == "scratch/"]
    assert scratch_rules, f"no lifecycle rule for scratch/ prefix, found: {rules}"
    assert scratch_rules[0].get("daysFromUploadingToHiding")


def test_prd_key_structure_present(bucket):
    """0.8: the PRD 8.2 layout exists under the test-project fixture."""
    expected_keys = {
        "projects/test-project/scene.json",
        "projects/test-project/shots/test-shot/spec/v1.json",
        "projects/test-project/shots/test-shot/locked/frame.png",
        "projects/test-project/shots/test-shot/locked/manifest.json",
        "projects/test-project/shots/test-shot/animatic/clip.mp4",
        "projects/test-project/shots/test-shot/animatic/audio.mp3",
        "projects/test-project/previs/sequence.mp4",
        "projects/test-project/previs/manifest.json",
    }
    present = {f.file_name for f, _ in bucket.ls("projects/test-project/", recursive=True)}
    missing = expected_keys - present
    assert not missing, f"missing expected keys: {missing}"


def test_locked_object_cannot_be_deleted(bucket):
    """
    0.9: the actual guarantee that matters — deleting a GOVERNANCE-locked
    object without bypass must fail. Safe to re-run: a failed delete
    changes nothing.
    """
    key = "projects/test-project/shots/test-shot/locked/frame.png"
    file_version, _ = next(bucket.ls(key, folder_to_list_can_be_a_file=True))

    with pytest.raises(Exception):
        bucket.delete_file_version(file_version.id_, key, bypass_governance=False)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
