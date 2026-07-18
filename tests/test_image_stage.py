"""
Backlog 3.1 acceptance: "One Shot Spec successfully produces one generated
still via Genblaze."

These drive a **real** ``genblaze_core.Pipeline`` — not a mocked one — with
the SDK's own ``MockProvider`` standing in for the wire call. That's the
honest offline proof: the Pipeline/Step/Asset/StageResult wiring is exercised
end to end, and only the provider's HTTP call is substituted. The live
nano-banana call is covered in ``test_gemini_image_provider.py``, which skips
without a ``GEMINI_API_KEY``.
"""

import warnings

from genblaze_core.models.asset import Asset
from genblaze_core.models.enums import Modality, ProviderErrorCode
from genblaze_core.testing import MockProvider

from nova.models.shot_spec import (
    Camera,
    Framing,
    Grade,
    Lens,
    Lighting,
    ShotSpec,
    Subject,
)
from nova.pipeline.image_stage import ImageStage

_SPEC = ShotSpec(
    shot_id="s3",
    intent="reveal the scale of the drone swarm above the ruined skyline",
    camera=Camera(angle="low", height_m=1.2, movement="slow push-in"),
    lens=Lens(focal_length_mm=18, aperture_f=2.8),
    framing=Framing(shot_size="extreme wide", composition="rule-of-thirds, subject lower-left"),
    lighting=Lighting(key="low-key", mood="dramatic shadows", practicals=["drone lights"]),
    grade=Grade(look="desaturated teal", contrast="high"),
    subject=Subject(primary="woman in tattered coat", blocking="walking left-to-right, foreground"),
    world=["destroyed buildings", "dense fog"],
)

_FRAME = Asset(url="https://mock.test/frame.png", media_type="image/png", sha256="a" * 64)


def test_one_shot_spec_produces_one_still():
    provider = MockProvider(name="mock-image", assets=[_FRAME])

    result = ImageStage(provider, model="mock-image-model").run(_SPEC)

    assert result.status == "succeeded"
    assert result.succeeded
    assert len(result.assets) == 1
    assert result.assets[0].media_type == "image/png"
    assert result.model == "mock-image-model"

    # The step the pipeline actually dispatched carries the compiled prompt
    # and params — i.e. the compiler's output really reached the provider,
    # rather than the stage quietly sending something else.
    step = provider.received_steps[0]
    assert step.modality == Modality.IMAGE
    assert "woman in tattered coat" in step.prompt
    assert "low-angle shot" in step.prompt
    assert step.params["aspect_ratio"] == "16:9"
    assert result.prompt == step.prompt


def test_provider_failure_becomes_a_failed_stage_result_not_an_exception():
    """A dead provider is a normal, renderable state in this product (the UI
    shows a retryable error card) — not a 500. Callers branch on
    StageResult.status, per the CLAUDE.md stage contract."""
    provider = MockProvider(
        name="mock-image",
        should_fail=True,
        error_code=ProviderErrorCode.RATE_LIMIT,
        error_message="rate limited",
    )

    result = ImageStage(provider, model="mock-image-model").run(_SPEC)

    assert result.status == "failed"
    assert not result.succeeded
    assert result.assets == []
    assert "rate limited" in result.error


def test_assetless_success_is_treated_as_failure():
    """A provider can return a completed step with zero assets (e.g. a
    swallowed safety block). Reporting that as 'succeeded' would let an
    empty shot become lockable downstream."""
    provider = MockProvider(name="mock-image", assets=[])

    result = ImageStage(provider, model="mock-image-model").run(_SPEC)

    assert result.status == "failed"
    assert "no image asset" in result.error


def test_reference_assets_are_passed_to_the_provider_as_step_inputs():
    """Backlog 3.4 depends on this seam: prior locked frames must arrive as
    Step.inputs so the provider can condition on them."""
    provider = MockProvider(name="mock-image", assets=[_FRAME])
    prior_frame = Asset(url="https://mock.test/s1_locked.png", media_type="image/png", sha256="b" * 64)

    result = ImageStage(provider, model="mock-image-model").run(
        _SPEC, project_id="proj123", reference_assets=[prior_frame]
    )

    assert result.status == "succeeded"
    step = provider.received_steps[0]
    assert [a.url for a in step.inputs] == [prior_frame.url]


def test_no_sink_means_no_manifest_key():
    """manifest_key is only real when a sink actually wrote one — never a
    guessed path."""
    provider = MockProvider(name="mock-image", assets=[_FRAME])
    result = ImageStage(provider, model="mock-image-model").run(_SPEC)
    assert result.manifest_key is None


def test_stage_does_not_emit_the_raise_on_failure_deprecation_warning():
    """genblaze-core 0.3.x warns when raise_on_failure is omitted and flips
    the default to True in 0.4.0. Passing it explicitly is what keeps this
    stage's contract (return a failed StageResult, don't raise) stable across
    that bump — this test fails if someone drops the explicit argument."""
    provider = MockProvider(name="mock-image", assets=[_FRAME])

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ImageStage(provider, model="mock-image-model").run(_SPEC)

    offenders = [
        w
        for w in caught
        if issubclass(w.category, DeprecationWarning) and "raise_on_failure" in str(w.message)
    ]
    assert not offenders, f"raise_on_failure was left to the default: {offenders}"
