"""
Backlog 4.4: chain-of-custody verification utility (PRD 8.4 use case 3).

Fetches a locked shot's manifest.json + frame.png from B2, recomputes both
SHA-256 seals independently, and reports PASS/FAIL. Exit code 0 on pass,
1 on any tamper flag — usable in CI or by a judge from a fresh clone.

Run:
    python scripts/verify_manifest.py <project_id> <shot_id>
    python scripts/verify_manifest.py --local <manifest.json> <frame.png>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nova.storage.manifest import ShotManifest, verify_shot_manifest


def _verify(manifest_data: dict, frame_bytes: bytes) -> int:
    manifest = ShotManifest.model_validate(manifest_data)
    report = verify_shot_manifest(manifest, frame_bytes)

    print(f"manifest seal : {'OK' if report.manifest_hash_ok else 'TAMPERED'}")
    print(f"  recorded    : {report.recorded_manifest_sha256}")
    print(f"  recomputed  : {report.expected_manifest_sha256}")
    print(f"frame bytes   : {'OK' if report.frame_hash_ok else 'TAMPERED'}")
    print(f"  recorded    : {manifest.frame.sha256}")

    if report.ok:
        print("PASS — chain of custody intact")
        return 0
    print("FAIL — provenance verification failed")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="verify local files instead of B2")
    parser.add_argument("args", nargs=2, metavar=("PROJECT_OR_MANIFEST", "SHOT_OR_FRAME"))
    ns = parser.parse_args()

    if ns.local:
        manifest_path, frame_path = ns.args
        manifest_data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        frame_bytes = Path(frame_path).read_bytes()
    else:
        from dotenv import load_dotenv

        load_dotenv()
        from nova.storage import keys
        from nova.storage.b2_client import get_bytes, get_json

        project_id, shot_id = ns.args
        manifest_data = get_json(keys.locked_manifest_key(project_id, shot_id))
        frame_bytes = get_bytes(keys.locked_frame_key(project_id, shot_id))

    return _verify(manifest_data, frame_bytes)


if __name__ == "__main__":
    sys.exit(main())
