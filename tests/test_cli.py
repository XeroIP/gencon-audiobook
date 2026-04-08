"""Unit tests for cli.py — all external calls mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from gencon_audiobook.audio import AudioError
from gencon_audiobook.cli import main
from gencon_audiobook.downloader import DownloadError
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


def _make_conference(title: str = "April 2024 General Conference") -> Conference:
    talk = Talk(
        title="Opening Remarks",
        speaker="President Eyring",
        talk_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04/01",
        mp3_url="https://assets.churchofjesuschrist.org/test.mp3",
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
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


# ---------------------------------------------------------------------------
# --epub-only stub
# ---------------------------------------------------------------------------


def test_epub_only_exits_cleanly() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--epub-only"])
    assert result.exit_code == 0
    assert "Phase 2" in result.output


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
    refs = [
        _make_ref("April 2024 General Conference", 2024, 4),
        _make_ref("October 2023 General Conference", 2023, 10),
    ]
    conference = _make_conference("October 2023 General Conference")

    with (
        patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs),
        patch("gencon_audiobook.cli.scrape_conference", return_value=conference) as mock_scrape,
        patch("gencon_audiobook.cli.download_conference"),
        patch("gencon_audiobook.cli.ensure_ffmpeg", return_value=Path("/usr/bin/ffmpeg")),
        patch("gencon_audiobook.cli.ensure_ffprobe", return_value=Path("/usr/bin/ffprobe")),
        patch("gencon_audiobook.cli.build_m4b"),
    ):
        runner = CliRunner()
        result = runner.invoke(
            main, ["--output", str(tmp_path), "--audiobook-only", "--conference", "October 2023"]
        )

    assert result.exit_code == 0, result.output
    called_url = mock_scrape.call_args[0][0]
    assert "2023/10" in called_url


def test_conference_filter_no_match_exits_nonzero(tmp_path: Path) -> None:
    refs = [_make_ref("April 2024 General Conference")]

    with patch("gencon_audiobook.cli.fetch_available_conferences", return_value=refs):
        runner = CliRunner()
        result = runner.invoke(
            main, ["--output", str(tmp_path), "--conference", "Nonexistent 1800"]
        )

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Disk space warning
# ---------------------------------------------------------------------------


def test_disk_space_warning_printed(tmp_path: Path) -> None:
    refs = [_make_ref()]
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

    assert "500 MB" in result.output, "Disk space warning should mention 500 MB"


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

    assert "Output saved to" in result.output, result.output
