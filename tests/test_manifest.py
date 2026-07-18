"""
Backlog 1.5 / 4.2 / 4.4 acceptance: the ShotManifest hash can be
independently recomputed and matches, and the verification utility
correctly flags a tampered manifest/frame as invalid.
"""

from nova.models.shot_spec import (
    Camera,
    Framing,
    Grade,
    Lens,
    Lighting,
    ShotSpec,
    Subject,
)
from nova.storage.manifest import (
    build_sequence_manifest,
    build_shot_manifest,
    compute_manifest_hash,
    verify_shot_manifest,
)

_FRAME_BYTES = b"\x89PNG\r\n\x1a\nfake-frame-bytes"


def _spec(shot_id: str = "s1") -> ShotSpec:
    return ShotSpec(
        shot_id=shot_id,
        version=2,
        intent="reveal the drone swarm",
        camera=Camera(angle="low", height_m=1.2, movement="slow push-in"),
        lens=Lens(focal_length_mm=18, aperture_f=2.8),
        framing=Framing(shot_size="extreme wide", composition="rule-of-thirds"),
        lighting=Lighting(key="low-key", mood="dramatic shadows", practicals=["drone lights"]),
        grade=Grade(look="desaturated teal", contrast="high"),
        subject=Subject(primary="woman in tattered coat", blocking="walking left-to-right"),
        world=["destroyed buildings", "dense fog"],
    )


def _manifest():
    return build_shot_manifest(
        project_id="p1",
        shot_id="s1",
        version=2,
        spec=_spec(),
        frame_key="projects/p1/shots/s1/locked/frame.png",
        frame_bytes=_FRAME_BYTES,
        provider="google-nano-banana",
        model="gemini-2.5-flash-image",
        prompt="a compiled prompt",
        params={"aspect_ratio": "16:9"},
        reference_keys=["projects/p1/shots/s0/locked/frame.png"],
    )


def test_manifest_hash_recomputes_and_matches():
    manifest = _manifest()
    assert manifest.manifest_sha256
    assert compute_manifest_hash(manifest) == manifest.manifest_sha256


def test_verify_passes_on_intact_manifest_and_frame():
    report = verify_shot_manifest(_manifest(), _FRAME_BYTES)
    assert report.manifest_hash_ok
    assert report.frame_hash_ok
    assert report.ok


def test_verify_flags_tampered_manifest_field():
    manifest = _manifest().model_copy(update={"shot_id": "s99"})
    report = verify_shot_manifest(manifest, _FRAME_BYTES)
    assert not report.manifest_hash_ok
    assert not report.ok


def test_verify_flags_tampered_frame_bytes():
    report = verify_shot_manifest(_manifest(), _FRAME_BYTES + b"tamper")
    assert report.manifest_hash_ok
    assert report.frame_hash_ok is False
    assert not report.ok


def test_verify_flags_edited_frame_hash_via_manifest_seal():
    # Editing the recorded frame hash to match tampered bytes must still
    # break the *manifest* seal — that's the chain-of-custody property.
    manifest = _manifest()
    tampered_frame = _FRAME_BYTES + b"tamper"
    forged = manifest.model_copy(
        update={"frame": manifest.frame.model_copy(update={"sha256": "0" * 64})}
    )
    report = verify_shot_manifest(forged, tampered_frame)
    assert not report.manifest_hash_ok
    assert not report.ok


def test_verify_without_frame_bytes_checks_manifest_only():
    report = verify_shot_manifest(_manifest())
    assert report.manifest_hash_ok
    assert report.frame_hash_ok is None
    assert report.ok


def test_sequence_manifest_seals_and_chains_shots():
    seq = build_sequence_manifest(
        project_id="p1",
        sequence_key="projects/p1/previs/sequence.mp4",
        sequence_bytes=b"fake-mp4",
        shots=[
            {"shot_id": "s1", "manifest_sha256": "a" * 64},
            {"shot_id": "s2", "manifest_sha256": "b" * 64},
        ],
    )
    assert seq.manifest_sha256
    assert [s["shot_id"] for s in seq.shots] == ["s1", "s2"]
    assert len(seq.sequence_sha256) == 64
