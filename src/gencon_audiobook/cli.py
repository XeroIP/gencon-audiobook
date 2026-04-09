"""CLI entry point for gencon-audiobook."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from . import __version__
from .audio import AudioError, build_m4b
from .downloader import DownloadError, download_conference
from .ffmpeg_manager import FfmpegNotFoundError, ensure_ffmpeg, ensure_ffprobe
from .scraper import ScraperError, fetch_available_conferences, scrape_conference

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    """Configure console logging at INFO (or DEBUG if verbose).

    Args:
        verbose: If True, set root level to DEBUG; otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


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
    click.echo("Fetching available conferences...")
    try:
        refs = fetch_available_conferences()
    except ScraperError as exc:
        click.echo(f"Error fetching conference list: {exc}", err=True)
        sys.exit(1)

    if not refs:
        click.echo("No conferences found. Please check your internet connection.", err=True)
        sys.exit(1)

    if conference_filter:
        needle = conference_filter.lower()
        matches = [r for r in refs if needle in r.title.lower()]
        if not matches:
            click.echo(
                f"No conference matching {conference_filter!r}. Available conferences:",
                err=True,
            )
            for i, r in enumerate(refs[:10], 1):
                click.echo(f"  {i}. {r.title}", err=True)
            sys.exit(1)
        selected = matches[0]
        click.echo(f"Selected: {selected.title}")
        return selected.title, selected.url

    # Default: most recent (first in list); print menu for context
    click.echo(f"Found {len(refs)} conferences. Defaulting to most recent: {refs[0].title}")
    return refs[0].title, refs[0].url


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
    help="Produce only the epub, skip audiobook. (Phase 2)",
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
    "--bitrate",
    default="64k",
    show_default=True,
    help="AAC encoding bitrate for the m4b (e.g., 32k, 48k, 64k). Lower values reduce file size.",
)
@click.option(
    "--sample-rate",
    default=44100,
    show_default=True,
    type=int,
    help="Audio sample rate in Hz for the m4b (e.g., 22050, 44100). Lower values reduce file size.",
)
@click.version_option(version=__version__, prog_name="gencon-audiobook")
def main(
    output: str,
    conference: str | None,
    audiobook_only: bool,
    epub_only: bool,
    verbose: bool,
    overwrite: bool,
    bitrate: str,
    sample_rate: int,
) -> None:
    """Download General Conference talks as a chaptered m4b audiobook and epub companion."""
    _setup_logging(verbose)

    if epub_only:
        click.echo("epub generation coming in Phase 2.")
        sys.exit(0)

    # Resolve output directory
    output_dir = Path(output).expanduser().resolve()

    # Select conference
    conf_title, conf_url = _select_conference(conference)

    # Disk space warning
    click.echo("Note: approximately 500 MB of disk space required.")

    # Scrape conference details
    click.echo(f"Scraping conference: {conf_title}")
    try:
        conf_obj = scrape_conference(conf_url)
    except ScraperError as exc:
        click.echo(f"Error scraping conference: {exc}", err=True)
        sys.exit(1)

    conf_output_dir = output_dir / conf_obj.title

    # Download audio and images
    click.echo(f"Downloading {len(conf_obj.talks)} talks...")
    try:
        download_conference(conf_obj, conf_output_dir, skip_audio=False)
    except DownloadError as exc:
        click.echo(f"Download error: {exc}", err=True)
        sys.exit(1)

    # Build m4b audiobook
    if not epub_only:
        click.echo("Building audiobook...")
        try:
            ffmpeg = ensure_ffmpeg()
            ffprobe = ensure_ffprobe()
        except FfmpegNotFoundError as exc:
            click.echo(f"ffmpeg not available:\n{exc}", err=True)
            sys.exit(1)

        audio_dir = conf_output_dir / "audio"
        cover_path = conf_output_dir / "cover.jpg"
        m4b_path = conf_output_dir / f"{conf_obj.title}.m4b"

        try:
            build_m4b(
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
            click.echo(f"Audiobook build error: {exc}", err=True)
            sys.exit(1)

        click.echo("")
        click.echo(f"Output saved to: {conf_output_dir}")
        if m4b_path.exists():
            size_mb = m4b_path.stat().st_size / 1_048_576
            chapter_count = len(conf_obj.talks)
            click.echo(
                f"  {m4b_path.name} ({size_mb:.0f} MB, {chapter_count} chapters)"
            )
    else:
        click.echo("")
        click.echo(f"Output saved to: {conf_output_dir}")
