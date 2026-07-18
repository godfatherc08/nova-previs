"""
Backlog 6.3/6.5: the Genblaze audio stage — Shot Spec in, scratch ambient
track out.

Primary: Stability's stable-audio-2 via Nova's own adapter
(``providers/stability_audio.py`` — no ``genblaze-stability`` package
exists, see that module's header). Fallback: ElevenLabs' sound-effects
model via the first-party ``genblaze-elevenlabs`` adapter. Both take a text
prompt compiled from the Shot Spec's atmosphere fields
(``build_audio_prompt``); duration matches the animatic clip so assembly
(7.2) can lay the track under the clip without trimming logic.

Cross-provider switching is Nova glue (``_runner.py``), not a Genblaze
feature.
"""

from __future__ import annotations

from genblaze_core import Modality
from genblaze_core.sinks.base import BaseSink

from nova.agent.compiler import build_audio_prompt
from nova.models.shot_spec import ShotSpec
from nova.models.stage import StageResult
from nova.pipeline._runner import StepPlan, run_with_fallback
from nova.pipeline.animatic_stage import CLIP_DURATION_SEC

_PIPELINE_NAME = "nova-audio-stage"

ELEVENLABS_SFX_MODEL = "eleven_text_to_sound_v2"


class AudioStage:
    """Runs one locked shot through the Genblaze audio pipeline."""

    def __init__(self, plans: list[StepPlan] | None = None) -> None:
        self._plans = plans

    def _default_plans(self) -> list[StepPlan]:
        from genblaze_elevenlabs import ElevenLabsSFXProvider

        from nova.providers.stability_audio import STABLE_AUDIO_MODEL, StabilityAudioProvider

        return [
            StepPlan(
                StabilityAudioProvider(),
                STABLE_AUDIO_MODEL,
                {"duration_seconds": CLIP_DURATION_SEC},
            ),
            # ElevenLabs SFX validates duration_seconds 0.5–30 client-side
            # (verified in the installed sfx.py) — 5s is comfortably inside.
            StepPlan(
                ElevenLabsSFXProvider(),
                ELEVENLABS_SFX_MODEL,
                {"duration_seconds": CLIP_DURATION_SEC},
            ),
        ]

    def run(
        self,
        shot_spec: ShotSpec,
        sink: BaseSink | None = None,
        *,
        project_id: str | None = None,
    ) -> StageResult:
        return run_with_fallback(
            self._plans or self._default_plans(),
            pipeline_name=_PIPELINE_NAME,
            prompt=build_audio_prompt(shot_spec),
            modality=Modality.AUDIO,
            sink=sink,
            project_id=project_id,
        )
