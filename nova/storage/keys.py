"""
Canonical B2 key builders (CLAUDE.md "B2 key structure").

Every path under ``nova-previs/`` must be built here, never string-formatted
inline elsewhere — the webhook handler (backlog 5.2) matches on the literal
``locked/frame.png`` suffix, so a locked frame written to a different path
silently breaks the trigger.

Only ``scene_json_key`` is used by backlog 2.1-2.3; the rest of the layout
is defined now since CLAUDE.md already specifies the exact paths and this
is the one place they're allowed to be written.
"""

from __future__ import annotations


def scene_json_key(project_id: str) -> str:
    return f"projects/{project_id}/scene.json"


def shot_spec_key(project_id: str, shot_id: str, version: int) -> str:
    return f"projects/{project_id}/shots/{shot_id}/spec/v{version}.json"


def frame_key(project_id: str, shot_id: str, version: int) -> str:
    return f"projects/{project_id}/shots/{shot_id}/frames/v{version}.png"


def locked_frame_key(project_id: str, shot_id: str) -> str:
    return f"projects/{project_id}/shots/{shot_id}/locked/frame.png"


def locked_manifest_key(project_id: str, shot_id: str) -> str:
    return f"projects/{project_id}/shots/{shot_id}/locked/manifest.json"


def animatic_clip_key(project_id: str, shot_id: str) -> str:
    return f"projects/{project_id}/shots/{shot_id}/animatic/clip.mp4"


def animatic_audio_key(project_id: str, shot_id: str) -> str:
    return f"projects/{project_id}/shots/{shot_id}/animatic/audio.mp3"


def previs_sequence_key(project_id: str) -> str:
    return f"projects/{project_id}/previs/sequence.mp4"


def previs_manifest_key(project_id: str) -> str:
    return f"projects/{project_id}/previs/manifest.json"


def take_key(project_id: str, shot_id: str, take_id: str) -> str:
    """Multi-take fan-out candidates (backlog 8.6) live under the flat
    ``scratch/`` prefix, NOT under ``projects/`` — that's the only prefix the
    bucket's lifecycle rule (backlog 0.10) can auto-expire, since B2 lifecycle
    rules match a literal prefix and can't wildcard mid-path. See the design
    note in ``scripts/setup_b2_bucket.py``. A promoted take is re-written to
    ``frame_key(...)`` as a new numbered version; unpromoted ones just expire.
    """
    return f"scratch/{project_id}/{shot_id}/{take_id}.png"


_LOCKED_FRAME_SUFFIX = "locked/frame.png"


def parse_locked_frame_key(key: str) -> tuple[str, str] | None:
    """Inverse of ``locked_frame_key``: -> ``(project_id, shot_id)``.

    The webhook handler (backlog 5.2) receives B2 Event Notification payloads
    whose ``objectName`` it must map back to a shot. Kept here, next to the
    builder it inverts, so the two can't drift. Returns None for any key that
    isn't exactly a locked-frame path — the notification rule is prefix-scoped
    but the handler must not trust that scoping (at-least-once delivery, and
    rules can be edited in the B2 console independently of this code).
    """
    parts = key.split("/")
    # projects/{project_id}/shots/{shot_id}/locked/frame.png
    if (
        len(parts) == 6
        and parts[0] == "projects"
        and parts[2] == "shots"
        and f"{parts[4]}/{parts[5]}" == _LOCKED_FRAME_SUFFIX
        and parts[1]
        and parts[3]
    ):
        return parts[1], parts[3]
    return None
