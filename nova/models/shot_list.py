"""
Backlog 2.1/2.2/2.3: the shot-list entry — the agent-proposed, user-editable
unit that precedes a full Shot Spec (``shot_spec.py``). One shot-list item
becomes one Shot once backlog 2.4 (per-shot Shot Spec generation) runs.

Shared by ``agent/scene_breakdown.py`` (produces these), ``api/routes.py``
(serves/accepts these), and ``storage/b2_client.py`` (persists these inside
scene.json) — kept in one place so the shape can't drift between callers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from nova.models.shot_spec import ShotSize

_ID_PATTERN = r"^[a-zA-Z0-9_-]+$"


class ShotListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_id: str = Field(pattern=_ID_PATTERN, min_length=1, max_length=64)
    order: int = Field(ge=0)
    description: str = Field(min_length=1, max_length=500)
    intent: str = Field(default="", max_length=500)
    shot_size: ShotSize = "medium"
