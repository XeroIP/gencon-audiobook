"""Unit tests for ffmpeg_manager.py — shutil.which and subprocess mocked throughout."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import gencon_audiobook.ffmpeg_manager as fm
from gencon_audiobook.ffmpeg_manager import FfmpegNotFoundError


def setup_function() -> None:
    """Reset the module-level cache before every test."""
    fm.reset_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_FFMPEG = Path("/usr/bin/ffmpeg")
_FAKE_FFPROBE = Path("/usr/bin/ffprobe")
_VERSION_OUTPUT = "ffmpeg version 6.1 Copyright (c) 2000-2024 the FFmpeg developers\n"


def _make_run_result(stdout: str = _VERSION_OUTPUT) -> MagicMock:
    result = MagicMock()
    result.stdout = stdout
    return result


# ---------------------------------------------------------------------------
# ensure_ffmpeg — system PATH found
# ---------------------------------------------------------------------------


def test_ensure_ffmpeg_uses_system_path_when_available() -> None:
    with (
        patch("shutil.which", return_value=str(_FAKE_FFMPEG)),
        patch("subprocess.run", return_value=_make_run_result()),
    ):
        path = fm.ensure_ffmpeg()

    assert path == _FAKE_FFMPEG, f"Expected {_FAKE_FFMPEG}, got {path}"


def test_ensure_ffmpeg_caches_result() -> None:
    with (
        patch("shutil.which", return_value=str(_FAKE_FFMPEG)),
        patch("subprocess.run", return_value=_make_run_result()),
    ):
        p1 = fm.ensure_ffmpeg()
        p2 = fm.ensure_ffmpeg()

    assert p1 is p2, "Second call should return cached object"


def test_ensure_ffmpeg_logs_version(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with (
        patch("shutil.which", return_value=str(_FAKE_FFMPEG)),
        patch("subprocess.run", return_value=_make_run_result()),
        caplog.at_level(logging.INFO, logger="gencon_audiobook.ffmpeg_manager"),
    ):
        fm.ensure_ffmpeg()

    assert any("ffmpeg" in r.message.lower() for r in caplog.records), \
        "Expected an INFO log mentioning ffmpeg"


# ---------------------------------------------------------------------------
# ensure_ffmpeg — static-ffmpeg fallback
# ---------------------------------------------------------------------------


def test_ensure_ffmpeg_falls_back_to_static_ffmpeg() -> None:
    mock_static = MagicMock()

    def which_side_effect(name: str) -> str | None:
        # First call (system PATH check) returns None; after add_paths(), returns a path
        which_side_effect.calls = getattr(which_side_effect, "calls", 0) + 1
        if which_side_effect.calls == 1:
            return None
        return str(_FAKE_FFMPEG)

    with (
        patch("shutil.which", side_effect=which_side_effect),
        patch("subprocess.run", return_value=_make_run_result()),
        patch.dict("sys.modules", {"static_ffmpeg": mock_static}),
    ):
        path = fm.ensure_ffmpeg()

    mock_static.add_paths.assert_called_once()
    assert path == _FAKE_FFMPEG


# ---------------------------------------------------------------------------
# ensure_ffmpeg — not found
# ---------------------------------------------------------------------------


def test_ensure_ffmpeg_raises_when_not_found() -> None:
    mock_static = MagicMock()

    with (
        patch("shutil.which", return_value=None),
        patch.dict("sys.modules", {"static_ffmpeg": mock_static}),
    ):
        with pytest.raises(FfmpegNotFoundError) as exc_info:
            fm.ensure_ffmpeg()

    assert "winget" in str(exc_info.value), "Error message should include Windows install hint"
    assert "brew" in str(exc_info.value), "Error message should include macOS install hint"
    assert "apt" in str(exc_info.value), "Error message should include Linux install hint"


def test_ensure_ffmpeg_raises_when_static_ffmpeg_throws() -> None:
    mock_static = MagicMock()
    mock_static.add_paths.side_effect = RuntimeError("download failed")

    with (
        patch("shutil.which", return_value=None),
        patch.dict("sys.modules", {"static_ffmpeg": mock_static}),
    ):
        with pytest.raises(FfmpegNotFoundError):
            fm.ensure_ffmpeg()


# ---------------------------------------------------------------------------
# ensure_ffprobe — found alongside ffmpeg
# ---------------------------------------------------------------------------


def test_ensure_ffprobe_found_alongside_ffmpeg(tmp_path: Path) -> None:
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffprobe = tmp_path / "ffprobe"
    fake_ffmpeg.write_bytes(b"")
    fake_ffprobe.write_bytes(b"")

    fm._ffmpeg_path = fake_ffmpeg  # seed cache so ensure_ffmpeg() is not called live

    with patch("subprocess.run", return_value=_make_run_result()):
        path = fm.ensure_ffprobe()

    assert path == fake_ffprobe


def test_ensure_ffprobe_found_alongside_ffmpeg_exe(tmp_path: Path) -> None:
    """Windows: ffmpeg.exe → ffprobe.exe in same directory."""
    fake_ffmpeg = tmp_path / "ffmpeg.exe"
    fake_ffprobe = tmp_path / "ffprobe.exe"
    fake_ffmpeg.write_bytes(b"")
    fake_ffprobe.write_bytes(b"")

    fm._ffmpeg_path = fake_ffmpeg

    with patch("subprocess.run", return_value=_make_run_result()):
        path = fm.ensure_ffprobe()

    assert path == fake_ffprobe


# ---------------------------------------------------------------------------
# ensure_ffprobe — fallback to PATH
# ---------------------------------------------------------------------------


def test_ensure_ffprobe_falls_back_to_path(tmp_path: Path) -> None:
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_bytes(b"")
    # No ffprobe in same dir — falls back to PATH

    fm._ffmpeg_path = fake_ffmpeg

    with (
        patch("shutil.which", return_value=str(_FAKE_FFPROBE)),
        patch("subprocess.run", return_value=_make_run_result()),
    ):
        path = fm.ensure_ffprobe()

    assert path == _FAKE_FFPROBE


def test_ensure_ffprobe_raises_when_not_found(tmp_path: Path) -> None:
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffmpeg.write_bytes(b"")

    fm._ffmpeg_path = fake_ffmpeg

    with patch("shutil.which", return_value=None):
        with pytest.raises(FfmpegNotFoundError):
            fm.ensure_ffprobe()


# ---------------------------------------------------------------------------
# ensure_ffprobe — caching
# ---------------------------------------------------------------------------


def test_ensure_ffprobe_caches_result(tmp_path: Path) -> None:
    fake_ffmpeg = tmp_path / "ffmpeg"
    fake_ffprobe = tmp_path / "ffprobe"
    fake_ffmpeg.write_bytes(b"")
    fake_ffprobe.write_bytes(b"")

    fm._ffmpeg_path = fake_ffmpeg

    with patch("subprocess.run", return_value=_make_run_result()):
        p1 = fm.ensure_ffprobe()
        p2 = fm.ensure_ffprobe()

    assert p1 is p2, "Second call should return cached object"


# ---------------------------------------------------------------------------
# reset_cache
# ---------------------------------------------------------------------------


def test_reset_cache_clears_both_paths(tmp_path: Path) -> None:
    fm._ffmpeg_path = tmp_path / "ffmpeg"
    fm._ffprobe_path = tmp_path / "ffprobe"

    fm.reset_cache()

    assert fm._ffmpeg_path is None
    assert fm._ffprobe_path is None
