"""
Backlog 6.1 acceptance: a locked shot produces a motion clip via Genblaze.
Backlog 6.2: simulated Runway failure results in a successful Luma-role
fallback clip. Backlog 6.3: a locked shot produces a scratch audio track.
Backlog 6.5: a forced provider stall does not fail the overall run.

Real genblaze Pipelines with the SDK's Mock(Video|Audio)Provider standing in
for wire calls — same honesty convention as test_image_stage.py.
"""

from genblaze_core.models.asset import Asset
from genblaze_core.models.enums import Modality, ProviderErrorCode
from genblaze_core.testing import MockAudioProvider, MockProvider, MockVideoProvider

from nova.models.shot_spec import (
    Camera,
    Framing,
    Grade,
    Lens,
    Lighting,
    ShotSpec,
    Subject,
)
from nova.pipeline._runner import StepPlan
from nova.pipeline.animatic_stage import AnimaticStage
from nova.pipeline.audio_stage import AudioStage

_SPEC = ShotSpec(
    shot_id="s3",
    intent="reveal the scale of the drone swarm",
    camera=Camera(angle="low", height_m=1.2, movement="slow push-in"),
    lens=Lens(focal_length_mm=18, aperture_f=2.8),
    framing=Framing(shot_size="extreme wide", composition="rule-of-thirds"),
    lighting=Lighting(key="low-key", mood="dramatic shadows", practicals=[]),
    grade=Grade(look="desaturated teal", contrast="high"),
    subject=Subject(primary="woman in tattered coat", blocking="walking left-to-right"),
    world=["destroyed buildings", "dense fog"],
)

_LOCKED_FRAME = Asset(
    url="https://mock.test/locked_frame.png", media_type="image/png", sha256="a" * 64
)


def _stalled(name: str) -> MockProvider:
    return MockProvider(
        name=name,
        should_fail=True,
        error_code=ProviderErrorCode.TIMEOUT,
        error_message=f"{name} stalled",
    )


def test_locked_shot_produces_a_motion_clip():
    provider = MockVideoProvider(name="mock-runway")

    result = AnimaticStage([StepPlan(provider, "mock-video-model")]).run(
        _SPEC, _LOCKED_FRAME, project_id="p1"
    )

    assert result.status == "succeeded"
    assert result.assets[0].media_type == "video/mp4"

    step = provider.received_steps[0]
    assert step.modality == Modality.VIDEO
    # The locked frame rides along as the provider's image input — that's
    # what makes the animatic animate the approved frame.
    assert [a.url for a in step.inputs] == [_LOCKED_FRAME.url]
    # The prompt speaks in motion terms from the spec's temporal fields.
    assert "slow push-in" in step.prompt


def test_runway_failure_falls_back_to_luma_role_provider():
    primary = _stalled("mock-runway")
    fallback = MockVideoProvider(name="mock-luma")

    result = AnimaticStage(
        [StepPlan(primary, "runway-model"), StepPlan(fallback, "luma-model")]
    ).run(_SPEC, _LOCKED_FRAME)

    assert result.status == "succeeded"
    assert result.model == "luma-model"
    assert primary.call_count == 1
    assert fallback.call_count == 1


def test_locked_shot_produces_a_scratch_audio_track():
    provider = MockAudioProvider(name="mock-stability")

    result = AudioStage([StepPlan(provider, "mock-audio-model")]).run(_SPEC, project_id="p1")

    assert result.status == "succeeded"
    assert result.assets[0].media_type == "audio/mpeg"

    step = provider.received_steps[0]
    assert step.modality == Modality.AUDIO
    assert "dramatic shadows" in step.prompt


def test_audio_stall_falls_back_to_sfx_role_provider():
    result = AudioStage(
        [StepPlan(_stalled("mock-stability"), "stable-audio-2"),
         StepPlan(MockAudioProvider(name="mock-sfx"), "sfx-model")]
    ).run(_SPEC)

    assert result.status == "succeeded"
    assert result.model == "sfx-model"


def test_whole_video_chain_stalling_reports_every_provider_without_raising():
    result = AnimaticStage(
        [StepPlan(_stalled("mock-runway"), "m1"), StepPlan(_stalled("mock-luma"), "m2")]
    ).run(_SPEC, _LOCKED_FRAME)

    assert result.status == "failed"
    assert "mock-runway" in result.error
    assert "mock-luma" in result.error


def test_default_plans_build_without_credentials(monkeypatch):
    for var in ("RUNWAYML_API_SECRET", "LUMAAI_API_KEY", "STABILITY_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("GMI_VIDEO_MODEL", raising=False)

    assert len(AnimaticStage()._default_plans()) == 2
    assert len(AudioStage()._default_plans()) == 2


def test_gmi_draft_tier_joins_video_chain_when_configured(monkeypatch):
    monkeypatch.setenv("GMI_VIDEO_MODEL", "some-draft-slug")
    plans = AnimaticStage()._default_plans()
    assert len(plans) == 3
    assert plans[2].model == "some-draft-slug"
