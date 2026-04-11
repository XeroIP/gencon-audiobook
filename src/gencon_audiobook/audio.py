"""Convert MP3 files to AAC and assemble a chaptered m4b audiobook."""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from mutagen.mp4 import MP4
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
)

from .models import Conference, Talk
from .progress import TimeRemainingWithLabel
from .utils import sanitize_filename

logger = logging.getLogger(__name__)


class AudioError(Exception):
    """Raised when an ffmpeg step fails."""


@dataclass
class BuildStats:
    """Quality and chapter statistics returned by build_m4b.

    Attributes:
        source_bitrate: Detected bitrate of the source MP3s (e.g., "128k").
        source_sample_rate: Detected sample rate of the source MP3s in Hz.
        output_bitrate: AAC encoding bitrate used (e.g., "128k").
        output_sample_rate: AAC sample rate used in Hz.
        chapter_count: Number of chapters written to the m4b.
        duration_seconds: Total audio duration in seconds.
    """

    source_bitrate: str
    source_sample_rate: int
    output_bitrate: str
    output_sample_rate: int
    chapter_count: int
    duration_seconds: float


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
    result = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    # If all characters were non-ASCII (e.g., non-Latin scripts), fall back to the
    # original text so the chapter title is not silently emptied.
    return result if result.strip() else text


def _ffmeta_escape(value: str) -> str:
    """Escape special characters in FFMETADATA1 string values.

    The FFMETADATA1 format requires backslash-escaping of =, ;, #, \\ and newlines.

    Args:
        value: Raw string to escape.

    Returns:
        Escaped string safe for use in an FFMETADATA1 file.
    """
    for ch in ("\\", "=", ";", "#", "\n", "\r"):
        value = value.replace(ch, "\\" + ch)
    return value


_SUBPROCESS_TIMEOUT = 600   # 10 minutes — generous for large conference builds
_FALLBACK_BITRATE = "64k"   # used when ffprobe quality probe fails
_FALLBACK_SAMPLE_RATE = 44100  # used when ffprobe quality probe fails


