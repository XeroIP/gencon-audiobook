"""Data models for conferences, sessions, and talks."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    transcript_html: str | None = None
    speaker_image_url: str | None = None
    inline_images: list[InlineImage] = field(default_factory=list)
    session_name: str = ""
    session_number: int = 0   # 1-indexed
    talk_number: int = 0      # 1-indexed within the session
    talk_index: int = 0       # 1-indexed across the whole conference
    duration_seconds: float = 0.0


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
