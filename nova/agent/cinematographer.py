"""
Backlog 2.4: shot description -> full Shot Spec IR (PRD Section 6, CLAUDE.md
module layout — "the agent").

Takes one ``ShotListItem`` (backlog 2.1/2.2) plus the parent scene text for
context, and asks the LLM to author the cinematographic detail: camera,
lens, lighting, grade, subject, world. ``shot_id``, ``version``, ``intent``,
and ``framing.shot_size`` are *not* left to the model — they're carried
over directly from the already-user-edited ``ShotListItem`` (same house
style as ``scene_breakdown.py`` assigning ``shot_id``/``order`` itself).
Two reasons: it keeps the Shot Spec's framing consistent with whatever shot
size the user settled on in the shot-list editor (2.2) instead of letting
the model silently redecide it, and it shrinks the model's output surface
to the fields that actually need cinematographic judgment — less surface
area for malformed output (backlog 2.5) to begin with.

``continuity_refs`` is intentionally left for the caller to pass in
(defaults to empty here): per CLAUDE.md, they must point at *locked* prior
shots, and nothing is locked yet at initial-generation time (backlog 2.4).
Populating them from real locked frames is backlog 3.4.

Malformed-output retry is the shared ``schema_retry.chat_for_schema``
helper (backlog 2.5) — same as ``scene_breakdown.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nova.agent.schema_retry import chat_for_schema
from nova.models.shot_list import ShotListItem
from nova.models.shot_spec import (
    Camera,
    CameraAngle,
    Contrast,
    Framing,
    Grade,
    Lens,
    Lighting,
    LightingKey,
    ShotSpec,
    Subject,
)

_CAMERA_ANGLE_VALUES = CameraAngle.__args__
_LIGHTING_KEY_VALUES = LightingKey.__args__
_CONTRAST_VALUES = Contrast.__args__

_MODEL = "gpt-4o-mini"

_SYSTEM_PROMPT = (
    "You are a cinematographer authoring the full technical spec for one "
    "shot in a previs shot list. You're given the overall scene, this "
    "shot's one-line description, its narrative intent, and its shot size "
    "(already decided — do not restate or contradict it). Fill in every "
    "other cinematographic parameter with concrete, realistic choices a "
    "director of photography would actually make, consistent with the "
    "shot's intent and the scene's tone:\n"
    f"- camera.angle: one of {', '.join(_CAMERA_ANGLE_VALUES)}\n"
    "- camera.height_m: realistic camera height in meters for that angle "
    "(human eye-level ~1.5; higher for drone/aerial, lower for worm's-eye)\n"
    "- camera.movement: free text, e.g. 'slow push-in', 'static', "
    "'handheld tracking'\n"
    "- lens.focal_length_mm (8-800) and lens.aperture_f (0.95-32): a real "
    "lens/stop combination appropriate to the shot\n"
    "- composition: free text framing note, e.g. 'rule-of-thirds, subject "
    "lower-left'\n"
    f"- lighting.key: one of {', '.join(_LIGHTING_KEY_VALUES)}\n"
    "- lighting.mood: free text, e.g. 'dramatic shadows'\n"
    "- lighting.practicals: visible in-scene light sources, if any\n"
    "- grade.look: free text color-grade description, e.g. 'desaturated "
    "teal'\n"
    f"- grade.contrast: one of {', '.join(_CONTRAST_VALUES)}\n"
    "- subject.primary and subject.blocking: who/what is on camera and "
    "how they're positioned/moving\n"
    "- world: list of environment/background elements visible in frame"
)


class _ShotSpecDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera: Camera
    lens: Lens
    composition: str = Field(min_length=1, max_length=300)
    lighting: Lighting
    grade: Grade
    subject: Subject
    world: list[str] = Field(default_factory=list)


def _build_prompt(scene_text: str, shot: ShotListItem) -> str:
    return (
        f"Scene: {scene_text}\n\n"
        f"This shot ({shot.shot_id}, position {shot.order + 1}):\n"
        f"Description: {shot.description}\n"
        f"Intent: {shot.intent or shot.description}\n"
        f"Shot size (fixed, do not change): {shot.shot_size}"
    )


def generate_shot_spec(
    shot: ShotListItem,
    *,
    scene_text: str,
    continuity_refs: list[str] | None = None,
    model: str = _MODEL,
) -> ShotSpec:
    """Author a full Shot Spec (v1) for one shot-list entry."""
    draft = chat_for_schema(
        model=model,
        system=_SYSTEM_PROMPT,
        prompt=_build_prompt(scene_text, shot),
        response_model=_ShotSpecDraft,
    )

    return ShotSpec(
        shot_id=shot.shot_id,
        version=1,
        intent=shot.intent or shot.description,
        camera=draft.camera,
        lens=draft.lens,
        framing=Framing(shot_size=shot.shot_size, composition=draft.composition),
        lighting=draft.lighting,
        grade=draft.grade,
        subject=draft.subject,
        world=draft.world,
        continuity_refs=continuity_refs or [],
    )


def generate_shot_specs(
    shot_list: list[ShotListItem],
    *,
    scene_text: str,
    model: str = _MODEL,
) -> list[ShotSpec]:
    """Author a full Shot Spec (v1) for every shot in an ordered shot list."""
    return [
        generate_shot_spec(shot, scene_text=scene_text, model=model)
        for shot in shot_list
    ]
