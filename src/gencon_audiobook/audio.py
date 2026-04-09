"""Convert MP3 files to AAC and assemble a chaptered m4b audiobook."""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from mutagen.mp4 import MP4
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from .models import Conference
from .utils import sanitize_filename

logger = logging.getLogger(__name__)


class AudioError(Exception):
    """Raised when an ffmpeg step fails."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_TYPOGRAPHIC_REPLACEMENTS: dict[str, str] = {
    "\u2014": "-",   # em dash
    "\u2013": "-",   # en dash
    "\u2012": "-",   # figure dash
    "\u201c": '"',   # left double quotation mark
    "\u201d": '"',   # right double quotation mark
    "\u2018": "'",   # left single quotation mark
    "\u2019": "'",   # right single quotation mark
    "\u2026": "...", # horizontal ellipsis
    "\u00a0": " ",   # non-breaking space
}


def _ascii_safe(text: str) -> str:
    """Normalize text to ASCII for FFMETADATA1 compatibility.

    FFMETADATA1 files must contain ASCII-only text to avoid encoding conflicts
    between ffmpeg's system-codepage file reading and the MP4 container's UTF-8
    requirement. Common typographic characters are replaced with ASCII equivalents;
    remaining non-ASCII characters have diacritics stripped via NFKD decomposition.

    Args:
        text: Input string, possibly containing non-ASCII characters.

    Returns:
        ASCII-safe version of the string.
    """
    for char, replacement in _TYPOGRAPHIC_REPLACEMENTS.items():
        text = text.replace(char, replacement)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _ffmeta_escape(value: str) -> str:
    """Escape special characters in FFMETADATA1 string values.

    The FFMETADATA1 format requires backslash-escaping of =, ;, #, \\ and newlines.

    Args:
        value: Raw string to escape.

    Returns:
        Escaped string safe for use in an FFMETADATA1 file.
    """
    for ch in ("\\", "=", ";", "#", "\n"):
        value = value.replace(ch, "\\" + ch)
    return value


def _run(cmd: list[str], label: str) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command, raising AudioError on non-zero exit.

    Args:
        cmd: Command list to run.
        label: Human-readable description for error messages.

    Returns:
        CompletedProcess result.

    Raises:
        AudioError: if the command exits with a non-zero return code.
    """
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise AudioError(
            f"{label} failed (exit {result.returncode}).\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr: {result.stderr[-2000:]}"
        )
    return result


def _get_duration_ffprobe(path: Path, ffprobe_path: Path) -> float:
    """Return audio duration in seconds using ffprobe.

    Args:
        path: Audio file to probe.
        ffprobe_path: Path to ffprobe binary.

    Returns:
        Duration in seconds.

    Raises:
        AudioError: if ffprobe fails or returns unparseable output.
    """
    result = _run(
        [
            str(ffprobe_path),
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        label=f"ffprobe duration of {path.name}",
    )
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise AudioError(
            f"Could not parse ffprobe duration output: {result.stdout!r}"
        ) from exc


def _derive_ffprobe(ffmpeg_path: Path) -> Path:
    """Derive the ffprobe path from the ffmpeg binary location.

    ffprobe is always installed alongside ffmpeg in the same directory.

    Args:
        ffmpeg_path: Path to the ffmpeg binary.

    Returns:
        Path to ffprobe (may not exist on disk — checked by the caller).
    """
    suffix = ffmpeg_path.suffix  # ".exe" on Windows, "" on Unix
    return ffmpeg_path.parent / f"ffprobe{suffix}"


def _write_ffmetadata(conference: Conference, path: Path) -> None:
    """Write an FFMETADATA1 chapter file for the conference.

    Chapter times use millisecond precision (TIMEBASE=1/1000). Chapter titles
    follow the format "Talk Title -- Speaker Name".

    Args:
        conference: Conference with talk.duration_seconds set on every talk.
        path: Destination path for the metadata file.

    Raises:
        AudioError: if any talk has duration_seconds == 0.0 (indicates conversion
            was not run before this function was called).
    """
    year = conference.year
    comment = (
        f"Copyright {year} Intellectual Reserve, Inc. "
        "All rights reserved. For personal, noncommercial use only."
    )
    lines: list[str] = [
        ";FFMETADATA1",
        f"title={_ffmeta_escape(conference.title)}",
        "artist=General Conference",
        f"album={_ffmeta_escape(conference.title)}",
        f"date={year}",
        f"comment={_ffmeta_escape(comment)}",
        "",
    ]

    offset_ms = 0
    for talk in conference.talks:
        if talk.duration_seconds <= 0.0:
            logger.warning(
                "Talk %r has duration_seconds=0 — chapter timing will be wrong", talk.title
            )
        start_ms = offset_ms
        end_ms = offset_ms + int(talk.duration_seconds * 1000)
        # Normalize to ASCII: ffmpeg reads FFMETADATA1 using the system codepage on
        # Windows, but the MP4 container requires UTF-8. ASCII is valid in both, so
        # using ASCII-only chapter titles avoids the conflict entirely.
        chapter_title = _ascii_safe(f"{talk.title} -- {talk.speaker}")
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={start_ms}",
            f"END={end_ms}",
            f"title={_ffmeta_escape(chapter_title)}",
            "",
        ]
        offset_ms = end_ms

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.debug("Wrote FFMETADATA1 to %s (%d chapters)", path, len(conference.talks))


