"""
Backlog 6.3: Stability Audio (ambient/score) as a **Nova-built Genblaze
provider adapter** — flagged per CLAUDE.md's verify-SDK-claims rule:

    There is NO ``genblaze-stability`` package. Verified directly:
    ``pip index versions genblaze-stability`` -> "No matching distribution
    found" (checked 2026-07-17). Every other provider in Nova's stack has a
    first-party Genblaze adapter; this one does not, so Nova implements the
    same public ``SyncProvider`` extension point its nano-banana adapter
    uses (``providers/gemini_image.py``), and the adapter is a first-class
    pipeline citizen: assets get real hashes, errors map into Genblaze's
    retry taxonomy, and it slots into the same Nova fallback chain.

Wire call: Stability's ``v2beta`` text-to-audio REST endpoint
(https://platform.stability.ai/docs/api-reference — stable-audio-2
text-to-audio). This endpoint shape is taken from Stability's public API
docs; it has not been exercised live yet because backlog 0.6 (provider API
keys) is still open. The live smoke test in
``tests/test_stability_audio_provider.py`` is marked ``live`` and skips
without ``STABILITY_API_KEY``, same convention as the nano-banana live test.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from genblaze_core.exceptions import ProviderError
from genblaze_core.models.asset import Asset, AudioMetadata
from genblaze_core.models.enums import Modality, ProviderErrorCode
from genblaze_core.models.step import Step
from genblaze_core.providers import (
    ModelRegistry,
    ModelSpec,
    ProviderCapabilities,
    SyncProvider,
)
from genblaze_core.runnable.config import RunnableConfig

STABLE_AUDIO_MODEL = "stable-audio-2"

_API_URL_TEMPLATE = "https://api.stability.ai/v2beta/audio/{model}/text-to-audio"

# Permissive fallback, same posture as the nano-banana adapter: Stability
# ships new audio slugs faster than a hardcoded list survives.
_FALLBACK_SPEC = ModelSpec(model_id="*", modality=Modality.AUDIO)


def _map_status(status_code: int, text: str) -> ProviderErrorCode:
    if status_code == 429:
        return ProviderErrorCode.RATE_LIMIT
    if status_code in (401, 403):
        return ProviderErrorCode.AUTH_FAILURE
    if status_code == 400:
        return ProviderErrorCode.INVALID_INPUT
    if status_code >= 500:
        return ProviderErrorCode.SERVER_ERROR
    lowered = text.lower()
    if "moderation" in lowered or "flagged" in lowered:
        return ProviderErrorCode.CONTENT_POLICY
    return ProviderErrorCode.UNKNOWN


class StabilityAudioProvider(SyncProvider):
    """Genblaze provider adapter for Stability's stable-audio text-to-audio.

    Args:
        api_key: Stability API key. Falls back to the ``STABILITY_API_KEY``
            env var at call time — constructing the provider never requires
            a credential (matches every other provider in Nova's chain).
        output_dir: Where generated MP3s land; temp files by default.
    """

    name = "stability-audio"

    @classmethod
    def create_registry(cls) -> ModelRegistry:
        return ModelRegistry(fallback=_FALLBACK_SPEC)

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.AUDIO],
            supported_inputs=["text"],
            accepts_chain_input=False,
            max_duration=190.0,
            models=[STABLE_AUDIO_MODEL],
            output_formats=["audio/mpeg"],
        )

    def __init__(
        self,
        api_key: str | None = None,
        *,
        output_dir: str | Path | None = None,
        http_timeout: float = 120.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._api_key = api_key
        self._output_dir = Path(output_dir) if output_dir else None
        self._http_timeout = http_timeout

    def _resolve_key(self) -> str:
        key = self._api_key or os.environ.get("STABILITY_API_KEY")
        if not key:
            raise ProviderError(
                "No Stability API key. Set STABILITY_API_KEY or pass api_key=.",
                error_code=ProviderErrorCode.AUTH_FAILURE,
            )
        return key

    def generate(self, step: Step, config: RunnableConfig | None = None) -> Step:
        import requests

        payload = self.prepare_payload(step)
        data: dict[str, Any] = {
            "prompt": payload.get("prompt", step.prompt or ""),
            "output_format": "mp3",
        }
        duration = payload.get("duration_seconds")
        if duration is not None:
            data["duration"] = float(duration)
        if payload.get("seed") is not None:
            data["seed"] = int(payload["seed"])

        try:
            response = requests.post(
                _API_URL_TEMPLATE.format(model=step.model),
                headers={
                    "authorization": f"Bearer {self._resolve_key()}",
                    "accept": "audio/*",
                },
                # v2beta endpoints take multipart form fields, not JSON.
                files={key: (None, str(value)) for key, value in data.items()},
                timeout=self._http_timeout,
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"stable-audio request failed: {exc}",
                error_code=ProviderErrorCode.TIMEOUT
                if "timed out" in str(exc).lower()
                else ProviderErrorCode.UNKNOWN,
            ) from exc

        if response.status_code != 200:
            raise ProviderError(
                f"stable-audio returned {response.status_code}: {response.text[:500]}",
                error_code=_map_status(response.status_code, response.text),
            )

        audio_bytes = response.content
        if not audio_bytes:
            raise ProviderError(
                "stable-audio returned an empty body",
                error_code=ProviderErrorCode.SERVER_ERROR,
            )

        if self._output_dir:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            out_path = self._output_dir / f"{step.step_id}.mp3"
        else:
            fd, tmp = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            out_path = Path(tmp)
        out_path.write_bytes(audio_bytes)

        asset = Asset(
            url=out_path.resolve().as_uri(),
            media_type="audio/mpeg",
            size_bytes=len(audio_bytes),
        )
        # Hash while the bytes are in hand — provenance manifests (4.2)
        # recompute this independently, same rationale as the nano-banana
        # adapter.
        asset.set_hash(audio_bytes)
        if duration is not None:
            # Duration lives on Asset itself (genblaze_core Asset.duration),
            # not on AudioMetadata — verified against models/asset.py.
            asset.duration = float(duration)
        asset.audio = AudioMetadata(codec="mp3")
        step.assets.append(asset)

        self._apply_registry_pricing(step)
        return step
