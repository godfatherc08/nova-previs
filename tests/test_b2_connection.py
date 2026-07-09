"""
Backlog 0.1 sanity check: confirm the B2 key ID / application key in .env
can actually authenticate against Backblaze B2, before/after a bucket exists.

Run with pytest:
    pytest tests/test_b2_connection.py -v -s

Or standalone:
    python tests/test_b2_connection.py
"""

# Windows + Avast (and similar AV HTTPS-scanning tools) inject a root CA
# whose Basic Constraints extension isn't marked critical, which OpenSSL
# 3.x's strict parser rejects even though the OS trust store (and every
# browser) accepts it fine. truststore routes verification through the
# OS-native trust store instead of the bundled certifi list, sidestepping
# that mismatch. Must run before anything creates an SSLContext.
import truststore

truststore.inject_into_ssl()

import os

import pytest
from b2sdk.v2 import B2Api, InMemoryAccountInfo
from dotenv import load_dotenv

load_dotenv()

KEY_ID = os.environ.get("keyID")
APPLICATION_KEY = os.environ.get("applicationKey")

pytestmark = pytest.mark.skipif(
    not (KEY_ID and APPLICATION_KEY),
    reason="keyID/applicationKey not set — expected in CI until B2 secrets are configured (backlog 0.7)",
)


def _authorized_api() -> B2Api:
    info = InMemoryAccountInfo()
    api = B2Api(info)
    api.authorize_account("production", KEY_ID, APPLICATION_KEY)
    return api


def test_b2_authentication_succeeds():
    """The key ID + application key pair must authenticate against B2."""
    api = _authorized_api()
    assert api.get_account_id()


def test_b2_account_info_and_buckets():
    """
    Authenticate, then report what the key can see: account id, API/S3
    endpoints, allowed capabilities, and any buckets already visible to
    this key. Useful diagnostic ahead of backlog 0.1/0.8 — prints even
    under plain pytest since -s is recommended above.
    """
    api = _authorized_api()
    account_info = api.account_info

    print(f"\naccount id:         {account_info.get_account_id()}")
    print(f"api url:            {account_info.get_api_url()}")
    print(f"s3 endpoint:        {account_info.get_s3_api_url()}")

    allowed = account_info.get_allowed()
    print(f"capabilities:       {sorted(allowed.get('capabilities', []))}")
    print(f"bucket restriction: {allowed.get('bucketName') or '(none — key is account-wide)'}")

    buckets = api.list_buckets()
    bucket_names = [b.name for b in buckets]
    print(f"visible buckets:    {bucket_names or '(none yet)'}")

    assert allowed is not None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
