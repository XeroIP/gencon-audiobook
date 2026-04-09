"""Tests for audio.py — requires ffmpeg to be available on PATH or via static-ffmpeg.

Tests are skipped automatically if ffmpeg is not found.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from gencon_audiobook.audio import AudioError, build_m4b, convert_mp3_to_aac
from gencon_audiobook.models import Conference, Session, Talk


# ---------------------------------------------------------------------------
# Fixtures and helpers
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


_FFMPEG = _find_ffmpeg()
_FFPROBE = _find_ffprobe(_FFMPEG) if _FFMPEG else None

requires_ffmpeg = pytest.mark.skipif(
    _FFMPEG is None or _FFPROBE is None,
    reason="ffmpeg/ffprobe not available on PATH",
)


def make_silent_mp3(path: Path, duration_seconds: float = 2.0) -> None:
    """Generate a short silent MP3 test fixture using ffmpeg.

    Args:
        path: Destination path for the MP3 file.
        duration_seconds: Duration of the generated audio.
    """
    assert _FFMPEG is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(_FFMPEG),
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


def _make_conference(tmp_path: Path, n_talks: int = 3, duration: float = 2.0) -> Conference:
    """Build a Conference with n_talks and generate MP3 fixtures in tmp_path/audio/."""
    talks = []
    for i in range(1, n_talks + 1):
        talk = Talk(
            title=f"Talk {i}",
            speaker=f"Speaker {i}",
            talk_url=f"https://www.churchofjesuschrist.org/t{i}",
            talk_index=i,
        )
        talks.append(talk)
        mp3 = tmp_path / "audio" / f"{i:03d}-Talk {i}.mp3"
        make_silent_mp3(mp3, duration_seconds=duration)

    session = Session(name="Morning Session", number=1, talks=talks)
    return Conference(
        title="April 2024 General Conference",
        year=2024,
        month=4,
        cover_image_url=None,
        sessions=[session],
        conference_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04",
    )


# ---------------------------------------------------------------------------
# convert_mp3_to_aac
# ---------------------------------------------------------------------------


@requires_ffmpeg
def test_convert_mp3_to_aac_produces_aac_file(tmp_path: Path) -> None:
    mp3 = tmp_path / "test.mp3"
    make_silent_mp3(mp3, duration_seconds=2.0)
    aac = tmp_path / "test.m4a"

    convert_mp3_to_aac(mp3, aac, _FFMPEG)

    assert aac.exists(), "AAC output file should exist"
    assert aac.stat().st_size > 0, "AAC output file should be non-empty"


@requires_ffmpeg
def test_convert_mp3_to_aac_returns_duration(tmp_path: Path) -> None:
    mp3 = tmp_path / "test.mp3"
    expected = 2.0
    make_silent_mp3(mp3, duration_seconds=expected)
    aac = tmp_path / "test.m4a"

    duration = convert_mp3_to_aac(mp3, aac, _FFMPEG)

    assert abs(duration - expected) < 0.2, \
        f"Expected duration ~{expected}s, got {duration:.3f}s"


@requires_ffmpeg
def test_convert_mp3_to_aac_custom_bitrate_and_sample_rate(tmp_path: Path) -> None:
    mp3 = tmp_path / "test.mp3"
    make_silent_mp3(mp3, duration_seconds=3.0)
    default_out = tmp_path / "default.m4a"
    custom_out = tmp_path / "custom.m4a"

    convert_mp3_to_aac(mp3, default_out, _FFMPEG)
    convert_mp3_to_aac(mp3, custom_out, _FFMPEG, bitrate="32k", sample_rate=22050)

    assert custom_out.stat().st_size < default_out.stat().st_size, (
        "Lower bitrate/sample-rate output should be smaller than default"
    )
    # Duration should still be approximately correct regardless of encoding settings
    duration = convert_mp3_to_aac(mp3, tmp_path / "check.m4a", _FFMPEG, bitrate="32k", sample_rate=22050)
    assert abs(duration - 3.0) < 0.2, f"Expected ~3.0s, got {duration:.3f}s"


@requires_ffmpeg
def test_audio_error_on_invalid_input(tmp_path: Path) -> None:
    mp3 = tmp_path / "nonexistent.mp3"
    aac = tmp_path / "output.m4a"

    with pytest.raises(AudioError):
        convert_mp3_to_aac(mp3, aac, _FFMPEG)


# ---------------------------------------------------------------------------
# build_m4b
# ---------------------------------------------------------------------------


@requires_ffmpeg
def test_build_m4b_with_three_talks(tmp_path: Path) -> None:
    conference = _make_conference(tmp_path, n_talks=3)
    audio_dir = tmp_path / "audio"
    output = tmp_path / "output.m4b"

    build_m4b(conference, audio_dir, output, None, _FFMPEG, _FFPROBE)

    assert output.exists(), "m4b output file should exist"
    assert output.stat().st_size > 0, "m4b output file should be non-empty"


@requires_ffmpeg
def test_build_m4b_chapter_count(tmp_path: Path) -> None:
    n = 3
    conference = _make_conference(tmp_path, n_talks=n)
    audio_dir = tmp_path / "audio"
    output = tmp_path / "output.m4b"

    build_m4b(conference, audio_dir, output, None, _FFMPEG, _FFPROBE)

    result = subprocess.run(
        [str(_FFPROBE), "-v", "quiet", "-print_format", "json",
         "-show_chapters", str(output)],
        capture_output=True, text=True, check=True,
    )
    chapters = json.loads(result.stdout).get("chapters", [])
    assert len(chapters) == n, f"Expected {n} chapters, got {len(chapters)}"


@requires_ffmpeg
def test_build_m4b_chapter_titles(tmp_path: Path) -> None:
    conference = _make_conference(tmp_path, n_talks=2)
    audio_dir = tmp_path / "audio"
    output = tmp_path / "output.m4b"

    build_m4b(conference, audio_dir, output, None, _FFMPEG, _FFPROBE)

    result = subprocess.run(
        [str(_FFPROBE), "-v", "quiet", "-print_format", "json",
         "-show_chapters", str(output)],
        capture_output=True, text=True, check=True,
    )
    chapters = json.loads(result.stdout).get("chapters", [])
    for ch in chapters:
        title = ch.get("tags", {}).get("title", "")
        assert " -- " in title, \
            f"Chapter title should contain ' -- ': {title!r}"


@requires_ffmpeg
def test_build_m4b_with_cover_art(tmp_path: Path) -> None:
    from mutagen.mp4 import MP4

    conference = _make_conference(tmp_path, n_talks=2)
    audio_dir = tmp_path / "audio"
    output = tmp_path / "output.m4b"

    cover = tmp_path / "cover.jpg"
    img = Image.new("RGB", (100, 100), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    cover.write_bytes(buf.getvalue())

    build_m4b(conference, audio_dir, output, cover, _FFMPEG, _FFPROBE)

    mp4 = MP4(str(output))
    assert mp4.tags is not None and "covr" in mp4.tags, \
        "Cover art should be embedded in the m4b"


@requires_ffmpeg
def test_build_m4b_sets_duration_seconds(tmp_path: Path) -> None:
    conference = _make_conference(tmp_path, n_talks=2, duration=2.0)
    audio_dir = tmp_path / "audio"
    output = tmp_path / "output.m4b"

    build_m4b(conference, audio_dir, output, None, _FFMPEG, _FFPROBE)

    for talk in conference.talks:
        assert talk.duration_seconds > 0, \
            f"talk.duration_seconds should be set for {talk.title!r}"
        assert abs(talk.duration_seconds - 2.0) < 0.2, \
            f"Expected ~2.0s, got {talk.duration_seconds:.3f}s for {talk.title!r}"


@requires_ffmpeg
def test_build_m4b_skips_missing_mp3(tmp_path: Path) -> None:
    conference = _make_conference(tmp_path, n_talks=3)
    audio_dir = tmp_path / "audio"
    output = tmp_path / "output.m4b"

    # Remove the second talk's MP3
    mp3_to_remove = audio_dir / "002-Talk 2.mp3"
    mp3_to_remove.unlink()

    build_m4b(conference, audio_dir, output, None, _FFMPEG, _FFPROBE)

    assert output.exists(), "m4b should still be produced when one MP3 is missing"


@requires_ffmpeg
def test_build_m4b_chapter_boundaries_aligned(tmp_path: Path) -> None:
    """Chapter end timestamps must sum to within 1s of the m4b total duration.

    Catches the ADTS estimation bug: if per-talk durations are underestimated,
    the final chapter ends before the actual audio ends.
    """
    n = 3
    duration = 3.0
    conference = _make_conference(tmp_path, n_talks=n, duration=duration)
    audio_dir = tmp_path / "audio"
    output = tmp_path / "output.m4b"

    build_m4b(conference, audio_dir, output, None, _FFMPEG, _FFPROBE)

    # Get total m4b duration
    probe = subprocess.run(
        [str(_FFPROBE), "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(output)],
        capture_output=True, text=True, check=True,
    )
    total_s = float(probe.stdout.strip())

    # Get chapter metadata
    ch_result = subprocess.run(
        [str(_FFPROBE), "-v", "quiet", "-print_format", "json",
         "-show_chapters", str(output)],
        capture_output=True, text=True, check=True,
    )
    chapters = json.loads(ch_result.stdout).get("chapters", [])
    assert chapters, "Expected chapters in output m4b"

    last_end_s = float(chapters[-1]["end_time"])
    assert abs(last_end_s - total_s) < 1.0, (
        f"Last chapter end ({last_end_s:.3f}s) should be within 1s of "
        f"total m4b duration ({total_s:.3f}s); drift={total_s - last_end_s:.3f}s"
    )
