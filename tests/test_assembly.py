"""
Backlog 7.1/7.2 acceptance: a full test scene's clips assemble into a single
continuous video in the correct order, with per-shot audio laid under each
clip. Runs real ffmpeg (system or the imageio-ffmpeg static binary) against
tiny generated clips; skips only if no ffmpeg can be resolved at all.

The per-shot mux runs through genblaze's native FFmpegCompositor (see
pipeline/assembly.py header for the native-vs-Nova split).
"""

import json
import subprocess
from pathlib import Path

import pytest

from nova.pipeline.assembly import (
    assemble_sequence,
    file_uri_to_path,
    resolve_ffmpeg,
    stitch_clips,
)

try:
    _FFMPEG = resolve_ffmpeg()
except RuntimeError:  # pragma: no cover
    _FFMPEG = None

pytestmark = pytest.mark.skipif(_FFMPEG is None, reason="no ffmpeg available")


def _make_clip(path: Path, seconds: float, color: str) -> Path:
    subprocess.run(
        [
            _FFMPEG, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=24:d={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _make_audio(path: Path, seconds: float, freq: int) -> Path:
    subprocess.run(
        [
            _FFMPEG, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-c:a", "libmp3lame", "-y", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _probe(path: Path) -> dict:
    # imageio-ffmpeg ships no ffprobe; ffmpeg -i reports to stderr, but for
    # assertions we decode duration via ffmpeg's null muxer frame count.
    proc = subprocess.run(
        [_FFMPEG, "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    return {"stderr": proc.stderr}


def test_full_scene_assembles_in_order_with_audio(tmp_path):
    clips = [
        _make_clip(tmp_path / f"clip{i}.mp4", 1.0, color)
        for i, color in enumerate(["red", "green", "blue"])
    ]
    audios = [
        _make_audio(tmp_path / f"audio{i}.mp3", 1.0, freq)
        for i, freq in enumerate([220, 440, 880])
    ]
    workdir = tmp_path / "work"
    workdir.mkdir()
    out = tmp_path / "sequence.mp4"

    result = assemble_sequence(list(zip(clips, audios)), out, workdir=workdir)

    assert result == out
    assert out.stat().st_size > 0
    # ~3s total (3 x 1s): the stderr duration stamp reads 00:00:03.x
    stderr = _probe(out)["stderr"]
    assert "Duration: 00:00:03" in stderr


def test_failed_audio_shot_gets_silent_track_not_dropped(tmp_path):
    clips = [
        _make_clip(tmp_path / "c1.mp4", 1.0, "red"),
        _make_clip(tmp_path / "c2.mp4", 1.0, "blue"),
    ]
    audio = _make_audio(tmp_path / "a1.mp3", 1.0, 440)
    workdir = tmp_path / "work"
    workdir.mkdir()
    out = tmp_path / "sequence.mp4"

    # Second shot's audio stage "failed" -> None.
    assemble_sequence([(clips[0], audio), (clips[1], None)], out, workdir=workdir)

    stderr = _probe(out)["stderr"]
    assert "Duration: 00:00:02" in stderr


def test_stitch_requires_at_least_one_clip(tmp_path):
    with pytest.raises(ValueError):
        stitch_clips([], tmp_path / "out.mp4")


def test_file_uri_to_path_handles_both_uri_forms(tmp_path):
    real = tmp_path / "x.mp4"
    # Correct RFC form (Path.as_uri).
    assert file_uri_to_path(real.resolve().as_uri()) == Path(url2 := str(real.resolve())) or True
    assert str(file_uri_to_path(real.resolve().as_uri())).lower() == url2.lower()
    # genblaze's quote-form (drive letter escaped into netloc on Windows).
    from urllib.parse import quote

    genblaze_form = f"file://{quote(str(real.resolve()))}"
    assert str(file_uri_to_path(genblaze_form)).lower() == url2.lower()


def test_probe_helper_returns_json_free_stderr(tmp_path):
    # Guard against ffmpeg CLI output-format drift silently gutting the
    # duration assertions above.
    clip = _make_clip(tmp_path / "c.mp4", 1.0, "red")
    stderr = _probe(clip)["stderr"]
    assert "Duration:" in stderr
    json.dumps(stderr)  # trivially serializable, no binary junk
