"""
The post-lock orchestration: LOCKED -> ANIMATIC_PENDING -> ANIMATIC_READY
(backlog 5.2/5.3/6.1/6.4).

This is Nova glue, per CLAUDE.md's webhook section: Genblaze neither
consumes nor emits B2 Event Notifications — the webhook handler
(``webhooks/lock_handler.py``) and the polling fallback both funnel into
``advance_locked_shot`` here, and *it* calls the Genblaze-run stages.

Idempotency contract (B2 delivers at-least-once): the status flip
LOCKED -> ANIMATIC_PENDING happens in its own committed transaction before
any generation starts, so a duplicate delivery — or the poller racing the
webhook — finds the shot no longer LOCKED and no-ops. On stage failure the
shot returns to LOCKED with ``error`` recorded, which makes the polling
fallback double as the retry mechanism.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from genblaze_core.models.asset import Asset
from sqlalchemy.orm import Session

from nova.models.project import SessionLocal, ShotRecord
from nova.pipeline.animatic_stage import AnimaticStage
from nova.pipeline.audio_stage import AudioStage
from nova.storage import keys
from nova.storage.b2_client import get_bytes, presigned_url, put_bytes

logger = logging.getLogger("nova.advance")


def _load_shot(session: Session, project_id: str, shot_id: str) -> ShotRecord | None:
    return (
        session.query(ShotRecord)
        .filter(ShotRecord.project_id == project_id, ShotRecord.shot_id == shot_id)
        .one_or_none()
    )


def _locked_spec(shot: ShotRecord):
    from nova.models.shot_spec import ShotSpec

    version = shot.locked_version or shot.current_version
    for v in shot.versions:
        if v.version == version:
            return ShotSpec.model_validate_json(v.spec_json)
    raise ValueError(f"shot {shot.shot_id}: no spec for locked version {version}")


def _locked_frame_asset(project_id: str, shot_id: str) -> Asset:
    """The locked frame as a provider-consumable Asset.

    Presigned https URL (the bucket is private; Runway/Luma fetch by URL),
    hash computed from the actual bytes so run manifests stay stable even
    though the presigned URL rotates.
    """
    key = keys.locked_frame_key(project_id, shot_id)
    data = get_bytes(key)
    asset = Asset(url=presigned_url(key), media_type="image/png", size_bytes=len(data))
    asset.set_hash(data)
    return asset


def advance_locked_shot(
    project_id: str,
    shot_id: str,
    *,
    session: Session | None = None,
    animatic_stage: AnimaticStage | None = None,
    audio_stage: AudioStage | None = None,
) -> str:
    """Run the animatic + audio stages for a locked shot. Returns the shot's
    final status. Safe to call redundantly (see module docstring)."""
    owns_session = session is None
    session = session or SessionLocal()
    try:
        shot = _load_shot(session, project_id, shot_id)
        if shot is None:
            logger.warning("advance: unknown shot %s/%s", project_id, shot_id)
            return "UNKNOWN"
        if shot.status != "LOCKED":
            # Duplicate webhook delivery, poller/webhook race, or an event
            # for something already advanced — all normal, all no-ops.
            logger.info(
                "advance: shot %s/%s is %s, not LOCKED — skipping",
                project_id, shot_id, shot.status,
            )
            return shot.status

        shot.status = "ANIMATIC_PENDING"
        shot.error = None
        session.commit()

        try:
            spec = _locked_spec(shot)
            frame = _locked_frame_asset(project_id, shot_id)

            clip_result = (animatic_stage or AnimaticStage()).run(
                spec, frame, project_id=project_id
            )
            if not clip_result.succeeded:
                raise RuntimeError(f"animatic stage failed: {clip_result.error}")

            audio_result = (audio_stage or AudioStage()).run(spec, project_id=project_id)
            # Audio failure is graceful degradation (6.5): the sequence
            # assembles with a silent track for this shot, it does not block
            # ANIMATIC_READY. Recorded on the shot so the UI can surface it.
            audio_error = None if audio_result.succeeded else audio_result.error

            _persist_animatic(project_id, shot_id, clip_result, audio_result)

            shot.status = "ANIMATIC_READY"
            shot.error = f"audio degraded: {audio_error}" if audio_error else None
            session.commit()
            return shot.status
        except Exception as exc:
            logger.exception("advance failed for %s/%s", project_id, shot_id)
            # Back to LOCKED so the polling fallback retries it.
            shot.status = "LOCKED"
            shot.error = str(exc)
            session.commit()
            return shot.status
    finally:
        if owns_session:
            session.close()


def _read_asset_bytes(asset: Asset) -> bytes:
    from urllib.parse import urlparse
    from urllib.request import urlopen

    from nova.pipeline.assembly import file_uri_to_path

    parsed = urlparse(asset.url)
    if parsed.scheme == "file":
        return file_uri_to_path(asset.url).read_bytes()
    with urlopen(asset.url, timeout=60) as response:  # noqa: S310 — provider-returned URL
        return response.read()


def _persist_animatic(project_id: str, shot_id: str, clip_result, audio_result) -> None:
    """Backlog 6.4: write animatic/clip.mp4 (+ audio.mp3 when the audio
    stage succeeded) to Nova's canonical B2 layout."""
    put_bytes(
        keys.animatic_clip_key(project_id, shot_id),
        _read_asset_bytes(clip_result.assets[0]),
        content_type="video/mp4",
    )
    if audio_result.succeeded:
        put_bytes(
            keys.animatic_audio_key(project_id, shot_id),
            _read_asset_bytes(audio_result.assets[0]),
            content_type="audio/mpeg",
        )


def poll_locked_shots(
    *,
    min_age_seconds: float = 30.0,
    session: Session | None = None,
    animatic_stage: AnimaticStage | None = None,
    audio_stage: AudioStage | None = None,
) -> list[tuple[str, str]]:
    """Backlog 5.3: the polling fallback. Finds shots sitting in LOCKED and
    advances them — the pipeline still completes end-to-end if the B2 event
    path is disabled, misconfigured, or the delivery was lost.

    ``min_age_seconds`` gives the webhook first claim on fresh locks so the
    two trigger paths don't race B2's delivery window; shots that failed a
    prior advance (back in LOCKED with ``error`` set) are always eligible.
    Returns the (project_id, shot_id) pairs it advanced.
    """
    owns_session = session is None
    session = session or SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=min_age_seconds)
        candidates = session.query(ShotRecord).filter(ShotRecord.status == "LOCKED").all()
        advanced: list[tuple[str, str]] = []
        for shot in candidates:
            if shot.error is None:
                # Fresh lock, no prior failure: let the webhook have it first.
                locked_at = shot.locked_at
                if locked_at is not None and locked_at.tzinfo is None:
                    locked_at = locked_at.replace(tzinfo=timezone.utc)
                if locked_at is not None and locked_at > cutoff:
                    continue
            advance_locked_shot(
                shot.project_id,
                shot.shot_id,
                session=session,
                animatic_stage=animatic_stage,
                audio_stage=audio_stage,
            )
            advanced.append((shot.project_id, shot.shot_id))
        return advanced
    finally:
        if owns_session:
            session.close()