def _run(cmd: list[str], label: str) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command, raising AudioError on non-zero exit or timeout.

    Args:
        cmd: Command list to run.
        label: Human-readable description for error messages.

    Returns:
        CompletedProcess result.

    Raises:
        AudioError: if the command exits with a non-zero return code or times out.
    """
    logger.debug("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise AudioError(
            f"{label} timed out after {_SUBPROCESS_TIMEOUT}s. "
            f"The ffmpeg process was killed. Try with fewer talks or check for corrupt MP3 files."
        )
    if result.returncode != 0:
        raise AudioError(
            f"{label} failed (exit {result.returncode}).\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr: {result.stderr[-2000:]}"
        )
    return result


def _run_ffmpeg_with_progress(
    cmd: list[str],
    label: str,
    source_duration_s: float,
    progress: Progress,
    task_id: TaskID,
) -> None:
    """Run an ffmpeg command, updating a Rich progress task as encoding proceeds.

    The command must already include `-progress pipe:1 -nostats` so ffmpeg writes
    key=value progress lines to stdout. A watchdog timer kills the process if it
    exceeds _SUBPROCESS_TIMEOUT seconds without finishing.

    Args:
        cmd: Complete ffmpeg command including -progress pipe:1 -nostats flags.
        label: Human-readable description for error messages.
        source_duration_s: Source audio duration in seconds (used as progress total).
        progress: Rich Progress instance to update.
        task_id: Task ID within progress to update.

    Raises:
        AudioError: if ffmpeg exits with non-zero code or the watchdog kills it.
    """
    logger.debug("Running (streaming): %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    killed_by_watchdog = False

    def _watchdog() -> None:
        nonlocal killed_by_watchdog
        if proc.poll() is None:
            killed_by_watchdog = True
            proc.kill()

    timer = threading.Timer(_SUBPROCESS_TIMEOUT, _watchdog)
    timer.start()
    try:
        assert proc.stdout is not None  # guaranteed by stdout=PIPE
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    seconds = min(us / 1_000_000, source_duration_s)
                    progress.update(task_id, completed=seconds)
                except (ValueError, IndexError):
                    pass
            elif line == "progress=end":
                break
    finally:
        timer.cancel()

    proc.wait()

    if killed_by_watchdog:
        raise AudioError(
            f"{label} timed out after {_SUBPROCESS_TIMEOUT}s. "
            "The ffmpeg process was killed. Try with fewer talks or check for corrupt MP3 files."
        )

    if proc.returncode != 0:
        stderr = ""
        if proc.stderr:
            stderr = proc.stderr.read()
        raise AudioError(
            f"{label} failed (exit {proc.returncode}).\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr: {stderr[-2000:]}"
        )


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


def _probe_source_quality(mp3_path: Path, ffprobe_path: Path) -> tuple[str, int]:
    """Detect the bitrate and sample rate of a source MP3 using ffprobe.

    Used to match AAC output quality to the source rather than applying a
    fixed default. On failure, logs a warning and returns safe defaults.

    Args:
        mp3_path: Source MP3 file to probe.
        ffprobe_path: Path to ffprobe binary.

    Returns:
        Tuple of (bitrate_str, sample_rate_int), e.g. ("128k", 44100).
        Falls back to ("64k", 44100) if probing fails.
    """
    try:
        result = _run(
            [
                str(ffprobe_path),
                "-v", "quiet",
                "-select_streams", "a:0",
                "-show_entries", "stream=bit_rate,sample_rate",
                "-of", "default=noprint_wrappers=1",
                str(mp3_path),
            ],
            label=f"ffprobe quality of {mp3_path.name}",
        )
        bit_rate: int | None = None
        sample_rate: int | None = None
        for line in result.stdout.splitlines():
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key == "bit_rate" and val.strip().isdigit():
                bit_rate = int(val.strip())
            elif key == "sample_rate" and val.strip().isdigit():
                sample_rate = int(val.strip())

        if bit_rate and sample_rate:
            # Round to nearest standard bitrate string (e.g. 128000 -> "128k")
            bitrate_str = f"{round(bit_rate / 1000)}k"
            return bitrate_str, sample_rate

        logger.warning(
            "Could not parse quality from %s (bit_rate=%r, sample_rate=%r) "
            "— falling back to %s/%d",
            mp3_path.name, bit_rate, sample_rate, _FALLBACK_BITRATE, _FALLBACK_SAMPLE_RATE,
        )
    except (AudioError, OSError) as exc:
        # OSError covers FileNotFoundError when the ffprobe binary itself is missing.
        logger.warning(
            "ffprobe quality probe failed for %s: %s — falling back to %s/%d",
            mp3_path.name, exc, _FALLBACK_BITRATE, _FALLBACK_SAMPLE_RATE,
        )
    return _FALLBACK_BITRATE, _FALLBACK_SAMPLE_RATE


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


def _write_ffmetadata(conference: Conference, talks: list[Talk], path: Path) -> None:
    """Write an FFMETADATA1 chapter file for the conference.

    Chapter times use millisecond precision (TIMEBASE=1/1000). Chapter titles
    follow the format "Talk Title -- Speaker Name".

    Only the talks that were successfully converted should be passed — omitting
    failed talks prevents ghost zero-length chapters from appearing in players.

    Args:
        conference: Conference object (used for title, year, copyright metadata).
        talks: Successfully converted talks with duration_seconds set.
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
    for talk in talks:
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
    logger.debug("Wrote FFMETADATA1 to %s (%d chapters)", path, len(talks))


