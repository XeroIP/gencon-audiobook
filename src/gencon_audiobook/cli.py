"""CLI entry point for gencon-audiobook."""

from __future__ import annotations

import logging
import shutil
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn

from . import __version__
from .audio import AudioError, BuildStats, build_m4b
from .cache import CACHE_FILENAME, load_cache, save_cache
from .downloader import DownloadError, download_conference
from .epub_builder import EpubError, build_epub
from .ffmpeg_manager import FfmpegNotFoundError, ensure_ffmpeg, ensure_ffprobe
from .models import Talk
from .scraper import ScraperError, fetch_available_conferences, scrape_conference

logger = logging.getLogger(__name__)

_LOG_FILENAME = "gencon-audiobook.log"
_MIN_PYTHON = (3, 10)
_DISK_WARN_MB = 500

# Module-level console so helpers can print without threading a Console argument.
console = Console()


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool) -> None:
    """Configure console logging using Rich.

    Args:
        verbose: If True, show DEBUG messages on the console; otherwise WARNING.
    """
    log_level = logging.DEBUG if verbose else logging.WARNING
    console_handler = RichHandler(
        level=log_level,
        console=console,
        show_time=False,
        show_path=False,
        markup=False,
    )
    # Root logger at DEBUG so the file handler (added later) captures everything.
    logging.basicConfig(level=logging.DEBUG, handlers=[console_handler], force=True)


def _add_file_logging(log_dir: Path) -> None:
    """Add a DEBUG-level file handler writing to log_dir/gencon-audiobook.log.

    Always writes at DEBUG level regardless of --verbose, so users have a full
    trace available for troubleshooting without re-running with --verbose.

    Args:
        log_dir: Directory to write the log file into. Created if it does not exist.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / _LOG_FILENAME
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    logging.getLogger().addHandler(file_handler)
    logger.debug("Debug log: %s", log_path)


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------


def _check_python_version() -> None:
    """Exit with a clear message if Python is older than _MIN_PYTHON."""
    if sys.version_info < _MIN_PYTHON:
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        req = ".".join(str(n) for n in _MIN_PYTHON)
        click.echo(
            f"Error: This tool requires Python {req} or newer. "
            f"You are running Python {ver}.\n"
            "Please upgrade: https://www.python.org/downloads/",
            err=True,
        )
        sys.exit(1)


def _check_disk_space(path: Path) -> None:
    """Warn (but do not abort) if available disk space is below _DISK_WARN_MB.

    Args:
        path: Directory (or its parent) to check available space for.
    """
    check_path = path if path.exists() else path.parent
    try:
        stat = shutil.disk_usage(check_path)
        available_mb = stat.free // (1024 * 1024)
        if available_mb < _DISK_WARN_MB:
            console.print(
                f"[yellow]Warning:[/yellow] Only {available_mb} MB available in "
                f"{check_path}. This tool requires approximately {_DISK_WARN_MB} MB. "
                "Proceed with caution."
            )
    except OSError:
        # Non-fatal — disk_usage can fail on unusual mount points.
        logger.debug("Could not check disk space for %s", path)


# ---------------------------------------------------------------------------
# Conference selection
# ---------------------------------------------------------------------------


def _select_conference(conference_filter: str | None) -> tuple[str, str]:
    """Resolve the conference to download.

    If conference_filter is given, find the first match (case-insensitive).
    Otherwise print a numbered menu and default to the most recent.

    Args:
        conference_filter: Partial conference name to match, or None.

    Returns:
        (title, url) of the selected conference.

    Raises:
        SystemExit: if the filter matches nothing or the list cannot be fetched.
    """
    try:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as sp:
            sp.add_task("Fetching available conferences...")
            refs = fetch_available_conferences()
    except ScraperError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if not refs:
        click.echo(
            "Error: No conferences found.\n"
            "Check your internet connection and try again.",
            err=True,
        )
        sys.exit(1)

    if conference_filter:
        needle = conference_filter.lower()
        matches = [r for r in refs if needle in r.title.lower()]
        if not matches:
            click.echo(
                f"Error: No conference matching {conference_filter!r}.\n\n"
                "Available conferences:",
                err=True,
            )
            for i, r in enumerate(refs[:10], 1):
                click.echo(f"  {i}. {r.title}", err=True)
            sys.exit(1)
        selected = matches[0]
        console.print(f"Selected: {selected.title}")
        return selected.title, selected.url

    # Default: most recent (first in list)
    console.print(f"Found {len(refs)} conferences. Using: {refs[0].title}")
    return refs[0].title, refs[0].url


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--output",
    default="~/gencon-audiobook",
    show_default=True,
    help="Directory to save output files.",
)
@click.option(
    "--conference",
    default=None,
    help="Conference to download (e.g., 'April 2024'). Defaults to most recent.",
)
@click.option(
    "--audiobook-only",
    is_flag=True,
    default=False,
    help="Produce only the m4b audiobook, skip epub.",
)
@click.option(
    "--epub-only",
    is_flag=True,
    default=False,
    help="Produce only the epub, skip audiobook.",
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable DEBUG-level console output.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite existing output files instead of skipping.",
)
@click.option(
    "--force-scrape",
    is_flag=True,
    default=False,
    help="Re-scrape conference data from the website even if a local cache exists.",
)
@click.option(
    "--bitrate",
    default=None,
    help="AAC encoding bitrate (e.g., 32k, 64k, 128k). Default: match source MP3.",
)
@click.option(
    "--sample-rate",
    default=None,
    type=int,
    help="Audio sample rate in Hz (e.g., 22050, 44100). Default: match source MP3.",
)
@click.version_option(version=__version__, prog_name="gencon-audiobook")
def main(
    output: str,
    conference: str | None,
    audiobook_only: bool,
    epub_only: bool,
    verbose: bool,
    overwrite: bool,
    force_scrape: bool,
    bitrate: str | None,
    sample_rate: int | None,
) -> None:
    """Download General Conference talks as a chaptered m4b audiobook and epub companion."""
    _check_python_version()
    _setup_logging(verbose)

    try:
        _run(
            output=output,
            conference=conference,
            audiobook_only=audiobook_only,
            epub_only=epub_only,
            overwrite=overwrite,
            force_scrape=force_scrape,
            bitrate=bitrate,
            sample_rate=sample_rate,
        )
    except KeyboardInterrupt:
        console.print(
            "\nDownload interrupted. "
            "Run again to resume — already-downloaded files will not be re-downloaded."
        )
        sys.exit(1)


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds as HH:MM:SS.

    Args:
        seconds: Duration in seconds.

    Returns:
        Duration string in HH:MM:SS format.
    """
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h}:{m:02d}:{s:02d}"


