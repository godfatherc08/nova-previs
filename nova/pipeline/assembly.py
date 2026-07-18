"""
Backlog 7.1-7.4: assemble locked shots' animatics + scratch audio into one
previs sequence.

What's native vs. Nova here (CLAUDE.md verify rule):

  * NATIVE: per-shot video+audio muxing. genblaze-core ships
    ``FFmpegCompositor`` (``genblaze_core.providers.compositor``) — a real
    SyncProvider that muxes one video + one audio input into MP4. Backlog
    7.2's per-shot sync runs through it via a normal Genblaze Pipeline.
  * NOT native: concatenating N muxed clips into one sequence. No genblaze
    provider does multi-clip concat (verified by reading every provider in
    genblaze_core 0.3.4). ``stitch_clips`` below is Nova's own ffmpeg
    concat, kept as a plain function rather than dressed up as a provider.

ffmpeg resolution: FFMPEG_PATH env var -> system PATH -> the static binary
bundled by ``imageio-ffmpeg`` (optional dep) — so a judge's fresh clone
works without a system ffmpeg install.

Windows file-URI note: ``FFmpegCompositor`` emits genblaze's
``file://{quote(path)}`` URL form, which urlparse mangles on Windows (drive
letter lands in netloc — same upstream bug documented at length in
``providers/gemini_image.py::_FILE_URI_NOTE``). ``file_uri_to_path`` below
tolerates both that form and the correct ``Path.as_uri()`` form.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from genblaze_core import Modality, Pipeline
from genblaze_core.models.asset import Asset
from genblaze_core.providers.compositor import FFmpegCompositor

_FFMPEG_TIMEOUT = 300


def resolve_ffmpeg() -> str:
    """FFMPEG_PATH env -> PATH -> imageio-ffmpeg bundled binary."""
    configured = os.environ.get("FFMPEG_PATH")
    if configured:
        return configured
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError(
            "ffmpeg not found: set FFMPEG_PATH, install ffmpeg on PATH, "
            "or pip install imageio-ffmpeg"
        ) from exc


def file_uri_to_path(url: str) -> Path:
    """Accept both ``Path.as_uri()`` and genblaze's ``file://{quote(path)}``."""
    parsed = urlparse(url)
    if parsed.scheme != "file":
        raise ValueError(f"not a file URI: {url!r}")
    if parsed.path:
        return Path(url2pathname(parsed.path))
    # genblaze quote-form on Windows: the whole path percent-escaped into
    # what urlparse reads as the netloc.
    return Path(unquote(parsed.netloc + parsed.path))


def _run_ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(
        [resolve_ffmpeg(), "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        timeout=_FFMPEG_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-2000:]}")


def _compositor_safe_uri(path: Path) -> str:
    """HACK, flagged loudly: a file URI form genblaze's ``resolve_input_path``
    survives on Windows.

    Upstream bug (same family as ``gemini_image.py::_FILE_URI_NOTE``, worth
    filing under backlog 11.5): ``_ffmpeg_utils.resolve_input_path`` does
    ``Path(unquote(urlparse(url).path))`` — on a correct ``file:///C:/x``
    URI that yields the drive-*relative* ``C:x``, which then fails the
    allowed-roots check. Reproduced against genblaze-core 0.3.4 in this
    repo's test run.

    Workaround: on Windows, emit ``file://C:/x/y`` (drive in the netloc) so
    ``parsed.path`` is ``/x/y`` and ``Path.resolve()`` re-anchors it to the
    process's current drive. Constraint that makes this safe here: the temp
    dirs and repo both live on the same drive as the process CWD. On POSIX
    (CI, deploy) the correct ``as_uri()`` form is used — the hack is
    Windows-dev-box-only. Delete once upstream uses ``url2pathname``.
    """
    resolved = path.resolve()
    if os.name == "nt":
        return f"file://{resolved.as_posix()}"
    return resolved.as_uri()


def mux_clip_with_audio(clip_path: Path, audio_path: Path, *, workdir: Path) -> Path:
    """Backlog 7.2, per shot: sync the scratch track under the clip.

    Runs through the *native* ``FFmpegCompositor`` via a real Genblaze
    Pipeline — not a hand-rolled mux — because that's the SDK's actual
    surface for this and keeps the per-step provenance trail consistent
    with every other stage.
    """
    compositor = FFmpegCompositor(output_dir=workdir, ffmpeg_path=resolve_ffmpeg())
    audio_media = "audio/mpeg" if audio_path.suffix == ".mp3" else "audio/wav"
    video = Asset(url=_compositor_safe_uri(clip_path), media_type="video/mp4")
    audio = Asset(url=_compositor_safe_uri(audio_path), media_type=audio_media)
    # Hash inputs so the run's manifest/cache keys are stable (the pipeline
    # warns loudly otherwise).
    video.set_hash(clip_path.read_bytes())
    audio.set_hash(audio_path.read_bytes())

    pipeline = Pipeline("nova-assembly-mux")
    pipeline.step(
        compositor,
        model="ffmpeg",
        modality=Modality.VIDEO,
        external_inputs=[video, audio],
    )
    result = pipeline.run(raise_on_failure=True)
    return file_uri_to_path(result.run.steps[0].assets[0].url)


def add_silent_audio(clip_path: Path, *, workdir: Path) -> Path:
    """Graceful degradation (6.5/7.2): a shot whose audio stage failed still
    assembles — with a silent track, so every concat input has identical
    stream layout (the concat filter requires it)."""
    out = workdir / f"{clip_path.stem}_silent.mp4"
    _run_ffmpeg(
        [
            "-i", str(clip_path),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-c:v", "copy", "-c:a", "aac", "-shortest", "-y", str(out),
        ]
    )
    return out


def stitch_clips(muxed_paths: list[Path], out_path: Path) -> Path:
    """Backlog 7.1: concatenate per-shot MP4s in shot order (Nova glue, see
    module docstring). Re-encodes to one uniform H.264/AAC stream because
    the inputs come from different video providers (Runway vs Luma vs draft
    tiers) and are not guaranteed concat-demuxer-compatible as-is."""
    if not muxed_paths:
        raise ValueError("stitch_clips needs at least one clip")

    with tempfile.TemporaryDirectory() as tmp:
        list_file = Path(tmp) / "concat.txt"
        # concat demuxer path escaping: single quotes around, embedded
        # single-quotes escaped.
        lines = [
            "file '" + str(p.resolve()).replace("'", "'\\''") + "'"
            for p in muxed_paths
        ]
        list_file.write_text("\n".join(lines), encoding="utf-8")
        _run_ffmpeg(
            [
                "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
                "-c:a", "aac", "-ar", "44100",
                "-movflags", "+faststart", "-y", str(out_path),
            ]
        )
    return out_path


def assemble_sequence(
    shot_media: list[tuple[Path, Path | None]],
    out_path: Path,
    *,
    workdir: Path,
) -> Path:
    """Full local assembly: mux each (clip, audio|None) pair, then stitch.

    ``shot_media`` is in shot order. ``None`` audio means the audio stage
    failed for that shot — silent track, not a dropped shot.
    """
    muxed: list[Path] = []
    for clip_path, audio_path in shot_media:
        if audio_path is not None:
            muxed.append(mux_clip_with_audio(clip_path, audio_path, workdir=workdir))
        else:
            muxed.append(add_silent_audio(clip_path, workdir=workdir))
    return stitch_clips(muxed, out_path)
