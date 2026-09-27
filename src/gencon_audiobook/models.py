"""Data models for conferences, sessions, and talks."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date

from .utils import validate_url


def conference_may_still_be_publishing(year: int, month: int, today: date | None = None) -> bool:
    """Return True if a conference is recent enough that the site may still be publishing it.

    Conferences are held the first weekend of April and October, and the Church posts
    talks and audio over the following days. Any conference in the current month or later
    can therefore be legitimately incomplete; an older one with missing talks points at a
    scrape failure instead.

    Args:
        year: Conference year.
        month: Conference month (4 or 10).
        today: Reference date; defaults to today's date.

    Returns:
        True if the conference month is the current month or in the future.
    """
    ref = today or date.today()
    return (year, month) >= (ref.year, ref.month)


@dataclass
class InlineImage:
    """An image embedded within a talk transcript body.

    Args:
        url: Absolute URL of the image on churchofjesuschrist.org.
        alt: Alt text from the <img> element.
        asset_id: Unique asset identifier (from data-assetId or derived from URL).
    """

    url: str
    alt: str
    asset_id: str


@dataclass
class Talk:
    """A single General Conference talk.

    Args:
        title: Talk title.
        speaker: Speaker's full name.
        talk_url: URL of the talk page on churchofjesuschrist.org.
        mp3_url: URL of the MP3 audio file, if available.
        video_url: URL of the 360p MP4 video file, if available.
        transcript_html: Raw HTML transcript, if available.
        speaker_image_url: URL of the speaker photo, if available.
        session_name: Name of the session this talk belongs to.
        session_number: 1-indexed session number within the conference.
        talk_number: 1-indexed talk number within the session.
        talk_index: 1-indexed position across the whole conference (used for filenames).
        duration_seconds: Duration of the audio in seconds; set by audio.py during conversion.
    """

    title: str
    speaker: str
    talk_url: str
    mp3_url: str | None = None
    video_url: str | None = None
    transcript_html: str | None = None
    speaker_image_url: str | None = None
    inline_images: list[InlineImage] = field(default_factory=list)
    session_name: str = ""
    session_number: int = 0   # 1-indexed
    talk_number: int = 0      # 1-indexed within the session
    talk_index: int = 0       # 1-indexed across the whole conference
    duration_seconds: float = 0.0

    def missing_fields(self) -> list[str]:
        """Return the names of required fields this talk lacks.

        A talk needs a title, a speaker, and an allowlisted MP3 URL to be usable. This is
        the single rule the scraper and CLI both use to decide whether a talk is complete.

        Returns:
            Missing field names in a stable order; empty when nothing is missing.
        """
        missing: list[str] = []
        if not self.title:
            missing.append("title")
        if not self.speaker:
            missing.append("speaker")
        if not self.mp3_url or not validate_url(self.mp3_url):
            missing.append("mp3_url")
        return missing

    @property
    def is_session_landing(self) -> bool:
        """True if this entry is a session landing page standing in for unpublished talks.

        Before a session's talks are posted, the conference listing links to the session's
        own page (e.g. ``.../2026/10/saturday-morning-session``) where its talks will go.
        Both the slug and the title must look like a session so that a real talk whose
        slug happens to end in "-session" is not misclassified.
        """
        slug = self.talk_url.rstrip("/").rsplit("/", 1)[-1].lower()
        return slug.endswith("-session") and self.title.strip().lower().endswith("session")

    @property
    def is_complete(self) -> bool:
        """True if this is a real talk with every required field present."""
        return not self.is_session_landing and not self.missing_fields()


@dataclass
class Session:
    """A session within a General Conference.

    Args:
        name: Session name, e.g. "Saturday Morning Session".
        number: 1-indexed session number within the conference.
        talks: Talks in this session, in order.
    """

    name: str
    number: int  # 1-indexed
    talks: list[Talk] = field(default_factory=list)


@dataclass
class Conference:
    """A complete General Conference.

    Args:
        title: Full title, e.g. "April 2024 General Conference".
        year: Four-digit year.
        month: Month number (4 for April, 10 for October).
        cover_image_url: URL of the conference cover image, if available.
        sessions: Sessions in this conference, in order.
        conference_url: URL of the conference listing page.
    """

    title: str
    year: int
    month: int  # 4 for April, 10 for October
    cover_image_url: str | None
    sessions: list[Session]
    conference_url: str

    @property
    def talks(self) -> list[Talk]:
        """All talks across all sessions, in order."""
        return [talk for session in self.sessions for talk in session.talks]

    @property
    def incomplete_talks(self) -> list[Talk]:
        """Listing entries that are not usable talks yet, in order.

        Includes talks missing required fields and session landing pages whose talks
        have not been posted. Empty for a fully published conference.
        """
        return [talk for talk in self.talks if not talk.is_complete]

    def without_incomplete_talks(self) -> Conference:
        """Return a copy containing only complete talks, dropping sessions left empty.

        Talks keep their original ``talk_index`` so audio filenames stay the same when
        the missing talks are published and the conference is rebuilt in full.

        Returns:
            A new Conference; this instance is not modified.
        """
        sessions: list[Session] = []
        for session in self.sessions:
            talks = [talk for talk in session.talks if talk.is_complete]
            if talks:
                sessions.append(dataclasses.replace(session, talks=talks))
        return dataclasses.replace(self, sessions=sessions)
