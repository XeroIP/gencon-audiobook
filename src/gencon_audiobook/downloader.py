"""Download MP3s, cover image, and speaker photos for a conference."""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import cast

import requests
from PIL import Image

from .models import Conference, Talk
from .progress import shared_console as _console
from .progress import standard_progress
from .utils import USER_AGENT, sanitize_filename, validate_url

logger = logging.getLogger(__name__)

_DOWNLOAD_CHUNK_SIZE = 65_536  # 64 KB chunks for streaming downloads
_JPEG_QUALITY = 85              # JPEG quality for converted images
_IMAGE_WORKERS = 8              # concurrent image download threads
_VIDEO_EXTRACT_TIMEOUT = 60 * 60 * 2

# Thread-local storage so each worker gets its own requests.Session.
# requests.Session is NOT thread-safe; sharing one across threads causes
# intermittent connection errors and garbled responses.
_thread_locals: threading.local = threading.local()


class DownloadError(Exception):
    """Raised when a file download fails after all retries."""


@dataclass
class DownloadResult:
    """Results returned by download_conference()."""

    failed_talks: list[Talk] = field(default_factory=list)
    downloaded: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class _DownloadItem:
    """One queued download or extraction operation."""

    url: str
    dest: Path
    label: str
    is_image: bool
    talk: Talk | None = None
    fallback_url: str | None = None
    fallback_dest: Path | None = None


@dataclass(frozen=True)
class AudioProbe:
    """Remote media probe details needed for quality comparison and estimates."""

    audio_bitrate_bps: int | None
    duration_seconds: float | None
    total_bitrate_bps: int | None