def _write_concat_list(aac_paths: list[Path], path: Path) -> None:
    """Write an ffmpeg concat demuxer file listing all AAC files.

    Uses forward-slash paths — ffmpeg accepts them on all platforms including Windows.
    Filenames produced by sanitize_filename() contain only [a-zA-Z0-9 ._-], but the
    parent directory path (e.g., the user's home dir) may contain single quotes.
    Single quotes are escaped as '\\'' for the ffmpeg concat demuxer format.

    Args:
        aac_paths: Ordered list of AAC file paths to concatenate.
        path: Destination path for the concat list file.
    """
    lines = []
    for p in aac_paths:
        # Replace backslashes first, then escape any single quotes in the full path.
        forward = str(p.resolve()).replace("\\", "/").replace("'", "'\\''")
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
    ffprobe_path: Path,
    bitrate: str = "64k",
    sample_rate: int = 44100,
    *,
    source_duration_s: float | None = None,
    progress: Progress | None = None,
    progress_task_id: TaskID | None = None,
) -> float:
    """Convert an MP3 file to AAC-LC / mono.

    When source_duration_s, progress, and progress_task_id are all provided, uses
    ffmpeg's -progress flag to stream encoding progress to the Rich task in real time.
    Falls back to a simple blocking call if -progress is unsupported.

    Args:
        mp3_path: Input MP3 file.
        aac_path: Output AAC file path.
        ffmpeg_path: Path to ffmpeg binary.
        ffprobe_path: Path to ffprobe binary.
        bitrate: AAC encoding bitrate as an ffmpeg bitrate string (e.g., "64k", "32k").
        sample_rate: Output sample rate in Hz (e.g., 44100, 22050).
        source_duration_s: Source duration in seconds for the inner progress bar total.
        progress: Rich Progress instance to update during encoding.
        progress_task_id: Task ID within progress to update.

    Returns:
        Duration of the audio in seconds.

    Raises:
        AudioError: if ffmpeg returns a non-zero exit code or the input does not exist.
    """
    if not mp3_path.exists():
        raise AudioError(f"MP3 file not found: {mp3_path}")

    aac_path.parent.mkdir(parents=True, exist_ok=True)

    label = f"MP3→AAC conversion of {mp3_path.name}"
    base_cmd = [
        str(ffmpeg_path),
        "-i", str(mp3_path),
        "-vn",          # strip embedded cover art / video streams from the MP3
        "-c:a", "aac",
        "-b:a", bitrate,
        "-ar", str(sample_rate),
        "-ac", "1",
        "-y",
        str(aac_path),
    ]

    use_progress = (
        source_duration_s is not None
        and source_duration_s > 0
        and progress is not None
        and progress_task_id is not None
    )

    if use_progress:
        assert source_duration_s is not None
        assert progress is not None
        assert progress_task_id is not None
        # Insert -progress and -nostats right after the ffmpeg binary
        progress_cmd = [base_cmd[0], "-progress", "pipe:1", "-nostats"] + base_cmd[1:]
        try:
            _run_ffmpeg_with_progress(progress_cmd, label, source_duration_s, progress, progress_task_id)
        except AudioError:
            # -progress may not be supported by this ffmpeg build; retry without it
            logger.warning(
                "ffmpeg -progress streaming failed for %s — falling back to non-streaming mode",
                mp3_path.name,
            )
            _run(base_cmd, label=label)
    else:
        _run(base_cmd, label=label)

    return _get_duration_ffprobe(aac_path, ffprobe_path)