def _print_completion_report(
    conf_title: str,
    conf_output_dir: Path,
    m4b_path: Path,
    epub_path: Path,
    failed_talks: list[Talk],
    stats: BuildStats | None,
    phase_times: dict[str, float],
) -> None:
    """Print a structured completion report to the console.

    Args:
        conf_title: Human-readable conference title.
        conf_output_dir: Conference output directory.
        m4b_path: Path to the built m4b file (may not exist if epub-only).
        epub_path: Path to the built epub file (may not exist if audiobook-only).
        failed_talks: Talks that failed to download.
        stats: BuildStats from build_m4b, or None if audiobook was skipped/cached.
        phase_times: Elapsed seconds per phase label.
    """
    console.print("")
    console.print("--- Completion Report ---")
    console.print(f"  Conference:    {conf_title}")

    if stats is not None:
        console.print(f"  Duration:      {_format_duration(stats.duration_seconds)}")
        console.print(f"  Chapters:      {stats.chapter_count}")
        if stats.source_bitrate != stats.output_bitrate or stats.source_sample_rate != stats.output_sample_rate:
            console.print(f"  Source audio:  {stats.source_bitrate} / {stats.source_sample_rate} Hz")
            console.print(f"  Output audio:  {stats.output_bitrate} / {stats.output_sample_rate} Hz")
        else:
            console.print(f"  Audio quality: {stats.output_bitrate} / {stats.output_sample_rate} Hz")

    if m4b_path.exists():
        size_mb = m4b_path.stat().st_size / 1_048_576
        console.print(f"  Audiobook:     {m4b_path.name} ({size_mb:.0f} MB)")

    if epub_path.exists():
        size_mb = epub_path.stat().st_size / 1_048_576
        console.print(f"  EPUB:          {epub_path.name} ({size_mb:.1f} MB)")

    if phase_times:
        parts = ", ".join(f"{label} {elapsed:.0f}s" for label, elapsed in phase_times.items())
        console.print(f"  Timing:        {parts}")

    if len(failed_talks) > 0:
        console.print(
            f"\n  Warning: {len(failed_talks)} talk(s) could not be downloaded "
            "and are not included in the output:"
        )
        for talk in failed_talks:
            console.print(f"    - {talk.title} ({talk.speaker})")

    console.print(f"\n  Output: {conf_output_dir}")
    console.print(f"  Log:    {conf_output_dir / _LOG_FILENAME}")


