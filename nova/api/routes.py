"""
The full Nova API surface (backlog 1.4 — this file IS the contract's
implementation; the documented contract lives in docs/api_contract.md and
mirrors frontend/src/lib/api.ts exactly).

Backlog 2.1-2.4: project create/list/fetch, shot-list edit, storyboard
generation. Backlog 3.5/3.6: per-shot frame generation + versioned refine.
Backlog 4.1-4.3: lock (Object-Locked frame + sealed provenance manifest) and
durable media URLs. Backlog 7.1-7.4: sequence assembly. Backlog 8.6:
multi-take fan-out. The webhook trigger surface is separate
(``webhooks/lock_handler.py``).

Media URLs: the bucket is private (Object Lock setup, backlog 0.9), so
user-facing URLs go through ``GET /api/media/{key}`` — the app streams from
B2 server-side. Manifests additionally record the credential-free canonical
B2 URL (``storage.b2_client.durable_url``) for provenance.
"""

from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from nova.agent.cinematographer import generate_shot_specs
from nova.agent.compiler import resolve_continuity_refs
from nova.agent.refine import refine_shot_spec
from nova.agent.scene_breakdown import break_down_scene
from nova.models.project import (
    ProjectRecord,
    ShotRecord,
    ShotListItemRecord,
    ShotVersionRecord,
    get_session,
    new_project_id,
)
from nova.models.shot_list import ShotListItem
from nova.models.shot_spec import ShotSpec
from nova.pipeline.advance import advance_locked_shot
from nova.pipeline.assembly import assemble_sequence
from nova.pipeline.image_stage import default_image_stage, fetch_reference_assets
from nova.storage import keys
from nova.storage.b2_client import get_bytes, put_bytes, put_json
from nova.storage.manifest import build_sequence_manifest, build_shot_manifest

router = APIRouter(prefix="/api")

# How lock triggers the animatic stage (backlog 5.1-5.3):
#   "webhook" — B2 Event Notification hits /webhooks/b2/lock (production).
#   "polling" — scripts/run_poller.py sweeps LOCKED shots.
#   "direct"  — the lock endpoint background-tasks the advance itself
#               (local dev with no public URL; also the safety net the
#               judges' fresh clone runs with zero B2 event setup).
_EVENT_MODE = lambda: os.environ.get("NOVA_EVENT_MODE", "direct")  # noqa: E731


class CreateProjectRequest(BaseModel):
    scene_text: str = Field(min_length=1)


class UpdateShotListRequest(BaseModel):
    shot_list: list[ShotListItem]


class ShotVersionOut(BaseModel):
    version: int
    frame_url: str | None = None
    spec: ShotSpec
    created_at: datetime | None = None


class ShotOut(BaseModel):
    shot_id: str
    order: int
    status: str
    description: str
    current_version: int
    versions: list[ShotVersionOut]
    locked_frame_url: str | None = None
    animatic_clip_url: str | None = None
    animatic_audio_url: str | None = None
    manifest_url: str | None = None
    error: str | None = None


class ProjectOut(BaseModel):
    project_id: str
    scene_text: str
    shot_list: list[ShotListItem]
    # Populated once backlog 2.4 (generate-storyboard) has run; empty before
    # that, matching the frontend's graceful "not generated yet" state.
    shots: list[ShotOut] = Field(default_factory=list)
    sequence_url: str | None = None
    sequence_manifest_url: str | None = None
    created_at: datetime
    updated_at: datetime


class ProjectSummaryOut(BaseModel):
    project_id: str
    scene_text: str
    shot_count: int
    created_at: datetime
    updated_at: datetime


def _shot_list_records(items: list[ShotListItem]) -> list[ShotListItemRecord]:
    return [
        ShotListItemRecord(
            shot_id=item.shot_id,
            order=item.order,
            description=item.description,
            intent=item.intent,
            shot_size=item.shot_size,
        )
        for item in items
    ]


def _media_url(key: str | None) -> str | None:
    return f"/api/media/{key}" if key else None


