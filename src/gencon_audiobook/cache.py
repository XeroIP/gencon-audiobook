"""Persist and restore scraped Conference objects to avoid redundant HTTP requests."""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

from .models import Conference, InlineImage, Session, Talk

logger = logging.getLogger(__name__)

CACHE_VERSION = 1
CACHE_FILENAME = "conference.json"


def save_cache(conference: Conference, directory: Path) -> Path:
    """Serialise a Conference to JSON in the given directory.

    Strips ``duration_seconds`` from each Talk before writing — that field is
    computed by ``audio.py`` at conversion time, not by the scraper, so it must
    not be treated as stable cached data.

    Args:
        conference: Fully-populated Conference returned by the scraper.
        directory: Output directory for this conference (must already exist or
            be created by the caller before this function is invoked).

    Returns:
        Path of the written cache file.
    """
    conf_dict = dataclasses.asdict(conference)
    for session in conf_dict["sessions"]:
        for talk in session["talks"]:
            talk.pop("duration_seconds", None)

    envelope = {"cache_version": CACHE_VERSION, "conference": conf_dict}
    cache_path = directory / CACHE_FILENAME
    cache_path.write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.debug("Wrote conference cache: %s", cache_path)
    return cache_path


def load_cache(directory: Path, expected_url: str) -> Conference | None:
    """Load a cached Conference from disk if the cache is valid.

    Returns ``None`` (and logs a warning) if the file is missing, contains
    corrupt JSON, has a version mismatch, or records a different conference URL
    than ``expected_url``.  Never raises — callers should fall back to scraping.

    Args:
        directory: Directory that may contain ``conference.json``.
        expected_url: The URL of the conference the caller intends to use.
            Must match the URL stored in the cache for the cache to be accepted.

    Returns:
        A reconstructed ``Conference``, or ``None`` if the cache cannot be used.
    """
    cache_path = directory / CACHE_FILENAME
    if not cache_path.exists():
        return None

    try:
        envelope = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Conference cache is unreadable, will re-scrape: %s", exc)
        return None

    if envelope.get("cache_version") != CACHE_VERSION:
        logger.warning(
            "Conference cache version mismatch (got %r, expected %d), will re-scrape",
            envelope.get("cache_version"),
            CACHE_VERSION,
        )
        return None

    conf_dict = envelope.get("conference", {})
    if conf_dict.get("conference_url") != expected_url:
        logger.warning(
            "Conference cache URL mismatch (cached %r, expected %r), will re-scrape",
            conf_dict.get("conference_url"),
            expected_url,
        )
        return None

    try:
        return _conference_from_dict(conf_dict)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Conference cache is malformed, will re-scrape: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Internal reconstruction helpers
# ---------------------------------------------------------------------------


def _conference_from_dict(d: dict) -> Conference:  # type: ignore[type-arg]
    """Reconstruct a Conference dataclass from a plain dict."""
    sessions = [_session_from_dict(s) for s in d["sessions"]]
    return Conference(
        title=d["title"],
        year=d["year"],
        month=d["month"],
        cover_image_url=d["cover_image_url"],
        sessions=sessions,
        conference_url=d["conference_url"],
    )


def _session_from_dict(d: dict) -> Session:  # type: ignore[type-arg]
    """Reconstruct a Session dataclass from a plain dict."""
    talks = [_talk_from_dict(t) for t in d["talks"]]
    return Session(name=d["name"], number=d["number"], talks=talks)


def _talk_from_dict(d: dict) -> Talk:  # type: ignore[type-arg]
    """Reconstruct a Talk dataclass from a plain dict.

    ``duration_seconds`` is always set to 0.0 — it was stripped during
    ``save_cache()`` and will be recomputed by ``audio.py``.
    """
    inline_images = [
        InlineImage(url=img["url"], alt=img["alt"], asset_id=img["asset_id"])
        for img in d.get("inline_images", [])
    ]
    return Talk(
        title=d["title"],
        speaker=d["speaker"],
        talk_url=d["talk_url"],
        mp3_url=d.get("mp3_url"),
        transcript_html=d.get("transcript_html"),
        speaker_image_url=d.get("speaker_image_url"),
        inline_images=inline_images,
        session_name=d.get("session_name", ""),
        session_number=d.get("session_number", 0),
        talk_number=d.get("talk_number", 0),
        talk_index=d.get("talk_index", 0),
        duration_seconds=0.0,
    )
