"""Unit tests for cli.py — all external calls mocked."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from gencon_audiobook.audio import AudioError
from gencon_audiobook.cli import main, _LOG_FILENAME
from gencon_audiobook.downloader import AudioProbe, DownloadError, DownloadResult
from gencon_audiobook.models import Conference, Session, Talk
from gencon_audiobook.scraper import ConferenceRef, ScraperError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ref(title: str = "April 2024 General Conference", year: int = 2024, month: int = 4) -> ConferenceRef:
    return ConferenceRef(
        title=title,
        url=f"https://www.churchofjesuschrist.org/study/general-conference/{year}/{month:02d}",
        year=year,
        month=month,
    )


def _make_conference(title: str = "April 2024 General Conference", *, video_url: str | None = None) -> Conference:
    talk = Talk(
        title="Opening Remarks",
        speaker="President Eyring",
        talk_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04/01",
        mp3_url="https://assets.churchofjesuschrist.org/test.mp3",
        video_url=video_url,
        talk_index=1,
        duration_seconds=120.0,
    )
    session = Session(name="Saturday Morning Session", number=1, talks=[talk])
    return Conference(
        title=title,
        year=2024,
        month=4,
        cover_image_url=None,
        sessions=[session],
        conference_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04",
    )


# ---------------------------------------------------------------------------
# --help / --version
# ---------------------------------------------------------------------------


def test_help_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0, result.output
    assert "--conference" in result.output


def test_version_flag() -> None:
    from gencon_audiobook import __version__
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


# ---------------------------------------------------------------------------
# --epub-only stub
# ---------------------------------------------------------------------------


def test_epub_only_skips_audiobook(tmp_path: Path) -> None:
    """--epub-only should build the EPUB but not call build_m4b."""
    refs = [_make_ref()]
    conference = _make_conference()

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.build_m4b") as mock_m4b,
        patch("gencon_audiobook.cli.build_epub") as mock_epub,
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--epub-only"])

    assert result.exit_code == 0, result.output
    mock_m4b.assert_not_called()
    mock_epub.assert_called_once()


def test_audiobook_only_skips_epub(tmp_path: Path) -> None:
    """--audiobook-only should call build_m4b but not build_epub."""
    refs = [_make_ref()]
    conference = _make_conference()

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b") as mock_m4b,
        patch("gencon_audiobook.cli.build_epub") as mock_epub,
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--audiobook-only"])

    assert result.exit_code == 0, result.output
    mock_m4b.assert_called_once()
    mock_epub.assert_not_called()


def test_default_builds_both(tmp_path: Path) -> None:
    """With no flags, both m4b and epub should be built."""
    refs = [_make_ref()]
    conference = _make_conference()

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b") as mock_m4b,
        patch("gencon_audiobook.cli.build_epub") as mock_epub,
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path)])

    assert result.exit_code == 0, result.output
    mock_m4b.assert_called_once()
    mock_epub.assert_called_once()


# ---------------------------------------------------------------------------
# Conference selection
# ---------------------------------------------------------------------------


def test_defaults_to_most_recent_conference(tmp_path: Path) -> None:
    refs = [_make_ref("April 2024 General Conference")]
    conference = _make_conference()

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b"),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--audiobook-only"])

    assert "April 2024 General Conference" in result.output, result.output


def test_conference_filter_selects_matching(tmp_path: Path) -> None:
    """YYYY-MM format constructs the URL directly without fetching the listing."""
    conference = _make_conference("October 2023 General Conference")

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences") as mock_listing,
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference) as mock_scrape,
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b"),
    ):
        runner = CliRunner()
        result = runner.invoke(
            main, ["--output", str(tmp_path), "--audiobook-only", "--conference", "2023-10"]
        )

    assert result.exit_code == 0, result.output
    mock_listing.assert_not_called()
    called_url = mock_scrape.call_args[0][0]
    assert "2023/10" in called_url, f"Expected 2023/10 in URL, got: {called_url}"


def test_conference_filter_no_match_exits_nonzero(tmp_path: Path) -> None:
    """Invalid YYYY-MM format exits with a non-zero code."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["--output", str(tmp_path), "--conference", "Nonexistent 1800"]
    )

    assert result.exit_code != 0


