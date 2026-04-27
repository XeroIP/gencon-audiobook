"""Locate ffmpeg and ffprobe, downloading via static-ffmpeg if not on system PATH."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_INSTALL_INSTRUCTIONS = (
    "ffmpeg could not be found or downloaded. To install manually:\n"
    "  - Windows: winget install ffmpeg\n"
    "  - macOS:   brew install ffmpeg\n"
    "  - Linux:   sudo apt install ffmpeg  (or equivalent for your distro)\n"
    "Then re-run gencon-audiobook."
)

_ffmpeg_path: Path | None = None
_ffprobe_path: Path | None = None


class FfmpegNotFoundError(Exception):
    """Raised when ffmpeg or ffprobe cannot be located or downloaded."""


def _get_version(binary: Path) -> str:
    """Return the first line of `binary -version` output, or 'unknown'.

    Args:
        binary: Path to an ffmpeg or ffprobe binary.

    Returns:
        First line of version output, e.g. "ffmpeg version 6.1 ...".
    """
    try:
        result = subprocess.run(
            [str(binary), "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else "unknown"
        return first_line
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Could not get version for %s: %s", binary, exc)
        return "unknown"


def ensure_ffmpeg() -> Path:
    """Locate ffmpeg, downloading via static-ffmpeg if not on system PATH.

    Search order:
    1. System PATH (shutil.which("ffmpeg"))
    2. static-ffmpeg auto-download

    Logs the ffmpeg path and version at INFO level on first call.
    Result is cached — subsequent calls return immediately.

    Returns:
        Path to the ffmpeg binary.

    Raises:
        FfmpegNotFoundError: with install instructions if ffmpeg cannot be
            located or downloaded.
    """
    global _ffmpeg_path
    if _ffmpeg_path is not None:
        return _ffmpeg_path

    # 1. System PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        path = Path(system_ffmpeg)
        version = _get_version(path)
        logger.info("Using system ffmpeg at %s (%s)", path, version)
        _ffmpeg_path = path
        return _ffmpeg_path

    # 2. static-ffmpeg fallback
    logger.debug("ffmpeg not found on PATH; trying static-ffmpeg")
    try:
        import static_ffmpeg

        static_ffmpeg.add_paths()
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            path = Path(system_ffmpeg)
            version = _get_version(path)
            logger.info("Downloaded ffmpeg to %s (%s)", path, version)
            _ffmpeg_path = path
            return _ffmpeg_path
    except (AttributeError, ImportError, OSError, RuntimeError) as exc:
        logger.debug("static-ffmpeg failed: %s", exc)

    raise FfmpegNotFoundError(_INSTALL_INSTRUCTIONS)


def ensure_ffprobe() -> Path:
    """Locate ffprobe, using the same directory as the ffmpeg binary.

    ffprobe is always bundled alongside ffmpeg (both system installs and
    static-ffmpeg). Calls ensure_ffmpeg() first to resolve the binary
    directory, then looks for ffprobe in the same location.

    Returns:
        Path to the ffprobe binary.

    Raises:
        FfmpegNotFoundError: if ffprobe cannot be found alongside ffmpeg.
    """
    global _ffprobe_path
    if _ffprobe_path is not None:
        return _ffprobe_path

    ffmpeg = ensure_ffmpeg()

    # ffprobe lives next to ffmpeg — same directory, same optional .exe suffix
    suffix = ffmpeg.suffix  # ".exe" on Windows, "" on Unix
    candidate = ffmpeg.parent / f"ffprobe{suffix}"
    if candidate.exists():
        version = _get_version(candidate)
        logger.debug("Found ffprobe at %s (%s)", candidate, version)
        _ffprobe_path = candidate
        return _ffprobe_path

    # Fallback: PATH lookup in case ffprobe was installed separately
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        path = Path(system_ffprobe)
        version = _get_version(path)
        logger.debug("Found ffprobe on PATH: %s (%s)", path, version)
        _ffprobe_path = path
        return _ffprobe_path

    raise FfmpegNotFoundError(
        f"ffprobe not found alongside ffmpeg ({ffmpeg.parent}). "
        "Reinstalling ffmpeg should also install ffprobe."
    )


def reset_cache() -> None:
    """Clear the cached ffmpeg/ffprobe paths (for testing only)."""
    global _ffmpeg_path, _ffprobe_path
    _ffmpeg_path = None
    _ffprobe_path = None
