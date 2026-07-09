"""
Backlog 1.1: the Shot Spec — Nova's model-agnostic cinematographic IR.

Canonical source of truth for the schema (PRD §6). The compiler
(``agent/cinematographer.py`` -> ``agent/compiler.py``), the refine loop,
and the provenance manifest all reference these models directly — do not
let a second copy of this shape drift into existence elsewhere.

Every model uses ``extra="forbid"``: this schema is being *locked* per
backlog 1.1, not left open-ended. If a field is missing, add it here
first rather than letting callers pass ad hoc extras.

Categorical fields (angle, shot size, lighting key, contrast) are closed
enums, not free text — the compiler has to map these deterministically to
provider-specific prompt language, and a closed vocabulary is what makes
that mapping reliable instead of fuzzy string matching. Compositional
fields (movement, composition, mood, look) stay as free text with a
documented vocabulary in each field's description, since they're
naturally combinatorial (e.g. "slow push-in", "fast whip-pan") rather
than drawn from a small closed set. Backlog 2.5 (malformed agent output
-> validation + retry) is what catches the agent missing an enum value.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CameraAngle = Literal[
    "eye-level",
    "low",
    "high",
    "overhead",
    "dutch",
    "worms-eye",
    "over-the-shoulder",
]

ShotSize = Literal[
    "extreme wide",
    "wide",
    "full",
    "medium wide",
    "medium",
    "medium close-up",
    "close-up",
    "extreme close-up",
    "insert",
]

LightingKey = Literal[
    "high-key",
    "low-key",
    "flat",
    "natural",
    "chiaroscuro",
]

Contrast = Literal["low", "medium", "high"]

# Keys embed directly into B2 paths (shots/{shot_id}/...) — must be safe
# as a single path segment, not just a valid JSON string.
_ID_PATTERN = r"^[a-zA-Z0-9_-]+$"
# Matches the PRD §6 convention: continuity_refs point at another shot's
# locked frame by a short reference like "s1_frame", resolved to a full
# B2 key at compile time (CLAUDE.md "Shot Spec schema").
_CONTINUITY_REF_PATTERN = r"^[a-zA-Z0-9_-]+_frame$"


class Camera(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle: CameraAngle
    height_m: float = Field(
        gt=0,
        le=50,
        description="Camera height above ground in meters. Human eye-level ~1.5; "
        "allows up to 50 for drone/aerial shots.",
    )
    movement: str = Field(
        min_length=1,
        max_length=200,
        description="Free text, e.g. 'slow push-in', 'static', 'fast whip-pan left', "
        "'handheld tracking'. Compositional (speed + direction + type), not a closed set.",
    )


class Lens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focal_length_mm: float = Field(ge=8, le=800, description="Real-world lens range: 8mm fisheye to 800mm super-telephoto.")
    aperture_f: float = Field(ge=0.95, le=32, description="f-stop, realistic range across production lenses.")


class Framing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shot_size: ShotSize
    composition: str = Field(
        min_length=1,
        max_length=300,
        description="Free text, e.g. 'rule-of-thirds, subject lower-left'.",
    )


class Lighting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: LightingKey
    mood: str = Field(min_length=1, max_length=200, description="Free text, e.g. 'dramatic shadows'.")
    practicals: list[str] = Field(
        default_factory=list,
        description="Visible in-scene light sources, e.g. ['drone lights', 'neon signage'].",
    )


class Grade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    look: str = Field(min_length=1, max_length=200, description="Free text, e.g. 'desaturated teal'.")
    contrast: Contrast


class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str = Field(min_length=1, max_length=300, description="e.g. 'woman in tattered coat'.")
    blocking: str = Field(min_length=1, max_length=300, description="e.g. 'walking left-to-right, foreground'.")


class ShotSpec(BaseModel):
    """The full per-shot cinematographic IR (PRD §6)."""

    model_config = ConfigDict(extra="forbid")

    shot_id: str = Field(pattern=_ID_PATTERN, min_length=1, max_length=64)
    version: int = Field(default=1, ge=1)
    intent: str = Field(
        min_length=1,
        max_length=500,
        description="Why this shot exists narratively, e.g. 'reveal the scale of the drone swarm'.",
    )
    camera: Camera
    lens: Lens
    framing: Framing
    lighting: Lighting
    grade: Grade
    subject: Subject
    world: list[str] = Field(
        default_factory=list,
        description="Environment/background elements, e.g. ['destroyed buildings', 'dense fog'].",
    )
    continuity_refs: list[str] = Field(
        default_factory=list,
        description="References to prior LOCKED shots' frames in the same scene, e.g. ['s1_frame']. "
        "Resolved to full B2 keys at compile time — see CLAUDE.md continuity_refs note.",
    )

    @field_validator("continuity_refs")
    @classmethod
    def _validate_continuity_ref_format(cls, refs: list[str]) -> list[str]:
        import re

        for ref in refs:
            if not re.match(_CONTINUITY_REF_PATTERN, ref):
                raise ValueError(
                    f"continuity_refs entry {ref!r} must match '<shot_id>_frame' "
                    f"(pattern {_CONTINUITY_REF_PATTERN!r})"
                )
        return refs

    @model_validator(mode="after")
    def _validate_no_self_reference(self) -> ShotSpec:
        self_ref = f"{self.shot_id}_frame"
        if self_ref in self.continuity_refs:
            raise ValueError(f"shot {self.shot_id!r} cannot list itself in continuity_refs ({self_ref!r})")
        return self
