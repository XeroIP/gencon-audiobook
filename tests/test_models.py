"""Unit tests for the completeness rules in models.py."""

from __future__ import annotations

from datetime import date

from gencon_audiobook.models import (
    Conference,
    Session,
    Talk,
    conference_may_still_be_publishing,
)

_BASE = "https://www.churchofjesuschrist.org/study/general-conference/2026/10"


def _talk(slug: str, index: int, *, speaker: str = "Elder Example", mp3: bool = True) -> Talk:
    return Talk(
        title=f"Talk {slug}",
        speaker=speaker,
        talk_url=f"{_BASE}/{slug}",
        mp3_url=f"https://assets.churchofjesuschrist.org/{slug}.mp3" if mp3 else None,
        talk_index=index,
    )


def _placeholder(slug: str, title: str, index: int) -> Talk:
    return Talk(title=title, speaker="", talk_url=f"{_BASE}/{slug}", talk_index=index)


def _conference(*sessions: Session) -> Conference:
    return Conference(
        title="October 2026 General Conference",
        year=2026,
        month=10,
        cover_image_url=None,
        sessions=list(sessions),
        conference_url=_BASE,
    )


# ---------------------------------------------------------------------------
# Talk.missing_fields / is_session_landing
# ---------------------------------------------------------------------------


def test_talk_missing_fields_empty_for_complete_talk() -> None:
    talk = _talk("11oaks", 1)
    assert talk.missing_fields() == [], f"Complete talk reported missing {talk.missing_fields()}"


def test_talk_missing_fields_reports_speaker_and_mp3() -> None:
    talk = _talk("11oaks", 1, speaker="", mp3=False)
    assert talk.missing_fields() == ["speaker", "mp3_url"], (
        f"Expected speaker and mp3_url missing, got {talk.missing_fields()}"
    )


def test_talk_missing_fields_rejects_mp3_outside_allowlist() -> None:
    talk = _talk("11oaks", 1)
    talk.mp3_url = "https://example.com/talk.mp3"
    assert talk.missing_fields() == ["mp3_url"], (
        f"An off-allowlist MP3 URL must count as missing, got {talk.missing_fields()}"
    )


def test_talk_is_session_landing_true_for_session_placeholder() -> None:
    talk = _placeholder("saturday-morning-session", "Saturday Morning Session", 1)
    assert talk.is_session_landing, "A session page listed in place of talks is a placeholder"


def test_talk_is_session_landing_false_for_talk_slug_ending_in_session() -> None:
    talk = Talk(
        title="What We Learn Together",
        speaker="Elder Example",
        talk_url=f"{_BASE}/lessons-from-a-study-session",
    )
    assert not talk.is_session_landing, (
        "A real talk whose slug ends in -session but whose title is not a session name "
        "must not be treated as a placeholder"
    )


def test_talk_is_complete_false_for_session_placeholder() -> None:
    talk = _placeholder("saturday-morning-session", "Saturday Morning Session", 1)
    assert not talk.is_complete, "A session placeholder is never a complete talk"


# ---------------------------------------------------------------------------
# Conference.incomplete_talks / without_incomplete_talks
# ---------------------------------------------------------------------------


def test_conference_incomplete_talks_empty_for_complete_conference() -> None:
    conf = _conference(Session("Saturday Morning Session", 1, [_talk("11a", 1), _talk("12b", 2)]))
    assert conf.incomplete_talks == [], (
        f"Complete conference reported incomplete talks: {conf.incomplete_talks}"
    )


def test_conference_incomplete_talks_flags_missing_mp3() -> None:
    missing = _talk("12b", 2, mp3=False)
    conf = _conference(Session("Saturday Morning Session", 1, [_talk("11a", 1), missing]))
    assert conf.incomplete_talks == [missing], (
        f"Expected only the talk without audio, got {conf.incomplete_talks}"
    )


def test_conference_incomplete_talks_flags_session_placeholder() -> None:
    placeholder = _placeholder("sunday-morning-session", "Sunday Morning Session", 3)
    conf = _conference(
        Session("Saturday Morning Session", 1, [_talk("11a", 1), _talk("12b", 2)]),
        Session("Sunday Morning Session", 2, [placeholder]),
    )
    assert conf.incomplete_talks == [placeholder], (
        f"Expected only the unpublished session placeholder, got {conf.incomplete_talks}"
    )


def test_conference_without_incomplete_talks_keeps_talk_index() -> None:
    conf = _conference(
        Session("Saturday Morning Session", 1, [_talk("11a", 1), _talk("12b", 2, mp3=False), _talk("13c", 3)]),
    )
    trimmed = conf.without_incomplete_talks()
    indexes = [t.talk_index for t in trimmed.talks]
    assert indexes == [1, 3], (
        f"Remaining talks must keep their original talk_index so filenames stay stable, got {indexes}"
    )


def test_conference_without_incomplete_talks_drops_empty_sessions() -> None:
    conf = _conference(
        Session("Saturday Morning Session", 1, [_talk("11a", 1)]),
        Session("Sunday Morning Session", 2, [_placeholder("sunday-morning-session", "Sunday Morning Session", 2)]),
    )
    trimmed = conf.without_incomplete_talks()
    names = [s.name for s in trimmed.sessions]
    assert names == ["Saturday Morning Session"], f"Empty sessions must be dropped, got {names}"


def test_conference_without_incomplete_talks_leaves_original_unchanged() -> None:
    conf = _conference(Session("Saturday Morning Session", 1, [_talk("11a", 1), _talk("12b", 2, mp3=False)]))
    conf.without_incomplete_talks()
    assert len(conf.talks) == 2, f"Original conference must not be modified, has {len(conf.talks)} talks"


# ---------------------------------------------------------------------------
# conference_may_still_be_publishing
# ---------------------------------------------------------------------------


def test_conference_may_still_be_publishing_true_in_conference_month() -> None:
    assert conference_may_still_be_publishing(2026, 10, today=date(2026, 10, 5)), (
        "A conference in the current month may still be publishing"
    )


def test_conference_may_still_be_publishing_true_for_upcoming_conference() -> None:
    assert conference_may_still_be_publishing(2026, 10, today=date(2026, 9, 27)), (
        "An upcoming conference may still be publishing"
    )


def test_conference_may_still_be_publishing_false_for_past_conference() -> None:
    assert not conference_may_still_be_publishing(2026, 4, today=date(2026, 9, 27)), (
        "A conference from an earlier month is finished publishing"
    )
