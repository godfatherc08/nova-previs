"""
Backlog 5.2/5.3/6.4: the post-lock orchestration. Idempotency under
duplicate delivery, the LOCKED -> ANIMATIC_PENDING -> ANIMATIC_READY walk,
B2 persistence of clip + audio, failure-returns-to-LOCKED retry semantics,
and the polling fallback's claim rules.

B2 I/O is monkeypatched at the advance-module import sites; the stages are
injected with real-Pipeline-backed mock providers (same honesty convention
as the stage tests).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import nova.pipeline.advance as advance_module
from genblaze_core.models.enums import ProviderErrorCode
from genblaze_core.testing import MockAudioProvider, MockProvider, MockVideoProvider
from nova.models.project import Base, ProjectRecord, ShotRecord, ShotVersionRecord
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
from nova.pipeline.advance import advance_locked_shot, poll_locked_shots
from nova.pipeline.animatic_stage import AnimaticStage
from nova.pipeline.audio_stage import AudioStage

_SPEC = ShotSpec(
    shot_id="s1",
    intent="establish the ruined city",
    camera=Camera(angle="eye-level", height_m=1.5, movement="slow pan right"),
    lens=Lens(focal_length_mm=35, aperture_f=4),
    framing=Framing(shot_size="wide", composition="centered"),
    lighting=Lighting(key="natural", mood="overcast gloom", practicals=[]),
    grade=Grade(look="cold steel blue", contrast="medium"),
    subject=Subject(primary="ruined skyline", blocking="static vista"),
    world=["collapsed towers"],
)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def b2_stub(monkeypatch):
    """Stub the three B2 touchpoints advance uses; record every put."""
    puts: dict[str, bytes] = {}
    monkeypatch.setattr(advance_module, "get_bytes", lambda key: b"locked-frame-bytes")
    monkeypatch.setattr(
        advance_module, "presigned_url", lambda key, **kw: f"https://signed.test/{key}"
    )
    monkeypatch.setattr(
        advance_module,
        "put_bytes",
        lambda key, data, **kw: puts.__setitem__(key, data) or key,
    )
    # Mock provider assets point at https://mock.test/... — hand back bytes.
    monkeypatch.setattr(advance_module, "_read_asset_bytes", lambda asset: b"asset-bytes")
    return puts


def _seed_locked_shot(session, *, status: str = "LOCKED", locked_at=None) -> None:
    project = ProjectRecord(project_id="p1", scene_text="scene")
    shot = ShotRecord(
        project_id="p1",
        shot_id="s1",
        order=0,
        description="wide establisher",
        status=status,
        current_version=1,
        locked_version=1,
        locked_at=locked_at,
        versions=[ShotVersionRecord(version=1, spec_json=_SPEC.model_dump_json())],
    )
    session.add_all([project, shot])
    session.commit()


def _stages(video_ok: bool = True, audio_ok: bool = True):
    video_provider = (
        MockVideoProvider(name="mock-video")
        if video_ok
        else MockProvider(
            name="mock-video",
            should_fail=True,
            error_code=ProviderErrorCode.SERVER_ERROR,
            error_message="video provider down",
        )
    )
    audio_provider = (
        MockAudioProvider(name="mock-audio")
        if audio_ok
        else MockProvider(
            name="mock-audio",
            should_fail=True,
            error_code=ProviderErrorCode.SERVER_ERROR,
            error_message="audio provider down",
        )
    )
    return (
        AnimaticStage([StepPlan(video_provider, "video-model")]),
        AudioStage([StepPlan(audio_provider, "audio-model")]),
    )


def test_locked_shot_advances_to_animatic_ready_and_persists_assets(
    session_factory, b2_stub
):
    session = session_factory()
    _seed_locked_shot(session)
    animatic, audio = _stages()

    status = advance_locked_shot(
        "p1", "s1", session=session, animatic_stage=animatic, audio_stage=audio
    )

    assert status == "ANIMATIC_READY"
    # Backlog 6.4: clip + audio landed at the canonical keys.
    assert "projects/p1/shots/s1/animatic/clip.mp4" in b2_stub
    assert "projects/p1/shots/s1/animatic/audio.mp3" in b2_stub
    shot = session.query(ShotRecord).one()
    assert shot.status == "ANIMATIC_READY"
    assert shot.error is None


def test_duplicate_delivery_is_a_no_op(session_factory, b2_stub):
    """B2 delivers at-least-once — the second call must find the shot no
    longer LOCKED and do nothing."""
    session = session_factory()
    _seed_locked_shot(session)
    animatic, audio = _stages()

    advance_locked_shot("p1", "s1", session=session, animatic_stage=animatic, audio_stage=audio)
    b2_stub.clear()

    status = advance_locked_shot(
        "p1", "s1", session=session, animatic_stage=animatic, audio_stage=audio
    )

    assert status == "ANIMATIC_READY"
    assert b2_stub == {}  # nothing regenerated, nothing rewritten


def test_video_failure_returns_shot_to_locked_with_error(session_factory, b2_stub):
    session = session_factory()
    _seed_locked_shot(session)
    animatic, audio = _stages(video_ok=False)

    status = advance_locked_shot(
        "p1", "s1", session=session, animatic_stage=animatic, audio_stage=audio
    )

    assert status == "LOCKED"
    shot = session.query(ShotRecord).one()
    assert shot.status == "LOCKED"
    assert "video provider down" in shot.error
    assert b2_stub == {}


def test_audio_failure_degrades_gracefully_not_fatally(session_factory, b2_stub):
    """Backlog 6.5: a dead audio provider must not fail the run — the clip
    still persists and the shot reaches ANIMATIC_READY (with the audio
    degradation recorded)."""
    session = session_factory()
    _seed_locked_shot(session)
    animatic, audio = _stages(audio_ok=False)

    status = advance_locked_shot(
        "p1", "s1", session=session, animatic_stage=animatic, audio_stage=audio
    )

    assert status == "ANIMATIC_READY"
    assert "projects/p1/shots/s1/animatic/clip.mp4" in b2_stub
    assert "projects/p1/shots/s1/animatic/audio.mp3" not in b2_stub
    shot = session.query(ShotRecord).one()
    assert "audio degraded" in shot.error


def test_unknown_shot_is_reported_not_raised(session_factory, b2_stub):
    session = session_factory()
    assert advance_locked_shot("nope", "s9", session=session) == "UNKNOWN"


def test_poller_advances_stale_locked_shot(session_factory, b2_stub):
    session = session_factory()
    _seed_locked_shot(
        session, locked_at=datetime.now(timezone.utc) - timedelta(minutes=10)
    )
    animatic, audio = _stages()

    advanced = poll_locked_shots(
        session=session, animatic_stage=animatic, audio_stage=audio
    )

    assert advanced == [("p1", "s1")]
    assert session.query(ShotRecord).one().status == "ANIMATIC_READY"


def test_poller_leaves_fresh_locks_for_the_webhook(session_factory, b2_stub):
    session = session_factory()
    _seed_locked_shot(session, locked_at=datetime.now(timezone.utc))
    animatic, audio = _stages()

    advanced = poll_locked_shots(
        session=session, animatic_stage=animatic, audio_stage=audio, min_age_seconds=3600
    )

    assert advanced == []
    assert session.query(ShotRecord).one().status == "LOCKED"


def test_poller_retries_failed_shots_regardless_of_age(session_factory, b2_stub):
    session = session_factory()
    _seed_locked_shot(session, locked_at=datetime.now(timezone.utc))
    session.query(ShotRecord).one().error = "previous animatic attempt failed"
    session.commit()
    animatic, audio = _stages()

    advanced = poll_locked_shots(
        session=session, animatic_stage=animatic, audio_stage=audio, min_age_seconds=3600
    )

    assert advanced == [("p1", "s1")]
