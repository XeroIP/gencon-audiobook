"""Unit tests for scraper functions against saved HTML fixtures.

Run scripts/update_fixtures.py before running these tests for the first time
or after the Church website structure changes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses as responses_lib

from gencon_audiobook.scraper import (
    ScraperError,
    _check_robots,
    _find_cover_image,
    _get_robots,
    _make_http_session as _scraper_make_session,
    _robots_cache,
    parse_conference_archive,
    parse_conference_listing,
    parse_talk_page,
    reset_robots_cache,
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
    assert data["speaker"] is not None, "Speaker should be present in the talk page fixture"
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


def test_parse_talk_page_extracts_inline_images_from_srcset():
    """Inline images with srcset-only (no src) are extracted using the largest resolution."""
    asset_id = "m4bm6mveb5rxslfl"
    srcset = (
        f"https://www.churchofjesuschrist.org/imgs/{asset_id}/full/%21100%2C/0/default 100w, "
        f"https://www.churchofjesuschrist.org/imgs/{asset_id}/full/%21500%2C/0/default 500w, "
        f"https://www.churchofjesuschrist.org/imgs/{asset_id}/full/%2160%2C/0/default 60w"
    )
    html = f"""
    <html><body>
      <div class="body-block">
        <p>Talk text.</p>
        <div><div class="imageWrapper-wTPPD">
          <img data-assetid="{asset_id}" srcset="{srcset}" alt="Pioneers"/>
        </div></div>
      </div>
    </body></html>
    """
    data = parse_talk_page(html, "https://www.churchofjesuschrist.org/test")
    images = data["inline_images"]
    assert len(images) == 1, f"Expected 1 inline image, got {len(images)}"
    assert images[0].asset_id == asset_id
    assert images[0].alt == "Pioneers"
    assert "500" in images[0].url, "Should pick the largest (500w) URL from srcset"


def test_parse_talk_page_inline_images_empty_when_no_images():
    """Talks with no inline images return an empty list."""
    html = """
    <html><body>
      <div class="body-block"><p>No images here.</p></div>
    </body></html>
    """
    data = parse_talk_page(html, "https://www.churchofjesuschrist.org/test")
    assert data["inline_images"] == [], "Should return empty list when no inline images"


def test_parse_talk_page_deduplicates_inline_images():
    """The same asset_id appearing twice in the body produces only one InlineImage."""
    asset_id = "dupasset"
    srcset = f"https://www.churchofjesuschrist.org/imgs/{asset_id}/full/%21100%2C/0/default 100w"
    html = f"""
    <html><body>
      <div class="body-block">
        <img data-assetid="{asset_id}" srcset="{srcset}" alt="First"/>
        <img data-assetid="{asset_id}" srcset="{srcset}" alt="Second"/>
      </div>
    </body></html>
    """
    data = parse_talk_page(html, "https://www.churchofjesuschrist.org/test")
    assert len(data["inline_images"]) == 1, "Duplicate asset_id should be deduplicated"


# ---------------------------------------------------------------------------
# robots.txt (#23)
# ---------------------------------------------------------------------------


def _make_http_session(robots_text: str, status: int = 200) -> MagicMock:
    """Build a mock requests.Session whose .get() returns the given robots.txt body."""
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.text = robots_text
    mock_response.raise_for_status.return_value = None  # no-op — 200 OK

    session = MagicMock()
    session.get.return_value = mock_response
    return session


def test_check_robots_allows_permitted_url() -> None:
    """A URL permitted by robots.txt must not raise."""
    robots_text = "User-agent: *\nDisallow: /private/\n"
    http = _make_http_session(robots_text)

    base = "https://www.churchofjesuschrist.org"
    reset_robots_cache()

    # Should not raise
    _check_robots(http, f"{base}/study/general-conference/2024/04")


def test_check_robots_raises_on_disallowed_url() -> None:
    """A URL explicitly disallowed by robots.txt must raise ScraperError."""
    robots_text = "User-agent: *\nDisallow: /study/general-conference/\n"
    http = _make_http_session(robots_text)

    base = "https://www.churchofjesuschrist.org"
    reset_robots_cache()

    with pytest.raises(ScraperError, match="disallowed by robots.txt"):
        _check_robots(http, f"{base}/study/general-conference/2024/04")


def test_get_robots_returns_none_on_fetch_failure() -> None:
    """If robots.txt fetch fails, _get_robots returns None (proceed anyway)."""
    session = MagicMock()
    session.get.side_effect = ConnectionError("network error")

    base = "https://www.churchofjesuschrist.org"
    reset_robots_cache()

    result = _get_robots(session, base)
    assert result is None, "Should return None when robots.txt is unreachable"


def test_check_robots_proceeds_when_robots_unreachable() -> None:
    """If robots.txt cannot be fetched, _check_robots should not raise."""
    session = MagicMock()
    session.get.side_effect = ConnectionError("network error")

    base = "https://www.churchofjesuschrist.org"
    reset_robots_cache()

    # Should not raise even though the fetch failed
    _check_robots(session, f"{base}/study/general-conference/2024/04")


def test_get_robots_caches_result() -> None:
    """_get_robots should only call session.get once per base URL (caching)."""
    robots_text = "User-agent: *\nDisallow:\n"
    http = _make_http_session(robots_text)

    base = "https://www.example-cache-test.org"
    reset_robots_cache()

    _get_robots(http, base)
    _get_robots(http, base)

    assert http.get.call_count == 1, \
        f"robots.txt should be fetched once and cached, got {http.get.call_count} calls"

    reset_robots_cache()


# ---------------------------------------------------------------------------
# _fetch — 429 retry behaviour
# ---------------------------------------------------------------------------


@responses_lib.activate
def test_fetch_retries_on_429_then_succeeds() -> None:
    """A 429 response should trigger retry; a subsequent 200 should succeed."""
    from gencon_audiobook.scraper import _fetch

    url = "https://www.churchofjesuschrist.org/study/general-conference"
    minimal_html = "<html><body>" + "x" * 1200 + "</body></html>"

    responses_lib.add(responses_lib.GET, url, status=429, body="Too Many Requests")
    responses_lib.add(responses_lib.GET, url, status=200, body=minimal_html)

    session = _scraper_make_session()
    # Patch time.sleep to avoid real delays in the test
    with patch("gencon_audiobook.scraper.time.sleep"):
        result = _fetch(session, url)

    assert len(result) > 100, f"Expected page content after retry, got: {result[:100]!r}"


@responses_lib.activate
def test_fetch_403_raises_immediately_without_retry() -> None:
    """A 403 response must raise ScraperError immediately, not be retried."""
    from gencon_audiobook.scraper import _fetch

    url = "https://www.churchofjesuschrist.org/study/general-conference"
    responses_lib.add(responses_lib.GET, url, status=403, body="Forbidden")
    # Only one response registered — if retry occurs, responses_lib raises ConnectionError

    session = _scraper_make_session()
    with patch("gencon_audiobook.scraper.time.sleep"):
        with pytest.raises(ScraperError, match="403"):
            _fetch(session, url)

    assert len(responses_lib.calls) == 1, (
        f"403 must not be retried — expected 1 request, got {len(responses_lib.calls)}"
    )


# ---------------------------------------------------------------------------
# _find_cover_image — IIIF URL upgrade
# ---------------------------------------------------------------------------


def test_find_cover_image_upgrades_iiif_percent_encoded_url() -> None:
    """og:image URLs with percent-encoded IIIF size must be upgraded to 800px."""
    from bs4 import BeautifulSoup
    html = (
        '<html><head>'
        '<meta property="og:image" content="https://www.churchofjesuschrist.org'
        '/imgs/abc123/full/%21250%2C/0/default"/>'
        '</head></html>'
    )
    soup = BeautifulSoup(html, "html.parser")
    result = _find_cover_image(soup)
    assert result is not None, "Should find cover image URL"
    assert "%21800%2C" in result, f"IIIF size not upgraded to 800: {result!r}"
    assert "%21250%2C" not in result, f"Original size still present: {result!r}"


def test_find_cover_image_upgrades_iiif_plain_url() -> None:
    """og:image URLs with plain IIIF size must also be upgraded."""
    from bs4 import BeautifulSoup
    html = (
        '<html><head>'
        '<meta property="og:image" content="https://www.churchofjesuschrist.org'
        '/imgs/abc123/full/!500,/0/default"/>'
        '</head></html>'
    )
    soup = BeautifulSoup(html, "html.parser")
    result = _find_cover_image(soup)
    assert result is not None
    assert "!800," in result, f"IIIF size not upgraded to 800: {result!r}"
    assert "!500," not in result, f"Original size still present: {result!r}"


def test_find_cover_image_leaves_non_iiif_url_unchanged() -> None:
    """URLs that don't match the IIIF pattern are returned as-is."""
    from bs4 import BeautifulSoup
    html = (
        '<html><head>'
        '<meta property="og:image" content="https://www.churchofjesuschrist.org'
        '/imgs/cover.jpg"/>'
        '</head></html>'
    )
    soup = BeautifulSoup(html, "html.parser")
    result = _find_cover_image(soup)
    assert result == "https://www.churchofjesuschrist.org/imgs/cover.jpg"
