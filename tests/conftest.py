"""Shared pytest fixtures and helpers used across multiple test files."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# ffmpeg / ffprobe discovery
# ---------------------------------------------------------------------------


def _find_ffmpeg() -> Path | None:
    which = shutil.which("ffmpeg")
    return Path(which) if which else None


def _find_ffprobe(ffmpeg: Path) -> Path | None:
    suffix = ffmpeg.suffix
    candidate = ffmpeg.parent / f"ffprobe{suffix}"
    if candidate.exists():
        return candidate
    which = shutil.which("ffprobe")
    return Path(which) if which else None


FFMPEG = _find_ffmpeg()
FFPROBE = _find_ffprobe(FFMPEG) if FFMPEG else None

requires_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None,
    reason="ffmpeg/ffprobe not available on PATH",
)


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------


def make_silent_mp3(path: Path, duration_seconds: float = 2.0) -> None:
    """Generate a short silent MP3 test fixture using ffmpeg.

    Args:
        path: Destination path for the MP3 file.
        duration_seconds: Duration of the generated audio.
    """
    assert FFMPEG is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(FFMPEG),
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
            "-t", str(duration_seconds),
            "-acodec", "libmp3lame",
            "-ab", "128k",
            "-y",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def make_jpeg(path: Path, size: tuple[int, int] = (100, 100), color: str = "gray") -> None:
    """Write a minimal JPEG test image to path, creating parent directories.

    Args:
        path: Destination path for the JPEG file.
        size: Image dimensions as (width, height).
        color: Fill color string understood by Pillow.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color=color)
    img.save(path, format="JPEG")