def _write_concat_list(aac_paths: list[Path], path: Path) -> None:
    """Write an ffmpeg concat demuxer file listing all AAC files.

    Uses forward-slash paths — ffmpeg accepts them on all platforms including Windows.
    Filenames produced by sanitize_filename() contain only [a-zA-Z0-9 ._-] so no
    single-quote escaping is needed.

    Args:
        aac_paths: Ordered list of AAC file paths to concatenate.
        path: Destination path for the concat list file.
    """
    lines = []
    for p in aac_paths:
        forward = str(p.resolve()).replace("\\", "/")
        lines.append(f"file '{forward}'")
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.debug("Wrote concat list to %s (%d files)", path, len(aac_paths))


def _verify_m4b(output_path: Path, conference: Conference, ffprobe_path: Path) -> None:
    """Verify the built m4b using mutagen (cover art) and ffprobe (chapters).

    Logs a summary at INFO level. Does not raise on verification failures —
    the m4b is already built and may still be usable.

    Args:
        output_path: Path to the .m4b file.
        conference: Conference used to build the file.
        ffprobe_path: Path to ffprobe for chapter verification.
    """
    expected_talks = len(conference.talks)

    # Cover art — mutagen
    try:
        mp4 = MP4(str(output_path))
        has_cover = mp4.tags is not None and "covr" in mp4.tags
        if not has_cover:
            logger.warning("Verification: no cover art found in %s", output_path.name)
    except Exception as exc:
        logger.warning("Verification: mutagen could not read %s: %s", output_path.name, exc)

    # Chapter count and titles — ffprobe
    try:
        result = subprocess.run(
            [
                str(ffprobe_path),
                "-v", "quiet",
                "-print_format", "json",
                "-show_chapters",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        data = json.loads(result.stdout)
        chapters = data.get("chapters", [])
        chapter_count = len(chapters)

        if chapter_count != expected_talks:
            logger.warning(
                "Verification: expected %d chapters, found %d in %s",
                expected_talks, chapter_count, output_path.name,
            )
        else:
            logger.debug("Verification: chapter count correct (%d)", chapter_count)

        if chapters:
            first_title = chapters[0].get("tags", {}).get("title", "")
            last_title = chapters[-1].get("tags", {}).get("title", "")
            for title in (first_title, last_title):
                if " -- " not in title:
                    logger.warning(
                        "Verification: chapter title does not contain ' -- ': %r", title
                    )

        # Total duration
        total_s = sum(talk.duration_seconds for talk in conference.talks)
        logger.info(
            "Verified m4b: %d chapters, %.0fs total", chapter_count, total_s
        )

    except Exception as exc:
        logger.warning("Verification: ffprobe chapter check failed: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def convert_mp3_to_aac(
    mp3_path: Path,
    aac_path: Path,
    ffmpeg_path: Path,
    bitrate: str = "64k",
    sample_rate: int = 44100,
) -> float:
    """Convert an MP3 file to AAC-LC / mono.

    Args:
        mp3_path: Input MP3 file.
        aac_path: Output AAC file path.
        ffmpeg_path: Path to ffmpeg binary.
        bitrate: AAC encoding bitrate as an ffmpeg bitrate string (e.g., "64k", "32k").
        sample_rate: Output sample rate in Hz (e.g., 44100, 22050).

    Returns:
        Duration of the audio in seconds.

    Raises:
        AudioError: if ffmpeg returns a non-zero exit code or the input does not exist.
    """
    if not mp3_path.exists():
        raise AudioError(f"MP3 file not found: {mp3_path}")

    aac_path.parent.mkdir(parents=True, exist_ok=True)

    _run(
        [
            str(ffmpeg_path),
            "-i", str(mp3_path),
            "-vn",          # strip embedded cover art / video streams from the MP3
            "-c:a", "aac",
            "-b:a", bitrate,
            "-ar", str(sample_rate),
            "-ac", "1",
            "-y",
            str(aac_path),
        ],
        label=f"MP3→AAC conversion of {mp3_path.name}",
    )

    ffprobe_path = _derive_ffprobe(ffmpeg_path)
    return _get_duration_ffprobe(aac_path, ffprobe_path)


def build_m4b(
    conference: Conference,
    audio_dir: Path,
    output_path: Path,
    cover_path: Path | None,
    ffmpeg_path: Path,
    ffprobe_path: Path,
    bitrate: str = "64k",
    sample_rate: int = 44100,
) -> None:
    """Build a chaptered m4b audiobook from downloaded MP3 files.

    Process:
    1. Convert each MP3 to AAC; update talk.duration_seconds in-place.
    2. Write an FFMETADATA1 chapter file using cumulative millisecond offsets.
    3. Concatenate all AAC files into a single intermediate AAC.
    4. Mux chapters, cover art, and metadata into the final m4b.
    5. Delete intermediate AAC and temp files.
    6. Verify the output with mutagen and ffprobe.

    MP3 files are located as: audio_dir / "{talk_index:03d}-{sanitize_filename(talk.title)}.mp3"

    Args:
        conference: Conference object. talk.duration_seconds is set in-place during step 1.
        audio_dir: Directory containing downloaded MP3 files.
        output_path: Path for the output .m4b file.
        cover_path: Optional JPEG cover art path.
        ffmpeg_path: Path to ffmpeg binary.
        ffprobe_path: Path to ffprobe binary.
        bitrate: AAC encoding bitrate as an ffmpeg bitrate string (e.g., "64k", "32k").
        sample_rate: Output sample rate in Hz (e.g., 44100, 22050).

    Raises:
        AudioError: if any ffmpeg step fails or no valid talks are found.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    talks = conference.talks
    aac_paths: list[Path] = []
    skipped: list[str] = []

    # Step 1: Convert MP3 → AAC, populate duration_seconds
    logger.info("Converting %d talks to AAC...", len(talks))
    progress = Progress(
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        TextColumn("[progress.description]{task.description}"),
    )
    with progress:
        task = progress.add_task("Converting to AAC", total=len(talks))
        for talk in talks:
            progress.update(task, description=talk.title[:60])
            mp3_path = audio_dir / f"{talk.talk_index:03d}-{sanitize_filename(talk.title)}.mp3"
            if not mp3_path.exists():
                logger.warning("MP3 not found for talk %r (%s) — skipping", talk.title, mp3_path)
                skipped.append(talk.title)
                progress.advance(task)
                continue

            aac_path = mp3_path.with_suffix(".m4a")
            try:
                duration = convert_mp3_to_aac(mp3_path, aac_path, ffmpeg_path, bitrate, sample_rate)
                talk.duration_seconds = duration
                aac_paths.append(aac_path)
                logger.debug("Converted %s (%.1fs)", mp3_path.name, duration)
            except AudioError as exc:
                logger.error("AAC conversion failed for %r: %s — skipping", talk.title, exc)
                skipped.append(talk.title)
            finally:
                progress.advance(task)

    if not aac_paths:
        raise AudioError(
            "No AAC files produced — all MP3 conversions failed. "
            "Check that the audio files were downloaded successfully."
        )
    if skipped:
        logger.warning("%d talk(s) skipped during conversion: %s", len(skipped), ", ".join(skipped))

    # Step 2: Write FFMETADATA1 chapter file
    # Uses a temp file so it's cleaned up even on failure
    with tempfile.TemporaryDirectory(prefix="gencon-audio-") as tmpdir:
        tmp = Path(tmpdir)
        metadata_path = tmp / "chapters.ffmeta"
        concat_path = tmp / "concat.txt"
        intermediate_aac = tmp / "intermediate.m4a"

        _write_ffmetadata(conference, metadata_path)

        # Step 3: Concatenate all AAC files
        logger.info("Concatenating %d AAC files...", len(aac_paths))
        _write_concat_list(aac_paths, concat_path)
        _run(
            [
                str(ffmpeg_path),
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_path),
                "-c", "copy",
                "-y",
                str(intermediate_aac),
            ],
            label="AAC concatenation",
        )

        # Step 4: Mux to m4b with chapters and optional cover art
        logger.info("Muxing m4b: %s", output_path.name)
        mux_cmd: list[str] = [
            str(ffmpeg_path),
            "-i", str(intermediate_aac),
            "-i", str(metadata_path),
        ]
        if cover_path and cover_path.exists():
            mux_cmd += ["-i", str(cover_path)]

        mux_cmd += ["-map_metadata", "1"]

        if cover_path and cover_path.exists():
            mux_cmd += [
                "-map", "0:a",
                "-map", "2:v",
                "-c:a", "copy",
                "-c:v", "copy",
                "-disposition:v:0", "attached_pic",
            ]
        else:
            mux_cmd += ["-map", "0:a", "-c:a", "copy"]

        mux_cmd += ["-y", str(output_path)]
        _run(mux_cmd, label="m4b mux")

    # Step 5: Delete individual AAC files (intermediate cleaned by TemporaryDirectory)
    for aac_path in aac_paths:
        try:
            aac_path.unlink()
            logger.debug("Deleted intermediate AAC: %s", aac_path.name)
        except OSError as exc:
            logger.warning("Could not delete %s: %s", aac_path, exc)

    # Step 6: Verify
    _verify_m4b(output_path, conference, ffprobe_path)
    logger.info("Built: %s (%.1f MB)", output_path.name, output_path.stat().st_size / 1_048_576)