def test_conference_filter_invalid_format_exits_nonzero(tmp_path: Path) -> None:
    """Month-first or free-text format is rejected with a clear error."""
    runner = CliRunner()
    result = runner.invoke(
        main, ["--output", str(tmp_path), "--conference", "april-2024"]
    )

    assert result.exit_code != 0
    assert "Invalid conference format" in result.output, result.output


def test_conference_direct_url_skips_listing_fetch(tmp_path: Path) -> None:
    """When --conference YYYY-MM is given, fetch_available_conferences is never called."""
    conference = _make_conference("April 2024 General Conference")

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences") as mock_listing,
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.build_epub"),
    ):
        runner = CliRunner()
        result = runner.invoke(
            main, ["--output", str(tmp_path), "--epub-only", "--conference", "2024-04"]
        )

    assert result.exit_code == 0, result.output
    mock_listing.assert_not_called()


# ---------------------------------------------------------------------------
# Disk space warning
# ---------------------------------------------------------------------------


def test_disk_space_warning_printed(tmp_path: Path) -> None:
    """Disk space warning fires only when available space is below the threshold."""
    refs = [_make_ref()]
    conference = _make_conference()

    # Simulate 100 MB free — well below the 500 MB threshold.
    import collections
    DiskUsage = collections.namedtuple("DiskUsage", ["total", "used", "free"])
    fake_usage = DiskUsage(total=1_000_000_000, used=900_000_000, free=100 * 1024 * 1024)

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b"),
        patch("gencon_audiobook.cli.shutil.disk_usage", return_value=fake_usage),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--audiobook-only"])

    normalized_output = " ".join(result.output.split())
    assert "500 MB" in normalized_output, "Disk space warning should mention 500 MB threshold"
    assert "100 MB" in normalized_output, "Disk space warning should show available space"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_scraper_error_exits_nonzero(tmp_path: Path) -> None:
    with patch(
        "gencon_audiobook.cli.fetch_available_conferences",
        side_effect=ScraperError("site changed"),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path)])

    assert result.exit_code != 0


def test_scrape_conference_error_exits_nonzero(tmp_path: Path) -> None:
    refs = [_make_ref()]
    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch(
            "gencon_audiobook.cli.scrape_conference",
            side_effect=ScraperError("parse failed"),
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path)])

    assert result.exit_code != 0


def test_audio_error_exits_nonzero(tmp_path: Path) -> None:
    refs = [_make_ref()]
    conference = _make_conference()

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b", side_effect=AudioError("ffmpeg failed")),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--audiobook-only"])

    assert result.exit_code != 0


def test_ffmpeg_not_found_exits_nonzero(tmp_path: Path) -> None:
    from gencon_audiobook.ffmpeg_manager import FfmpegNotFoundError

    refs = [_make_ref()]
    conference = _make_conference()

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch(
            "gencon_audiobook.cli.ensure_ffmpeg",
            side_effect=FfmpegNotFoundError("not found"),
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--audiobook-only"])

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Completion summary
# ---------------------------------------------------------------------------


def test_completion_summary_printed(tmp_path: Path) -> None:
    refs = [_make_ref()]
    conference = _make_conference()

    # Create a fake m4b so the size check works
    fake_m4b = tmp_path / "April 2024 General Conference" / "April 2024 General Conference.m4b"
    fake_m4b.parent.mkdir(parents=True)
    fake_m4b.write_bytes(b"\x00" * 1024 * 1024 * 5)  # 5 MB

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b"),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--audiobook-only"])

    assert "Completion Report" in result.output, result.output
    assert "Audiobook:" in result.output, result.output


# ---------------------------------------------------------------------------
# --overwrite
# ---------------------------------------------------------------------------


def test_overwrite_flag_skips_build_when_m4b_exists(tmp_path: Path) -> None:
    """Without --overwrite, build_m4b should not be called if the m4b already exists."""
    refs = [_make_ref()]
    conference = _make_conference()

    # Pre-create the m4b so the skip check triggers
    m4b_path = tmp_path / "April 2024 General Conference" / "April 2024 General Conference.m4b"
    m4b_path.parent.mkdir(parents=True)
    m4b_path.write_bytes(b"\x00" * 1024)

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b") as mock_build,
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--audiobook-only"])

    assert result.exit_code == 0, result.output
    mock_build.assert_not_called()
    assert "--overwrite" in result.output, \
        "Skip message should mention --overwrite so the user knows how to rebuild"


