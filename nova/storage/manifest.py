"""
Backlog 1.5 / 4.2 / 4.4: Nova's provenance manifest — schema, build, verify.

Two manifest layers exist in this system, deliberately:

  * **Genblaze's own ``Manifest``** (``genblaze_core.models.manifest``) — the
    SDK-native run manifest with a canonical-JSON SHA-256
    (``canonical_hash``), written by ``ObjectStorageSink`` when a sink is
    attached to a pipeline run. That format is confirmed-native (CLAUDE.md)
    and Nova does not reimplement or fork it.
  * **This module's ``ShotManifest``** — Nova's per-shot chain-of-custody
    record written at *lock* time to ``locked/manifest.json`` under Object
    Lock. It exists because a shot's provenance spans more than one pipeline
    run (spec authorship -> N frame generations -> the one locked version)
    and Genblaze's run manifest describes exactly one run. The ShotManifest
    *references* the Genblaze manifest key when one exists rather than
    duplicating its contents.

Hashing follows the same idea as Genblaze's canonical manifest: the
``manifest_sha256`` field is the SHA-256 of the manifest's canonical JSON
(sorted keys, compact separators) with the hash field itself blanked. That
makes the manifest self-verifying: recompute and compare (backlog 4.2's
acceptance criterion), and any tampering — including editing the recorded
``frame_sha256`` — breaks the seal. ``verify_shot_manifest`` checks both
seals: manifest integrity, and frame-bytes-match-recorded-hash.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from nova.models.shot_spec import ShotSpec

SCHEMA_VERSION = "nova-shot-manifest/1.0"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class FrameProvenance(BaseModel):
    """The locked frame artifact itself."""

    model_config = ConfigDict(extra="forbid")

    b2_key: str
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    media_type: str = "image/png"


class GenerationProvenance(BaseModel):
    """What produced the locked frame: provider, model, and exact prompt.

    ``seed`` is optional because not every provider exposes one —
    nano-banana's ``generate_content`` API does not accept or return a seed
    (verified against google-genai 2.11), so for Gemini-generated frames
    reproducibility rests on the recorded prompt + reference frames rather
    than a seed. Providers that do return one (e.g. Flux via GMI Cloud)
    get it recorded here.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    prompt: str
    params: dict = Field(default_factory=dict)
    seed: int | str | None = None
    # Full B2 keys of prior locked frames passed as reference images
    # (continuity_refs, backlog 3.4) — part of provenance because they
    # condition the output.
    reference_keys: list[str] = Field(default_factory=list)


class ShotManifest(BaseModel):
    """Chain-of-custody record for one locked shot (written under Object Lock)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    project_id: str
    shot_id: str
    version: int = Field(ge=1)
    locked_at: str  # ISO-8601 UTC
    spec: ShotSpec
    frame: FrameProvenance
    generation: GenerationProvenance
    # Key of the Genblaze-native run manifest for the generation run, when a
    # sink was attached. None for runs without a sink; the ShotManifest is
    # then the sole provenance record.
    genblaze_manifest_key: str | None = None
    # SHA-256 of this manifest's canonical JSON with this field blanked.
    manifest_sha256: str = ""


def compute_manifest_hash(manifest: ShotManifest) -> str:
    payload = manifest.model_dump(mode="json")
    payload["manifest_sha256"] = ""
    return _sha256_hex(_canonical_json(payload))


def build_shot_manifest(
    *,
    project_id: str,
    shot_id: str,
    version: int,
    spec: ShotSpec,
    frame_key: str,
    frame_bytes: bytes,
    provider: str,
    model: str,
    prompt: str,
    params: dict | None = None,
    seed: int | str | None = None,
    reference_keys: list[str] | None = None,
    genblaze_manifest_key: str | None = None,
    media_type: str = "image/png",
) -> ShotManifest:
    """Assemble and seal a ShotManifest for a frame about to be locked."""
    manifest = ShotManifest(
        project_id=project_id,
        shot_id=shot_id,
        version=version,
        locked_at=datetime.now(timezone.utc).isoformat(),
        spec=spec,
        frame=FrameProvenance(
            b2_key=frame_key,
            sha256=_sha256_hex(frame_bytes),
            size_bytes=len(frame_bytes),
            media_type=media_type,
        ),
        generation=GenerationProvenance(
            provider=provider,
            model=model,
            prompt=prompt,
            params=params or {},
            seed=seed,
            reference_keys=reference_keys or [],
        ),
        genblaze_manifest_key=genblaze_manifest_key,
    )
    return manifest.model_copy(update={"manifest_sha256": compute_manifest_hash(manifest)})


class ManifestVerification(BaseModel):
    """Result of a chain-of-custody check (backlog 4.4, PRD 8.4 use case 3)."""

    manifest_hash_ok: bool
    frame_hash_ok: bool | None = None  # None when frame bytes weren't supplied
    expected_manifest_sha256: str
    recorded_manifest_sha256: str

    @property
    def ok(self) -> bool:
        return self.manifest_hash_ok and self.frame_hash_ok is not False


def verify_shot_manifest(
    manifest: ShotManifest, frame_bytes: bytes | None = None
) -> ManifestVerification:
    """Recompute both hashes and flag tampering.

    ``manifest_hash_ok`` — the manifest document itself is intact (any edited
    field, including the recorded frame hash, breaks it).
    ``frame_hash_ok`` — the frame bytes on disk/in B2 are the exact bytes
    that were locked. Skipped (None) when the caller has no frame bytes.
    """
    expected = compute_manifest_hash(manifest)
    frame_ok: bool | None = None
    if frame_bytes is not None:
        frame_ok = _sha256_hex(frame_bytes) == manifest.frame.sha256
    return ManifestVerification(
        manifest_hash_ok=expected == manifest.manifest_sha256,
        frame_hash_ok=frame_ok,
        expected_manifest_sha256=expected,
        recorded_manifest_sha256=manifest.manifest_sha256,
    )


class SequenceManifest(BaseModel):
    """Full-chain manifest for the assembled previs (backlog 7.3).

    One entry per assembled shot, in sequence order, each carrying the
    locked-shot manifest hash — so the sequence manifest chains back to
    every per-shot chain-of-custody record.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "nova-sequence-manifest/1.0"
    project_id: str
    assembled_at: str
    sequence_key: str
    sequence_sha256: str
    shots: list[dict] = Field(default_factory=list)
    manifest_sha256: str = ""


def build_sequence_manifest(
    *,
    project_id: str,
    sequence_key: str,
    sequence_bytes: bytes,
    shots: list[dict],
) -> SequenceManifest:
    manifest = SequenceManifest(
        project_id=project_id,
        assembled_at=datetime.now(timezone.utc).isoformat(),
        sequence_key=sequence_key,
        sequence_sha256=_sha256_hex(sequence_bytes),
        shots=shots,
    )
    payload = manifest.model_dump(mode="json")
    payload["manifest_sha256"] = ""
    return manifest.model_copy(
        update={"manifest_sha256": _sha256_hex(_canonical_json(payload))}
    )
