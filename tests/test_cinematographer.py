"""
Backlog 2.4 acceptance criteria: given a shot list, each shot gets a valid
Shot Spec matching the schema locked in backlog 1.1. `genblaze_openai.chat`
(called via the shared `schema_retry.chat_for_schema` helper, backlog 2.5)
is monkeypatched at its `nova.agent.schema_retry` import site so this runs
without an OpenAI credential or network access.
"""

import json

from nova.agent.cinematographer import generate_shot_spec, generate_shot_specs
from nova.models.shot_list import ShotListItem
from nova.models.shot_spec import ShotSpec

_DRAFT_PAYLOAD = {
    "camera": {"angle": "low", "height_m": 1.2, "movement": "slow push-in"},
    "lens": {"focal_length_mm": 18, "aperture_f": 2.8},
    "composition": "rule-of-thirds, subject lower-left",
    "lighting": {"key": "low-key", "mood": "dramatic shadows", "practicals": ["drone lights"]},
    "grade": {"look": "desaturated teal", "contrast": "high"},
    "subject": {"primary": "woman in tattered coat", "blocking": "walking left-to-right, foreground"},
    "world": ["destroyed buildings", "dumped cars", "airborne drones", "dense fog"],
}

_SHOT = ShotListItem(
    shot_id="s3",
    order=2,
    description="Low-angle wide on the woman as drones swarm overhead.",
    intent="reveal the scale of the drone swarm above the ruined skyline",
    shot_size="extreme wide",
)


class _FakeChatResponse:
    def __init__(self, text: str) -> None:
        self.text = text


def test_generate_shot_spec_produces_schema_valid_spec(monkeypatch):
    def fake_chat(*, model, system, prompt, response_format):
        assert model
        assert "extreme wide" in prompt
        assert response_format is not None
        return _FakeChatResponse(json.dumps(_DRAFT_PAYLOAD))

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    spec = generate_shot_spec(
        _SHOT,
        scene_text="A woman walks through a ruined city as drones circle overhead.",
    )

    assert isinstance(spec, ShotSpec)
    assert spec.shot_id == "s3"
    assert spec.version == 1
    assert spec.intent == _SHOT.intent
    # shot_size is carried over from the shot-list entry, not left to the model.
    assert spec.framing.shot_size == "extreme wide"
    assert spec.framing.composition == _DRAFT_PAYLOAD["composition"]
    assert spec.camera.angle == "low"
    assert spec.continuity_refs == []


def test_generate_shot_spec_defaults_intent_to_description_when_blank(monkeypatch):
    def fake_chat(**_kwargs):
        return _FakeChatResponse(json.dumps(_DRAFT_PAYLOAD))

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    blank_intent_shot = ShotListItem(
        shot_id="s1", order=0, description="Wide establishing shot.", shot_size="wide"
    )
    spec = generate_shot_spec(blank_intent_shot, scene_text="A scene.")
    assert spec.intent == "Wide establishing shot."


def test_generate_shot_specs_covers_every_shot_in_order(monkeypatch):
    def fake_chat(**_kwargs):
        return _FakeChatResponse(json.dumps(_DRAFT_PAYLOAD))

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    shot_list = [
        ShotListItem(shot_id="s1", order=0, description="Wide.", intent="establish", shot_size="wide"),
        ShotListItem(shot_id="s2", order=1, description="Medium.", intent="introduce", shot_size="medium"),
    ]
    specs = generate_shot_specs(shot_list, scene_text="A scene.")

    assert [s.shot_id for s in specs] == ["s1", "s2"]
    assert all(isinstance(s, ShotSpec) for s in specs)


def test_generate_shot_spec_recovers_from_one_malformed_response(monkeypatch):
    """Backlog 2.5: a schema-invalid first response retries and recovers
    instead of crashing the caller."""
    calls = {"count": 0}

    def fake_chat(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            # Missing every required field.
            return _FakeChatResponse("{}")
        return _FakeChatResponse(json.dumps(_DRAFT_PAYLOAD))

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    spec = generate_shot_spec(_SHOT, scene_text="A scene.")

    assert calls["count"] == 2
    assert isinstance(spec, ShotSpec)
    assert spec.camera.angle == "low"