def _probe_audio_info(url: str, ffprobe_path: Path) -> AudioProbe:
    """Probe a remote media URL with ffprobe.

    ffprobe uses HTTP range requests for MP3/MP4 metadata, so this does not
    download the full file.
    """
    if not validate_url(url):
        raise ValueError(f"URL not on allowlist: {url!r}")

    try:
        result = subprocess.run(
            [
                str(ffprobe_path),
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-show_format",
                "-select_streams", "a:0",
                url,
            ],
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise DownloadError(f"ffprobe failed for {url!r}: {exc}") from exc
    streams = data.get("streams", [])
    audio_stream = streams[0] if streams else {}
    fmt = data.get("format", {})

    audio_bitrate = _parse_int(audio_stream.get("bit_rate"))
    duration = _parse_float(audio_stream.get("duration")) or _parse_float(fmt.get("duration"))
    total_bitrate = _parse_int(fmt.get("bit_rate")) or audio_bitrate
    return AudioProbe(audio_bitrate, duration, total_bitrate)


def _parse_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _parse_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def download_file(
    url: str,
    dest: Path,
    session: requests.Session,
    timeout: tuple[int, int] = (30, 120),
    retries: int = 3,
) -> bool:
    """Download a single file to dest, using .tmp + rename for atomicity.

    Skips download if dest already exists with expected size (from Content-Length).
    Cleans up .tmp file on failure.

    Args:
        url: URL to download. Must pass validate_url().
        dest: Final destination path.
        session: requests.Session to use.
        timeout: (connect_timeout, read_timeout) in seconds.
        retries: Number of retry attempts with exponential backoff.

    Returns:
        True if the file was downloaded, False if it was skipped (already present).

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
                return False
        except (OSError, requests.RequestException, ValueError) as exc:
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
            return True

        except (OSError, requests.RequestException) as exc:
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
) -> bool:
    """Download an image, convert to JPEG, and save to dest.

    Skips if dest already exists (images don't resume by size — content-identical
    re-downloads would waste Pillow conversion time for identical JPEGs).

    Args:
        url: Image URL. Must pass validate_url().
        dest: Final .jpg destination path.
        session: requests.Session to use.
        timeout: (connect_timeout, read_timeout) in seconds.
        retries: Number of retry attempts.

    Returns:
        True if the image was downloaded, False if it was skipped (already present).

    Raises:
        DownloadError: if download or conversion fails after all retries.
        ValueError: if url fails validate_url().
    """
    if not validate_url(url):
        raise ValueError(f"URL not on allowlist: {url!r}")

    if dest.exists():
        logger.debug("Skipping image %s — already exists", dest.name)
        return False

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
            return True

        except (OSError, requests.RequestException) as exc:
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


def _get_thread_session() -> requests.Session:
    """Return the requests.Session for the current thread, creating it on first access.

    Each thread gets its own Session because requests.Session is not thread-safe.
    """
    if not hasattr(_thread_locals, "session"):
        _thread_locals.session = _make_session()
    # threading.local attributes are typed as Any; cast makes the return type explicit.
    return cast(requests.Session, _thread_locals.session)


def _audio_path(output_dir: Path, talk: Talk) -> Path:
    """Return the destination path for a talk's MP3."""
    name = sanitize_filename(talk.title)
    return output_dir / "audio" / f"{talk.talk_index:03d}-{name}.mp3"


def _video_audio_path(output_dir: Path, talk: Talk) -> Path:
    """Return the destination path for extracted video audio."""
    return _audio_path(output_dir, talk).with_suffix(".m4a")


def _extract_video_audio(video_url: str, dest: Path, ffmpeg_path: Path) -> bool:
    """Extract AAC audio from a remote MP4 video URL into dest."""
    if not validate_url(video_url):
        raise ValueError(f"URL not on allowlist: {video_url!r}")
    if dest.exists():
        logger.debug("Skipping video audio %s — already extracted", dest.name)
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    cmd = [
        str(ffmpeg_path),
        "-nostdin",
        "-i", video_url,
        "-vn",
        "-acodec", "copy",
        "-f", "ipod",
        "-y",
        str(tmp),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_VIDEO_EXTRACT_TIMEOUT,
        )
        if result.returncode != 0:
            raise DownloadError(
                f"ffmpeg video audio extraction failed for {video_url!r}: "
                f"{result.stderr[-2000:]}"
            )
        tmp.replace(dest)
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        raise DownloadError(f"Failed to extract video audio from {video_url!r}: {exc}") from exc
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _speaker_path(output_dir: Path, talk: Talk) -> Path:
    """Return the destination path for a talk's speaker photo."""
    name = sanitize_filename(talk.speaker)
    return output_dir / "speakers" / f"{talk.talk_index:03d}-{name}.jpg"


def _inline_image_path(output_dir: Path, talk: Talk, asset_id: str) -> Path:
    """Return the destination path for an inline body image."""
    safe_id = sanitize_filename(asset_id)
    return output_dir / "inline" / f"{talk.talk_index:03d}-{safe_id}.jpg"


def conference_downloads_complete(
    conference: Conference,
    output_dir: Path,
    skip_audio: bool = False,
    prefer_video_audio: bool = False,
) -> bool:
    """Return True when every file download_conference would queue already exists."""
    expected: list[Path] = []

    if not skip_audio:
        for talk in conference.talks:
            if prefer_video_audio and talk.video_url:
                expected.append(_video_audio_path(output_dir, talk))
            elif talk.mp3_url:
                expected.append(_audio_path(output_dir, talk))

    if conference.cover_image_url:
        expected.append(output_dir / "cover.jpg")

    for talk in conference.talks:
        if talk.speaker_image_url:
            expected.append(_speaker_path(output_dir, talk))
        expected.extend(
            _inline_image_path(output_dir, talk, img.asset_id)
            for img in talk.inline_images
        )

    return bool(expected) and all(path.exists() for path in expected)


def download_conference(
    conference: Conference,
    output_dir: Path,
    delay: float = 0.5,
    skip_audio: bool = False,
    prefer_video_audio: bool = False,
    ffmpeg_path: Path | None = None,
) -> DownloadResult:
    """Download all MP3s, cover image, and speaker photos for a conference.

    Files are downloaded to .tmp first, renamed on success. Existing files of
    the correct size are skipped (resume behavior). Speaker photos are converted
    to JPEG. Progress is shown via rich progress bars only when files actually
    need downloading.

    Args:
        conference: Fully populated Conference object with mp3_urls set.
        output_dir: Directory to download into. Created if it doesn't exist.
        delay: Seconds to wait between audio HTTP requests.
        skip_audio: If True, skip MP3 downloads (for --epub-only mode).
        prefer_video_audio: If True, extract audio from talk.video_url when present.
        ffmpeg_path: Required when prefer_video_audio is True.

    Returns:
        DownloadResult with counts of downloaded/skipped files and any failed talks.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_tmp_files(output_dir)
    if prefer_video_audio and ffmpeg_path is None:
        raise ValueError("ffmpeg_path is required when prefer_video_audio=True")

    session = _make_session()
    talks = conference.talks

    # talk is set for audio items so failed talks can be returned to the caller.
    queue: list[_DownloadItem] = []

    if not skip_audio:
        for talk in talks:
            if prefer_video_audio and talk.video_url:
                dest = _video_audio_path(output_dir, talk)
                queue.append(_DownloadItem(
                    url=talk.video_url,
                    dest=dest,
                    label=f"[video audio] {talk.title[:50]}",
                    is_image=False,
                    talk=talk,
                    fallback_url=talk.mp3_url,
                    fallback_dest=_audio_path(output_dir, talk) if talk.mp3_url else None,
                ))
            elif talk.mp3_url:
                dest = _audio_path(output_dir, talk)
                queue.append(_DownloadItem(
                    url=talk.mp3_url,
                    dest=dest,
                    label=f"[audio] {talk.title[:50]}",
                    is_image=False,
                    talk=talk,
                ))
            else:
                logger.warning("Talk %r has no mp3_url — skipping audio download", talk.title)

    if conference.cover_image_url:
        cover_dest = output_dir / "cover.jpg"
        queue.append(_DownloadItem(conference.cover_image_url, cover_dest, "[cover] cover.jpg", True))

    for talk in talks:
        if talk.speaker_image_url:
            dest = _speaker_path(output_dir, talk)
            queue.append(_DownloadItem(talk.speaker_image_url, dest, f"[photo] {talk.speaker[:40]}", True))

    for talk in talks:
        for img in talk.inline_images:
            dest = _inline_image_path(output_dir, talk, img.asset_id)
            queue.append(_DownloadItem(img.url, dest, f"[image] {img.asset_id[:40]}", True))

    if not queue:
        logger.info("Nothing to download.")
        return DownloadResult()

    # Pre-scan: count locally present files without making HEAD requests.
    # This is an approximation — audio files are further verified by Content-Length
    # inside download_file, but the pre-scan is cheap and accurate enough for UX.
    pre_exists = sum(1 for item in queue if item.dest.exists())
    needs_download = len(queue) - pre_exists

    if needs_download == 0:
        logger.debug("All %d files already present — skipping download phase.", len(queue))
        return DownloadResult(skipped=len(queue))

    image_queue = [item for item in queue if item.is_image]
    audio_queue = [item for item in queue if not item.is_image]
    needed_audio = sum(1 for item in audio_queue if not item.dest.exists())
    needed_images = sum(1 for item in image_queue if not item.dest.exists())
    breakdown = f"{needed_audio} audio, {needed_images} image(s)"
    if pre_exists > 0:
        _console.print(
            f"Downloading {needs_download} of {len(queue)} files "
            f"({breakdown}; {pre_exists} already present)..."
        )
    else:
        _console.print(f"Downloading {len(queue)} files ({breakdown})...")

    logger.debug(
        "Download queue: %d audio, %d image(s)",
        len(audio_queue),
        len(image_queue),
    )

    overall_progress = standard_progress()

    failed: list[str] = []
    failed_talks: list[Talk] = []
    downloaded = 0
    skipped = 0

    with overall_progress:
        overall_task = overall_progress.add_task("Downloading files", total=len(queue))

        # Images: parallel downloads via ThreadPoolExecutor.
        # Each worker creates its own session via _get_thread_session() because
        # requests.Session is not thread-safe.
        if image_queue:

            def _download_one_image(item: _DownloadItem) -> tuple[bool, str | None]:
                """Worker: download one image. Returns (was_downloaded, label_on_failure)."""
                try:
                    was_downloaded = _download_image(
                        item.url, item.dest, _get_thread_session(), retries=3
                    )
                    return was_downloaded, None
                except (DownloadError, ValueError) as exc:
                    logger.error("Failed to download %s: %s", item.label, exc)
                    return False, item.label
                finally:
                    overall_progress.advance(overall_task)

            workers = min(_IMAGE_WORKERS, len(image_queue))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_download_one_image, item): item for item in image_queue}
                for future in as_completed(futures):
                    was_downloaded, error_label = future.result()
                    if error_label is not None:
                        failed.append(error_label)
                    elif was_downloaded:
                        downloaded += 1
                    else:
                        skipped += 1

        # Audio: sequential with courtesy delay between requests.
        # MP3s are large; parallel streaming of many large files simultaneously
        # would be impolite to the server and offers little wall-clock benefit
        # since the bottleneck is bandwidth, not latency.
        for item in audio_queue:
            overall_progress.update(overall_task, description=item.label)
            try:
                if item.dest.suffix == ".m4a":
                    assert ffmpeg_path is not None
                    try:
                        was_downloaded = _extract_video_audio(item.url, item.dest, ffmpeg_path)
                    except (DownloadError, ValueError) as exc:
                        if item.fallback_url is None or item.fallback_dest is None:
                            raise
                        logger.warning(
                            "Video audio extraction failed for %r; falling back to MP3: %s",
                            item.talk.title if item.talk else item.label,
                            exc,
                        )
                        was_downloaded = download_file(
                            item.fallback_url, item.fallback_dest, session, retries=3
                        )
                else:
                    was_downloaded = download_file(item.url, item.dest, session, retries=3)
                if was_downloaded:
                    downloaded += 1
                    time.sleep(delay)
                else:
                    skipped += 1
            except (DownloadError, ValueError) as exc:
                logger.error("Failed to download %s: %s", item.label, exc)
                failed.append(item.label)
                if item.talk is not None:
                    failed_talks.append(item.talk)
            finally:
                overall_progress.advance(overall_task)

    if failed:
        logger.warning(
            "%d file(s) failed to download and will be absent from output: %s",
            len(failed),
            ", ".join(failed),
        )

    return DownloadResult(failed_talks=failed_talks, downloaded=downloaded, skipped=skipped)
