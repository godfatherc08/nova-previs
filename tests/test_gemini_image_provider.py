"""
Backlog 3.2 acceptance: "Storyboard still generated successfully via
nano-banana for a test shot."

Two layers:

  * Offline — a fake ``google.genai`` client asserts we call the *right* API
    (``generate_content``, not Imagen's ``generate_images``) with the right
    shape. This is the regression guard for the exact mistake documented in
    ``nova/providers/gemini_image.py``: genblaze-google's ``ImagenProvider``
    silently cannot serve this model.
  * Live — a real call to nano-banana, skipped unless ``GEMINI_API_KEY`` is
    set (backlog 0.6 hasn't landed the key yet). Same skip-if-no-creds
    convention as ``tests/test_b2_connection.py``. Run it with
    ``pytest -m live``.
"""

import hashlib
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest
from genblaze_core.exceptions import ProviderError
from genblaze_core.models.asset import Asset
from genblaze_core.models.enums import Modality, ProviderErrorCode
from genblaze_core.models.step import Step

from nova.models.shot_spec import (
    Camera,
    Framing,
    Grade,
    Lens,
    Lighting,
    ShotSpec,
    Subject,
)
from nova.pipeline.image_stage import ImageStage
from nova.providers.gemini_image import NANO_BANANA_MODEL, NanoBananaProvider

# A real (if tiny) 1x1 PNG, so the sha256/size assertions mean something.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000b49444154789c6360000200000500017a5eab3f00"
    "00000049454e44ae426082"
)

_SPEC = ShotSpec(
    shot_id="s1",
    intent="establish the ruined skyline at dusk",
    camera=Camera(angle="low", height_m=1.2, movement="slow push-in"),
    lens=Lens(focal_length_mm=18, aperture_f=2.8),
    framing=Framing(shot_size="extreme wide", composition="rule-of-thirds, subject lower-left"),
    lighting=Lighting(key="low-key", mood="dramatic shadows", practicals=["drone lights"]),
    grade=Grade(look="desaturated teal", contrast="high"),
    subject=Subject(primary="woman in tattered coat", blocking="walking left-to-right, foreground"),
    world=["destroyed buildings", "dense fog"],
)


class _FakeBlob:
    def __init__(self, data: bytes, mime_type: str = "image/png") -> None:
        self.data = data
        self.mime_type = mime_type


class _FakePart:
    def __init__(self, inline_data=None) -> None:
        self.inline_data = inline_data


class _FakeContent:
    def __init__(self, parts) -> None:
        self.parts = parts


class _FakeCandidate:
    def __init__(self, parts) -> None:
        self.content = _FakeContent(parts)


class _FakeResponse:
    def __init__(self, parts) -> None:
        self.candidates = [_FakeCandidate(parts)]


