"""
Backlog 3.3 acceptance: "Simulated primary-provider failure results in a
successful fallback-generated still."
Backlog 3.4: continuity refs fetched from B2 become provider inputs.
Backlog 3.6 (stage half): refine() edits the prior frame in place with a
distinct prompt shape, and never reuses the generate-from-scratch path.

Same convention as test_image_stage.py: real genblaze Pipeline, MockProvider
standing in for the wire call only.
"""

from genblaze_core.models.asset import Asset
from genblaze_core.models.enums import ProviderErrorCode
from genblaze_core.testing import MockProvider

import nova.pipeline.image_stage as image_stage_module
from nova.models.shot_spec import (
    Camera,
    Framing,
    Grade,
    Lens,
    Lighting,
    ShotSpec,
    Subject,
)
from nova.pipeline.image_stage import ImageStage, fetch_reference_assets

_SPEC = ShotSpec(
    shot_id="s3",
    intent="reveal the scale of the drone swarm",
    camera=Camera(angle="low", height_m=1.2, movement="slow push-in"),
    lens=Lens(focal_length_mm=18, aperture_f=2.8),
    framing=Framing(shot_size="extreme wide", composition="rule-of-thirds"),
    lighting=Lighting(key="low-key", mood="dramatic shadows", practicals=[]),
    grade=Grade(look="desaturated teal", contrast="high"),
    subject=Subject(primary="woman in tattered coat", blocking="walking left-to-right"),
    world=["destroyed buildings"],
)

_FRAME = Asset(url="https://mock.test/frame.png", media_type="image/png", sha256="a" * 64)


def _failing(name: str) -> MockProvider:
    return MockProvider(
        name=name,
        should_fail=True,
        error_code=ProviderErrorCode.SERVER_ERROR,
        error_message=f"{name} down",
    )


def _chain(primary: MockProvider, *fallback_providers: MockProvider) -> ImageStage:
    return ImageStage(
        primary,
        model="primary-model",
        fallbacks=[ImageStage(p, model=f"{p.name}-model") for p in fallback_providers],
    )


def test_primary_failure_falls_back_to_next_provider():
    primary = _failing("primary")
    fallback = MockProvider(name="fallback", assets=[_FRAME])

    result = _chain(primary, fallback).run(_SPEC)

    assert result.status == "succeeded"
    assert result.model == "fallback-model"
    assert primary.call_count == 1
    assert fallback.call_count == 1


def test_fallback_is_not_called_when_primary_succeeds():
    primary = MockProvider(name="primary", assets=[_FRAME])
    fallback = MockProvider(name="fallback", assets=[_FRAME])

    result = _chain(primary, fallback).run(_SPEC)

    assert result.status == "succeeded"
    assert result.model == "primary-model"
    assert fallback.call_count == 0


def test_second_fallback_serves_when_first_two_fail():
    result = _chain(
        _failing("primary"), _failing("first-fb"), MockProvider(name="second-fb", assets=[_FRAME])
    ).run(_SPEC)

    assert result.status == "succeeded"
    assert result.model == "second-fb-model"


def test_whole_chain_failing_reports_every_provider():
    result = _chain(_failing("primary"), _failing("fb-a"), _failing("fb-b")).run(_SPEC)

    assert result.status == "failed"
    for name in ("primary", "fb-a", "fb-b"):
        assert name in result.error


def test_refine_sends_prior_frame_first_and_edit_prompt():
    provider = MockProvider(name="mock-image", assets=[_FRAME])
    prior = Asset(url="https://mock.test/v1.png", media_type="image/png", sha256="b" * 64)
    ref = Asset(url="https://mock.test/s1_locked.png", media_type="image/png", sha256="c" * 64)

    result = ImageStage(provider, model="m").refine(
        _SPEC, prior, instruction="make the fog denser", reference_assets=[ref]
    )

    assert result.status == "succeeded"
    step = provider.received_steps[0]
    # Prior frame anchors the edit; continuity refs follow.
    assert [a.url for a in step.inputs] == [prior.url, ref.url]
    assert "make the fog denser" in step.prompt
    assert step.prompt.startswith("Edit the provided storyboard frame")
    # The full spec prose still rides along as ground truth.
    assert "woman in tattered coat" in step.prompt


def test_refine_falls_back_across_providers_with_edit_prompt_intact():
    primary = _failing("primary")
    fallback = MockProvider(name="fallback", assets=[_FRAME])
    prior = Asset(url="https://mock.test/v1.png", media_type="image/png", sha256="b" * 64)

    result = _chain(primary, fallback).refine(_SPEC, prior, instruction="warmer light")

    assert result.status == "succeeded"
    step = fallback.received_steps[0]
    assert "warmer light" in step.prompt
    assert [a.url for a in step.inputs] == [prior.url]


def test_fetch_reference_assets_wraps_b2_bytes_as_file_assets(monkeypatch, tmp_path):
    payload = b"\x89PNG\r\n\x1a\nlocked-frame"
    fetched_keys: list[str] = []

    def fake_get_bytes(key: str) -> bytes:
        fetched_keys.append(key)
        return payload

    monkeypatch.setattr("nova.storage.b2_client.get_bytes", fake_get_bytes)

    assets = fetch_reference_assets(["projects/p/shots/s1/locked/frame.png"])

    assert fetched_keys == ["projects/p/shots/s1/locked/frame.png"]
    assert len(assets) == 1
    asset = assets[0]
    assert asset.url.startswith("file://")
    assert asset.media_type == "image/png"
    assert asset.size_bytes == len(payload)
    # Hash is set from the actual bytes so provenance manifests record a
    # real digest for the reference chain.
    import hashlib

    assert asset.sha256 == hashlib.sha256(payload).hexdigest()


def test_default_image_stage_builds_without_credentials(monkeypatch):
    """The chain must be constructible with no API keys in the environment —
    keys are read at first call, not at construction."""
    for var in ("GEMINI_API_KEY", "OPENAI_API_KEY", "GMI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    stage = image_stage_module.default_image_stage()
    assert stage is not None
