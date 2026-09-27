"""Live smoke tests against the real churchofjesuschrist.org site.

These tests make real HTTP requests. They are excluded from normal CI.
Run manually to verify the site structure has not changed:

    pytest tests/test_scraper_live.py -v -m live
"""

from __future__ import annotations

import pytest

from gencon_audiobook.models import Conference
from gencon_audiobook.scraper import (
    ConferenceNotPublishedError,
    ConferenceRef,
    fetch_available_conferences,
    scrape_conference,
)
from gencon_audiobook.utils import validate_url


@pytest.fixture(scope="module")
def conference_refs() -> list[ConferenceRef]:
    return fetch_available_conferences()


@pytest.fixture(scope="module")
def newest_listed_result(
    conference_refs: list[ConferenceRef],
) -> Conference | ConferenceNotPublishedError:
    """Scrape the newest listed conference once; an unpublished one yields its error."""
    try:
        return scrape_conference(conference_refs[0].url)
    except ConferenceNotPublishedError as exc:
        return exc


@pytest.fixture(scope="module")
def newest_complete_conference(
    conference_refs: list[ConferenceRef],
    newest_listed_result: Conference | ConferenceNotPublishedError,
) -> Conference:
    """The newest fully published conference, scraped once for all structure checks.

    The site lists the next conference before it is held and fills it in over the days
    after, so the newest listed conference is skipped while it is upcoming or still
    being published instead of failing every test twice a year.
    """
    if isinstance(newest_listed_result, Conference) and not newest_listed_result.incomplete_talks:
        return newest_listed_result
    try:
        conference = scrape_conference(conference_refs[1].url)
    except ConferenceNotPublishedError:
        pytest.fail("Neither of the two newest conferences is published; the site may have changed")
    if conference.incomplete_talks:
        pytest.fail(
            f"{conference.title} has {len(conference.incomplete_talks)} incomplete talk(s); "
            "the site may have changed"
        )
    return conference


@pytest.mark.live
def test_fetch_available_conferences_returns_many(conference_refs):
    # General Conference has run twice per year since 1971 (~110+ conferences by 2026)
    assert len(conference_refs) >= 100, f"Expected >= 100 conferences, got {len(conference_refs)}"


@pytest.mark.live
def test_fetch_available_conferences_most_recent_is_recent(conference_refs):
    assert conference_refs[0].year >= 2020, \
        f"Most recent conference year should be >= 2020, got {conference_refs[0].year}"


@pytest.mark.live
def test_fetch_available_conferences_ordered_most_recent_first(conference_refs):
    years = [r.year for r in conference_refs[:10]]
    assert years == sorted(years, reverse=True), \
        f"First 10 should be ordered most-recent first: {years}"


@pytest.mark.live
def test_fetch_available_conferences_months_are_valid(conference_refs):
    assert all(r.month in (4, 10) for r in conference_refs), \
        "All conferences should have month 4 or 10"


@pytest.mark.live
def test_newest_listed_conference_scrapes_or_reports_not_published(newest_listed_result):
    """The newest listed conference is either usable or reported unpublished.

    Any other ScraperError propagates from the fixture and fails this test: that is the
    generic "website structure may have changed" path users must not see for a
    conference that simply has not been posted yet.
    """
    if isinstance(newest_listed_result, ConferenceNotPublishedError):
        return
    complete = len(newest_listed_result.talks) - len(newest_listed_result.incomplete_talks)
    assert complete >= 1, "A conference that scraped must have at least one usable talk"


@pytest.mark.live
def test_scrape_newest_complete_conference_returns_talks(newest_complete_conference):
    all_talks = newest_complete_conference.talks
    assert len(all_talks) >= 30, f"Expected >= 30 talks, got {len(all_talks)}"


@pytest.mark.live
def test_scrape_conference_talks_have_required_fields(newest_complete_conference):
    for talk in newest_complete_conference.talks:
        assert talk.title, f"Talk missing title: {talk.talk_url}"
        assert talk.speaker, f"Talk missing speaker: {talk.talk_url}"


@pytest.mark.live
def test_scrape_conference_talks_have_valid_mp3_urls(newest_complete_conference):
    talks_with_mp3 = [t for t in newest_complete_conference.talks if t.mp3_url]
    assert len(talks_with_mp3) >= 30, \
        f"Expected >= 30 talks with mp3_url, got {len(talks_with_mp3)}"
    for talk in talks_with_mp3:
        assert validate_url(talk.mp3_url), \
            f"mp3_url failed allowlist: {talk.mp3_url}"
        assert talk.mp3_url.endswith(".mp3"), \
            f"mp3_url should end with .mp3: {talk.mp3_url}"


@pytest.mark.live
def test_scrape_conference_talks_have_transcripts(newest_complete_conference):
    talks_with_transcript = [t for t in newest_complete_conference.talks if t.transcript_html]
    assert len(talks_with_transcript) >= 30, \
        f"Expected >= 30 talks with transcripts, got {len(talks_with_transcript)}"


@pytest.mark.live
def test_scrape_conference_has_sessions(newest_complete_conference):
    assert len(newest_complete_conference.sessions) >= 4, \
        f"Expected >= 4 sessions, got {len(newest_complete_conference.sessions)}"


@pytest.mark.live
def test_scrape_conference_talk_indexes_are_sequential(newest_complete_conference):
    indexes = [t.talk_index for t in newest_complete_conference.talks]
    assert indexes == list(range(1, len(indexes) + 1)), \
        f"talk_index should be 1..N in order, got {indexes[:5]}..."