class _FakeModels:
    """Records the call so the test can assert on API surface and arguments."""

    def __init__(self, parts) -> None:
        self._parts = parts
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._parts)

    def generate_images(self, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError(
            "called Imagen's generate_images() — nano-banana is served by "
            "generate_content(). This is the exact bug ImagenProvider has."
        )


class _FakeClient:
    def __init__(self, parts) -> None:
        self.models = _FakeModels(parts)


def _path_from_url(url: str) -> Path:
    """Resolve a ``file://`` asset URL back to a real path, cross-platform."""
    return Path(url2pathname(urlparse(url).path))


def _provider_with(parts, tmp_path: Path) -> NanoBananaProvider:
    provider = NanoBananaProvider(api_key="test-key", output_dir=tmp_path)
    provider._client = _FakeClient(parts)
    return provider


def _step(prompt: str = "a test prompt", **params) -> Step:
    return Step(
        provider="google-nano-banana",
        model=NANO_BANANA_MODEL,
        modality=Modality.IMAGE,
        prompt=prompt,
        params=params,
    )


def test_generate_calls_generate_content_and_returns_a_hashed_png(tmp_path):
    provider = _provider_with([_FakePart(_FakeBlob(_PNG))], tmp_path)

    step = provider.generate(_step("a ruined skyline", aspect_ratio="16:9"))

    call = provider._client.models.calls[0]
    assert call["model"] == NANO_BANANA_MODEL
    assert call["config"].response_modalities == ["IMAGE"]
    assert call["config"].image_config.aspect_ratio == "16:9"

    assert len(step.assets) == 1
    asset = step.assets[0]
    assert asset.media_type == "image/png"
    assert asset.size_bytes == len(_PNG)

    # sha256 is populated from the bytes in hand. Without it, the manifest's
    # canonical hash and the step cache key fall back to a rotating URL —
    # and backlog 4.2 must be able to recompute this hash independently.
    assert asset.sha256 == hashlib.sha256(_PNG).hexdigest()

    # The asset URL must round-trip back to the bytes on disk. This is what
    # catches the malformed-file-URI-on-Windows bug described in the
    # provider's _FILE_URI_NOTE — a `file://` + quote(path) URL parses to an
    # empty path and reads the CWD instead.
    assert _path_from_url(asset.url).read_bytes() == _PNG


def test_reference_images_lead_the_prompt(tmp_path):
    """Continuity (3.4): prior locked frames must go in *before* the prompt —
    Gemini reads leading image parts as the visual context the instruction
    then operates against."""
    provider = _provider_with([_FakePart(_FakeBlob(_PNG))], tmp_path)

    prior = tmp_path / "s1_locked.png"
    prior.write_bytes(_PNG)

    step = _step("stage the next shot")
    step.inputs = [Asset(url=prior.as_uri(), media_type="image/png")]

    provider.generate(step)

    contents = provider._client.models.calls[0]["contents"]
    assert len(contents) == 2
    assert contents[0].inline_data.data == _PNG  # reference image first
    assert contents[1].text == "stage the next shot"  # prompt second


def test_declares_image_input_support():
    """The whole reason this adapter exists instead of ImagenProvider, which
    declares supported_inputs=['text'] and accepts_chain_input=False."""
    caps = NanoBananaProvider(api_key="test-key").get_capabilities()
    assert caps.accepts_chain_input is True
    assert "image" in caps.supported_inputs
    assert Modality.IMAGE in caps.supported_modalities


def test_safety_block_raises_instead_of_returning_zero_assets(tmp_path):
    """Gemini returns a candidate with no image part on a safety block rather
    than erroring. A silent zero-asset 'success' would be lockable."""
    provider = _provider_with([_FakePart(inline_data=None)], tmp_path)

    with pytest.raises(ProviderError) as exc:
        provider.generate(_step())

    assert exc.value.error_code == ProviderErrorCode.CONTENT_POLICY


def test_transport_error_is_classified_for_genblaze_retry(tmp_path):
    """Genblaze only retries codes it deems transient, so a 429 must not be
    classified UNKNOWN or the fallback chain (3.3) never fires."""
    provider = NanoBananaProvider(api_key="test-key", output_dir=tmp_path)

    class _Boom:
        class models:
            @staticmethod
            def generate_content(**_kwargs):
                raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")

    provider._client = _Boom()

    with pytest.raises(ProviderError) as exc:
        provider.generate(_step())

    assert exc.value.error_code == ProviderErrorCode.RATE_LIMIT


def test_image_stage_defaults_to_nano_banana():
    """Backlog 3.2: nano-banana is the *primary* provider, not an option."""
    stage = ImageStage()
    assert isinstance(stage._provider, NanoBananaProvider)
    assert stage._model == NANO_BANANA_MODEL


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="no GEMINI_API_KEY — backlog 0.6 (provision provider API keys) not done yet",
)
def test_live_nano_banana_generates_a_real_still(tmp_path):
    """Backlog 3.2 acceptance, for real: one Shot Spec -> one storyboard still
    from Gemini 2.5 Flash Image, through the Genblaze Pipeline."""
    result = ImageStage(NanoBananaProvider(output_dir=tmp_path)).run(_SPEC)

    assert result.status == "succeeded", result.error
    assert len(result.assets) == 1

    asset = result.assets[0]
    assert asset.media_type.startswith("image/")
    assert asset.sha256

    written = _path_from_url(asset.url)
    assert written.stat().st_size > 1000  # a real frame, not an empty file
