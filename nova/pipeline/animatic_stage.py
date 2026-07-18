"""
Backlog 6.1/6.2/6.5: the Genblaze video stage — locked frame + Shot Spec in,
motion clip out.

The locked frame is the whole point of the state machine: the animatic is
generated *from* the exact immutable frame the user approved, passed to the
video provider as its image input (``external_inputs`` -> the provider's
image slot: Runway routes it to ``prompt_image``, Luma to keyframe
``frame0`` — both verified in the installed adapters' ``input_mapping``).
The prompt carries only the Shot Spec's temporal fields
(``build_motion_prompt``), so the model animates the approved frame instead
of re-imagining the shot.

Provider chain (6.2): Runway ``gen4_turbo`` primary, Luma ``ray-2``
fallback, and optionally GMI Cloud's video queue as a draft tier when
``GMI_VIDEO_MODEL`` is set (their registry passes unknown slugs through to
the queue, so the exact draft model is deployment config, not code).
Cross-provider switching is Nova glue (see ``_runner.py``), not a Genblaze
feature.

This stage is normally invoked by the lock webhook / polling fallback
(backlog 5.2/5.3) via ``pipeline/advance.py`` — it has no idea a webhook
exists, per CLAUDE.md: Genblaze neither consumes nor emits B2 Event
Notifications.
"""

from __future__ import annotations

import os

from genblaze_core import Modality
from genblaze_core.models.asset import Asset
from genblaze_core.sinks.base import BaseSink

from nova.agent.compiler import build_motion_prompt
from nova.models.shot_spec import ShotSpec
from nova.models.stage import StageResult
from nova.pipeline._runner import StepPlan, run_with_fallback

_PIPELINE_NAME = "nova-animatic-stage"

RUNWAY_MODEL = "gen4_turbo"
LUMA_MODEL = "ray-2"

# Previs animatics are short by design: enough to read the camera move.
CLIP_DURATION_SEC = 5


class AnimaticStage:
    """Runs one locked shot through the Genblaze video pipeline.

    Args:
        plans: Ordered provider attempts. Defaults to the production chain
            (Runway -> Luma [-> GMI draft]); injectable so tests drive a real
            Pipeline with MockVideoProvider and so a draft tier can be
            forced first for cheap iterations.
    """

    def __init__(self, plans: list[StepPlan] | None = None) -> None:
        self._plans = plans

    def _default_plans(self) -> list[StepPlan]:
        from genblaze_luma import LumaProvider
        from genblaze_runway import RunwayProvider

        plans = [
            # Runway's gen4 family takes duration + ratio (verified against
            # genblaze_runway's submit(): it forwards duration/ratio/seed/
            # watermark/prompt_image).
            StepPlan(RunwayProvider(), RUNWAY_MODEL, {"duration": CLIP_DURATION_SEC, "ratio": "1280:720"}),
            StepPlan(LumaProvider(), LUMA_MODEL, {"aspect_ratio": "16:9"}),
        ]
        gmi_model = os.environ.get("GMI_VIDEO_MODEL")
        if gmi_model:
            from genblaze_gmicloud import GMICloudVideoProvider

            plans.append(StepPlan(GMICloudVideoProvider(), gmi_model, {}))
        return plans

    def run(
        self,
        shot_spec: ShotSpec,
        locked_frame: Asset,
        sink: BaseSink | None = None,
        *,
        project_id: str | None = None,
    ) -> StageResult:
        """Generate the animatic clip for a locked shot.

        ``locked_frame``'s URL must be reachable by the provider — for live
        runs that means a presigned B2 URL (the bucket is private), which
        ``pipeline/advance.py`` produces; tests pass file/mock URLs.
        """
        return run_with_fallback(
            self._plans or self._default_plans(),
            pipeline_name=_PIPELINE_NAME,
            prompt=build_motion_prompt(shot_spec),
            modality=Modality.VIDEO,
            external_inputs=[locked_frame],
            sink=sink,
            project_id=project_id,
        )
