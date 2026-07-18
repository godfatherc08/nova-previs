"""
Backlog 2.5 acceptance criteria: an injected malformed test case triggers
retry and recovers without crashing. Covers the shared
`nova.agent.schema_retry.chat_for_schema` helper directly (used by both
scene_breakdown.py and cinematographer.py) rather than through either
call site.
"""

import json

import pytest
from genblaze_core.exceptions import ProviderError
from pydantic import BaseModel, ConfigDict

from nova.agent.schema_retry import AgentOutputError, chat_for_schema


class _Simple(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


class _FakeChatResponse:
    def __init__(self, text: str) -> None:
        self.text = text


def test_recovers_after_one_malformed_json_response(monkeypatch):
    calls = {"count": 0}

    def fake_chat(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return _FakeChatResponse("not valid json")
        return _FakeChatResponse(json.dumps({"value": 42}))

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    result = chat_for_schema(
        model="gpt-4o-mini", system="sys", prompt="prompt", response_model=_Simple
    )

    assert result.value == 42
    assert calls["count"] == 2


def test_feeds_validation_error_back_into_retry_system_prompt(monkeypatch):
    seen_systems = []

    def fake_chat(*, system, **_kwargs):
        seen_systems.append(system)
        if len(seen_systems) == 1:
            return _FakeChatResponse(json.dumps({"value": "not an int"}))
        return _FakeChatResponse(json.dumps({"value": 7}))

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    result = chat_for_schema(
        model="gpt-4o-mini", system="base system", response_model=_Simple, prompt="p"
    )

    assert result.value == 7
    assert seen_systems[0] == "base system"
    assert "base system" in seen_systems[1]
    assert "failed schema validation" in seen_systems[1]


def test_retries_on_provider_error_then_succeeds(monkeypatch):
    calls = {"count": 0}

    def fake_chat(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ProviderError("rate limited")
        return _FakeChatResponse(json.dumps({"value": 1}))

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    result = chat_for_schema(
        model="gpt-4o-mini", system="sys", prompt="prompt", response_model=_Simple
    )

    assert result.value == 1
    assert calls["count"] == 2


def test_raises_agent_output_error_after_exhausting_all_attempts(monkeypatch):
    def fake_chat(**_kwargs):
        return _FakeChatResponse("still not json")

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    with pytest.raises(AgentOutputError):
        chat_for_schema(
            model="gpt-4o-mini",
            system="sys",
            prompt="prompt",
            response_model=_Simple,
            max_attempts=2,
        )


def test_non_retryable_exception_propagates_immediately(monkeypatch):
    calls = {"count": 0}

    def fake_chat(**_kwargs):
        calls["count"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr("nova.agent.schema_retry.chat", fake_chat)

    with pytest.raises(RuntimeError, match="boom"):
        chat_for_schema(
            model="gpt-4o-mini", system="sys", prompt="prompt", response_model=_Simple
        )

    assert calls["count"] == 1
