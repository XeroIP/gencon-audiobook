"""Live smoke tests against the real churchofjesuschrist.org site.

These tests make real HTTP requests. They are excluded from normal CI.
Run manually to verify the site structure has not changed:

    pytest tests/test_scraper_live.py -v -m live
"""

from __future__ import annotations

import pytest

from gencon_audiobook.scraper import fetch_available_conferences, scrape_conference
from gencon_audiobook.utils import validate_url


@pytest.mark.live
def test_fetch_available_conferences_returns_many():
    refs = fetch_available_conferences()
    # General Conference has run twice per year since 1971 (~110+ conferences by 2026)
    assert len(refs) >= 100, f"Expected >= 100 conferences, got {len(refs)}"


@pytest.mark.live
def test_fetch_available_conferences_most_recent_is_recent():
    refs = fetch_available_conferences()
    assert refs[0].year >= 2020, \
        f"Most recent conference year should be >= 2020, got {refs[0].year}"


@pytest.mark.live
def test_fetch_available_conferences_ordered_most_recent_first():
    refs = fetch_available_conferences()
    years = [r.year for r in refs[:10]]
    assert years == sorted(years, reverse=True), \
        f"First 10 should be ordered most-recent first: {years}"


@pytest.mark.live
def test_fetch_available_conferences_months_are_valid():
    refs = fetch_available_conferences()
    assert all(r.month in (4, 10) for r in refs), \
        "All conferences should have month 4 or 10"


@pytest.mark.live
def test_scrape_most_recent_conference_returns_talks():
    refs = fetch_available_conferences()
    conference = scrape_conference(refs[0].url)
    all_talks = conference.talks
    assert len(all_talks) >= 30, f"Expected >= 30 talks, got {len(all_talks)}"


@pytest.mark.live
def test_scrape_conference_talks_have_required_fields():
    refs = fetch_available_conferences()
    conference = scrape_conference(refs[0].url)
    for talk in conference.talks:
        assert talk.title, f"Talk missing title: {talk.talk_url}"
        assert talk.speaker, f"Talk missing speaker: {talk.talk_url}"


@pytest.mark.live
def test_scrape_conference_talks_have_valid_mp3_urls():
    refs = fetch_available_conferences()
    conference = scrape_conference(refs[0].url)
    talks_with_mp3 = [t for t in conference.talks if t.mp3_url]
    assert len(talks_with_mp3) >= 30, \
        f"Expected >= 30 talks with mp3_url, got {len(talks_with_mp3)}"
    for talk in talks_with_mp3:
        assert validate_url(talk.mp3_url), \
            f"mp3_url failed allowlist: {talk.mp3_url}"
        assert talk.mp3_url.endswith(".mp3"), \
            f"mp3_url should end with .mp3: {talk.mp3_url}"


@pytest.mark.live
def test_scrape_conference_talks_have_transcripts():
    refs = fetch_available_conferences()
    conference = scrape_conference(refs[0].url)
    talks_with_transcript = [t for t in conference.talks if t.transcript_html]
    assert len(talks_with_transcript) >= 30, \
        f"Expected >= 30 talks with transcripts, got {len(talks_with_transcript)}"


@pytest.mark.live
def test_scrape_conference_has_sessions():
    refs = fetch_available_conferences()
    conference = scrape_conference(refs[0].url)
    assert len(conference.sessions) >= 4, \
        f"Expected >= 4 sessions, got {len(conference.sessions)}"


@pytest.mark.live
def test_scrape_conference_talk_indexes_are_sequential():
    refs = fetch_available_conferences()
    conference = scrape_conference(refs[0].url)
    indexes = [t.talk_index for t in conference.talks]
    assert indexes == list(range(1, len(indexes) + 1)), \
        f"talk_index should be 1..N in order, got {indexes[:5]}..."