def test_overwrite_flag_rebuilds_when_m4b_exists(tmp_path: Path) -> None:
    """With --overwrite, build_m4b should be called even if the m4b already exists."""
    refs = [_make_ref()]
    conference = _make_conference()

    m4b_path = tmp_path / "April 2024 General Conference" / "April 2024 General Conference.m4b"
    m4b_path.parent.mkdir(parents=True)
    m4b_path.write_bytes(b"\x00" * 1024)

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b") as mock_build,
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--audiobook-only", "--overwrite"])

    assert result.exit_code == 0, result.output
    mock_build.assert_called_once()


# ---------------------------------------------------------------------------
# Debug log file (#21)
# ---------------------------------------------------------------------------


def test_epub_error_exits_nonzero(tmp_path: Path) -> None:
    """An EpubError during build_epub must produce a non-zero exit and a readable message.

    Without this test, the try/except EpubError block in cli.py could be silently
    removed and users would see a Python traceback instead of an actionable error.
    """
    from gencon_audiobook.epub_builder import EpubError

    refs = [_make_ref()]
    conference = _make_conference()

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.build_epub", side_effect=EpubError("disk full")),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--epub-only"])

    assert result.exit_code != 0
    assert "EPUB build error" in result.output or "disk full" in result.output, \
        f"Expected error message in output, got: {result.output!r}"


def test_download_error_exits_nonzero(tmp_path: Path) -> None:
    """A DownloadError must produce a non-zero exit and a readable message.

    The download phase can fail due to network issues; the user must see a
    clear message rather than an unhandled exception traceback.
    """
    refs = [_make_ref()]
    conference = _make_conference()

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch(
            "gencon_audiobook.cli.download_conference",
            side_effect=DownloadError("connection timed out"),
        ),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path)])

    assert result.exit_code != 0
    assert "Download error" in result.output or "timed out" in result.output, \
        f"Expected download error message in output, got: {result.output!r}"


def test_overwrite_skips_epub_when_epub_exists(tmp_path: Path) -> None:
    """Without --overwrite, build_epub must not be called if the .epub already exists."""
    refs = [_make_ref()]
    conference = _make_conference()

    epub_path = tmp_path / "April 2024 General Conference" / "April 2024 General Conference.epub"
    epub_path.parent.mkdir(parents=True)
    epub_path.write_bytes(b"\x00" * 1024)

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.build_epub") as mock_epub,
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--epub-only"])

    assert result.exit_code == 0, result.output
    mock_epub.assert_not_called()
    assert "--overwrite" in result.output, \
        "Skip message should mention --overwrite so the user knows how to rebuild"


def test_epub_summary_line_printed(tmp_path: Path) -> None:
    """The completion summary must include the EPUB filename and size."""
    refs = [_make_ref()]
    conference = _make_conference()

    epub_path = tmp_path / "April 2024 General Conference" / "April 2024 General Conference.epub"
    epub_path.parent.mkdir(parents=True)
    epub_path.write_bytes(b"\x00" * 1024 * 512)  # 0.5 MB

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.build_epub"),
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--epub-only"])

    assert ".epub" in result.output, \
        f"EPUB filename should appear in the completion summary: {result.output!r}"



def test_log_file_created_in_output_dir(tmp_path: Path) -> None:
    """A gencon-audiobook.log file should be created in the conference output directory."""
    refs = [_make_ref()]
    conference = _make_conference()

    # Isolate logging handlers so the test doesn't inherit stale handlers from other tests
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]

    try:
        with (
            patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
            patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
            patch("gencon_audiobook.cli.download_conference"),
            patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
            patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
            patch("gencon_audiobook.cli.build_m4b"),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["--output", str(tmp_path), "--audiobook-only"])
    finally:
        # Remove any file handlers added during this test run to avoid leaking open handles
        for h in root_logger.handlers[:]:
            if h not in original_handlers:
                h.close()
                root_logger.removeHandler(h)

    assert result.exit_code == 0, result.output
    log_path = tmp_path / "April 2024 General Conference" / _LOG_FILENAME
    assert log_path.exists(), \
        f"Log file should exist at {log_path}; output dir contents: {list(log_path.parent.iterdir()) if log_path.parent.exists() else 'dir missing'}"


# ---------------------------------------------------------------------------
# Source quality auto-detection
# ---------------------------------------------------------------------------