_POST_LOCK_STATUSES = ("LOCKED", "ANIMATIC_PENDING", "ANIMATIC_READY", "ASSEMBLED")
_ANIMATIC_STATUSES = ("ANIMATIC_READY", "ASSEMBLED")


def _to_shot_out(shot: ShotRecord) -> ShotOut:
    locked = shot.status in _POST_LOCK_STATUSES
    has_animatic = shot.status in _ANIMATIC_STATUSES
    audio_degraded = bool(shot.error and shot.error.startswith("audio degraded"))
    return ShotOut(
        shot_id=shot.shot_id,
        order=shot.order,
        status=shot.status,
        description=shot.description,
        current_version=shot.current_version,
        versions=[
            ShotVersionOut(
                version=v.version,
                frame_url=_media_url(v.frame_key),
                spec=ShotSpec.model_validate_json(v.spec_json),
                created_at=v.created_at,
            )
            for v in shot.versions
        ],
        locked_frame_url=(
            _media_url(keys.locked_frame_key(shot.project_id, shot.shot_id)) if locked else None
        ),
        manifest_url=(
            _media_url(keys.locked_manifest_key(shot.project_id, shot.shot_id))
            if locked
            else None
        ),
        animatic_clip_url=(
            _media_url(keys.animatic_clip_key(shot.project_id, shot.shot_id))
            if has_animatic
            else None
        ),
        animatic_audio_url=(
            _media_url(keys.animatic_audio_key(shot.project_id, shot.shot_id))
            if has_animatic and not audio_degraded
            else None
        ),
        error=shot.error,
    )


