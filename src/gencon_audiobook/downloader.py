"""Download MP3s, cover image, and speaker photos for a conference."""

from __future__ import annotations

import logging
import time
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from .models import Conference, Talk
from .utils import USER_AGENT, sanitize_filename, validate_url

logger = logging.getLogger(__name__)

_DOWNLOAD_CHUNK_SIZE = 65_536  # 64 KB chunks for streaming downloads
_JPEG_QUALITY = 85              # JPEG quality for converted images


class DownloadError(Exception):
    """Raised when a file download fails after all retries."""


def download_file(
    url: str,
    dest: Path,
    session: requests.Session,
    timeout: tuple[int, int] = (30, 120),
    retries: int = 3,
) -> None:
    """Download a single file to dest, using .tmp + rename for atomicity.

    Skips download if dest already exists with expected size (from Content-Length).
    Cleans up .tmp file on failure.

    Args:
        url: URL to download. Must pass validate_url().
        dest: Final destination path.
        session: requests.Session to use.
        timeout: (connect_timeout, read_timeout) in seconds.
        retries: Number of retry attempts with exponential backoff.

    Raises:
        DownloadError: if download fails after all retries.
        ValueError: if url fails validate_url().
    """
    if not validate_url(url):
        raise ValueError(f"URL not on allowlist: {url!r}")

    # Resume: skip if existing file matches expected Content-Length
    if dest.exists():
        try:
            head = session.head(url, timeout=timeout)
            expected = int(head.headers.get("Content-Length", -1))
            if expected > 0 and dest.stat().st_size == expected:
                logger.debug("Skipping %s — already downloaded (%d bytes)", dest.name, expected)
                return
        except Exception as exc:
            logger.debug("HEAD request failed for %s, re-downloading: %s", url, exc)

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        if attempt > 0:
            wait = 2 ** (attempt - 1)
            logger.debug("Retry %d for %s (waiting %ds)", attempt, url, wait)
            time.sleep(wait)

        try:
            logger.debug("Downloading: %s -> %s", url, dest)
            with session.get(url, timeout=timeout, stream=True) as resp:
                resp.raise_for_status()
                tmp.parent.mkdir(parents=True, exist_ok=True)
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                        if chunk:
                            fh.write(chunk)

            tmp.replace(dest)
            logger.debug("Downloaded: %s (%d bytes)", dest.name, dest.stat().st_size)
            return

        except Exception as exc:
            last_exc = exc
            logger.debug("Download attempt %d failed for %s: %s", attempt + 1, url, exc)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    raise DownloadError(
        f"Failed to download {url!r} after {retries} retries. Last error: {last_exc}"
    ) from last_exc


