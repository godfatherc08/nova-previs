"""
Backlog 3.1: the Genblaze image stage — Shot Spec in, generated still out.

Three pieces, each owning one concern:

  * ``agent/compiler.py``  — Shot Spec -> prompt + params (the translation)
  * ``providers/gemini_image.py`` — the nano-banana provider (the wire call)
  * this file — the Genblaze ``Pipeline`` that runs it and normalizes the
    outcome into a ``StageResult`` (the orchestration)

The stage never raises on a provider failure. ``Pipeline.run(...)`` is called
with ``raise_on_failure=False`` and the failed run is translated into
``StageResult(status="failed", error=...)``, because a failed shot is a
*normal* state in this product — the UI renders it as a retryable error card
(backlog 1.6 / 9.3) and the fan-out case (8.6) expects some branches to fail
while others succeed. Genuine programming errors (a spec that won't compile)
still raise.

``raise_on_failure`` is passed explicitly rather than left to default: in
genblaze-core 0.3.x omitting it emits a ``DeprecationWarning`` and the
default flips to ``True`` in 0.4.0, so relying on the default would silently
change this stage's contract on a version bump.

``refine(...)`` (backlog 3.6) is a separate method, not a flag on ``run()``
— CLAUDE.md is explicit that the prompt construction differs (edit-in-place
vs generate-from-scratch), and the compile path differs accordingly
(``compile_refine`` vs ``compile_shot``).

Fallback (backlog 3.3) — what's native vs. Nova glue, verified by reading
genblaze_core 0.3.4 ``pipeline/pipeline.py`` directly:

  * NATIVE: ``Pipeline.step(fallback_models=[...])`` retries the *same
    provider* with alternate model slugs, and only on ``MODEL_ERROR``
    (``_try_fallback_models``). Useful for e.g. a renamed Gemini slug.
  * NOT native: switching to a *different provider* (nano-banana ->
    gpt-image-1 -> Flux) on any failure. That chain is Nova's own loop in
    ``run()``/``refine()`` below. Each link is still a real Genblaze
    ``Pipeline`` run, so per-attempt manifests/sinks behave identically —
    but the chain itself must not be described as a Genblaze feature.

Writing frames to B2 under Nova's own key layout is backlog 3.5, done by
the API layer via ``storage/keys.py``; see the note on ``sink`` below.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from genblaze_core import Modality, Pipeline
from genblaze_core.models.asset import Asset
from genblaze_core.sinks.base import BaseSink

from nova.agent.compiler import CompileTarget, compile_refine, compile_shot
from nova.models.shot_spec import ShotSpec
from nova.models.stage import StageResult
from nova.providers.gemini_image import NANO_BANANA_MODEL, NanoBananaProvider

_PIPELINE_NAME = "nova-image-stage"


def fetch_reference_assets(reference_keys: list[str]) -> list[Asset]:
    """Backlog 3.4: fetch prior locked frames from B2 as input ``Asset``s.

    The compiler resolves ``continuity_refs`` to full B2 keys; this pulls
    each frame's bytes down (the bucket is private, so no URL form works
    anonymously) into a temp file and wraps it in a ``file://`` Asset —
    the shape ``NanoBananaProvider._read_asset_bytes`` consumes. Hashes are
    set from the bytes so the reference chain lands in provenance manifests
    with real digests, not blank ones.
    """
    from nova.storage.b2_client import get_bytes

    import os

    assets: list[Asset] = []
    for key in reference_keys:
        data = get_bytes(key)
        fd, tmp = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        out = Path(tmp)
        out.write_bytes(data)
        asset = Asset(url=out.resolve().as_uri(), media_type="image/png", size_bytes=len(data))
        asset.set_hash(data)
        assets.append(asset)
    return assets


class ImageStage:
    """Runs one Shot Spec through the Genblaze image pipeline.

    Args:
        provider: The Genblaze provider to generate with. Defaults to
            nano-banana (backlog 3.2). Injectable so tests can drive a real
            ``Pipeline`` with ``genblaze_core.testing.MockProvider`` and so
            backlog 3.3 can swap in the fallback chain.
        model: Model slug. Defaults to ``gemini-2.5-flash-image``.
        target: Which provider's params the compiler should emit.
    """

    def __init__(
        self,
        provider=None,
        *,
        model: str = NANO_BANANA_MODEL,
        target: CompileTarget = "nano-banana",
        fallbacks: list["ImageStage"] | None = None,
        fallback_models: list[str] | None = None,
    ) -> None:
        self._provider = provider if provider is not None else NanoBananaProvider()
        self._model = model
        self._target = target
        # Cross-provider chain — Nova glue, not a Genblaze feature (see
        # module docstring). Each entry is a fully-configured stage so the
        # compiler re-targets params per provider.
        self._fallbacks = fallbacks or []
        # Same-provider alternate slugs — this one IS native genblaze
        # (Pipeline.step(fallback_models=...), fires on MODEL_ERROR).
        self._fallback_models = fallback_models or []

    def run(
        self,
        shot_spec: ShotSpec,
        sink: BaseSink | None = None,
        *,
        project_id: str | None = None,
        reference_assets: list[Asset] | None = None,
    ) -> StageResult:
        """Generate the storyboard still for ``shot_spec``.

        Args:
            sink: Optional Genblaze sink. When an ``ObjectStorageSink`` is
                passed, Genblaze writes the assets *and* the SHA-256
                provenance manifest to B2 natively — but under the *sink's*
                key layout (``KeyStrategy``), not Nova's
                ``projects/{id}/shots/{id}/frames/v{n}.png``. The sink cannot
                be pointed at an arbitrary per-asset key; that's a real
                constraint of ``ObjectStorageSink``, verified by reading its
                source. Writing frames to Nova's canonical layout is a
                separate explicit put through ``storage/keys.py``
                (backlog 3.5). Note the sink is spent after a run — construct
                a fresh one per call.
            reference_assets: Prior locked frames to condition on, for
                cross-shot continuity (backlog 3.4 — fetch them with
                ``fetch_reference_assets``). Passed straight through to the
                provider as ``external_inputs``.
        """
        result = self._run_once(
            compile_shot(shot_spec, project_id=project_id, target=self._target),
            sink=sink,
            project_id=project_id,
            reference_assets=reference_assets,
        )
        if result.succeeded or not self._fallbacks:
            return result
        return self._run_fallbacks(
            result,
            shot_spec,
            sink=sink,
            project_id=project_id,
            reference_assets=reference_assets,
        )

    def refine(
        self,
        shot_spec: ShotSpec,
        prior_frame: Asset,
        *,
        instruction: str,
        sink: BaseSink | None = None,
        project_id: str | None = None,
        reference_assets: list[Asset] | None = None,
    ) -> StageResult:
        """Backlog 3.6: regenerate by *editing* the prior version's frame.

        ``prior_frame`` leads the input list so the model anchors on it as
        the image being edited; continuity references follow. Compilation
        goes through ``compile_refine`` (edit-in-place prompt), never
        ``compile_shot`` — see module docstring.
        """
        inputs = [prior_frame, *(reference_assets or [])]
        result = self._run_once(
            compile_refine(
                shot_spec, instruction, project_id=project_id, target=self._target
            ),
            sink=sink,
            project_id=project_id,
            reference_assets=inputs,
        )
        if result.succeeded or not self._fallbacks:
            return result
        # Fallback for refine re-runs the same edit compile on the next
        # provider — the instruction semantics must survive the switch, so
        # each fallback stage re-compiles with its own target.
        last = result
        errors = [f"{self._provider.name}/{self._model}: {result.error}"]
        for stage in self._fallbacks:
            attempt = stage._run_once(
                compile_refine(
                    shot_spec, instruction, project_id=project_id, target=stage._target
                ),
                sink=sink,
                project_id=project_id,
                reference_assets=inputs,
            )
            if attempt.succeeded:
                return attempt
            errors.append(f"{stage._provider.name}/{stage._model}: {attempt.error}")
            last = attempt
        return StageResult(
            status="failed",
            assets=[],
            manifest_key=last.manifest_key,
            error="all providers in the fallback chain failed: " + "; ".join(errors),
            prompt=last.prompt,
            provider=last.provider,
            model=last.model,
        )

    def _run_fallbacks(
        self,
        primary_result: StageResult,
        shot_spec: ShotSpec,
        *,
        sink: BaseSink | None,
        project_id: str | None,
        reference_assets: list[Asset] | None,
    ) -> StageResult:
        last = primary_result
        errors = [f"{self._provider.name}/{self._model}: {primary_result.error}"]
        for stage in self._fallbacks:
            attempt = stage._run_once(
                compile_shot(shot_spec, project_id=project_id, target=stage._target),
                sink=sink,
                project_id=project_id,
                reference_assets=reference_assets,
            )
            if attempt.succeeded:
                return attempt
            errors.append(f"{stage._provider.name}/{stage._model}: {attempt.error}")
            last = attempt
        return StageResult(
            status="failed",
            assets=[],
            manifest_key=last.manifest_key,
            error="all providers in the fallback chain failed: " + "; ".join(errors),
            prompt=last.prompt,
            provider=last.provider,
            model=last.model,
        )

    def _run_once(
        self,
        compiled,
        *,
        sink: BaseSink | None,
        project_id: str | None,
        reference_assets: list[Asset] | None,
    ) -> StageResult:
        pipeline = Pipeline(_PIPELINE_NAME, project_id=project_id)
        pipeline.step(
            self._provider,
            model=self._model,
            prompt=compiled.prompt,
            modality=Modality.IMAGE,
            fallback_models=self._fallback_models or None,
            external_inputs=reference_assets or None,
            **compiled.params,
        )

        result = pipeline.run(sink=sink, raise_on_failure=False)

        manifest_key = None
        if sink is not None and hasattr(sink, "manifest_key_for"):
            manifest_key = sink.manifest_key_for(result.run)

        failed = result.failed_steps()
        if failed or not result.run.steps:
            return StageResult(
                status="failed",
                assets=[],
                manifest_key=manifest_key,
                error=result.error_summary() or "image stage produced no step",
                prompt=compiled.prompt,
                provider=self._provider.name,
                model=self._model,
            )

        step = result.run.steps[0]
        if not step.assets:
            # A step can complete without emitting an asset (e.g. a provider
            # that swallows a safety block). Treat that as a failure rather
            # than handing the caller an empty success — an assetless
            # "succeeded" would otherwise be lockable downstream.
            return StageResult(
                status="failed",
                assets=[],
                manifest_key=manifest_key,
                error="image stage succeeded but returned no image asset",
                prompt=compiled.prompt,
                provider=self._provider.name,
                model=step.model,
            )

        return StageResult(
            status="succeeded",
            assets=list(step.assets),
            manifest_key=manifest_key,
            prompt=compiled.prompt,
            provider=step.provider or self._provider.name,
            # Read back off the step, not off self: with a fallback chain
            # (backlog 3.3) the model that actually served the request is not
            # the one we asked for.
            model=step.model,
        )


def default_image_stage() -> ImageStage:
    """The production chain (backlog 3.2 + 3.3): nano-banana primary,
    gpt-image-1 then Flux (GMI Cloud draft tier) as cross-provider fallbacks.

    Providers are constructed lazily w.r.t. credentials — each reads its API
    key env var (GEMINI_API_KEY / OPENAI_API_KEY / GMI_API_KEY) at first
    call, not at construction, so building the chain never requires keys
    (verified against each installed provider's ``__init__``). The Flux slug
    is env-overridable because GMI Cloud's registry is deliberately
    permissive (unknown slugs pass through to their queue) and their model
    lineup moves faster than a hardcoded default.
    """
    import os

    from genblaze_gmicloud import GMICloudImageProvider
    from genblaze_openai import DalleProvider

    return ImageStage(
        NanoBananaProvider(),
        model=NANO_BANANA_MODEL,
        target="nano-banana",
        fallbacks=[
            ImageStage(DalleProvider(), model="gpt-image-1", target="gpt-image-1"),
            ImageStage(
                GMICloudImageProvider(),
                model=os.environ.get("GMI_FLUX_MODEL", "FLUX.1-Kontext-dev"),
                target="flux",
            ),
        ],
    )
