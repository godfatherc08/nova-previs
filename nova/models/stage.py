"""
The shared pipeline-stage contract (CLAUDE.md "Pipeline stage interface").

Every stage — image (backlog 3.x), animatic (6.1), audio (6.3) — returns a
``StageResult`` with the same shape, so orchestration code never has to
special-case per stage. Callers must check ``status`` before touching
``assets``: on failure ``assets`` is empty, and in the fan-out/multi-take
case (backlog 8.6) some parallel branches can fail while others succeed.

``Asset`` here is genblaze-core's own ``Asset`` model, re-exported rather
than re-declared — the pipeline already returns those, and a parallel Nova
copy would be a second source of truth for ``sha256``/``url``/``media_type``
that the provenance manifest (backlog 4.2) depends on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from genblaze_core.models.asset import Asset

__all__ = ["Asset", "StageResult"]


@dataclass(frozen=True)
class StageResult:
    """Outcome of one pipeline stage for one shot."""

    status: Literal["succeeded", "failed"]
    assets: list[Asset] = field(default_factory=list)
    # B2 key of the Genblaze-written provenance manifest. None when no sink
    # was attached (local/offline runs) or when the stage failed before the
    # sink wrote anything.
    manifest_key: str | None = None
    error: str | None = None
    # The prompt actually sent to the provider. Kept on the result because
    # the refine loop (backlog 3.6) diffs successive prompts, and the
    # manifest (4.2) records what produced the frame.
    prompt: str | None = None
    # Provider + model that actually served the request. With a fallback
    # chain (backlog 3.3) this is not knowable up front — it's whichever
    # model in the chain succeeded.
    provider: str | None = None
    model: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"