def build_m4b(
    conference: Conference,
    audio_dir: Path,
    output_path: Path,
    cover_path: Path | None,
    ffmpeg_path: Path,
    ffprobe_path: Path,
    bitrate: str | None = None,
    sample_rate: int | None = None,
) -> BuildStats:
    """Build a chaptered m4b audiobook from downloaded MP3 files.

    Process:
    1. Probe the first MP3 to detect source bitrate/sample_rate (unless overridden).
    2. Convert each MP3 to AAC; update talk.duration_seconds in-place.
    3. Write an FFMETADATA1 chapter file using cumulative millisecond offsets.
    4. Concatenate all AAC files into a single intermediate AAC.
    5. Mux chapters, cover art, and metadata into the final m4b.
    6. Delete intermediate AAC and temp files.
    7. Verify the output with mutagen and ffprobe.

    MP3 files are located as: audio_dir / "{talk_index:03d}-{sanitize_filename(talk.title)}.mp3"

    Args:
        conference: Conference object. talk.duration_seconds is set in-place during step 2.
        audio_dir: Directory containing downloaded MP3 files.
        output_path: Path for the output .m4b file.
        cover_path: Optional JPEG cover art path.
        ffmpeg_path: Path to ffmpeg binary.
        ffprobe_path: Path to ffprobe binary.
        bitrate: AAC encoding bitrate (e.g., "64k", "128k"). Defaults to source bitrate.
        sample_rate: Output sample rate in Hz. Defaults to source sample rate.

    Returns:
        BuildStats with source/output quality and chapter statistics.

    Raises:
        AudioError: if any ffmpeg step fails or no valid talks are found.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    talks = conference.talks
    aac_paths: list[Path] = []
    successful_talks: list[Talk] = []
    skipped: list[str] = []

    # Tracked separately so BuildStats can report source quality vs. output quality.
    source_bitrate: str | None = None
    source_sample_rate: int | None = None

    # Step 1: Auto-detect source quality unless the caller explicitly overrode it.
    # Probe the first available MP3 — all talks in a conference come from the same
    # source pipeline and share the same bitrate/sample_rate.
    first_mp3 = next(
        (
            audio_dir / f"{t.talk_index:03d}-{sanitize_filename(t.title)}.mp3"
            for t in talks
            if (audio_dir / f"{t.talk_index:03d}-{sanitize_filename(t.title)}.mp3").exists()
        ),
        None,
    )
    if first_mp3 is not None:
        detected_bitrate, detected_sample_rate = _probe_source_quality(first_mp3, ffprobe_path)
        source_bitrate = detected_bitrate
        source_sample_rate = detected_sample_rate
        if bitrate is None:
            bitrate = detected_bitrate
        if sample_rate is None:
            sample_rate = detected_sample_rate
        logger.info("Source quality: %s / %d Hz", bitrate, sample_rate)
    # Final fallback if no MP3s exist yet or probe returned nothing
    bitrate = bitrate or _FALLBACK_BITRATE
    sample_rate = sample_rate or _FALLBACK_SAMPLE_RATE
    # If probe failed entirely, report source quality == output quality
    source_bitrate = source_bitrate or bitrate
    source_sample_rate = source_sample_rate or sample_rate

    # Step 2: Convert MP3 → AAC, populate duration_seconds
    logger.info("Converting %d talks to AAC...", len(talks))
    conv_progress = Progress(
        SpinnerColumn(),
        MofNCompleteColumn(),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingWithLabel(compact=True),
        TextColumn("[progress.description]{task.description}"),
    )
    with conv_progress:
        outer_task = conv_progress.add_task("Converting to AAC", total=len(talks))
        inner_task = conv_progress.add_task("", total=1.0, visible=False)
        for talk in talks:
            conv_progress.update(outer_task, description=talk.title[:60])
            mp3_path = audio_dir / f"{talk.talk_index:03d}-{sanitize_filename(talk.title)}.mp3"
            if not mp3_path.exists():
                logger.warning("MP3 not found for talk %r (%s) — skipping", talk.title, mp3_path)
                skipped.append(talk.title)
                conv_progress.advance(outer_task)
                continue

            # Probe source duration for the inner per-file progress bar.
            source_dur: float | None = None
            try:
                source_dur = _get_duration_ffprobe(mp3_path, ffprobe_path)
                conv_progress.update(
                    inner_task,
                    completed=0,
                    total=source_dur,
                    visible=True,
                    description="Converting...",
                )
            except AudioError:
                conv_progress.update(inner_task, visible=False)

            aac_path = mp3_path.with_suffix(".m4a")
            try:
                duration = convert_mp3_to_aac(
                    mp3_path, aac_path, ffmpeg_path, ffprobe_path, bitrate, sample_rate,
                    source_duration_s=source_dur,
                    progress=conv_progress,
                    progress_task_id=inner_task,
                )
                talk.duration_seconds = duration
                aac_paths.append(aac_path)
                successful_talks.append(talk)
                logger.debug("Converted %s (%.1fs)", mp3_path.name, duration)
            except AudioError as exc:
                logger.error("AAC conversion failed for %r: %s — skipping", talk.title, exc)
                skipped.append(talk.title)
            finally:
                conv_progress.update(inner_task, visible=False)
                conv_progress.advance(outer_task)

    if not aac_paths:
        raise AudioError(
            "No AAC files produced — all MP3 conversions failed. "
            "Check that the audio files were downloaded successfully."
        )
    if skipped:
        logger.warning("%d talk(s) skipped during conversion: %s", len(skipped), ", ".join(skipped))

    # Step 3: Write FFMETADATA1 chapter file
    # Uses a temp file so it's cleaned up even on failure
    with tempfile.TemporaryDirectory(prefix="gencon-audio-") as tmpdir:
        tmp = Path(tmpdir)
        metadata_path = tmp / "chapters.ffmeta"
        concat_path = tmp / "concat.txt"
        intermediate_aac = tmp / "intermediate.m4a"

        _write_ffmetadata(conference, successful_talks, metadata_path)

        # Step 4: Concatenate all AAC files
        logger.info("Concatenating %d AAC files...", len(aac_paths))
        _write_concat_list(aac_paths, concat_path)
        _spinner_progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
        )
        with _spinner_progress:
            _spinner_progress.add_task(f"Concatenating {len(aac_paths)} AAC files...")
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

        # Step 5: Mux to m4b with chapters and optional cover art
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
        _spinner_progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
        )
        with _spinner_progress:
            _spinner_progress.add_task(f"Muxing m4b: {output_path.name}")
            _run(mux_cmd, label="m4b mux")

    # Step 6: Delete individual AAC files (intermediate cleaned by TemporaryDirectory)
    for aac_path in aac_paths:
        try:
            aac_path.unlink()
            logger.debug("Deleted intermediate AAC: %s", aac_path.name)
        except OSError as exc:
            logger.warning("Could not delete %s: %s", aac_path, exc)

    # Step 7: Verify
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as sp:
        sp.add_task(f"Verifying m4b: {output_path.name}")
        _verify_m4b(output_path, conference, ffprobe_path)
    logger.info("Built: %s (%.1f MB)", output_path.name, output_path.stat().st_size / 1_048_576)

    return BuildStats(
        source_bitrate=source_bitrate,
        source_sample_rate=source_sample_rate,
        output_bitrate=bitrate,
        output_sample_rate=sample_rate,
        chapter_count=len(successful_talks),
        duration_seconds=sum(t.duration_seconds for t in successful_talks),
    )
