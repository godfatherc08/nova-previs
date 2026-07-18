"""
Backlog 2.1: scene text -> ordered, editable shot list (PRD Section 5 step 2).

Uses ``genblaze_openai.chat()`` — confirmed by reading the installed
``genblaze_openai/chat.py`` and ``genblaze_core/models/chat.py`` directly
(per CLAUDE.md's verify-before-asserting rule) to be a real standalone
helper, outside the Pipeline/Step machinery, that accepts
``response_format=<pydantic model>`` for schema-constrained structured
output. That lets the model return schema-valid JSON directly instead of
prompt-engineered parsing.

Model choice (gpt-4o-mini): reuses the OpenAI credential/dependency already
on the roadmap for the gpt-image-1 fallback (backlog 3.3) rather than
introducing a new LLM provider — confirmed with the user, since neither the
PRD nor backlog 0.6 names which model powers "the agent LLM".

``shot_id`` and ``order`` are assigned here, not trusted from the model, so
downstream ``continuity_refs`` (shot_spec.py) can rely on the
``s{n}_frame`` convention the frontend's shot-list UI already uses.
Malformed-output retry (backlog 2.5) is handled by the shared
``schema_retry.chat_for_schema`` helper — a provider error or a schema
violation retries a bounded number of times before raising
``AgentOutputError``, rather than propagating a raw parse/validation
exception to the caller.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nova.agent.schema_retry import chat_for_schema
from nova.models.shot_list import ShotListItem
from nova.models.shot_spec import ShotSize

_SHOT_SIZE_VALUES = ShotSize.__args__

_MODEL = "gpt-4o-mini"

_SYSTEM_PROMPT = (
    "You are a film cinematographer breaking a scene description into a "
    "shot list a director could actually shoot. Propose an ordered "
    "sequence of shots that together cover the scene coherently — vary "
    "shot size and function the way a real shot list would (e.g. an "
    "establishing wide, then a medium on the subject, an insert on a "
    "key detail, a reverse angle), rather than one shot per sentence of "
    "the input. Aim for 3-8 shots unless the scene clearly needs more or "
    "fewer. For each shot give: a one-sentence `description` of what's "
    "seen and happens, an `intent` describing why this shot exists "
    f"narratively, and a `shot_size` from exactly this set: "
    f"{', '.join(_SHOT_SIZE_VALUES)}."
)


class _ShotDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=500)
    intent: str = Field(min_length=1, max_length=500)
    shot_size: ShotSize


class _ShotDraftList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shots: list[_ShotDraft] = Field(min_length=1)


def break_down_scene(scene_text: str, *, model: str = _MODEL) -> list[ShotListItem]:
    """Decompose a free-text scene description into an ordered shot list."""
    drafts = chat_for_schema(
        model=model,
        system=_SYSTEM_PROMPT,
        prompt=scene_text,
        response_model=_ShotDraftList,
    )

    return [
        ShotListItem(
            shot_id=f"s{index + 1}",
            order=index,
            description=draft.description,
            intent=draft.intent,
            shot_size=draft.shot_size,
        )
        for index, draft in enumerate(drafts.shots)
    ]
