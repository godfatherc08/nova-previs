"""
Backlog 3.6 (agent half) acceptance: a natural-language instruction produces
a new Shot Spec *version* — version bumped, shot_id pinned, continuity_refs
carried over, untouched fields intact. `chat` is monkeypatched at its
`nova.agent.schema_retry` import site (same convention as
test_cinematographer.py) so no OpenAI credential is needed.
"""

import json

from nova.agent.refine import refine_shot_spec
from nova.models.shot_spec import (
    Camera,
    Framing,
    Grade,
    Lens,
    Lighting,
    ShotSpec,
    Subject,
)

_CURRENT = ShotSpec(
    shot_id="s3",
    version=2,
    intent="reveal the scale of the drone swarm",
    camera=Camera(angle="low", height_m=1.2, movement="slow push-in"),
    lens=Lens(focal_length_mm=18, aperture_f=2.8),
    framing=Framing(shot_size="extreme wide", composition="rule-of-thirds"),
    lighting=Lighting(key="low-key", mood="dramatic shadows", practicals=["drone lights"]),
    grade=Grade(look="desaturated teal", contrast="high"),
    subject=Subject(primary="woman in tattered coat", blocking="walking left-to-right"),
    world=["destroyed buildings", "dense fog"],
    continuity_refs=["s1_frame", "s2_frame"],
)


class _FakeChatResponse:
    def __init__(self, text: str) -> None:
        self.text = text


def _draft_from_current(**overrides) -> dict:
    draft = {
        "intent": _CURRENT.intent,
        "camera": _CURRENT.camera.model_dump(),
        "lens": _CURRENT.lens.model_dump(),
        "framing": _CURRENT.framing.model_dump(),
        "lighting": _CURRENT.lighting.model_dump(),
        "grade": _CURRENT.grade.model_dump(),
        "subject": _CURRENT.subject.model_dump(),
        "world": list(_CURRENT.world),
    }
    draft.update(overrides)
    return draft


def test_refine_bumps_version_and_applies_only_the_change(monkeypatch):
    def fake_chat(*, model, system, prompt, response_format):
        # The model sees the current spec and the instruction.
        assert "Refinement instruction: make the fog denser" in prompt
        assert '"shot_id": "s3"' in prompt or '"shot_id":"s3"' in prompt
        return _FakeChatResponse(
            json.dumps(
                _draft_from_current(
                    world=["destroyed buildings", "dense rolling fog banks"]
                )
            )
        )

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    refined = refine_shot_spec(_CURRENT, "make the fog denser", scene_text="ruined city")

    assert refined.shot_id == "s3"
    assert refined.version == 3
    assert refined.world == ["destroyed buildings", "dense rolling fog banks"]
    # Untouched fields survive byte-identical.
    assert refined.camera == _CURRENT.camera
    assert refined.lens == _CURRENT.lens
    assert refined.grade == _CURRENT.grade
    # Refs to locked prior shots carry over — a refine doesn't change which
    # shots this one must stay consistent with.
    assert refined.continuity_refs == ["s1_frame", "s2_frame"]


def test_refine_can_change_shot_size(monkeypatch):
    def fake_chat(*, model, system, prompt, response_format):
        return _FakeChatResponse(
            json.dumps(
                _draft_from_current(
                    framing={"shot_size": "close-up", "composition": "centered on her face"}
                )
            )
        )

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    refined = refine_shot_spec(_CURRENT, "push in to a close-up on her face")

    assert refined.framing.shot_size == "close-up"
    assert refined.version == 3
