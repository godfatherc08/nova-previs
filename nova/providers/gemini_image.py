"""
Backlog 3.2: Gemini 2.5 Flash Image ("nano-banana") as the primary image
provider — as a **Nova-built Genblaze provider adapter**, not a Genblaze
one.

Flagged loudly per CLAUDE.md's verify-SDK-claims rule, because the obvious
assumption here is wrong and the PRD's provider table implies otherwise:

    `genblaze-google` ships `ImagenProvider`, and it CANNOT serve
    nano-banana.

Verified by reading the installed `genblaze_google` 0.3.1 source directly:

  1. `ImagenProvider.generate()` calls `client.models.generate_images()`
     — the **Imagen** API. nano-banana is a Gemini multimodal model and is
     served over `client.models.generate_content()` with
     `response_modalities=["IMAGE"]`. Different API surface entirely; the
     slug does not work on `generate_images()`.
  2. Its model family (`genblaze_google/_families.py: GOOGLE_IMAGEN_FAMILY`)
     is pattern `^imagen-`, which `gemini-2.5-flash-image` does not match.
     It falls through to the registry's permissive `*` fallback spec, so
     preflight does NOT catch this — it fails at the wire call instead.
  3. `ImagenProvider.get_capabilities()` declares `supported_inputs=["text"]`
     and leaves `accepts_chain_input` at its `False` default — so it takes
     no reference images at all.

(3) is the one that actually forces the issue. CLAUDE.md: passing prior
locked frames as reference images is "the main compensating mechanism for
not having FIBO's native determinism anymore; don't drop it during
refactors." Continuity across shots (backlog 3.4) is only possible on a
provider that accepts image inputs. `ImagenProvider` doesn't, so it could
not be Nova's primary image provider even if the slug worked.

So this adapter implements genblaze-core's *public, documented* extension
point (`SyncProvider` — a top-level export, with `MockProvider` in
`genblaze_core.testing` as the reference implementation). It is a first-class
Genblaze provider: it plugs into `Pipeline.step()`, participates in
`fallback_models` chains, and its assets flow to `ObjectStorageSink` and the
provenance manifest like any other. Nothing here reaches around the SDK.

This is a real gap worth reporting upstream — it's a strong candidate for
backlog 11.5 (file Genblaze SDK feedback issues).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

from genblaze_core.exceptions import ProviderError
from genblaze_core.models.asset import Asset
from genblaze_core.models.enums import Modality, ProviderErrorCode
from genblaze_core.models.step import Step
from genblaze_core.providers import (
    ModelRegistry,
    ModelSpec,
    ProviderCapabilities,
    SyncProvider,
)
from genblaze_core.runnable.config import RunnableConfig

NANO_BANANA_MODEL = "gemini-2.5-flash-image"

# --- _FILE_URI_NOTE ---------------------------------------------------------
# This provider emits ``Path.as_uri()`` (``file:///C:/... `` /
# ``file:///tmp/...``), NOT genblaze-google's ``f"file://{quote(path)}"``.
# The latter is not a valid file URI on Windows: ``quote()`` percent-escapes
# the backslashes and colon, so the drive letter lands in the URL's *netloc*
# and ``urlparse(...).path`` comes back empty. Anything that reads the asset
# back then resolves to the CWD. Verified against a real path on this machine.
#
# Known genblaze-core bug this does NOT fully dodge (worth filing — backlog
# 11.5): ``genblaze_core/storage/transfer.py::_read_local_file`` parses
# file:// URLs as ``Path(unquote(urlparse(url).path))``. On Windows that
# turns a correct ``file:///C:/x/y.png`` into the drive-*relative* path
# ``C:x\y.png`` and raises FileNotFoundError, so ``ObjectStorageSink`` cannot
# upload local assets on Windows regardless of which URI form we emit. The
# fix upstream is one line — use ``urllib.request.url2pathname`` (what this
# module uses) instead of ``Path(unquote(...))``.
#
# Practical impact: asset->B2 transfer through the sink works on Linux (CI,
# deploy) and is broken on a Windows dev box. Frames still generate locally;
# only the sink upload leg is affected, and Nova's canonical frame write
# (backlog 3.5) goes through storage/keys.py + the B2 client directly anyway.
# ---------------------------------------------------------------------------

# Permissive fallback spec: Google ships new Gemini image slugs (and
# -preview / -latest suffixes) faster than a hardcoded list survives, and a
# wrong "unknown model" hard-fail at preflight is worse than a clean 404
# from the API. Same posture genblaze-google itself takes.
_FALLBACK_SPEC = ModelSpec(model_id="*", modality=Modality.IMAGE)

_DEFAULT_MIME = "image/png"


def _map_error(exc: Exception) -> ProviderErrorCode:
    """Classify a google-genai exception into Genblaze's error taxonomy.

    Genblaze's retry layer only retries codes it considers transient (see
    `Step.retryable`), so a misclassification here either wastes retries on
    a permanently bad request or gives up on a transient one. Matching on the
    message is crude but google-genai raises a small number of exception
    types with the status in the text; the cost of being wrong is bounded to
    retry behavior, not correctness.
    """
    text = str(exc).lower()
    if "429" in text or "resource_exhausted" in text or "rate limit" in text or "quota" in text:
        return ProviderErrorCode.RATE_LIMIT
    if "401" in text or "403" in text or "permission" in text or "api key" in text:
        return ProviderErrorCode.AUTH_FAILURE
    if "safety" in text or "blocked" in text or "prohibited" in text:
        return ProviderErrorCode.CONTENT_POLICY
    if "400" in text or "invalid" in text:
        return ProviderErrorCode.INVALID_INPUT
    if "deadline" in text or "timeout" in text:
        return ProviderErrorCode.TIMEOUT
    if "500" in text or "503" in text or "internal" in text or "unavailable" in text:
        return ProviderErrorCode.SERVER_ERROR
    return ProviderErrorCode.UNKNOWN


def _read_asset_bytes(asset: Asset) -> bytes:
    """Load an input asset's bytes for use as a reference image.

    Handles the two URL flavors Nova actually produces: `file://` (what this
    provider emits, so a chained step can consume a prior step's output) and
    `http(s)://` (a durable B2 URL for a prior locked frame, backlog 3.4).
    """
    parsed = urlparse(asset.url)
    if parsed.scheme == "file":
        return Path(url2pathname(parsed.path)).read_bytes()
    if parsed.scheme in ("http", "https"):
        from urllib.request import urlopen

        with urlopen(asset.url, timeout=30) as response:  # noqa: S310 — scheme checked above
            return response.read()
    raise ProviderError(
        f"unsupported reference-image URL scheme {parsed.scheme!r} on input asset {asset.url!r}",
        error_code=ProviderErrorCode.INVALID_INPUT,
    )


class NanoBananaProvider(SyncProvider):
    """Genblaze provider adapter for Gemini 2.5 Flash Image (nano-banana).

    Args:
        api_key: Gemini API key. Falls back to the ``GEMINI_API_KEY`` env var
            (same var ``genblaze-google`` reads, so one credential serves both).
        output_dir: Where generated PNGs land. Defaults to a temp file per
            asset; the pipeline's sink is what moves them to B2.
    """

    name = "google-nano-banana"

    @classmethod
    def create_registry(cls) -> ModelRegistry:
        return ModelRegistry(fallback=_FALLBACK_SPEC)

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.IMAGE],
            # The whole reason this adapter exists: image inputs, so prior
            # locked frames can ride along as continuity references (3.4).
            supported_inputs=["text", "image"],
            accepts_chain_input=True,
            output_formats=["image/png"],
            models=[NANO_BANANA_MODEL],
        )

    def __init__(
        self,
        api_key: str | None = None,
        *,
        output_dir: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._output_dir = Path(output_dir) if output_dir else None
        self._client: Any = None

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:
                raise ProviderError(
                    "google-genai package not installed. Run: pip install google-genai"
                ) from exc
            kwargs: dict = {}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            self._client = genai.Client(**kwargs)
        return self._client

    def _build_contents(self, step: Step) -> list[Any]:
        """Prompt plus any reference images, as google-genai `Part`s.

        Reference images go *before* the prompt: Gemini treats leading image
        parts as the visual context the instruction then operates against,
        which is exactly the continuity semantics Nova wants ("keep this
        character and this world, now stage them per the prompt").
        """
        from google.genai import types

        contents: list[Any] = []
        for asset in step.inputs:
            contents.append(
                types.Part.from_bytes(
                    data=_read_asset_bytes(asset),
                    mime_type=asset.media_type or _DEFAULT_MIME,
                )
            )
        contents.append(types.Part.from_text(text=step.prompt or ""))
        return contents

    def generate(self, step: Step, config: RunnableConfig | None = None) -> Step:
        """Generate one storyboard still via `generate_content`."""
        client = self._get_client()

        try:
            from google.genai import types

            payload = self.prepare_payload(step)

            image_config_kwargs: dict = {}
            if payload.get("aspect_ratio"):
                image_config_kwargs["aspect_ratio"] = payload["aspect_ratio"]

            gen_config = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=(
                    types.ImageConfig(**image_config_kwargs) if image_config_kwargs else None
                ),
            )

            response = client.models.generate_content(
                model=step.model,
                contents=self._build_contents(step),
                config=gen_config,
            )

            image_parts = [
                part
                for candidate in (response.candidates or [])
                for part in (candidate.content.parts if candidate.content else [])
                if part.inline_data is not None and part.inline_data.data
            ]

            # A safety block returns a candidate with no image part rather
            # than raising — silently producing a zero-asset "success" would
            # let an empty shot slide through to lock. Fail explicitly.
            if not image_parts:
                raise ProviderError(
                    "nano-banana returned no image — the prompt was most likely "
                    "blocked by a safety filter",
                    error_code=ProviderErrorCode.CONTENT_POLICY,
                )

            for index, part in enumerate(image_parts):
                data = part.inline_data.data
                mime_type = part.inline_data.mime_type or _DEFAULT_MIME
                suffix = ".jpeg" if "jpeg" in mime_type else ".png"

                if self._output_dir:
                    self._output_dir.mkdir(parents=True, exist_ok=True)
                    out_path = self._output_dir / f"{step.step_id}_{index}{suffix}"
                else:
                    fd, tmp = tempfile.mkstemp(suffix=suffix)
                    os.close(fd)
                    out_path = Path(tmp)

                out_path.write_bytes(data)

                asset = Asset(
                    # ``Path.as_uri()``, not genblaze-google's
                    # ``f"file://{quote(path)}"`` — see _FILE_URI_NOTE below.
                    url=out_path.resolve().as_uri(),
                    media_type=mime_type,
                    size_bytes=len(data),
                )
                # Hash here, while the bytes are in hand. genblaze-google's
                # ImagenProvider skips this; without it the manifest's
                # canonical hash and the step cache key both fall back to the
                # (rotating) URL. Provenance is a judged criterion — backlog
                # 4.2 recomputes this hash independently and it must match.
                asset.set_hash(data)
                step.assets.append(asset)

            self._apply_registry_pricing(step)
            return step

        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(
                f"nano-banana generation failed: {exc}",
                error_code=_map_error(exc),
            ) from exc