def _to_project_out(record: ProjectRecord) -> ProjectOut:
    return ProjectOut(
        project_id=record.project_id,
        scene_text=record.scene_text,
        shot_list=[
            ShotListItem(
                shot_id=item.shot_id,
                order=item.order,
                description=item.description,
                intent=item.intent,
                shot_size=item.shot_size,
            )
            for item in record.shot_list_items
        ],
        shots=[_to_shot_out(shot) for shot in record.shots],
        sequence_url=_media_url(record.sequence_key),
        sequence_manifest_url=_media_url(record.sequence_manifest_key),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _persist_scene_json(project_id: str, scene_text: str, shot_list: list[ShotListItem]) -> None:
    put_json(
        keys.scene_json_key(project_id),
        {
            "project_id": project_id,
            "scene_text": scene_text,
            "shot_list": [item.model_dump() for item in shot_list],
        },
    )


@router.post("/projects", response_model=ProjectOut)
def create_project(
    body: CreateProjectRequest, session: Session = Depends(get_session)
) -> ProjectOut:
    try:
        shot_list = break_down_scene(body.scene_text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Scene breakdown failed: {exc}") from exc

    record = ProjectRecord(project_id=new_project_id(), scene_text=body.scene_text)
    record.shot_list_items = _shot_list_records(shot_list)
    session.add(record)
    session.commit()
    session.refresh(record)

    try:
        _persist_scene_json(record.project_id, record.scene_text, shot_list)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 write failed: {exc}") from exc

    return _to_project_out(record)


@router.get("/projects", response_model=list[ProjectSummaryOut])
def list_projects(session: Session = Depends(get_session)) -> list[ProjectSummaryOut]:
    records = session.query(ProjectRecord).order_by(ProjectRecord.created_at.desc()).all()
    return [
        ProjectSummaryOut(
            project_id=r.project_id,
            scene_text=r.scene_text,
            shot_count=len(r.shot_list_items),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in records
    ]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(get_session)) -> ProjectOut:
    record = session.get(ProjectRecord, project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_project_out(record)


@router.put("/projects/{project_id}/shot-list", response_model=ProjectOut)
def update_shot_list(
    project_id: str,
    body: UpdateShotListRequest,
    session: Session = Depends(get_session),
) -> ProjectOut:
    record = session.get(ProjectRecord, project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")

    record.shot_list_items = _shot_list_records(body.shot_list)
    session.commit()
    session.refresh(record)

    try:
        _persist_scene_json(record.project_id, record.scene_text, body.shot_list)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 write failed: {exc}") from exc

    return _to_project_out(record)


@router.post("/projects/{project_id}/generate-storyboard", response_model=ProjectOut)
def generate_storyboard(project_id: str, session: Session = Depends(get_session)) -> ProjectOut:
    """Backlog 2.4: author a v1 Shot Spec for every shot via the
    cinematographer agent, persist each to B2 and to a fresh DRAFT
    ShotRecord/ShotVersionRecord pair.

    Re-running this on a project that already has shots replaces them
    wholesale (cascade delete-orphan on ``ProjectRecord.shots``) rather than
    merging — nothing can be LOCKED yet (that state only exists from
    backlog 4.1 on), so there's no in-progress work to protect against a
    regenerate at this stage of the pipeline.
    """
    record = session.get(ProjectRecord, project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")

    shot_list = [
        ShotListItem(
            shot_id=item.shot_id,
            order=item.order,
            description=item.description,
            intent=item.intent,
            shot_size=item.shot_size,
        )
        for item in record.shot_list_items
    ]
    if not shot_list:
        raise HTTPException(status_code=400, detail="Project has no shots to generate specs for")

    try:
        specs = generate_shot_specs(shot_list, scene_text=record.scene_text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Shot Spec generation failed: {exc}") from exc

    try:
        for spec in specs:
            put_json(keys.shot_spec_key(project_id, spec.shot_id, spec.version), spec.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 write failed: {exc}") from exc

    shots_by_id = {item.shot_id: item for item in shot_list}
    record.shots = [
        ShotRecord(
            shot_id=spec.shot_id,
            order=shots_by_id[spec.shot_id].order,
            description=shots_by_id[spec.shot_id].description,
            status="DRAFT",
            current_version=spec.version,
            versions=[ShotVersionRecord(version=spec.version, spec_json=spec.model_dump_json())],
        )
        for spec in specs
    ]
    session.commit()
    session.refresh(record)

    return _to_project_out(record)


# --------------------------------------------------------------------------
# Per-shot generation, refine, spec edit (backlog 3.4/3.5/3.6)
# --------------------------------------------------------------------------


class RefineRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)


class UpdateSpecRequest(BaseModel):
    spec: ShotSpec


class LockRequest(BaseModel):
    version: int | None = None


class TakesRequest(BaseModel):
    count: int = Field(default=3, ge=2, le=4)


class PromoteTakeRequest(BaseModel):
    take_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")


def _get_shot(session: Session, project_id: str, shot_id: str) -> ShotRecord:
    shot = (
        session.query(ShotRecord)
        .filter(ShotRecord.project_id == project_id, ShotRecord.shot_id == shot_id)
        .one_or_none()
    )
    if shot is None:
        raise HTTPException(status_code=404, detail="Shot not found")
    return shot


def _version_record(shot: ShotRecord, version: int) -> ShotVersionRecord:
    for v in shot.versions:
        if v.version == version:
            return v
    raise HTTPException(status_code=404, detail=f"Shot version {version} not found")


def _asset_bytes(asset) -> bytes:
    """Read a StageResult asset's bytes (file:// from local providers,
    http(s):// from CDN-returning ones)."""
    from urllib.parse import urlparse
    from urllib.request import urlopen

    from nova.pipeline.assembly import file_uri_to_path

    parsed = urlparse(asset.url)
    if parsed.scheme == "file":
        return file_uri_to_path(asset.url).read_bytes()
    with urlopen(asset.url, timeout=60) as response:  # noqa: S310 — provider-returned URL
        return response.read()


def _locked_earlier_refs(record: ProjectRecord, shot: ShotRecord) -> list[str]:
    """Backlog 3.4: continuity refs auto-point at every already-locked
    earlier shot in the scene, in shot order. Only *locked* frames qualify
    (CLAUDE.md: refs must reference immutable frames)."""
    return [
        f"{s.shot_id}_frame"
        for s in record.shots
        if s.order < shot.order and s.status in _POST_LOCK_STATUSES
    ]


def _reference_assets_for(spec: ShotSpec, project_id: str):
    if not spec.continuity_refs:
        return None
    try:
        return fetch_reference_assets(resolve_continuity_refs(spec, project_id))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 read failed: {exc}") from exc


def _persist_generation(
    session: Session,
    shot: ShotRecord,
    version_record: ShotVersionRecord,
    spec: ShotSpec,
    result,
) -> None:
    """Backlog 3.5: each generation writes a *new* versioned frame object —
    spec/v{n}.json is written by the caller that created the version."""
    if not result.succeeded:
        shot.error = result.error
        session.commit()
        return
    frame_key = keys.frame_key(shot.project_id, shot.shot_id, version_record.version)
    try:
        put_bytes(frame_key, _asset_bytes(result.assets[0]), content_type="image/png")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 write failed: {exc}") from exc
    version_record.frame_key = frame_key
    version_record.provider = result.provider
    version_record.model = result.model
    version_record.prompt = result.prompt
    shot.status = "REFINING"
    shot.error = None
    session.commit()


@router.post("/projects/{project_id}/shots/{shot_id}/generate", response_model=ShotOut)
def generate_shot_frame(
    project_id: str, shot_id: str, session: Session = Depends(get_session)
) -> ShotOut:
    """Backlog 3.1/3.2/3.5: run the image stage for the shot's current spec
    version and persist the frame. A failed provider chain is returned as a
    shot with ``error`` set (renderable, retryable), not a 5xx."""
    record = session.get(ProjectRecord, project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")
    shot = _get_shot(session, project_id, shot_id)
    if shot.status in _POST_LOCK_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"Shot is {shot.status}; refine to create a new version"
        )
    version_record = _version_record(shot, shot.current_version)
    spec = ShotSpec.model_validate_json(version_record.spec_json)

    refs = _locked_earlier_refs(record, shot)
    if refs and set(refs) != set(spec.continuity_refs):
        spec = spec.model_copy(update={"continuity_refs": refs})
        version_record.spec_json = spec.model_dump_json()
        try:
            put_json(keys.shot_spec_key(project_id, shot_id, spec.version), spec.model_dump())
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"B2 write failed: {exc}") from exc

    result = default_image_stage().run(
        spec,
        project_id=project_id,
        reference_assets=_reference_assets_for(spec, project_id),
    )
    _persist_generation(session, shot, version_record, spec, result)
    session.refresh(shot)
    return _to_shot_out(shot)


@router.post("/projects/{project_id}/shots/{shot_id}/refine", response_model=ShotOut)
def refine_shot(
    project_id: str,
    shot_id: str,
    body: RefineRequest,
    session: Session = Depends(get_session),
) -> ShotOut:
    """Backlog 3.6: instruction -> new Shot Spec version -> regenerated frame.

    Refining a post-lock shot creates a NEW version at REFINING (CLAUDE.md);
    the locked artifacts in B2 stay immutable — Object Lock enforces that
    below the app anyway.
    """
    record = session.get(ProjectRecord, project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")
    shot = _get_shot(session, project_id, shot_id)
    prior_record = _version_record(shot, shot.current_version)
    prior_spec = ShotSpec.model_validate_json(prior_record.spec_json)

    try:
        new_spec = refine_shot_spec(prior_spec, body.instruction, scene_text=record.scene_text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Spec refinement failed: {exc}") from exc

    refs = _locked_earlier_refs(record, shot)
    if refs:
        new_spec = new_spec.model_copy(update={"continuity_refs": refs})

    try:
        put_json(
            keys.shot_spec_key(project_id, shot_id, new_spec.version), new_spec.model_dump()
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 write failed: {exc}") from exc

    new_record = ShotVersionRecord(
        version=new_spec.version, spec_json=new_spec.model_dump_json()
    )
    shot.versions.append(new_record)
    shot.current_version = new_spec.version
    shot.status = "REFINING"
    session.commit()

    stage = default_image_stage()
    reference_assets = _reference_assets_for(new_spec, project_id)
    if prior_record.frame_key:
        # Edit-in-place against the prior frame (the whole point of refine).
        try:
            prior_bytes = get_bytes(prior_record.frame_key)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"B2 read failed: {exc}") from exc
        import tempfile as _tempfile

        fd, tmp = _tempfile.mkstemp(suffix=".png")
        os.close(fd)
        prior_path = Path(tmp)
        prior_path.write_bytes(prior_bytes)
        from genblaze_core.models.asset import Asset as _Asset

        prior_asset = _Asset(
            url=prior_path.resolve().as_uri(), media_type="image/png", size_bytes=len(prior_bytes)
        )
        prior_asset.set_hash(prior_bytes)
        result = stage.refine(
            new_spec,
            prior_asset,
            instruction=body.instruction,
            project_id=project_id,
            reference_assets=reference_assets,
        )
    else:
        # No prior frame yet (refined straight from DRAFT) — generate fresh.
        result = stage.run(new_spec, project_id=project_id, reference_assets=reference_assets)

    _persist_generation(session, shot, new_record, new_spec, result)
    session.refresh(shot)
    return _to_shot_out(shot)


@router.put("/projects/{project_id}/shots/{shot_id}/spec", response_model=ShotOut)
def update_shot_spec(
    project_id: str,
    shot_id: str,
    body: UpdateSpecRequest,
    session: Session = Depends(get_session),
) -> ShotOut:
    """Manual spec edit -> new version (no frame until the user generates)."""
    shot = _get_shot(session, project_id, shot_id)
    if body.spec.shot_id != shot_id:
        raise HTTPException(status_code=400, detail="spec.shot_id does not match the URL")

    new_version = shot.current_version + 1
    new_spec = body.spec.model_copy(update={"version": new_version})
    try:
        put_json(keys.shot_spec_key(project_id, shot_id, new_version), new_spec.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 write failed: {exc}") from exc

    shot.versions.append(
        ShotVersionRecord(version=new_version, spec_json=new_spec.model_dump_json())
    )
    shot.current_version = new_version
    if shot.status in _POST_LOCK_STATUSES:
        shot.status = "REFINING"
    session.commit()
    session.refresh(shot)
    return _to_shot_out(shot)


# --------------------------------------------------------------------------
# Lock (backlog 4.1/4.2) + manifests (4.2/4.4 surface)
# --------------------------------------------------------------------------


@router.post("/projects/{project_id}/shots/{shot_id}/lock", response_model=ShotOut)
def lock_shot(
    project_id: str,
    shot_id: str,
    body: LockRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
) -> ShotOut:
    """Backlog 4.1: write locked/frame.png + locked/manifest.json under
    Object Lock. This B2 write is what fires the Event Notification in
    webhook mode; in the default "direct" mode the advance is background-
    tasked here so the pipeline completes without any B2 event setup."""
    shot = _get_shot(session, project_id, shot_id)
    if shot.status not in ("DRAFT", "REFINING"):
        raise HTTPException(status_code=409, detail=f"Cannot lock a shot in {shot.status}")

    version = body.version or shot.current_version
    version_record = _version_record(shot, version)
    if not version_record.frame_key:
        raise HTTPException(
            status_code=409, detail=f"Version {version} has no generated frame to lock"
        )

    spec = ShotSpec.model_validate_json(version_record.spec_json)
    try:
        frame_bytes = get_bytes(version_record.frame_key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 read failed: {exc}") from exc

    locked_key = keys.locked_frame_key(project_id, shot_id)
    manifest = build_shot_manifest(
        project_id=project_id,
        shot_id=shot_id,
        version=version,
        spec=spec,
        frame_key=locked_key,
        frame_bytes=frame_bytes,
        provider=version_record.provider or "unknown",
        model=version_record.model or "unknown",
        prompt=version_record.prompt or "",
        reference_keys=resolve_continuity_refs(spec, project_id),
    )
    try:
        put_bytes(locked_key, frame_bytes, content_type="image/png", object_lock=True)
        put_json(
            keys.locked_manifest_key(project_id, shot_id),
            manifest.model_dump(mode="json"),
            object_lock=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 write failed: {exc}") from exc

    shot.status = "LOCKED"
    shot.locked_version = version
    shot.locked_at = datetime.now(timezone.utc)
    shot.error = None
    session.commit()

    if _EVENT_MODE() == "direct":
        background.add_task(advance_locked_shot, project_id, shot_id)

    session.refresh(shot)
    return _to_shot_out(shot)


@router.get("/projects/{project_id}/shots/{shot_id}/manifest")
def get_shot_manifest(project_id: str, shot_id: str) -> dict:
    try:
        import json as _json

        return _json.loads(
            get_bytes(keys.locked_manifest_key(project_id, shot_id)).decode("utf-8")
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Manifest not found: {exc}") from exc


@router.get("/projects/{project_id}/manifest")
def get_sequence_manifest(project_id: str) -> dict:
    try:
        import json as _json

        return _json.loads(get_bytes(keys.previs_manifest_key(project_id)).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Manifest not found: {exc}") from exc


# --------------------------------------------------------------------------
# Assembly (backlog 7.1-7.4)
# --------------------------------------------------------------------------


@router.post("/projects/{project_id}/assemble", response_model=ProjectOut)
def assemble_project(project_id: str, session: Session = Depends(get_session)) -> ProjectOut:
    record = session.get(ProjectRecord, project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")

    ready = [s for s in record.shots if s.status in _ANIMATIC_STATUSES]
    if not ready:
        raise HTTPException(
            status_code=409, detail="No shots are ANIMATIC_READY — lock at least one shot first"
        )
    ready.sort(key=lambda s: s.order)

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        shot_media: list[tuple[Path, Path | None]] = []
        shot_entries: list[dict] = []
        for shot in ready:
            try:
                clip_bytes = get_bytes(keys.animatic_clip_key(project_id, shot.shot_id))
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"B2 read failed for {shot.shot_id} clip: {exc}",
                ) from exc
            clip_path = workdir / f"{shot.shot_id}_clip.mp4"
            clip_path.write_bytes(clip_bytes)

            audio_path: Path | None = None
            try:
                audio_bytes = get_bytes(keys.animatic_audio_key(project_id, shot.shot_id))
                audio_path = workdir / f"{shot.shot_id}_audio.mp3"
                audio_path.write_bytes(audio_bytes)
            except Exception:
                # Audio degraded for this shot (backlog 6.5) — silent track.
                audio_path = None

            manifest_hash = None
            try:
                import json as _json

                manifest_hash = _json.loads(
                    get_bytes(keys.locked_manifest_key(project_id, shot.shot_id)).decode("utf-8")
                ).get("manifest_sha256")
            except Exception:
                pass

            shot_media.append((clip_path, audio_path))
            shot_entries.append(
                {
                    "shot_id": shot.shot_id,
                    "order": shot.order,
                    "locked_version": shot.locked_version,
                    "manifest_sha256": manifest_hash,
                }
            )

        out_path = workdir / "sequence.mp4"
        try:
            assemble_sequence(shot_media, out_path, workdir=workdir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Assembly failed: {exc}") from exc
        sequence_bytes = out_path.read_bytes()

    sequence_key = keys.previs_sequence_key(project_id)
    sequence_manifest = build_sequence_manifest(
        project_id=project_id,
        sequence_key=sequence_key,
        sequence_bytes=sequence_bytes,
        shots=shot_entries,
    )
    try:
        put_bytes(sequence_key, sequence_bytes, content_type="video/mp4")
        put_json(keys.previs_manifest_key(project_id), sequence_manifest.model_dump(mode="json"))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 write failed: {exc}") from exc

    for shot in ready:
        shot.status = "ASSEMBLED"
    record.sequence_key = sequence_key
    record.sequence_manifest_key = keys.previs_manifest_key(project_id)
    session.commit()
    session.refresh(record)
    return _to_project_out(record)


# --------------------------------------------------------------------------
# Multi-take fan-out (backlog 8.6)
# --------------------------------------------------------------------------


class TakeOut(BaseModel):
    take_id: str
    frame_url: str


class TakesOut(BaseModel):
    takes: list[TakeOut]
    errors: list[str] = Field(default_factory=list)


@router.post("/projects/{project_id}/shots/{shot_id}/takes", response_model=TakesOut)
def generate_takes(
    project_id: str,
    shot_id: str,
    body: TakesRequest,
    session: Session = Depends(get_session),
) -> TakesOut:
    """Parallel candidate takes for the current spec. Stored under the
    lifecycle-swept ``scratch/`` prefix (see storage/keys.py) — unpromoted
    takes auto-expire, promoted ones are re-written as a numbered version.

    Per the CLAUDE.md stage contract, branches fail independently: a dead
    branch lands in ``errors`` while the surviving takes still return.
    """
    record = session.get(ProjectRecord, project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found")
    shot = _get_shot(session, project_id, shot_id)
    version_record = _version_record(shot, shot.current_version)
    spec = ShotSpec.model_validate_json(version_record.spec_json)
    reference_assets = _reference_assets_for(spec, project_id)

    def _one_take(index: int):
        stage = default_image_stage()
        return index, stage.run(spec, project_id=project_id, reference_assets=reference_assets)

    takes: list[TakeOut] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=body.count) as pool:
        for index, result in pool.map(_one_take, range(body.count)):
            if not result.succeeded:
                errors.append(f"take {index + 1}: {result.error}")
                continue
            take_id = f"v{shot.current_version}-t{index + 1}"
            key = keys.take_key(project_id, shot_id, take_id)
            try:
                put_bytes(key, _asset_bytes(result.assets[0]), content_type="image/png")
            except Exception as exc:
                errors.append(f"take {index + 1}: B2 write failed: {exc}")
                continue
            takes.append(TakeOut(take_id=take_id, frame_url=f"/api/media/{key}"))

    if not takes:
        raise HTTPException(status_code=502, detail="; ".join(errors) or "all takes failed")
    return TakesOut(takes=takes, errors=errors)


@router.post(
    "/projects/{project_id}/shots/{shot_id}/takes/promote", response_model=ShotOut
)
def promote_take(
    project_id: str,
    shot_id: str,
    body: PromoteTakeRequest,
    session: Session = Depends(get_session),
) -> ShotOut:
    """Promote a scratch take to a real numbered version (its frame is
    re-written under frames/ so the lifecycle sweep can't eat it)."""
    shot = _get_shot(session, project_id, shot_id)
    current = _version_record(shot, shot.current_version)
    try:
        frame_bytes = get_bytes(keys.take_key(project_id, shot_id, body.take_id))
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Take not found: {exc}") from exc

    new_version = shot.current_version + 1
    spec = ShotSpec.model_validate_json(current.spec_json).model_copy(
        update={"version": new_version}
    )
    frame_key = keys.frame_key(project_id, shot_id, new_version)
    try:
        put_json(keys.shot_spec_key(project_id, shot_id, new_version), spec.model_dump())
        put_bytes(frame_key, frame_bytes, content_type="image/png")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"B2 write failed: {exc}") from exc

    shot.versions.append(
        ShotVersionRecord(
            version=new_version,
            spec_json=spec.model_dump_json(),
            frame_key=frame_key,
            provider=current.provider,
            model=current.model,
            prompt=current.prompt,
        )
    )
    shot.current_version = new_version
    shot.status = "REFINING"
    session.commit()
    session.refresh(shot)
    return _to_shot_out(shot)


# --------------------------------------------------------------------------
# Media proxy (backlog 4.3/7.4 user-facing durable URLs)
# --------------------------------------------------------------------------

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".json": "application/json",
}


@router.get("/media/{key:path}")
def get_media(key: str) -> Response:
    """Streams a B2 object through the app — the user-facing durable link
    for a private bucket. Only Nova's own key prefixes are reachable; this
    is not a general proxy."""
    if not (key.startswith("projects/") or key.startswith("scratch/")) or ".." in key:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        data = get_bytes(key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Object not found: {exc}") from exc
    media_type = _MEDIA_TYPES.get(Path(key).suffix.lower(), "application/octet-stream")
    return Response(
        content=data,
        media_type=media_type,
        # Frames/clips are immutable-by-key (new version => new key), so
        # long cache is safe and makes the storyboard grid snappy.
        headers={"Cache-Control": "public, max-age=86400"},
    )