def _run(
    output: str,
    conference: str | None,
    audiobook_only: bool,
    epub_only: bool,
    overwrite: bool,
    force_scrape: bool,
    bitrate: str | None,
    sample_rate: int | None,
) -> None:
    """Inner implementation of main() — separated so KeyboardInterrupt is handled cleanly."""
    output_dir = Path(output).expanduser().resolve()
    phase_times: dict[str, float] = {}

    conf_title, conf_url = _select_conference(conference)

    # Resolve the output directory early — conf_title matches conf_obj.title, so we
    # can check the cache before scraping rather than after.
    conf_output_dir = output_dir / conf_title

    # Load from cache if available and --force-scrape not set.
    conf_obj = None
    if not force_scrape:
        conf_obj = load_cache(conf_output_dir, expected_url=conf_url)
        if conf_obj is not None:
            console.print(
                f"Loaded {len(conf_obj.talks)} talks from cache "
                f"({conf_output_dir / CACHE_FILENAME}). "
                "Use --force-scrape to refresh."
            )

    if conf_obj is None:
        # Scrape conference details — progress bar printed inside scrape_conference()
        t0 = time.monotonic()
        try:
            conf_obj = scrape_conference(conf_url)
        except ScraperError as exc:
            click.echo(f"Error: {exc}", err=True)
            sys.exit(1)
        phase_times["scrape"] = time.monotonic() - t0
        conf_output_dir.mkdir(parents=True, exist_ok=True)
        save_cache(conf_obj, conf_output_dir)
        logger.info("Saved conference cache: %s", conf_output_dir / CACHE_FILENAME)

    # Wire up the log file now that we know where output goes.
    try:
        _add_file_logging(conf_output_dir)
    except OSError as exc:
        click.echo(
            f"Error: Cannot write to {conf_output_dir}.\n"
            f"Check permissions and try again.\n({exc})",
            err=True,
        )
        sys.exit(1)

    # Warn if disk space is low before starting downloads.
    _check_disk_space(conf_output_dir)

    # Download audio (skipped for --epub-only) and images.
    console.print(f"Downloading files for {len(conf_obj.talks)} talks...")
    t0 = time.monotonic()
    try:
        failed_talks: list[Talk] = download_conference(
            conf_obj, conf_output_dir, skip_audio=epub_only
        )
    except DownloadError as exc:
        click.echo(f"Error: Download failed: {exc}", err=True)
        sys.exit(1)
    phase_times["download"] = time.monotonic() - t0

    m4b_path = conf_output_dir / f"{conf_obj.title}.m4b"
    epub_path = conf_output_dir / f"{conf_obj.title}.epub"
    build_stats: BuildStats | None = None

    # Build m4b audiobook
    if not epub_only:
        console.print("Building audiobook...")
        try:
            ffmpeg = ensure_ffmpeg()
            ffprobe = ensure_ffprobe()
        except FfmpegNotFoundError as exc:
            click.echo(f"Error: ffmpeg not available.\n{exc}", err=True)
            sys.exit(1)

        audio_dir = conf_output_dir / "audio"
        cover_path = conf_output_dir / "cover.jpg"

        if m4b_path.exists() and not overwrite:
            console.print(
                f"Audiobook already exists (use --overwrite to rebuild): {m4b_path.name}"
            )
        else:
            t0 = time.monotonic()
            try:
                build_stats = build_m4b(
                    conference=conf_obj,
                    audio_dir=audio_dir,
                    output_path=m4b_path,
                    cover_path=cover_path if cover_path.exists() else None,
                    ffmpeg_path=ffmpeg,
                    ffprobe_path=ffprobe,
                    bitrate=bitrate,
                    sample_rate=sample_rate,
                )
            except AudioError as exc:
                click.echo(f"Error: Audiobook build failed.\n{exc}", err=True)
                sys.exit(1)
            phase_times["audiobook"] = time.monotonic() - t0

    # Build EPUB companion
    if not audiobook_only:
        if epub_path.exists() and not overwrite:
            console.print(
                f"EPUB already exists (use --overwrite to rebuild): {epub_path.name}"
            )
        else:
            t0 = time.monotonic()
            try:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                ) as sp:
                    sp.add_task(f"Building EPUB: {conf_obj.title}")
                    build_epub(
                        conference=conf_obj,
                        images_dir=conf_output_dir,
                        output_path=epub_path,
                    )
            except EpubError as exc:
                click.echo(f"Error: EPUB build failed.\n{exc}", err=True)
                sys.exit(1)
            phase_times["epub"] = time.monotonic() - t0

    _print_completion_report(
        conf_title=conf_obj.title,
        conf_output_dir=conf_output_dir,
        m4b_path=m4b_path,
        epub_path=epub_path,
        failed_talks=failed_talks,
        stats=build_stats,
        phase_times=phase_times,
    )
