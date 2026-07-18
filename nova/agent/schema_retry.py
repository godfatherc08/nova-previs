"""
Backlog 2.5: shared retry helper for LLM calls that must return schema-valid
structured output (Risk mitigation). Both scene_breakdown.py (backlog 2.1)
and cinematographer.py (backlog 2.4) call ``genblaze_openai.chat()`` with
``response_format=<pydantic model>`` and hit the same two failure modes: the
provider call itself fails (``ProviderError`` — rate limit, timeout, etc.),
or the model returns text that doesn't parse/validate against the schema
(malformed JSON, a hallucinated enum value, a missing field). Neither is a
reason to fail the whole request outright — both are common enough LLM
failure modes to retry a bounded number of times before giving up.

On a schema/parse failure, the validation error is fed back into the system
prompt for the retry so the model has a shot at self-correcting instead of
blindly repeating the same mistake. On a provider error, the retry reuses
the original prompt unchanged since there's nothing to "fix" in the request.
"""

from __future__ import annotations

from typing import TypeVar

from genblaze_core.exceptions import ProviderError
from genblaze_openai import chat
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class AgentOutputError(RuntimeError):
    """Agent output still failed schema validation after every retry attempt."""


def chat_for_schema(
    *,
    model: str,
    system: str,
    prompt: str,
    response_model: type[T],
    max_attempts: int = 3,
) -> T:
    """Call ``chat()`` and validate the response against ``response_model``,
    retrying on a provider error or a schema/parse failure.

    Returns the validated instance on success. Raises ``AgentOutputError``
    (chaining the last underlying error) if every attempt fails — this never
    lets a malformed response propagate as an unhandled parse/validation
    exception.
    """
    retry_system = system
    last_error: Exception | None = None

    for _attempt in range(max_attempts):
        try:
            response = chat(
                model=model,
                system=retry_system,
                prompt=prompt,
                response_format=response_model,
            )
            return response_model.model_validate_json(response.text)
        except ProviderError as exc:
            last_error = exc
        except ValidationError as exc:
            last_error = exc
            retry_system = (
                f"{system}\n\nYour previous response failed schema validation "
                f"with this error — return corrected JSON only, matching the "
                f"schema exactly:\n{exc}"
            )

    raise AgentOutputError(
        f"agent output failed schema validation after {max_attempts} attempts: {last_error}"
    ) from last_error
