"""Unit tests for scraper functions against saved HTML fixtures.

Run scripts/update_fixtures.py before running these tests for the first time
or after the Church website structure changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gencon_audiobook.scraper import (
    ScraperError,
    parse_conference_archive,
    parse_conference_listing,
    parse_talk_page,
)
from gencon_audiobook.utils import validate_url

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(f"Fixture not found: {path}. Run: python scripts/update_fixtures.py")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# parse_conference_archive
# ---------------------------------------------------------------------------


def test_parse_conference_archive_returns_conferences():
    html = _load("conference_archive.html")
    refs = parse_conference_archive(html)
    assert len(refs) >= 10, f"Expected >= 10 conferences, got {len(refs)}"


def test_parse_conference_archive_titles_non_empty():
    html = _load("conference_archive.html")
    refs = parse_conference_archive(html)
    assert all(ref.title for ref in refs), "All refs should have non-empty titles"


def test_parse_conference_archive_urls_are_full():
    html = _load("conference_archive.html")
    refs = parse_conference_archive(html)
    assert all(r.url.startswith("https://") for r in refs), \
        "All conference URLs should start with https://"


def test_parse_conference_archive_years_valid():
    html = _load("conference_archive.html")
    refs = parse_conference_archive(html)
    assert all(1971 <= ref.year <= 2100 for ref in refs), \
        f"All years should be in [1971, 2100]"


def test_parse_conference_archive_months_valid():
    html = _load("conference_archive.html")
    refs = parse_conference_archive(html)
    assert all(ref.month in (4, 10) for ref in refs), \
        "All months should be 4 (April) or 10 (October)"


def test_parse_conference_archive_most_recent_first():
    html = _load("conference_archive.html")
    refs = parse_conference_archive(html)
    assert refs[0].year >= refs[-1].year, \
        f"Should be ordered most-recent first, got {refs[0].year} ... {refs[-1].year}"


def test_parse_conference_archive_raises_on_empty_html():
    with pytest.raises(ScraperError):
        parse_conference_archive("<html><body>nothing here</body></html>")


# ---------------------------------------------------------------------------
# parse_conference_listing
# ---------------------------------------------------------------------------


def test_parse_conference_listing_returns_sessions():
    html = _load("conference_listing.html")
    sessions = parse_conference_listing(html)
    assert len(sessions) >= 1, f"Expected >= 1 session, got {len(sessions)}"


def test_parse_conference_listing_sessions_have_names():
    html = _load("conference_listing.html")
    sessions = parse_conference_listing(html)
    assert all(s.name for s in sessions), "All sessions should have non-empty names"


def test_parse_conference_listing_sessions_have_talks():
    html = _load("conference_listing.html")
    sessions = parse_conference_listing(html)
    assert all(len(s.talks) > 0 for s in sessions), "All sessions should have at least one talk"


def test_parse_conference_listing_talk_titles_non_empty():
    html = _load("conference_listing.html")
    sessions = parse_conference_listing(html)
    all_talks = [t for s in sessions for t in s.talks]
    assert all(t.title for t in all_talks), "All talks should have non-empty titles"


def test_parse_conference_listing_talk_urls_are_full():
    html = _load("conference_listing.html")
    sessions = parse_conference_listing(html)
    all_talks = [t for s in sessions for t in s.talks]
    assert all(t.talk_url.startswith("https://") for t in all_talks), \
        "All talk URLs should be absolute https:// URLs"


def test_parse_conference_listing_at_least_25_talks_total():
    html = _load("conference_listing.html")
    sessions = parse_conference_listing(html)
    total = sum(len(s.talks) for s in sessions)
    assert total >= 25, f"Expected >= 25 talks total, got {total}"


def test_parse_conference_listing_raises_on_empty_html():
    with pytest.raises(ScraperError):
        parse_conference_listing("<html><body>nothing here</body></html>")


# ---------------------------------------------------------------------------
# parse_talk_page
# ---------------------------------------------------------------------------


def test_parse_talk_page_extracts_mp3_url():
    html = _load("talk_page.html")
    data = parse_talk_page(html, "https://www.churchofjesuschrist.org/test")
    assert data["mp3_url"] is not None, "mp3_url should be non-None"
    assert data["mp3_url"].endswith(".mp3"), \
        f"mp3_url should end with .mp3, got {data['mp3_url']!r}"


def test_parse_talk_page_mp3_url_passes_validate_url():
    html = _load("talk_page.html")
    data = parse_talk_page(html, "https://www.churchofjesuschrist.org/test")
    assert data["mp3_url"] is not None
    assert validate_url(data["mp3_url"]), \
        f"mp3_url should pass validate_url(), got {data['mp3_url']!r}"


def test_parse_talk_page_extracts_transcript():
    html = _load("talk_page.html")
    data = parse_talk_page(html, "https://www.churchofjesuschrist.org/test")
    assert data["transcript_html"] is not None, "transcript_html should be non-None"
    assert len(data["transcript_html"]) >= 500, \
        f"transcript_html should be at least 500 chars, got {len(data['transcript_html'] or '')}"


def test_parse_talk_page_missing_speaker_photo_returns_none():
    # A minimal page with no speaker photo should return None, not raise
    minimal_html = """
    <html><body>
      <h1>Test Talk</h1>
      <p class="author-name">Elder Test Speaker</p>
      <div class="body-block"><p>Content here.</p></div>
      <video><source src="https://assets.churchofjesuschrist.org/test.mp3" type="audio/mpeg"/></video>
    </body></html>
    """
    data = parse_talk_page(minimal_html, "https://www.churchofjesuschrist.org/test")
    assert data["speaker_image_url"] is None, \
        "speaker_image_url should be None when no photo found"


def test_parse_talk_page_extracts_speaker_name():
    html = _load("talk_page.html")
    data = parse_talk_page(html, "https://www.churchofjesuschrist.org/test")
    # Speaker may not always be present — just check it doesn't contain "Presented by"
    if data["speaker"]:
        assert "presented by" not in data["speaker"].lower(), \
            f"Speaker should not contain 'Presented by': {data['speaker']!r}"


# ---------------------------------------------------------------------------
# Validation behaviour
# ---------------------------------------------------------------------------


def test_parse_talk_page_handles_missing_mp3_gracefully():
    html = """
    <html><body>
      <h1>No MP3 Here</h1>
      <div class="body-block"><p>Text.</p></div>
    </body></html>
    """
    data = parse_talk_page(html, "https://www.churchofjesuschrist.org/test")
    assert data["mp3_url"] is None


def test_parse_talk_page_handles_missing_transcript_gracefully():
    html = """
    <html><body>
      <h1>No Transcript</h1>
      <video><source src="https://assets.churchofjesuschrist.org/a.mp3" type="audio/mpeg"/></video>
    </body></html>
    """
    data = parse_talk_page(html, "https://www.churchofjesuschrist.org/test")
    assert data["transcript_html"] is None