def test_default_bitrate_passes_none_to_build_m4b(tmp_path: Path) -> None:
    """Without --bitrate, build_m4b receives bitrate=None so it auto-detects source quality."""
    refs = [_make_ref()]
    conference = _make_conference()

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b") as mock_m4b,
    ):
        runner = CliRunner()
        result = runner.invoke(main, ["--output", str(tmp_path), "--audiobook-only"])

    assert result.exit_code == 0, result.output
    _, kwargs = mock_m4b.call_args
    assert kwargs.get("bitrate") is None, \
        f"Expected bitrate=None (auto-detect), got {kwargs.get('bitrate')!r}"
    assert kwargs.get("sample_rate") is None, \
        f"Expected sample_rate=None (auto-detect), got {kwargs.get('sample_rate')!r}"


def test_explicit_bitrate_passed_to_build_m4b(tmp_path: Path) -> None:
    """--bitrate and --sample-rate override auto-detection when explicitly provided."""
    refs = [_make_ref()]
    conference = _make_conference()

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b") as mock_m4b,
    ):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--output", str(tmp_path), "--audiobook-only", "--bitrate", "48k", "--sample-rate", "22050"],
        )

    assert result.exit_code == 0, result.output
    _, kwargs = mock_m4b.call_args
    assert kwargs.get("bitrate") == "48k", \
        f"Expected bitrate='48k', got {kwargs.get('bitrate')!r}"
    assert kwargs.get("sample_rate") == 22050, \
        f"Expected sample_rate=22050, got {kwargs.get('sample_rate')!r}"


def test_quality_banner_exits_by_default_when_video_audio_is_better(tmp_path: Path) -> None:
    conference = _make_conference(
        video_url="https://assets.churchofjesuschrist.org/video-360p-en.mp4"
    )

    with (
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli._probe_audio_info", side_effect=[
            AudioProbe(audio_bitrate_bps=32_000, duration_seconds=600.0, total_bitrate_bps=32_000),
            AudioProbe(audio_bitrate_bps=96_000, duration_seconds=600.0, total_bitrate_bps=600_000),
        ]),
        patch("gencon_audiobook.cli.download_conference") as mock_download,
    ):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--output", str(tmp_path), "--audiobook-only", "--conference", "2024-04"],
            input="\n",
        )

    assert result.exit_code == 0, result.output
    assert "Higher quality audio is available" in result.output
    mock_download.assert_not_called()


def test_prefer_video_audio_prompts_with_estimates_and_enables_extraction(tmp_path: Path) -> None:
    conference = _make_conference(
        video_url="https://assets.churchofjesuschrist.org/video-360p-en.mp4"
    )

    with (
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli._probe_audio_info", side_effect=[
            AudioProbe(audio_bitrate_bps=32_000, duration_seconds=600.0, total_bitrate_bps=32_000),
            AudioProbe(audio_bitrate_bps=96_000, duration_seconds=600.0, total_bitrate_bps=600_000),
        ]),
        patch("gencon_audiobook.cli.download_conference", return_value=DownloadResult()) as mock_download,
        patch("gencon_audiobook.cli.build_m4b"),
    ):
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--output", str(tmp_path),
                "--audiobook-only",
                "--conference", "2024-04",
                "--prefer-video-audio",
            ],
            input="y\n",
        )

    assert result.exit_code == 0, result.output
    assert "--prefer-video-audio is active" in result.output
    assert "Estimated download" in result.output
    assert mock_download.call_args.kwargs["prefer_video_audio"] is True


def test_prefer_video_audio_does_not_downgrade_better_mp3(tmp_path: Path) -> None:
    conference = _make_conference(
        video_url="https://assets.churchofjesuschrist.org/video-360p-en.mp4"
    )

    with (
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli._probe_audio_info", side_effect=[
            AudioProbe(audio_bitrate_bps=128_000, duration_seconds=600.0, total_bitrate_bps=128_000),
            AudioProbe(audio_bitrate_bps=96_000, duration_seconds=600.0, total_bitrate_bps=600_000),
        ]),
        patch("gencon_audiobook.cli.download_conference", return_value=DownloadResult()) as mock_download,
        patch("gencon_audiobook.cli.build_m4b"),
    ):
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--output", str(tmp_path),
                "--audiobook-only",
                "--conference", "2024-04",
                "--prefer-video-audio",
            ],
            input="\n",
        )

    assert result.exit_code == 0, result.output
    assert "MP3 source is already equal" in result.output
    assert "better for this conference" in result.output
    assert mock_download.call_args.kwargs["prefer_video_audio"] is False
