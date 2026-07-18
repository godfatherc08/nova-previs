"""
Backlog 6.3: Nova's Stability Audio adapter. Offline tests mock the HTTP
POST at the ``requests`` boundary (the adapter is Nova code, so unlike the
first-party adapters there's no SDK mock for it); the live smoke test skips
without STABILITY_API_KEY, same convention as test_gemini_image_provider.py.
"""

import os
from types import SimpleNamespace

import pytest
from genblaze_core.exceptions import ProviderError
from genblaze_core.models.enums import Modality, ProviderErrorCode
from genblaze_core.models.step import Step

from nova.providers.stability_audio import STABLE_AUDIO_MODEL, StabilityAudioProvider

_MP3_BYTES = b"ID3fake-mp3-payload"


def _step(**params) -> Step:
    return Step(
        provider="stability-audio",
        model=STABLE_AUDIO_MODEL,
        prompt="cinematic ambient, dramatic shadows mood",
        modality=Modality.AUDIO,
        params=params,
    )


def _mock_post(captured: dict, *, status_code: int = 200, content: bytes = _MP3_BYTES):
    def post(url, *, headers, files, timeout):
        captured.update(url=url, headers=headers, files=files, timeout=timeout)
        return SimpleNamespace(
            status_code=status_code,
            content=content,
            text=content.decode("latin-1", errors="replace"),
        )

    return post


def test_generate_returns_hashed_mp3_asset(monkeypatch, tmp_path):
    captured: dict = {}
    monkeypatch.setattr("requests.post", _mock_post(captured))

    provider = StabilityAudioProvider(api_key="test-key", output_dir=tmp_path)
    step = provider.generate(_step(duration_seconds=5))

    assert len(step.assets) == 1
    asset = step.assets[0]
    assert asset.media_type == "audio/mpeg"
    assert asset.size_bytes == len(_MP3_BYTES)
    assert asset.duration == 5.0
    import hashlib

    assert asset.sha256 == hashlib.sha256(_MP3_BYTES).hexdigest()

    # Wire-call shape: bearer auth, model in path, multipart form fields.
    assert STABLE_AUDIO_MODEL in captured["url"]
    assert captured["headers"]["authorization"] == "Bearer test-key"
    form_fields = {k: v[1] for k, v in captured["files"].items()}
    assert form_fields["prompt"].startswith("cinematic ambient")
    assert form_fields["duration"] == "5.0"
    assert form_fields["output_format"] == "mp3"


def test_missing_api_key_maps_to_auth_failure(monkeypatch):
    monkeypatch.delenv("STABILITY_API_KEY", raising=False)
    with pytest.raises(ProviderError) as excinfo:
        StabilityAudioProvider().generate(_step())
    assert excinfo.value.error_code == ProviderErrorCode.AUTH_FAILURE


def test_http_429_maps_to_rate_limit(monkeypatch):
    monkeypatch.setattr(
        "requests.post", _mock_post({}, status_code=429, content=b"rate limited")
    )
    with pytest.raises(ProviderError) as excinfo:
        StabilityAudioProvider(api_key="k").generate(_step())
    assert excinfo.value.error_code == ProviderErrorCode.RATE_LIMIT


def test_empty_body_is_a_server_error_not_a_silent_success(monkeypatch):
    monkeypatch.setattr("requests.post", _mock_post({}, status_code=200, content=b""))
    with pytest.raises(ProviderError) as excinfo:
        StabilityAudioProvider(api_key="k").generate(_step())
    assert excinfo.value.error_code == ProviderErrorCode.SERVER_ERROR


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("STABILITY_API_KEY"), reason="STABILITY_API_KEY not set"
)
def test_live_stable_audio_generates_real_track(tmp_path):
    provider = StabilityAudioProvider(output_dir=tmp_path)
    step = provider.generate(_step(duration_seconds=1))
    assert step.assets and step.assets[0].size_bytes > 0
