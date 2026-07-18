"""
Shared single-step pipeline execution for the animatic (6.1) and audio (6.3)
stages — one Genblaze ``Pipeline`` run normalized into a ``StageResult``,
plus the Nova cross-provider fallback loop (6.5).

Same posture as image_stage.py (which predates this helper and keeps its own
copy): ``raise_on_failure=False`` explicitly, assetless success treated as
failure, and the honest split between what's native and what's Nova glue —
genblaze's ``fallback_models`` is same-provider/MODEL_ERROR-only, so the
provider-to-provider chain here is Nova's own loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from genblaze_core import Modality, Pipeline
from genblaze_core.models.asset import Asset
from genblaze_core.sinks.base import BaseSink

from nova.models.stage import StageResult


@dataclass
class StepPlan:
    """One provider attempt: who to call and with what."""

    provider: object
    model: str
    params: dict = field(default_factory=dict)


def run_step(
    plan: StepPlan,
    *,
    pipeline_name: str,
    prompt: str,
    modality: Modality,
    external_inputs: list[Asset] | None = None,
    sink: BaseSink | None = None,
    project_id: str | None = None,
) -> StageResult:
    pipeline = Pipeline(pipeline_name, project_id=project_id)
    pipeline.step(
        plan.provider,
        model=plan.model,
        prompt=prompt,
        modality=modality,
        external_inputs=external_inputs or None,
        **plan.params,
    )
    result = pipeline.run(sink=sink, raise_on_failure=False)

    manifest_key = None
    if sink is not None and hasattr(sink, "manifest_key_for"):
        manifest_key = sink.manifest_key_for(result.run)

    provider_name = getattr(plan.provider, "name", "unknown")
    if result.failed_steps() or not result.run.steps:
        return StageResult(
            status="failed",
            assets=[],
            manifest_key=manifest_key,
            error=result.error_summary() or f"{pipeline_name} produced no step",
            prompt=prompt,
            provider=provider_name,
            model=plan.model,
        )

    step = result.run.steps[0]
    if not step.assets:
        return StageResult(
            status="failed",
            assets=[],
            manifest_key=manifest_key,
            error=f"{pipeline_name} succeeded but returned no asset",
            prompt=prompt,
            provider=provider_name,
            model=step.model,
        )

    return StageResult(
        status="succeeded",
        assets=list(step.assets),
        manifest_key=manifest_key,
        prompt=prompt,
        provider=step.provider or provider_name,
        model=step.model,
    )


def run_with_fallback(
    plans: list[StepPlan],
    *,
    pipeline_name: str,
    prompt: str,
    modality: Modality,
    external_inputs: list[Asset] | None = None,
    sink: BaseSink | None = None,
    project_id: str | None = None,
) -> StageResult:
    """Try each plan in order; first success wins (backlog 6.5).

    This provider-to-provider chain is Nova glue, not a Genblaze feature —
    see module docstring. Every attempt is still a real Genblaze Pipeline
    run, so sinks/manifests behave identically per attempt.
    """
    if not plans:
        raise ValueError("run_with_fallback requires at least one StepPlan")

    errors: list[str] = []
    last: StageResult | None = None
    for plan in plans:
        attempt = run_step(
            plan,
            pipeline_name=pipeline_name,
            prompt=prompt,
            modality=modality,
            external_inputs=external_inputs,
            sink=sink,
            project_id=project_id,
        )
        if attempt.succeeded:
            return attempt
        errors.append(f"{getattr(plan.provider, 'name', '?')}/{plan.model}: {attempt.error}")
        last = attempt

    assert last is not None
    if len(errors) == 1:
        return last
    return StageResult(
        status="failed",
        assets=[],
        manifest_key=last.manifest_key,
        error="all providers in the fallback chain failed: " + "; ".join(errors),
        prompt=last.prompt,
        provider=last.provider,
        model=last.model,
    )