def _image_to_jpeg(data: bytes) -> bytes:
    """Convert raw image bytes to JPEG.

    Args:
        data: Raw image bytes (any Pillow-supported format).

    Returns:
        JPEG-encoded bytes.
    """
    with Image.open(BytesIO(data)) as raw:
        # Convert palette/transparency modes that JPEG can't handle.
        # PIL stubs type .convert() as Image.Image; cast via local var avoids
        # the ImageFile/Image mismatch that confuses mypy.
        img: Image.Image = raw.convert("RGB") if raw.mode != "RGB" else raw
        out = BytesIO()
        img.save(out, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return out.getvalue()


def _download_image(
    url: str,
    dest: Path,
    session: requests.Session,
    timeout: tuple[int, int] = (30, 120),
    retries: int = 3,
) -> None:
    """Download an image, convert to JPEG, and save to dest.

    Skips if dest already exists (images don't resume by size — content-identical
    re-downloads would waste Pillow conversion time for identical JPEGs).

    Args:
        url: Image URL. Must pass validate_url().
        dest: Final .jpg destination path.
        session: requests.Session to use.
        timeout: (connect_timeout, read_timeout) in seconds.
        retries: Number of retry attempts.

    Raises:
        DownloadError: if download or conversion fails after all retries.
        ValueError: if url fails validate_url().
    """
    if not validate_url(url):
        raise ValueError(f"URL not on allowlist: {url!r}")

    if dest.exists():
        logger.debug("Skipping image %s — already exists", dest.name)
        return

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        if attempt > 0:
            wait = 2 ** (attempt - 1)
            logger.debug("Retry %d for image %s (waiting %ds)", attempt, url, wait)
            time.sleep(wait)

        try:
            logger.debug("Downloading image: %s -> %s", url, dest)
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            jpeg_bytes = _image_to_jpeg(resp.content)
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(jpeg_bytes)
            tmp.replace(dest)
            logger.debug("Downloaded image: %s (%d bytes)", dest.name, dest.stat().st_size)
            return

        except Exception as exc:
            last_exc = exc
            logger.debug("Image download attempt %d failed for %s: %s", attempt + 1, url, exc)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    raise DownloadError(
        f"Failed to download image {url!r} after {retries} retries. Last error: {last_exc}"
    ) from last_exc


def cleanup_tmp_files(directory: Path) -> None:
    """Remove any leftover .tmp files in directory and its subdirectories.

    Call on startup to clean up partial downloads from a previous crash.

    Args:
        directory: Root directory to scan.
    """
    for tmp in directory.rglob("*.tmp"):
        try:
            tmp.unlink()
            logger.debug("Cleaned up leftover tmp file: %s", tmp)
        except OSError as exc:
            logger.warning("Could not remove tmp file %s: %s", tmp, exc)


def _make_session() -> requests.Session:
    """Create a requests.Session with the project User-Agent."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _audio_path(output_dir: Path, talk: Talk) -> Path:
    """Return the destination path for a talk's MP3."""
    name = sanitize_filename(talk.title)
    return output_dir / "audio" / f"{talk.talk_index:03d}-{name}.mp3"


def _speaker_path(output_dir: Path, talk: Talk) -> Path:
    """Return the destination path for a talk's speaker photo."""
    name = sanitize_filename(talk.speaker)
    return output_dir / "speakers" / f"{talk.talk_index:03d}-{name}.jpg"


def download_conference(
    conference: Conference,
    output_dir: Path,
    delay: float = 0.5,
    skip_audio: bool = False,
) -> list[Talk]:
    """Download all MP3s, cover image, and speaker photos for a conference.

    Files are downloaded to .tmp first, renamed on success. Existing files of
    the correct size are skipped (resume behavior). Speaker photos are converted
    to JPEG. Progress is shown via rich progress bars.

    Args:
        conference: Fully populated Conference object with mp3_urls set.
        output_dir: Directory to download into. Created if it doesn't exist.
        delay: Seconds to wait between HTTP requests.
        skip_audio: If True, skip MP3 downloads (for --epub-only mode).

    Returns:
        List of Talk objects whose audio download failed (empty if all succeeded).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_tmp_files(output_dir)

    session = _make_session()
    talks = conference.talks

    # Build download queue: (url, dest, label, is_image, talk_or_none)
    # talk_or_none is set for audio items so failed talks can be returned to the caller.
    queue: list[tuple[str, Path, str, bool, Talk | None]] = []

    if not skip_audio:
        for talk in talks:
            if talk.mp3_url:
                dest = _audio_path(output_dir, talk)
                queue.append((talk.mp3_url, dest, f"[audio] {talk.title[:50]}", False, talk))
            else:
                logger.warning("Talk %r has no mp3_url — skipping audio download", talk.title)

    if conference.cover_image_url:
        cover_dest = output_dir / "cover.jpg"
        queue.append((conference.cover_image_url, cover_dest, "[cover] cover.jpg", True, None))

    for talk in talks:
        if talk.speaker_image_url:
            dest = _speaker_path(output_dir, talk)
            queue.append((talk.speaker_image_url, dest, f"[photo] {talk.speaker[:40]}", True, None))

    if not queue:
        logger.info("Nothing to download.")
        return []

    logger.info(
        "Downloading %d file(s) for %s",
        len(queue),
        conference.title,
    )

    overall_progress = Progress(
        SpinnerColumn(),
        MofNCompleteColumn(),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeRemainingColumn(),
    )
    file_progress = Progress(
        SpinnerColumn(),
        MofNCompleteColumn(),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeRemainingColumn(),
    )

    failed: list[str] = []
    failed_talks: list[Talk] = []

    with overall_progress, file_progress:
        overall_task = overall_progress.add_task("Downloading files", total=len(queue))

        for url, dest, label, is_image, queue_talk in queue:
            overall_progress.update(overall_task, description=label)
            try:
                if is_image:
                    _download_image(url, dest, session, retries=3)
                else:
                    download_file(url, dest, session, retries=3)
                time.sleep(delay)
            except (DownloadError, ValueError) as exc:
                logger.error("Failed to download %s: %s", label, exc)
                failed.append(label)
                if queue_talk is not None:
                    failed_talks.append(queue_talk)
            finally:
                overall_progress.advance(overall_task)

    if failed:
        logger.warning(
            "%d file(s) failed to download and will be absent from output: %s",
            len(failed),
            ", ".join(failed),
        )

    return failed_talks
