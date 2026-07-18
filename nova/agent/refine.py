"""
Backlog 3.6 (agent half): natural-language feedback -> a new Shot Spec
version.

The refine loop's controllability comes from refining the *spec*, not the
prompt: the user's instruction is applied to the structured IR, the compiler
re-emits the prompt deterministically, and (because enum -> phrase mapping
is stable, see agent/compiler.py) only the clauses touched by the changed
fields move. The LLM's job here is narrow: parse "make it a low angle at
dusk" into ``camera.angle="low"`` + lighting changes, leaving every other
field byte-identical.

``shot_id`` is pinned and ``version`` is incremented here, not left to the
model — same house style as scene_breakdown.py/cinematographer.py.
``continuity_refs`` carry over unchanged: refs point at *locked* prior
shots, and a refinement of this shot doesn't change which prior shots it
must stay consistent with.

Malformed-output retry is the shared ``schema_retry.chat_for_schema``
helper (backlog 2.5).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nova.agent.schema_retry import chat_for_schema
from nova.models.shot_spec import (
    Camera,
    Framing,
    Grade,
    Lens,
    Lighting,
    ShotSpec,
    Subject,
)

_MODEL = "gpt-4o-mini"

_SYSTEM_PROMPT = (
    "You are a cinematographer revising one shot's technical spec based on "
    "a director's feedback. You are given the current spec as JSON and a "
    "free-text refinement instruction. Return the FULL revised spec, "
    "changing ONLY the fields the instruction requires — every field the "
    "instruction does not touch must be returned exactly as it was. Do not "
    "reinterpret or 'improve' fields the director didn't mention. The "
    "instruction may change any cinematographic field, including framing "
    "shot_size and narrative intent, if that's what it asks for."
)


class _RefinedSpecDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=500)
    camera: Camera
    lens: Lens
    framing: Framing
    lighting: Lighting
    grade: Grade
    subject: Subject
    world: list[str] = Field(default_factory=list)


def refine_shot_spec(
    current: ShotSpec,
    instruction: str,
    *,
    scene_text: str = "",
    model: str = _MODEL,
) -> ShotSpec:
    """Apply a refinement instruction to ``current``, returning version+1."""
    prompt = (
        (f"Scene context: {scene_text}\n\n" if scene_text else "")
        + f"Current spec (JSON):\n{current.model_dump_json(indent=2)}\n\n"
        + f"Refinement instruction: {instruction}"
    )
    draft = chat_for_schema(
        model=model,
        system=_SYSTEM_PROMPT,
        prompt=prompt,
        response_model=_RefinedSpecDraft,
    )

    return ShotSpec(
        shot_id=current.shot_id,
        version=current.version + 1,
        intent=draft.intent,
        camera=draft.camera,
        lens=draft.lens,
        framing=draft.framing,
        lighting=draft.lighting,
        grade=draft.grade,
        subject=draft.subject,
        world=draft.world,
        continuity_refs=list(current.continuity_refs),
    )
