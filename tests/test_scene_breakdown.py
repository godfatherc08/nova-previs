"""
Backlog 2.1 acceptance criteria: given a sample scene, the agent returns a
coherent ordered shot list. `genblaze_openai.chat` (called via the shared
`schema_retry.chat_for_schema` helper, backlog 2.5) is monkeypatched at its
`nova.agent.schema_retry` import site so this runs without an OpenAI
credential or network access, matching the skip-if-no-creds spirit used
elsewhere in this repo for external calls.
"""

import json

from nova.agent.scene_breakdown import break_down_scene
from nova.models.shot_list import ShotListItem


class _FakeChatResponse:
    def __init__(self, text: str) -> None:
        self.text = text


def test_break_down_scene_assigns_ids_and_order(monkeypatch):
    payload = {
        "shots": [
            {
                "description": "Wide establishing shot of the ruined skyline.",
                "intent": "establish scale and setting",
                "shot_size": "extreme wide",
            },
            {
                "description": "Medium shot on the woman walking through rubble.",
                "intent": "introduce the protagonist",
                "shot_size": "medium",
            },
            {
                "description": "Low-angle insert on the drones overhead.",
                "intent": "reveal the threat",
                "shot_size": "insert",
            },
        ]
    }

    def fake_chat(*, model, system, prompt, response_format):
        assert model
        assert system
        assert prompt == "A woman walks through a ruined city as drones circle overhead."
        assert response_format is not None
        return _FakeChatResponse(json.dumps(payload))

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    result = break_down_scene(
        "A woman walks through a ruined city as drones circle overhead."
    )

    assert [item.shot_id for item in result] == ["s1", "s2", "s3"]
    assert [item.order for item in result] == [0, 1, 2]
    assert all(isinstance(item, ShotListItem) for item in result)
    assert result[0].shot_size == "extreme wide"
    assert result[2].description.startswith("Low-angle insert")


def test_break_down_scene_propagates_non_retryable_errors(monkeypatch):
    """Only ProviderError/ValidationError are retried (schema_retry.py);
    anything else is a bug, not a flaky agent call, and propagates as-is."""

    def fake_chat(**_kwargs):
        raise RuntimeError("upstream provider failed")

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    try:
        break_down_scene("anything")
    except RuntimeError as exc:
        assert "upstream provider failed" in str(exc)
    else:
        raise AssertionError("expected break_down_scene to propagate the non-retryable error")
