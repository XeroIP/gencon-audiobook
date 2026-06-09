"""Tests for conference metadata caching (cache.py)."""

from __future__ import annotations

import json

import pytest

from gencon_audiobook.cache import (
    CACHE_FILENAME,
    CACHE_VERSION,
    load_cache,
    save_cache,
)
from gencon_audiobook.models import Conference, InlineImage, Session, Talk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_conference() -> Conference:
    """Return a representative Conference for cache tests."""
    inline = InlineImage(
        url="https://assets.churchofjesuschrist.org/img.jpg",
        alt="A map",
        asset_id="abc123",
    )
    talk1 = Talk(
        title="Opening Remarks",
        speaker="President Henry B. Eyring",
        talk_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04/talk1",
        mp3_url="https://assets.churchofjesuschrist.org/audio/talk1.mp3",
        video_url="https://assets.churchofjesuschrist.org/video/talk1-360p-en.mp4",
        transcript_html="<p>Welcome.</p>",
        speaker_image_url="https://assets.churchofjesuschrist.org/photo1.jpg",
        inline_images=[inline],
        session_name="Saturday Morning Session",
        session_number=1,
        talk_number=1,
        talk_index=1,
        duration_seconds=124.5,
    )
    talk2 = Talk(
        title="Another Talk",
        speaker="Elder Test Speaker",
        talk_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04/talk2",
        mp3_url=None,
        video_url=None,
        transcript_html=None,
        speaker_image_url=None,
        inline_images=[],
        session_name="Saturday Morning Session",
        session_number=1,
        talk_number=2,
        talk_index=2,
        duration_seconds=0.0,
    )
    session = Session(name="Saturday Morning Session", number=1, talks=[talk1, talk2])
    return Conference(
        title="April 2024 General Conference",
        year=2024,
        month=4,
        cover_image_url="https://assets.churchofjesuschrist.org/cover.jpg",
        sessions=[session],
        conference_url="https://www.churchofjesuschrist.org/study/general-conference/2024/04",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_save_load_round_trip(tmp_path: "pytest.TempPathFactory") -> None:
    """save_cache → load_cache must reconstruct a Conference equal to the original.

    duration_seconds is the only field that should differ (set to 0.0 on load).
    """
    conf = _make_conference()
    save_cache(conf, tmp_path)

    loaded = load_cache(tmp_path, expected_url=conf.conference_url)
    assert loaded is not None, "load_cache should return a Conference, not None"

    assert loaded.title == conf.title
    assert loaded.year == conf.year
    assert loaded.month == conf.month
    assert loaded.cover_image_url == conf.cover_image_url
    assert loaded.conference_url == conf.conference_url
    assert len(loaded.sessions) == len(conf.sessions)

    orig_talk = conf.talks[0]
    loaded_talk = loaded.talks[0]
    assert loaded_talk.title == orig_talk.title
    assert loaded_talk.speaker == orig_talk.speaker
    assert loaded_talk.talk_url == orig_talk.talk_url
    assert loaded_talk.mp3_url == orig_talk.mp3_url
    assert loaded_talk.video_url == orig_talk.video_url
    assert loaded_talk.transcript_html == orig_talk.transcript_html
    assert loaded_talk.speaker_image_url == orig_talk.speaker_image_url
    assert loaded_talk.session_name == orig_talk.session_name
    assert loaded_talk.session_number == orig_talk.session_number
    assert loaded_talk.talk_number == orig_talk.talk_number
    assert loaded_talk.talk_index == orig_talk.talk_index

    assert len(loaded_talk.inline_images) == 1
    orig_img = orig_talk.inline_images[0]
    loaded_img = loaded_talk.inline_images[0]
    assert loaded_img.url == orig_img.url
    assert loaded_img.alt == orig_img.alt
    assert loaded_img.asset_id == orig_img.asset_id


def test_save_cache_strips_duration_seconds(tmp_path: "pytest.TempPathFactory") -> None:
    """duration_seconds must be stripped during save and reset to 0.0 on load."""
    conf = _make_conference()
    assert conf.talks[0].duration_seconds == 124.5, "pre-condition: non-zero duration"

    save_cache(conf, tmp_path)
    loaded = load_cache(tmp_path, expected_url=conf.conference_url)

    assert loaded is not None
    for talk in loaded.talks:
        assert talk.duration_seconds == 0.0, (
            f"duration_seconds must be 0.0 after load, got {talk.duration_seconds}"
        )


def test_load_cache_missing_file(tmp_path: "pytest.TempPathFactory") -> None:
    """load_cache returns None when no cache file exists."""
    result = load_cache(tmp_path, expected_url="https://example.com/conf")
    assert result is None, "Expected None for missing cache file"


def test_load_cache_corrupt_json(tmp_path: "pytest.TempPathFactory") -> None:
    """load_cache returns None (not an exception) for corrupt JSON."""
    (tmp_path / CACHE_FILENAME).write_text("this is not valid json{{{", encoding="utf-8")
    result = load_cache(tmp_path, expected_url="https://example.com/conf")
    assert result is None, "Expected None for corrupt JSON"


def test_load_cache_malformed_conference_data(tmp_path: "pytest.TempPathFactory") -> None:
    """Valid JSON with an invalid conference shape must fall back to re-scraping."""
    expected_url = "https://www.churchofjesuschrist.org/study/general-conference/2024/04"
    malformed = {
        "cache_version": CACHE_VERSION,
        "conference": {
            "conference_url": expected_url,
            "title": "April 2024 General Conference",
            # Missing sessions/year/month/cover_image_url.
        },
    }
    (tmp_path / CACHE_FILENAME).write_text(json.dumps(malformed), encoding="utf-8")

    result = load_cache(tmp_path, expected_url=expected_url)

    assert result is None, "Expected None for malformed conference cache data"


def test_load_cache_version_mismatch(tmp_path: "pytest.TempPathFactory") -> None:
    """load_cache returns None when cache_version does not match CACHE_VERSION."""
    conf = _make_conference()
    save_cache(conf, tmp_path)

    cache_path = tmp_path / CACHE_FILENAME
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    data["cache_version"] = CACHE_VERSION + 99
    cache_path.write_text(json.dumps(data), encoding="utf-8")

    result = load_cache(tmp_path, expected_url=conf.conference_url)
    assert result is None, "Expected None for version mismatch"


def test_load_cache_url_mismatch(tmp_path: "pytest.TempPathFactory") -> None:
    """load_cache returns None when the cached URL differs from expected_url."""
    conf = _make_conference()
    save_cache(conf, tmp_path)

    result = load_cache(
        tmp_path,
        expected_url="https://www.churchofjesuschrist.org/study/general-conference/2025/04",
    )
    assert result is None, "Expected None when expected_url does not match cached URL"


def test_save_cache_writes_expected_filename(tmp_path: "pytest.TempPathFactory") -> None:
    """save_cache must write to CACHE_FILENAME in the given directory."""
    conf = _make_conference()
    path = save_cache(conf, tmp_path)

    assert path == tmp_path / CACHE_FILENAME, (
        f"Expected cache at {tmp_path / CACHE_FILENAME}, got {path}"
    )
    assert path.exists(), "Cache file must exist after save_cache"


def test_save_cache_is_valid_json(tmp_path: "pytest.TempPathFactory") -> None:
    """The cache file must contain valid JSON with the expected envelope structure."""
    conf = _make_conference()
    path = save_cache(conf, tmp_path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["cache_version"] == CACHE_VERSION
    assert "conference" in data
    assert data["conference"]["title"] == conf.title
