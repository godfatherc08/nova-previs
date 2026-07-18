"""
Backlog 9.1 (fallback at every stage) + 9.4 (full-scene run) — offline
analogues.

9.1 acceptance is "all 3 pipeline stages complete under a forced primary-
provider failure." 9.4 is "a full 5-6 shot scene completes from description
to shareable previs with no manual intervention." The live acceptance
happens against real providers during hardening week; these tests prove the
*orchestration* survives a forced primary failure at image, animatic, AND
audio simultaneously, and that a 6-shot scene walks the whole state machine
to a sealed, verifiable previs — all with real genblaze Pipelines and the
SDK's mock providers standing in only for the wire calls.
"""

import pytest
from genblaze_core.models.asset import Asset
from genblaze_core.models.enums import ProviderErrorCode
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
from nova.pipeline.image_stage import ImageStage
from nova.storage.manifest import build_shot_manifest, verify_shot_manifest


def _spec(shot_id: str, order: int) -> ShotSpec:
    return ShotSpec(
        shot_id=shot_id,
        intent=f"beat {order}",
        camera=Camera(angle="eye-level", height_m=1.5, movement="slow pan"),
        lens=Lens(focal_length_mm=35, aperture_f=2.8),
        framing=Framing(shot_size="wide", composition="centered"),
        lighting=Lighting(key="natural", mood="tense", practicals=[]),
        grade=Grade(look="steel blue", contrast="medium"),
        subject=Subject(primary="lone figure", blocking="advancing"),
        world=["ruined street"],
    )


def _dead(name: str) -> MockProvider:
    return MockProvider(
        name=name,
        should_fail=True,
        error_code=ProviderErrorCode.SERVER_ERROR,
        error_message=f"{name} down",
    )


_IMG = Asset(url="https://mock.test/frame.png", media_type="image/png", sha256="a" * 64)
_FRAME_INPUT = Asset(url="https://mock.test/locked.png", media_type="image/png", sha256="b" * 64)


def test_forced_primary_failure_at_every_stage_still_completes():
    """Backlog 9.1: primary dead at image, animatic, and audio — the run
    still produces a frame, a clip, and a track via fallbacks."""
    image = ImageStage(
        _dead("img-primary"),
        model="img-primary",
        fallbacks=[ImageStage(MockProvider(name="img-fallback", assets=[_IMG]), model="img-fb")],
    )
    animatic = AnimaticStage(
        [StepPlan(_dead("vid-primary"), "vid-primary"),
         StepPlan(MockVideoProvider(name="vid-fallback"), "vid-fb")]
    )
    audio = AudioStage(
        [StepPlan(_dead("aud-primary"), "aud-primary"),
         StepPlan(MockAudioProvider(name="aud-fallback"), "aud-fb")]
    )

    spec = _spec("s1", 0)
    image_result = image.run(spec)
    assert image_result.succeeded and image_result.model == "img-fb"

    animatic_result = animatic.run(spec, _FRAME_INPUT)
    assert animatic_result.succeeded and animatic_result.model == "vid-fb"

    audio_result = audio.run(spec)
    assert audio_result.succeeded and audio_result.model == "aud-fb"


def test_full_six_shot_scene_walks_state_machine_to_verifiable_previs():
    """Backlog 9.4 (offline): 6 shots each generate -> lock (sealed manifest)
    -> animatic + audio, with no manual intervention and no stage raising.
    Proves the manifest chain is intact end to end."""
    image = ImageStage(MockProvider(name="img", assets=[_IMG]), model="img")
    animatic = AnimaticStage([StepPlan(MockVideoProvider(name="vid"), "vid")])
    audio = AudioStage([StepPlan(MockAudioProvider(name="aud"), "aud")])

    shot_manifests = []
    for order in range(6):
        shot_id = f"s{order + 1}"
        spec = _spec(shot_id, order)

        img = image.run(spec, project_id="p1")
        assert img.succeeded

        # Lock: seal a provenance manifest for the generated frame.
        frame_bytes = b"frame-%d" % order
        manifest = build_shot_manifest(
            project_id="p1",
            shot_id=shot_id,
            version=1,
            spec=spec,
            frame_key=f"projects/p1/shots/{shot_id}/locked/frame.png",
            frame_bytes=frame_bytes,
            provider=img.provider,
            model=img.model,
            prompt=img.prompt or "",
        )
        assert verify_shot_manifest(manifest, frame_bytes).ok
        shot_manifests.append(manifest)

        # Post-lock: animatic + audio both complete.
        assert animatic.run(spec, _FRAME_INPUT, project_id="p1").succeeded
        assert audio.run(spec, project_id="p1").succeeded

    assert len(shot_manifests) == 6
    # Every shot's manifest is independently verifiable and distinct.
    hashes = {m.manifest_sha256 for m in shot_manifests}
    assert len(hashes) == 6


def test_scene_completes_even_when_audio_dead_for_every_shot():
    """Backlog 6.5 at scene scale: audio provider dead for all shots is
    graceful degradation, not a scene failure — frames and clips still land,
    audio is simply absent."""
    image = ImageStage(MockProvider(name="img", assets=[_IMG]), model="img")
    animatic = AnimaticStage([StepPlan(MockVideoProvider(name="vid"), "vid")])
    audio = AudioStage([StepPlan(_dead("aud-only"), "aud")])

    degraded = 0
    for order in range(3):
        spec = _spec(f"s{order + 1}", order)
        assert image.run(spec).succeeded
        assert animatic.run(spec, _FRAME_INPUT).succeeded
        if not audio.run(spec).succeeded:
            degraded += 1
    # All three shots degraded on audio but the scene still produced frames
    # and clips throughout.
    assert degraded == 3


@pytest.mark.parametrize("failing_stage", ["image", "animatic", "audio"])
def test_whole_chain_dead_at_one_stage_reports_cleanly(failing_stage):
    """When *every* provider for one stage is dead, that stage returns a
    failed StageResult (never raises) naming the providers — the retryable
    error card the UI renders."""
    spec = _spec("s1", 0)
    if failing_stage == "image":
        r = ImageStage(
            _dead("a"), model="a",
            fallbacks=[ImageStage(_dead("b"), model="b")],
        ).run(spec)
    elif failing_stage == "animatic":
        r = AnimaticStage([StepPlan(_dead("a"), "a"), StepPlan(_dead("b"), "b")]).run(
            spec, _FRAME_INPUT
        )
    else:
        r = AudioStage([StepPlan(_dead("a"), "a"), StepPlan(_dead("b"), "b")]).run(spec)

    assert r.status == "failed"
    assert "a" in r.error and "b" in r.error
